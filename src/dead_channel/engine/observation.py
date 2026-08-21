"""Mechanical observation: engine-side noisy sensing of truth into IntelPayloads.

Engine module — may read TrueWorldState. Its output is raw reports for downstream
rendering/assessment layers; agents never receive it directly.
"""

import random

import pydantic

from dead_channel.core.config import SimParams
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    CountryState,
    IntelPayload,
    IntelSource,
    ResourceKind,
    StateID,
    TrueWorldState,
)
from dead_channel.engine.beliefs import BeliefState

ATTRIBUTES: tuple[str, ...] = ("readiness", *(kind.value for kind in ResourceKind))

_SIGMA_FLOOR = 0.3
_SIGMA_CEILING = 3.0
_RELIABILITY_MIN = 0.3
_RELIABILITY_MAX = 0.95
_DRIFT_SIGMA = 0.02
_TOP_K = 4
_PHANTOM_READINESS = 8.0


class ObservationBatch(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    reports: list[IntelPayload]
    # Contract: feed these back into the next generate_observations call and persist them,
    # so a resumed replay reproduces the same drift trajectory.
    reliabilities: dict[StateID, dict[IntelSource, float]]


def _truth(target: CountryState, attribute: str) -> float:
    if attribute == "readiness":
        return target.readiness
    return target.resources[ResourceKind(attribute)]


def _sigma_eff(base: float, observer: CountryState, target: CountryState) -> float:
    raw = base * (0.5 + target.concealment) * (1.4 - observer.intelligence_capability / 250)
    return min(max(raw, _SIGMA_FLOOR * base), _SIGMA_CEILING * base)


def _weighted_pick[T](options: list[T], weights: list[float], stream: random.Random) -> T:
    total = sum(weights)
    roll = stream.random() * total
    acc = 0.0
    for option, weight in zip(options, weights, strict=True):
        acc += weight
        if roll <= acc:
            return option
    return options[-1]


def _pick_attribute(
    beliefs: dict[StateID, BeliefState], observer: StateID, stream: random.Random
) -> str:
    scored = sorted(
        ((beliefs[observer].uncertainty(attr), attr) for attr in ATTRIBUTES),
        key=lambda item: (-item[0], item[1]),
    )
    top = scored[:_TOP_K]
    return _weighted_pick([attr for _, attr in top], [score for score, _ in top], stream)


def _pick_source(
    reliabilities: dict[StateID, dict[IntelSource, float]], observer: StateID, stream: random.Random
) -> IntelSource:
    weights = reliabilities[observer]
    return _weighted_pick(list(IntelSource), [weights[s] for s in IntelSource], stream)


def generate_observations(
    world: TrueWorldState,
    beliefs: dict[StateID, BeliefState],
    params: SimParams,
    rng: SeededRNG,
    turn: int,
    reliabilities: dict[StateID, dict[IntelSource, float]],
    active_exercises: dict[StateID, int],
) -> ObservationBatch:
    reports: list[IntelPayload] = []
    for observer in StateID:
        target_id = next(state for state in StateID if state != observer)
        target, obs_state = world.countries[target_id], world.countries[observer]
        count = rng.stream("obs_count", turn, observer=observer).randint(
            *params.reports_per_turn_range
        )
        for i in range(count):
            attr_rng = rng.stream("attribute", turn, observer=observer, idx=i)
            attr = _pick_attribute(beliefs, observer, attr_rng)
            source = _pick_source(
                reliabilities, observer, rng.stream("source", turn, observer=observer, idx=i)
            )
            truth = _truth(target, attr)
            if (
                active_exercises.get(target_id, 0) > 0
                and source == IntelSource.IMINT
                and attr == "readiness"
            ):
                truth += _PHANTOM_READINESS
            sigma = _sigma_eff(params.noise_sigma[source], obs_state, target)
            raw = truth + rng.stream("value", turn, observer=observer, idx=i).gauss(0, sigma)
            reported = min(max(raw, 0.0), 100.0)
            # Confidence uses the raw draw so a boundary-clamped report never scores
            # as a perfect reading.
            confidence = (0.9 - abs(raw - truth) / (3 * sigma)) * reliabilities[observer][source]
            reports.append(
                IntelPayload(
                    attribute=attr,
                    value=reported,
                    confidence=min(max(confidence, 0.05), 0.95),
                    age_turns=0,
                    source=source,
                    about=target_id,
                )
            )
    return ObservationBatch(reports=reports, reliabilities=_drift(rng, turn, reliabilities))


def _drift(
    rng: SeededRNG,
    turn: int,
    reliabilities: dict[StateID, dict[IntelSource, float]],
) -> dict[StateID, dict[IntelSource, float]]:
    drifted: dict[StateID, dict[IntelSource, float]] = {}
    for observer in StateID:
        drifted[observer] = {
            source: min(
                max(
                    value
                    + rng.stream("reliability", turn, observer=observer, source=source).gauss(
                        0, _DRIFT_SIGMA
                    ),
                    _RELIABILITY_MIN,
                ),
                _RELIABILITY_MAX,
            )
            for source, value in reliabilities[observer].items()
        }
    return drifted
