import pydantic
import pytest

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

ACTION_VALUES = {
    "raise_readiness",
    "lower_readiness",
    "reposition_forces",
    "conduct_exercise",
    "covert_mobilization",
    "increase_surveillance",
    "verify_report",
    "plant_false_intel",
    "attempt_infiltration",
    "reassure",
    "threaten",
    "propose_agreement",
    "accuse",
    "request_clarification",
    "stay_silent",
    "invest_military",
    "invest_research",
    "invest_economy",
    "stockpile",
    "sanction",
    "offer_trade",
}


def test_action_kind_has_exactly_21_members():
    assert len(ActionKind) == 21
    assert {kind.value for kind in ActionKind} == ACTION_VALUES


def test_direction_members():
    assert {d.value for d in Direction} == {
        "rising",
        "falling",
        "stable",
        "hostile_intent",
        "deception",
    }


def test_claim_roundtrip():
    claim = Claim(
        subject="vesper.readiness",
        direction=Direction.RISING,
        magnitude=12.0,
        horizon_turns=4,
    )
    assert Claim.model_validate(claim.model_dump()) == claim
    assert Claim(subject="s", direction="stable").magnitude == 0.0
    assert Claim(subject="s", direction="stable").horizon_turns == 3


def test_claim_rejects_bad_direction_and_ranges():
    with pytest.raises(pydantic.ValidationError):
        Claim(subject="s", direction="doom")
    with pytest.raises(pydantic.ValidationError):
        Claim(subject="s", direction="stable", magnitude=100.5)
    with pytest.raises(pydantic.ValidationError):
        Claim(subject="s", direction="stable", horizon_turns=0)


def test_assessment_roundtrip():
    assessment = Assessment(
        role="analyst",
        interpretation="Vesper readiness is climbing at the border districts.",
        claim=Claim(subject="vesper.readiness", direction=Direction.RISING, magnitude=9.0),
        recommended_action=ActionSpec(kind=ActionKind.INCREASE_SURVEILLANCE, params={"days": 2.0}),
        urgency=4,
    )
    restored = Assessment.model_validate(assessment.model_dump())
    assert restored == assessment
    assert restored.dissent is None


def test_assessment_rejects_urgency_out_of_band():
    for urgency in (0, 6):
        with pytest.raises(pydantic.ValidationError):
            Assessment(
                role="analyst",
                interpretation="x",
                claim=Claim(subject="s", direction=Direction.STABLE),
                recommended_action=ActionSpec(kind=ActionKind.STAY_SILENT),
                urgency=urgency,
            )


def test_decision_roundtrip():
    decision = Decision(
        action=ActionSpec(kind=ActionKind.REASSURE, params={"channel": "hotline"}),
        rationale="De-escalate before the summit.",
    )
    assert Decision.model_validate(decision.model_dump()) == decision


def test_country_and_true_world_state_roundtrip():
    northstar = CountryState(
        resources={ResourceKind.ECONOMY: 50.0, ResourceKind.MILITARY: 40.0},
        readiness=30.0,
        stability=70.0,
        intelligence_capability=0.5,
        diplomatic_credibility=0.8,
    )
    world = TrueWorldState(countries={StateID.NORTHSTAR: northstar})
    restored = TrueWorldState.model_validate(world.model_dump())
    assert restored == world
    assert restored.turn == 0


def test_country_state_rejects_out_of_range_attributes():
    with pytest.raises(pydantic.ValidationError):
        CountryState(
            resources={},
            readiness=101.0,
            stability=70.0,
            intelligence_capability=0.5,
            diplomatic_credibility=0.8,
        )
    with pytest.raises(pydantic.ValidationError):
        CountryState(
            resources={ResourceKind.ECONOMY: 50.0},
            readiness=30.0,
            stability=70.0,
            intelligence_capability=0.5,
            diplomatic_credibility=0.8,
            concealment=1.5,
        )


def test_intel_payload_field_presence():
    payload = IntelPayload(
        attribute="readiness",
        value=41.0,
        confidence=0.7,
        age_turns=2,
        source=IntelSource.SIGINT,
        about=StateID.VESPER,
    )
    assert payload.planted is False
    with pytest.raises(pydantic.ValidationError):
        IntelPayload(attribute="readiness", value=41.0)


def test_intel_payload_rejects_out_of_range_confidence():
    with pytest.raises(pydantic.ValidationError):
        IntelPayload(
            attribute="stability",
            value=10.0,
            confidence=1.5,
            age_turns=0,
            source=IntelSource.DEFECTOR,
            about=StateID.NORTHSTAR,
            planted=True,
        )
    with pytest.raises(pydantic.ValidationError):
        IntelPayload(
            attribute="stability",
            value=10.0,
            confidence=-0.1,
            age_turns=0,
            source=IntelSource.DEFECTOR,
            about=StateID.NORTHSTAR,
        )


def _sample_world() -> TrueWorldState:
    return TrueWorldState(
        countries={
            StateID.NORTHSTAR: CountryState(
                resources={ResourceKind.ECONOMY: 50.0},
                readiness=30.0,
                stability=70.0,
                intelligence_capability=0.5,
                diplomatic_credibility=0.8,
            )
        }
    )


@pytest.mark.parametrize(
    ("model", "mutation"),
    [
        (
            Claim(subject="s", direction=Direction.RISING),
            lambda m: setattr(m, "magnitude", 5.0),
        ),
        (
            ActionSpec(kind=ActionKind.REASSURE),
            lambda m: setattr(m, "kind", ActionKind.THREATEN),
        ),
        (
            Assessment(
                role="analyst",
                interpretation="x",
                claim=Claim(subject="s", direction=Direction.STABLE),
                recommended_action=ActionSpec(kind=ActionKind.STAY_SILENT),
                urgency=2,
            ),
            lambda m: setattr(m, "urgency", 5),
        ),
        (
            Decision(action=ActionSpec(kind=ActionKind.REASSURE), rationale="r"),
            lambda m: setattr(m, "rationale", "other"),
        ),
        (
            IntelPayload(
                attribute="readiness",
                value=1.0,
                confidence=0.5,
                age_turns=0,
                source=IntelSource.OSINT,
                about=StateID.VESPER,
            ),
            lambda m: setattr(m, "confidence", 0.9),
        ),
        (_sample_world(), lambda m: setattr(m, "turn", 9)),
    ],
)
def test_models_are_frozen(model: pydantic.BaseModel, mutation) -> None:
    with pytest.raises(pydantic.ValidationError):
        mutation(model)
