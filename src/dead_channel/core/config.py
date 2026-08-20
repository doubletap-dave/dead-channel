import pydantic

from dead_channel.core.types import IntelSource


class ThreatWeights(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    readiness_delta: float = 0.8
    hostile_msg: float = 6.0
    exercise: float = 5.0
    betrayal: float = 8.0
    reassurance: float = 12.0
    decay: float = 2.0


class SimParams(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    noise_sigma: dict[IntelSource, float] = {
        IntelSource.SIGINT: 6.0,
        IntelSource.IMINT: 8.0,
        IntelSource.HUMINT: 10.0,
        IntelSource.OSINT: 12.0,
        IntelSource.DEFECTOR: 25.0,
    }
    source_reliability_init: dict[IntelSource, float] = {
        IntelSource.SIGINT: 0.8,
        IntelSource.IMINT: 0.75,
        IntelSource.HUMINT: 0.6,
        IntelSource.OSINT: 0.7,
        IntelSource.DEFECTOR: 0.4,
    }
    threat_weights: ThreatWeights = ThreatWeights()
    defcon_bands: list[float] = [35.0, 60.0, 80.0]
    trust_half_life: float = 8.0
    claim_error_scale: float = 30.0
    reports_per_turn_range: tuple[int, int] = (3, 5)

    @pydantic.field_validator("defcon_bands")
    @classmethod
    def _bands_ascending(cls, v: list[float]) -> list[float]:
        if len(v) != 3 or any(a >= b for a, b in zip(v, v[1:], strict=True)):
            raise ValueError("defcon_bands must be 3 strictly ascending values")
        return v

    @pydantic.field_validator("reports_per_turn_range")
    @classmethod
    def _range_sane(cls, v: tuple[int, int]) -> tuple[int, int]:
        low, high = v
        if low <= 0 or low > high:
            raise ValueError("reports_per_turn_range must satisfy 0 < low <= high")
        return v


class ModelMatrix(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    default: str = "openai:gpt-5-mini"
    states: dict[str, dict[str, str]] = {}


class RunConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    seed: int
    turns: int = 40
    model_matrix: ModelMatrix = ModelMatrix()
    params: SimParams = SimParams()
