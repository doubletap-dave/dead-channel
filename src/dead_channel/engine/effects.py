"""Effect: the atomic state mutation produced by action resolution."""

import pydantic

from dead_channel.core.types import StateID


class Effect(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    state: StateID
    attribute: str
    delta: float
    reason: str
