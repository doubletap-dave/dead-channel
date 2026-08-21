"""Event-sourced projections: agent beliefs (observer-scoped) and true world replay."""

from collections.abc import Iterable

from dead_channel.core.events import Event
from dead_channel.core.types import StateID, TrueWorldState
from dead_channel.engine.beliefs import BeliefState, BelievedValue
from dead_channel.engine.effects import Effect
from dead_channel.engine.world import apply_effects, initial_world

_REPORT_RENDERED = "report.rendered"
_EFFECT_APPLIED = "effect.applied"
_WORLD_TICKED = "world.ticked"
_RUN_STARTED = "run.started"


def _other(observer: StateID) -> StateID:
    return next(state for state in StateID if state != observer)


def project_beliefs(events: Iterable[Event], observer: StateID) -> BeliefState:
    target = _other(observer)
    attributes: dict[str, BelievedValue] = {}

    for event in events:
        if event.type != _REPORT_RENDERED:
            continue
        payload = event.payload
        attribute = payload.get("attribute")
        value = payload.get("value")
        confidence = payload.get("confidence")
        if (
            payload.get("observer") != observer.value
            or payload.get("about") != target.value
            or not isinstance(attribute, str)
        ):
            continue
        if not isinstance(value, (int, float)) or not isinstance(confidence, (int, float)):
            continue

        existing = attributes.get(attribute)
        if existing is not None and event.turn < existing.last_report_turn:
            continue
        verified = event.turn if payload.get("verified") is True else None
        attributes[attribute] = BelievedValue(
            value=float(value),
            confidence=float(confidence),
            last_report_turn=event.turn,
            last_verified_turn=(
                verified
                if verified is not None
                else existing.last_verified_turn
                if existing is not None
                else None
            ),
        )

    return BeliefState(observer=observer, target=target, attributes=attributes)


def project_world(events: Iterable[Event]) -> TrueWorldState:
    world: TrueWorldState | None = None
    turn = 0
    effects: list[Effect] = []

    for event in events:
        turn = max(turn, event.turn)
        if event.type == _RUN_STARTED:
            snapshot = event.payload.get("initial_world")
            if isinstance(snapshot, dict):
                world = TrueWorldState.model_validate(snapshot)
        elif event.type == _EFFECT_APPLIED:
            payload = event.payload
            state = payload.get("state")
            attribute = payload.get("attribute")
            delta = payload.get("delta")
            if (
                isinstance(state, str)
                and isinstance(attribute, str)
                and isinstance(delta, (int, float))
            ):
                effects.append(
                    Effect(
                        state=StateID(state),
                        attribute=attribute,
                        delta=float(delta),
                        reason="replay",
                    )
                )

    if world is None:
        world = initial_world(0)
    world = apply_effects(world, effects)
    return world.model_copy(update={"turn": turn})
