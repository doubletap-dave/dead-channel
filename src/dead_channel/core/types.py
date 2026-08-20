from enum import StrEnum
from typing import Annotated

import pydantic

Bounded = Annotated[float, pydantic.Field(ge=0.0, le=100.0)]


class ResourceKind(StrEnum):
    ECONOMY = "economy"
    ENERGY = "energy"
    FOOD = "food"
    MILITARY = "military"
    RESEARCH = "research"


class IntelSource(StrEnum):
    SIGINT = "sigint"
    IMINT = "imint"
    HUMINT = "humint"
    OSINT = "osint"
    DEFECTOR = "defector"


class StateID(StrEnum):
    NORTHSTAR = "northstar"
    VESPER = "vesper"


class Direction(StrEnum):
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"
    HOSTILE_INTENT = "hostile_intent"
    DECEPTION = "deception"


class ActionKind(StrEnum):
    RAISE_READINESS = "raise_readiness"
    LOWER_READINESS = "lower_readiness"
    REPOSITION_FORCES = "reposition_forces"
    CONDUCT_EXERCISE = "conduct_exercise"
    COVERT_MOBILIZATION = "covert_mobilization"
    INCREASE_SURVEILLANCE = "increase_surveillance"
    VERIFY_REPORT = "verify_report"
    PLANT_FALSE_INTEL = "plant_false_intel"
    ATTEMPT_INFILTRATION = "attempt_infiltration"
    REASSURE = "reassure"
    THREATEN = "threaten"
    PROPOSE_AGREEMENT = "propose_agreement"
    ACCUSE = "accuse"
    REQUEST_CLARIFICATION = "request_clarification"
    STAY_SILENT = "stay_silent"
    INVEST_MILITARY = "invest_military"
    INVEST_RESEARCH = "invest_research"
    INVEST_ECONOMY = "invest_economy"
    STOCKPILE = "stockpile"
    SANCTION = "sanction"
    OFFER_TRADE = "offer_trade"


class ActionSpec(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    kind: ActionKind
    params: dict[str, float | str] = {}


class Claim(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    subject: str
    direction: Direction
    magnitude: Bounded = 0.0
    horizon_turns: Annotated[int, pydantic.Field(ge=1)] = 3


class Assessment(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    role: str
    interpretation: str
    claim: Claim
    recommended_action: ActionSpec
    urgency: Annotated[int, pydantic.Field(ge=1, le=5)]
    dissent: str | None = None


class Decision(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    action: ActionSpec
    rationale: str


class CountryState(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    resources: dict[ResourceKind, Bounded]
    readiness: Bounded
    stability: Bounded
    intelligence_capability: Bounded
    diplomatic_credibility: Bounded
    concealment: Annotated[float, pydantic.Field(ge=0.0, le=1.0)] = 0.0


class TrueWorldState(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    turn: int = 0
    countries: dict[StateID, CountryState]


class IntelPayload(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    attribute: str
    value: float
    confidence: Annotated[float, pydantic.Field(ge=0.0, le=1.0)]
    age_turns: int
    source: IntelSource
    about: StateID
    planted: bool = False
