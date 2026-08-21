"""Verification: tight re-observation of a targeted attribute against truth."""

from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    CountryState,
    IntelPayload,
    IntelSource,
    ResourceKind,
    StateID,
    TrueWorldState,
)

VERIFY_SOURCE = IntelSource.IMINT
VERIFY_SIGMA_FACTOR = 0.4
VERIFY_CONFIDENCE_FLOOR = 0.8
IMINT_BASE_SIGMA = 8.0


def _truth(country: CountryState, attribute: str) -> float:
    if attribute in ResourceKind:
        return country.resources[ResourceKind(attribute)]
    if attribute in CountryState.model_fields:
        return float(getattr(country, attribute))
    raise ValueError(f"attribute {attribute!r} is not observable")


def verify_attribute(
    world: TrueWorldState,
    attribute: str,
    observer: StateID,
    rng: SeededRNG,
    turn: int,
) -> IntelPayload:
    target = next(state for state in StateID if state is not observer)
    value = _truth(world.countries[target], attribute)
    sigma = IMINT_BASE_SIGMA * VERIFY_SIGMA_FACTOR
    observed = value + rng.stream("verify", turn, observer=observer.value).gauss(0.0, sigma)
    reported = min(max(observed, 0.0), 100.0)
    confidence = max(VERIFY_CONFIDENCE_FLOOR, 0.95 - abs(reported - value) / (3 * sigma))
    return IntelPayload(
        attribute=attribute,
        value=reported,
        confidence=min(confidence, 0.95),
        age_turns=0,
        source=VERIFY_SOURCE,
        about=target,
        planted=False,
    )
