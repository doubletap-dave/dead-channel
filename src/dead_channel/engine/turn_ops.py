"""Per-state turn mechanics: report rendering and advisor assessments."""

import asyncio

from dead_channel.agents.calls import get_assessment
from dead_channel.agents.packets import assemble_packet
from dead_channel.agents.policy import Role
from dead_channel.agents.prompts import assessment_prompt, render_report_prompt, trust_note_for
from dead_channel.agents.renderer import render_report
from dead_channel.core.events import Event
from dead_channel.core.types import Assessment, IntelPayload, StateID
from dead_channel.engine.support import TurnHost, make_claim_id
from dead_channel.engine.turn_state import TurnState

ADVISORS = (Role.INTELLIGENCE_CHIEF, Role.MILITARY_CHIEF, Role.DIPLOMAT)
_ALL_ROLES = (Role.HEAD_OF_STATE, *ADVISORS)


def report_fields(payload: IntelPayload, text: str, **flags: object) -> dict[str, object]:
    """The canonical report.rendered payload shape, shared by every emit site."""
    return {
        "about": payload.about.value,
        "attribute": payload.attribute,
        "value": payload.value,
        "confidence": payload.confidence,
        "age_turns": payload.age_turns,
        "source": payload.source.value,
        "text": text,
        **flags,
    }


async def render_reports(
    host: TurnHost,
    turn: int,
    observer: StateID,
    payloads: list[IntelPayload],
    **flags: object,
) -> list[Event]:
    model = host.resolver.for_role(observer, Role.INTELLIGENCE_CHIEF)

    async def one(payload: IntelPayload) -> tuple[IntelPayload, str]:
        return payload, await render_report(host.caller, model, payload)

    rendered = await asyncio.gather(*(one(payload) for payload in payloads))
    events: list[Event] = []
    for payload, text in rendered:
        event = host.emit(
            "report.rendered",
            turn,
            observer=observer.value,
            **report_fields(payload, text, **flags),
        )
        host._persist(event, text, model, render_report_prompt(payload))
        events.append(event)
    return events


def _assessment_event(host: TurnHost, turn: int, state: StateID, result: Assessment) -> Event:
    return host.emit(
        "assessment.made",
        turn,
        state=state.value,
        role=result.role,
        interpretation=result.interpretation,
        claim=result.claim.model_dump(),
        recommended_action=result.recommended_action.model_dump(),
        urgency=result.urgency,
        dissent=result.dissent,
    )


def _trust_notes(state: TurnState, turn: int) -> dict[str, float]:
    return {role.value: state.trust.trust(role.value, turn) for role in ADVISORS}


async def advisor_assessments(
    host: TurnHost,
    state: TurnState,
    turn: int,
    log: list[Event],
    observer: StateID,
) -> list[Event]:
    beliefs = host.beliefs(observer)
    ledger_slice = state.trust.salient(state.ledger.records_for(observer), k=5, now_turn=turn)
    trust_notes = _trust_notes(state, turn)

    async def one(role: Role) -> tuple[Role, Assessment, str, str]:
        packet = assemble_packet(
            role,
            observer,
            turn,
            log,
            beliefs,
            ledger_slice,
            trust_notes=trust_notes,
        )
        model = host.resolver.for_role(observer, role)
        note = trust_note_for(trust_notes[role.value]) if role in ADVISORS else None
        result = await get_assessment(host.caller, model, role, packet, trust_note=note)
        prompt = assessment_prompt(role, packet, trust_note=note)
        return role, result, prompt, model

    results = await asyncio.gather(*(one(role) for role in _ALL_ROLES))
    events: list[Event] = []
    for role, result, prompt, model in results:
        event = _assessment_event(host, turn, observer, result)
        host._persist(event, result.model_dump(), model, prompt)
        state.ledger.open(
            result.claim,
            author_role=role.value,
            state=observer,
            turn=turn,
            claim_id=make_claim_id(observer, role.value, turn),
        )
        events.append(event)
    return events
