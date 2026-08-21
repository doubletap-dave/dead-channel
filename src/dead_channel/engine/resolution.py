"""Action resolution: turns ActionSpecs into effects, intel, and threat signals.

Pure — effects are data the runner applies; resolve never mutates the world.
Chance branches (leak, infiltration) draw from named seeded streams only.
"""

import pydantic
from pydantic import Field

from dead_channel.core.config import SimParams
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    ActionKind,
    ActionSpec,
    IntelPayload,
    IntelSource,
    StateID,
    TrueWorldState,
)
from dead_channel.engine import resolution_table as table
from dead_channel.engine.effects import Effect


class ResolutionResult(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    effects: list[Effect] = Field(default_factory=list)
    intel: list[IntelPayload] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)
    verify_target: str | None = None


def other(state: StateID) -> StateID:
    return StateID.VESPER if state is StateID.NORTHSTAR else StateID.NORTHSTAR


def _route(actor: StateID, enemy: StateID, attribute: str, delta: float, reason: str) -> Effect:
    if attribute.startswith(table.ENEMY_PREFIX):
        return Effect(
            state=enemy,
            attribute=attribute.removeprefix(table.ENEMY_PREFIX),
            delta=delta,
            reason=reason,
        )
    return Effect(state=actor, attribute=attribute, delta=delta, reason=reason)


def resolve(
    action: ActionSpec,
    actor: StateID,
    world: TrueWorldState,
    params: SimParams,
    rng: SeededRNG,
    turn: int,
    deception_active: dict[StateID, str] | None = None,
) -> ResolutionResult:
    me = world.countries[actor]
    enemy = other(actor)
    kind = action.kind

    effects = [
        _route(actor, enemy, attr, delta, kind.value)
        for attr, delta in table.ACTOR_EFFECTS.get(kind, ())
    ]
    intel: list[IntelPayload] = []
    signals = dict(table.SIGNALS.get(kind, {}))

    if kind is ActionKind.VERIFY_REPORT:
        target = str(action.params["target_attribute"])
        result = ResolutionResult(
            effects=effects, intel=intel, signals=signals, verify_target=target
        )
        return result
    if kind is ActionKind.PLANT_FALSE_INTEL:
        payload = IntelPayload(
            attribute=str(action.params["target_attribute"]),
            value=float(action.params["value"]),
            confidence=table.PLANT_CONFIDENCE,
            age_turns=0,
            source=IntelSource(str(action.params.get("source", table.PLANT_DEFAULT_SOURCE))),
            about=actor,
            planted=True,
        )
        intel.append(payload)
    elif kind is ActionKind.COVERT_MOBILIZATION:
        post_effect_readiness = me.readiness + 12.0
        leaked = rng.stream("leak", turn, actor=actor.value).random() < table.LEAK_PROBABILITY
        if leaked:
            intel.append(
                IntelPayload(
                    attribute="readiness",
                    value=post_effect_readiness,
                    confidence=table.LEAK_CONFIDENCE,
                    age_turns=0,
                    source=IntelSource.HUMINT,
                    about=actor,
                    planted=False,
                )
            )
    elif kind is ActionKind.ATTEMPT_INFILTRATION:
        chance = (
            table.INFILTRATION_BASE_CHANCE
            + me.intelligence_capability / table.INFILTRATION_CAPABILITY_SCALE
        )
        if rng.stream("infil", turn, actor=actor.value).random() < chance:
            signals["infiltrated"] = 1.0
        else:
            effects.append(
                Effect(
                    state=actor,
                    attribute="diplomatic_credibility",
                    delta=-3.0,
                    reason="attempt_infiltration_failed",
                )
            )
            signals["hostile"] = 0.5
    elif kind is ActionKind.ACCUSE:
        enemy_deceiving = bool(deception_active and deception_active.get(enemy))
        if enemy_deceiving:
            effects.append(
                Effect(
                    state=enemy,
                    attribute="diplomatic_credibility",
                    delta=-8.0,
                    reason="accuse_confirmed_deception",
                )
            )
        else:
            effects.append(
                Effect(
                    state=actor,
                    attribute="diplomatic_credibility",
                    delta=-5.0,
                    reason="accuse_unsubstantiated",
                )
            )

    return ResolutionResult(effects=effects, intel=intel, signals=signals)
