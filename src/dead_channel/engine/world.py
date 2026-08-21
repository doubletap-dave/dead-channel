"""World construction and effect application over the true world state."""

import hashlib
from collections.abc import Iterable

from dead_channel.core.types import (
    CountryState,
    ResourceKind,
    StateID,
    TrueWorldState,
)
from dead_channel.engine.effects import Effect

_RESOURCE_ATTRIBUTES: frozenset[str] = frozenset(item.value for item in ResourceKind)

_HIDDEN_ATTRIBUTES: frozenset[str] = frozenset(CountryState.model_fields) - {"resources"}

_ROUTABLE_ATTRIBUTES = _RESOURCE_ATTRIBUTES | _HIDDEN_ATTRIBUTES

_BASE_RESOURCE = 55.0
_RESOURCE_JITTER = 5.0
_BASELINE: dict[str, float] = {
    "readiness": 40.0,
    "stability": 60.0,
    "intelligence_capability": 50.0,
    "diplomatic_credibility": 70.0,
    "concealment": 0.0,
}


def _jitter(seed: int, state: StateID, kind: ResourceKind) -> float:
    digest = hashlib.sha256(f"{seed}:{state.value}:{kind.value}".encode()).digest()
    unit = int.from_bytes(digest[:8], "big") / 2**64
    return _BASE_RESOURCE + (unit * 2.0 - 1.0) * _RESOURCE_JITTER


def _country(seed: int, state: StateID) -> CountryState:
    resources = {kind: _jitter(seed, state, kind) for kind in ResourceKind}
    return CountryState(
        resources=resources,
        readiness=_BASELINE["readiness"],
        stability=_BASELINE["stability"],
        intelligence_capability=_BASELINE["intelligence_capability"],
        diplomatic_credibility=_BASELINE["diplomatic_credibility"],
        concealment=_BASELINE["concealment"],
    )


def initial_world(seed: int) -> TrueWorldState:
    return TrueWorldState(
        turn=0,
        countries={state: _country(seed, state) for state in StateID},
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _route(country: CountryState, attribute: str, delta: float) -> CountryState:
    if attribute in _RESOURCE_ATTRIBUTES:
        kind = ResourceKind(attribute)
        current = country.resources[kind]
        return country.model_copy(
            update={"resources": {**country.resources, kind: _clamp(current + delta, 0.0, 100.0)}}
        )
    if attribute in _HIDDEN_ATTRIBUTES:
        bound = 1.0 if attribute == "concealment" else 100.0
        return country.model_copy(
            update={attribute: _clamp(getattr(country, attribute) + delta, 0.0, bound)}
        )
    raise ValueError(
        f"unknown effect attribute {attribute!r}; routable: {sorted(_ROUTABLE_ATTRIBUTES)}"
    )


def apply_effects(world: TrueWorldState, effects: Iterable[Effect]) -> TrueWorldState:
    countries = dict(world.countries)
    for effect in effects:
        country = countries.get(effect.state)
        if country is not None:
            countries[effect.state] = _route(country, effect.attribute, effect.delta)
    return world.model_copy(update={"countries": countries})
