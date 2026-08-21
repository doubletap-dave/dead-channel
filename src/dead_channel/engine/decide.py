"""HoS decision call site: packet assembly, LLM call, decision + message events."""

from dead_channel.agents.calls import get_decision
from dead_channel.agents.packets import assemble_packet
from dead_channel.agents.policy import Role
from dead_channel.agents.prompts import hos_prompt
from dead_channel.core.events import Event
from dead_channel.core.types import Assessment, Decision, StateID
from dead_channel.engine.support import TurnHost
from dead_channel.engine.turn_ops import ADVISORS
from dead_channel.engine.turn_state import TurnState


def _decision_event(host: TurnHost, turn: int, state_id: StateID, result: Decision) -> Event:
    event = host.emit_payload(
        "decision.made",
        turn,
        {
            "state": state_id.value,
            "action": result.action.model_dump(),
            "rationale": result.rationale,
        },
    )
    host.emit_payload(
        "message.sent",
        turn,
        {
            "sender": state_id.value,
            "text": result.rationale,
            "kind": result.action.kind.value,
        },
    )
    return event


async def hos_decision(
    host: TurnHost,
    state: TurnState,
    turn: int,
    log: list[Event],
    state_id: StateID,
    advisor_events: list[Event],
) -> Event:
    ranking = [(role.value, state.trust.trust(role.value, turn)) for role in ADVISORS]
    assessments = [
        Assessment.model_validate({"role": item.payload["role"], **item.payload})
        for item in advisor_events
        if item.payload["role"] != Role.HEAD_OF_STATE.value
    ]
    packet = assemble_packet(
        Role.HEAD_OF_STATE,
        state_id,
        turn,
        log,
        host.beliefs(state_id),
        state.trust.salient(state.ledger.records_for(state_id), k=5, now_turn=turn),
        trust_notes=dict(ranking),
        assessments=assessments,
    )
    model = host.resolver.for_role(state_id, Role.HEAD_OF_STATE)
    prompt = hos_prompt(packet, ranking)
    result = await get_decision(host.caller, model, packet, ranking)
    event = _decision_event(host, turn, state_id, result)
    host._persist(event, result.model_dump(), model, prompt)
    return event
