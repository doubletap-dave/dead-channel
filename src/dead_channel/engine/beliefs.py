"""BeliefState: what a state believes about its rival — derived only from reports."""

import pydantic

from dead_channel.core.types import StateID


class BelievedValue(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    value: float
    confidence: float
    last_report_turn: int
    last_verified_turn: int | None = None


class BeliefState(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    observer: StateID
    target: StateID
    attributes: dict[str, BelievedValue]

    def uncertainty(self, attribute: str) -> float:
        believed = self.attributes.get(attribute)
        if believed is None:
            return 1.0
        return max(0.0, 1.0 - believed.confidence)
