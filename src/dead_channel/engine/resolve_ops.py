"""Resolution application, threat update, and diplomacy outcomes (agreements, violations)."""

from dead_channel.core.config import SimParams
from dead_channel.core.events import Event
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    ActionKind,
    Decision,
    IntelPayload,
    StateID,
    TrueWorldState,
)
from dead_channel.engine.resolution import ResolutionResult
from dead_channel.engine.support import TurnHost, other
from dead_channel.engine.territories import contact_position
from dead_channel.engine.threat import Signals, update_threat
from dead_channel.engine.turn_ops import report_fields
from dead_channel.engine.turn_state import TurnState

_CONTACT_SIGNAL_KINDS = {"exercise": "exercise", "surveillance": "surveillance"}
_AGREEMENT_ACCEPT_BASE = 0.8
_AGREEMENT_ACCEPT_FLOOR = 0.05
_AGREEMENT_ACCEPT_CEIL = 0.9
_TRADE_THREAT_CEIL = 50.0
# Neutral reference posture for betrayal-signal scaling: the betrayer's victim is
# scored as if both sides stood at the 50-point midpoint, isolating the betrayal signal.
_NEUTRAL_POSTURE = 50.0


def apply_resolution(
    host: TurnHost,
    turn: int,
    state_id: StateID,
    result: ResolutionResult,
) -> None:
    for effect in result.effects:
        host.emit(
            "effect.applied",
            turn,
            state=effect.state.value,
            attribute=effect.attribute,
            delta=effect.delta,
            reason=effect.reason,
        )
    for payload in result.intel:
        _resolution_intel_events(host, turn, state_id, payload)
    _contact_events(host, turn, state_id, result.signals, host.rng)


def _contact_events(
    host: TurnHost, turn: int, actor: StateID, signals: dict[str, float], rng: SeededRNG
) -> None:
    observer = other(actor)
    for key, kind in _CONTACT_SIGNAL_KINDS.items():
        if signals.get(key, 0.0) > 0.0:
            lon, lat = contact_position(actor, turn, kind, rng)
            host.emit_payload(
                "contact.detected",
                turn,
                {
                    "observer": observer.value,
                    "about": actor.value,
                    "kind": kind,
                    "lat": lat,
                    "lon": lon,
                    "detail": f"{kind} activity attributed to {actor.value}",
                },
            )


def _resolution_intel_events(
    host: TurnHost,
    turn: int,
    actor: StateID,
    payload: IntelPayload,
) -> None:
    observer = other(actor)
    if payload.planted:
        host.emit_payload(
            "deception.planted",
            turn,
            {
                "state": actor.value,
                "about": observer.value,
                "attribute": payload.attribute,
                "value": payload.value,
            },
        )
    host.emit(
        "report.rendered",
        turn,
        observer=observer.value,
        **report_fields(
            payload,
            f"{payload.attribute} reported at {payload.value:.1f} by {payload.source.value}.",
            planted=payload.planted,
        ),
    )


def threat_event(
    host: TurnHost,
    state: TurnState,
    turn: int,
    state_id: StateID,
    world: TrueWorldState,
    results: dict[StateID, ResolutionResult],
    params: SimParams,
) -> Event:
    enemy = other(state_id)
    current = host.beliefs(state_id).attributes.get("readiness")
    previous = state.believed_readiness.get(state_id)
    delta = 0.0 if current is None or previous is None else current.value - previous
    update = update_threat(
        state.threats.get(state_id, 20.0),
        believed_readiness_delta=delta,
        signals=_signals_from(results, state_id),
        own_readiness=world.countries[state_id].readiness,
        actor_credibility=world.countries[enemy].diplomatic_credibility,
        hotline_active=state.hotline_active,
        params=params,
    )
    state.believed_readiness[state_id] = current.value if current else None
    state.threats[state_id] = update.new_threat
    return host.emit_payload(
        "threat.updated",
        turn,
        {
            "state": state_id.value,
            "threat": update.new_threat,
            "drivers": update.drivers,
            "defcon": state.defcon.defcon,
            "hold": state.defcon.hold,
        },
    )


def handle_agreements(
    host: TurnHost,
    state: TurnState,
    turn: int,
    decisions: dict[StateID, Decision],
    threats: dict[StateID, float],
    world: TrueWorldState,
    rng: SeededRNG,
) -> None:
    for actor, decision in decisions.items():
        enemy = other(actor)
        if decision.action.kind is ActionKind.PROPOSE_AGREEMENT and not state.hotline_active:
            acceptance = min(
                _AGREEMENT_ACCEPT_CEIL,
                max(
                    _AGREEMENT_ACCEPT_FLOOR,
                    _AGREEMENT_ACCEPT_BASE
                    - threats.get(enemy, 0.0) / 150.0
                    + world.countries[actor].diplomatic_credibility / 200.0,
                ),
            )
            if rng.stream("agreement", turn, actor=actor.value).random() < acceptance:
                state.hotline_active = True
                host.emit_payload(
                    "agreement.formed",
                    turn,
                    {"states": [actor.value, enemy.value], "kind": "hotline"},
                )
        if decision.action.kind is ActionKind.OFFER_TRADE and (
            threats.get(enemy, 100.0) < _TRADE_THREAT_CEIL
        ):
            for target in (actor, enemy):
                host.emit(
                    "effect.applied",
                    turn,
                    state=target.value,
                    attribute="economy",
                    delta=2.0,
                    reason="offer_trade",
                )


def handle_violations(
    host: TurnHost,
    state: TurnState,
    turn: int,
    decisions: dict[StateID, Decision],
) -> None:
    if not state.hotline_active:
        return
    for actor, decision in decisions.items():
        if decision.action.kind is ActionKind.COVERT_MOBILIZATION:
            state.hotline_active = False
            host.emit_payload(
                "agreement.violated",
                turn,
                {"state": actor.value, "kind": "hotline"},
            )
            _betrayal_threat(host, state, turn, actor)


def _betrayal_threat(host: TurnHost, state: TurnState, turn: int, betrayer: StateID) -> None:
    victim = other(betrayer)
    update = update_threat(
        state.threats.get(victim, 20.0),
        believed_readiness_delta=0.0,
        signals=Signals(betrayals=1.0),
        own_readiness=_NEUTRAL_POSTURE,
        actor_credibility=_NEUTRAL_POSTURE,
        hotline_active=False,
        params=state.params,
    )
    state.threats[victim] = update.new_threat
    host.emit_payload(
        "threat.updated",
        turn,
        {
            "state": victim.value,
            "threat": update.new_threat,
            "drivers": update.drivers,
            "defcon": state.defcon.defcon,
            "hold": state.defcon.hold,
        },
    )


def _signals_from(results: dict[StateID, ResolutionResult], observer: StateID) -> Signals:
    actor = other(observer)
    actor_signals = results[actor].signals if actor in results else {}
    return Signals(
        hostile_messages=actor_signals.get("hostile", 0.0),
        exercises_detected=actor_signals.get("exercise", 0.0),
        betrayals=actor_signals.get("betrayal", 0.0),
        reassurance_messages=actor_signals.get("reassurance", 0.0),
    )
