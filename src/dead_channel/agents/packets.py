"""Context packet assembly: the only doorway from event log to agent prompt.

`assemble_packet` accepts projections and events — its signature has no
TrueWorldState parameter, so truth leakage is a type error, not a review catch.
"""

import pydantic

from dead_channel.agents.policy import ROLE_POLICY, Role, visible
from dead_channel.core.events import Event
from dead_channel.core.types import Assessment, StateID
from dead_channel.engine.beliefs import BeliefState
from dead_channel.engine.ledger import ClaimRecord


class AgentPacket(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    role: Role
    state: StateID
    turn: int
    events: list[Event]
    beliefs: BeliefState | None
    ledger_slice: list[ClaimRecord]
    trust_notes: dict[str, float] = {}
    assessments: list[Assessment] = []


def _redact(event: Event, fields: frozenset[str]) -> Event:
    if not fields:
        return event
    payload = {key: value for key, value in event.payload.items() if key not in fields}
    return event.model_copy(update={"payload": payload})


def assemble_packet(
    role: Role,
    state: StateID,
    turn: int,
    events: list[Event],
    beliefs: BeliefState | None,
    ledger_slice: list[ClaimRecord],
    trust_notes: dict[str, float] | None = None,
    assessments: list[Assessment] | None = None,
) -> AgentPacket:
    policy = ROLE_POLICY[role]
    filtered = [event for event in events if visible(role, event, state)]
    redacted = [_redact(event, policy.redact_fields) for event in filtered]
    is_hos = role is Role.HEAD_OF_STATE
    return AgentPacket(
        role=role,
        state=state,
        turn=turn,
        events=redacted,
        beliefs=beliefs,
        ledger_slice=ledger_slice,
        trust_notes=trust_notes if is_hos and trust_notes is not None else {},
        assessments=assessments if is_hos and assessments is not None else [],
    )


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def _event_lines(packet: AgentPacket, event_type: str | None = None) -> list[str]:
    ordered = sorted(packet.events, key=lambda event: (event.turn, event.seq))
    lines: list[str] = []
    for event in ordered:
        if event_type is not None and event.type != event_type:
            continue
        payload = event.payload
        match event.type:
            case "report.rendered":
                attribute = payload.get("attribute")
                value = payload.get("value")
                confidence = payload.get("confidence")
                if isinstance(value, (int, float)) and isinstance(confidence, (int, float)):
                    lines.append(
                        f"turn {event.turn} {payload.get('source')} {attribute}"
                        f"={value:.1f} conf={confidence:.2f}"
                    )
            case "message.sent":
                lines.append(f"turn {event.turn} message: {payload.get('text')}")
            case "agreement.formed":
                lines.append(f"turn {event.turn} agreement formed: {payload.get('kind')}")
            case "agreement.violated":
                lines.append(f"turn {event.turn} agreement violated: {payload.get('kind')}")
            case "contact.detected":
                lines.append(
                    f"turn {event.turn} contact detected: {payload.get('kind', 'activity')}"
                )
            case "deception.planted":
                lines.append(
                    f"turn {event.turn} suspected plant detected: {payload.get('attribute')}"
                )
            case "effect.applied":
                attribute = payload.get("attribute")
                delta = payload.get("delta")
                if isinstance(delta, (int, float)):
                    lines.append(
                        f"turn {event.turn} {payload.get('state')} {attribute} "
                        f"{'+' if delta >= 0 else ''}{delta:.1f}"
                    )
            case "threat.updated":
                threat = payload.get("new_threat")
                if isinstance(threat, (int, float)):
                    lines.append(f"turn {event.turn} threat level: {_fmt(float(threat))}")
            case "decision.made":
                lines.append(f"turn {event.turn} decision: {payload.get('action', 'unknown')}")
            case _:
                lines.append(f"turn {event.turn} {event.type}")
    return lines


def _belief_lines(packet: AgentPacket) -> list[str]:
    if packet.beliefs is None:
        return []
    attributes = packet.beliefs.attributes
    return [
        f"{name}={believed.value:.1f} conf={believed.confidence:.2f} "
        f"(last report turn {believed.last_report_turn})"
        for name, believed in sorted(attributes.items())
    ]


def _memory_lines(packet: AgentPacket) -> list[str]:
    return [
        f"{record.claim_id} [{record.status}] {record.claim.subject} "
        f"{record.claim.direction.value} (turn {record.opened_turn}, by {record.author_role})"
        + (f", scored {record.outcome:.2f}" if record.outcome is not None else "")
        for record in sorted(packet.ledger_slice, key=lambda record: record.claim_id)
    ]


def packet_to_prompt_text(packet: AgentPacket) -> str:
    sections = [
        f"ROLE: {packet.role.value}",
        f"STATE: {packet.state.value}",
        f"TURN: {packet.turn}",
    ]
    belief_lines = _belief_lines(packet)
    if belief_lines:
        sections.append("BELIEFS:\n" + "\n".join(belief_lines))
    event_lines = _event_lines(packet)
    if event_lines:
        sections.append("INTEL/REPORTS:\n" + "\n".join(event_lines))
    message_lines = _event_lines(packet, "message.sent")
    if message_lines:
        sections.append("MESSAGES:\n" + "\n".join(message_lines))
    memory_lines = _memory_lines(packet)
    if memory_lines:
        sections.append("MEMORY:\n" + "\n".join(memory_lines))
    if packet.assessments:
        assessment_lines = [
            f"[{item.role}] urgency={item.urgency} {item.interpretation} "
            f"Recommends: {item.recommended_action.kind.value}."
            + (f" Dissent: {item.dissent}" if item.dissent else "")
            for item in packet.assessments
        ]
        sections.append("SIBLING ASSESSMENTS:\n" + "\n".join(assessment_lines))
    if packet.trust_notes:
        trust_lines = [
            f"{role}: {_fmt(score)}" for role, score in sorted(packet.trust_notes.items())
        ]
        sections.append("TRUST:\n" + "\n".join(trust_lines))
    return "<packet>\n" + "\n\n".join(sections) + "\n</packet>\n"
