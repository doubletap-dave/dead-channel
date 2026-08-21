"""Rebuild of TurnState from the event log: the log is the only truth."""

from collections.abc import Iterable

from dead_channel.core.config import SimParams
from dead_channel.core.events import Event
from dead_channel.core.types import Claim, IntelSource, StateID
from dead_channel.engine.support import (
    action_of,
    advance_defcon,
    apply_decision_side_effects,
    make_claim_id,
)
from dead_channel.engine.threat import DefconState
from dead_channel.engine.turn_state import TurnState


def _reliabilities_of(payload: dict[str, object]) -> dict[IntelSource, float] | None:
    raw = payload.get("reliabilities")
    if not isinstance(raw, dict) or not raw:
        return None
    restored: dict[IntelSource, float] = {}
    for source, value in raw.items():
        if not isinstance(source, str) or not isinstance(value, (int, float)):
            return None
        try:
            restored[IntelSource(source)] = float(value)
        except ValueError:
            return None
    return restored if set(restored) == set(IntelSource) else None


def _apply_decision(state: TurnState, state_id: StateID, payload: dict[str, object]) -> None:
    parsed = action_of(payload)
    if parsed is None:
        return
    kind, params = parsed
    apply_decision_side_effects(state, state_id, kind, params, int(payload.get("turn", 0)))


def _apply_event(state: TurnState, event: Event) -> None:
    payload = event.payload
    event_type = event.type
    if event_type == "turn.started":
        state.tick_timers()
    elif event_type == "observation.generated":
        observer = payload.get("observer")
        reliabilities = _reliabilities_of(payload)
        if isinstance(observer, str) and reliabilities is not None:
            state.reliabilities[StateID(observer)] = reliabilities
    elif event_type == "report.rendered":
        observer = payload.get("observer")
        if isinstance(observer, str):
            if payload.get("verified") is True:
                state.pending_verification.pop(StateID(observer), None)
            value = payload.get("value")
            if payload.get("attribute") == "readiness" and isinstance(value, (int, float)):
                state.believed_readiness[StateID(observer)] = float(value)
    elif event_type == "assessment.made":
        claim = payload.get("claim")
        role = payload.get("role")
        state_value = payload.get("state")
        if isinstance(claim, dict) and isinstance(role, str) and isinstance(state_value, str):
            state.ledger.open(
                Claim.model_validate(claim),
                author_role=role,
                state=StateID(state_value),
                turn=event.turn,
                claim_id=make_claim_id(StateID(state_value), role, event.turn),
            )
    elif event_type == "claim.scored":
        state.trust.update(
            str(payload.get("role", "")), float(payload.get("outcome", 0.0)), event.turn
        )
        claim_id = payload.get("claim_id")
        if isinstance(claim_id, str):
            state.ledger.mark_scored(
                claim_id,
                outcome=float(payload.get("outcome", 0.0)),
                scored_turn=event.turn,
            )
    elif event_type == "decision.made":
        state_id = payload.get("state")
        if isinstance(state_id, str):
            _apply_decision(state, StateID(state_id), payload)
    elif event_type == "threat.updated":
        state_id = payload.get("state")
        if isinstance(state_id, str):
            state.threats[StateID(state_id)] = float(payload.get("threat", 0.0))
        state.defcon = DefconState(
            defcon=int(payload.get("defcon", 5)), hold=int(payload.get("hold", 0))
        )
    elif event_type == "agreement.formed":
        state.hotline_active = True
    elif event_type == "agreement.violated":
        state.hotline_active = False
    elif event_type == "conflict.threshold_crossed":
        state.conflict_crossed = True


def rebuild_state(events: Iterable[Event], params: SimParams | None = None) -> TurnState:
    state = TurnState(params)
    saw_threat = False
    for event in events:
        _apply_event(state, event)
        saw_threat = saw_threat or event.type == "threat.updated"
    if saw_threat:
        state.defcon = advance_defcon(state)
    return state
