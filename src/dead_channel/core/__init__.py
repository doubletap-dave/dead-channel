"""Core contracts: shared types, seeded RNG, event schema, and simulation parameters.

Frozen layer — every later module depends on these definitions.
"""

from dead_channel.core.config import ModelMatrix, RunConfig, SimParams, ThreatWeights
from dead_channel.core.events import EVENT_TYPES, Event, make_event
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    ActionKind,
    ActionSpec,
    Assessment,
    Claim,
    CountryState,
    Decision,
    Direction,
    IntelPayload,
    IntelSource,
    ResourceKind,
    StateID,
    TrueWorldState,
)

__all__ = [
    "EVENT_TYPES",
    "ActionKind",
    "ActionSpec",
    "Assessment",
    "Claim",
    "CountryState",
    "Decision",
    "Direction",
    "Event",
    "IntelPayload",
    "IntelSource",
    "ModelMatrix",
    "ResourceKind",
    "RunConfig",
    "SeededRNG",
    "SimParams",
    "StateID",
    "ThreatWeights",
    "TrueWorldState",
    "make_event",
]
