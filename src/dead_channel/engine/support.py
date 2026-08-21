"""Shared TurnRunner surface: host protocol, restart-critical helpers, constants.

The restart guarantee is between-turn determinism: replaying the log reproduces
TurnState exactly at every turn boundary. Everything here exists to keep the
live path and the rebuild path computing identical values.
"""

from typing import Protocol

from dead_channel.agents.calls import ModelResolver
from dead_channel.core.events import Event
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import ActionKind, StateID
from dead_channel.engine.beliefs import BeliefState
from dead_channel.engine.threat import DefconState, derive_defcon
from dead_channel.engine.turn_state import PendingVerification, TurnState
from dead_channel.providers.caller import Caller

EXERCISE_TURNS = 2
DECEPTION_TURNS = 2


class TurnHost(Protocol):
    """What helper modules may do back to the runner: emit, observe, persist, call LLMs."""

    caller: Caller

    resolver: ModelResolver

    rng: SeededRNG

    def emit(self, event_type: str, turn: int, **payload: object) -> Event: ...

    def emit_payload(self, event_type: str, turn: int, payload: dict[str, object]) -> Event: ...

    def beliefs(self, observer: StateID) -> BeliefState: ...

    def _persist(self, event: Event, response: object, model: str, prompt: str) -> None: ...


def other(state: StateID) -> StateID:
    return StateID.VESPER if state is StateID.NORTHSTAR else StateID.NORTHSTAR


def make_claim_id(state: StateID, role: str, turn: int) -> str:
    return f"{state.value}:{role}:{turn}"


def apply_decision_side_effects(
    state: TurnState,
    state_id: StateID,
    kind: ActionKind | str,
    params: dict[str, object],
    turn: int,
) -> None:
    """Register timers/pending work a decision starts; shared by live and rebuild paths."""
    kind_value = kind.value if isinstance(kind, ActionKind) else str(kind)
    if kind_value == ActionKind.CONDUCT_EXERCISE.value:
        state.active_exercises[state_id] = EXERCISE_TURNS
    elif kind_value == ActionKind.PLANT_FALSE_INTEL.value:
        state.deception_active[state_id] = DECEPTION_TURNS
    elif kind_value == ActionKind.VERIFY_REPORT.value:
        target = params.get("target_attribute")
        if isinstance(target, str):
            state.pending_verification[state_id] = PendingVerification(
                attribute=target, opened_turn=turn
            )


def action_of(payload: dict[str, object]) -> tuple[ActionKind, dict[str, float | str]] | None:
    action = payload.get("action")
    if not isinstance(action, dict) or not isinstance(action.get("kind"), str):
        return None
    params = action.get("params")
    return (
        ActionKind(action["kind"]),
        params if isinstance(params, dict) else {},
    )


def advance_defcon(state: TurnState) -> DefconState:
    """One final derive over end-of-turn threats; advances the hysteresis chain.

    threat.updated payloads carry the pre-derive defcon of their turn, so both
    the live runner and a fresh rebuild need this same closing step to agree.
    """
    return derive_defcon(
        state.threats.get(StateID.NORTHSTAR, 0.0),
        state.threats.get(StateID.VESPER, 0.0),
        state.conflict_crossed,
        state.defcon,
        state.params,
    )
