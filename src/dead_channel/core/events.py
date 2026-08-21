import pydantic

EVENT_TYPES = frozenset[str](
    {
        "run.started",
        "run.stopped",
        "run.failed",
        "agent.activity",
        "turn.started",
        "world.ticked",
        "observation.generated",
        "report.rendered",
        "assessment.made",
        "decision.made",
        "effect.applied",
        "threat.updated",
        "claim.scored",
        "message.sent",
        "contact.detected",
        "deception.planted",
        "agreement.formed",
        "agreement.violated",
        "conflict.threshold_crossed",
        "run.ended",
    }
)


class Event(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    seq: int
    turn: int
    type: str
    payload: dict[str, object]

    @pydantic.field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {v}")
        return v


def make_event(event_type: str, *, seq: int, turn: int, **payload: object) -> Event:
    return Event(seq=seq, turn=turn, type=event_type, payload=payload)
