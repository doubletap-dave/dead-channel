"""Tests for the mechanical observation model (engine-side noisy sensing)."""

from dead_channel.core.config import SimParams
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    CountryState,
    IntelSource,
    ResourceKind,
    StateID,
    TrueWorldState,
)
from dead_channel.engine.beliefs import BeliefState, BelievedValue
from dead_channel.engine.observation import (
    ATTRIBUTES,
    generate_observations,
)

TRUTH_VALUE = 50.0
DRAWS = 200


def _country(
    readiness: float = TRUTH_VALUE,
    intelligence_capability: float = TRUTH_VALUE,
    concealment: float = 0.0,
) -> CountryState:
    return CountryState(
        resources={kind: TRUTH_VALUE for kind in ResourceKind},
        readiness=readiness,
        stability=TRUTH_VALUE,
        intelligence_capability=intelligence_capability,
        diplomatic_credibility=TRUTH_VALUE,
        concealment=concealment,
    )


def _world(
    northstar: CountryState | None = None,
    vesper: CountryState | None = None,
) -> TrueWorldState:
    return TrueWorldState(
        countries={
            StateID.NORTHSTAR: northstar or _country(),
            StateID.VESPER: vesper or _country(),
        }
    )


def _beliefs() -> dict[StateID, BeliefState]:
    pairs = ((StateID.NORTHSTAR, StateID.VESPER), (StateID.VESPER, StateID.NORTHSTAR))
    return {
        obs: BeliefState(
            observer=obs,
            target=tgt,
            attributes={
                "economy": BelievedValue(value=TRUTH_VALUE, confidence=0.95, last_report_turn=0)
            },
        )
        for obs, tgt in pairs
    }


def _reliabilities() -> dict[StateID, dict[IntelSource, float]]:
    return {state: dict(SimParams().source_reliability_init) for state in StateID}


def test_determinism_same_and_different_seed() -> None:
    args = (_world(), _beliefs(), SimParams(), SeededRNG(42), 3, _reliabilities(), {})
    first = generate_observations(*args)
    second = generate_observations(*args)
    assert first == second

    divergent = generate_observations(
        _world(), _beliefs(), SimParams(), SeededRNG(43), 3, _reliabilities(), {}
    )
    assert first != divergent


def test_report_counts_and_payload_sanity() -> None:
    params = SimParams()
    low, high = params.reports_per_turn_range
    for seed in range(20):
        batch = generate_observations(
            _world(), _beliefs(), params, SeededRNG(seed), seed, _reliabilities(), {}
        )
        about_counts: dict[StateID, int] = {}
        for report in batch.reports:
            about_counts[report.about] = about_counts.get(report.about, 0) + 1
            assert report.attribute in ATTRIBUTES
            assert 0.0 <= report.value <= 100.0
            assert 0.05 <= report.confidence <= 0.95
            assert report.age_turns == 0
        assert set(about_counts) == set(StateID)
        assert all(low <= count <= high for count in about_counts.values())


def test_planted_always_false() -> None:
    for seed in range(10):
        batch = generate_observations(
            _world(),
            _beliefs(),
            SimParams(),
            SeededRNG(seed),
            seed,
            _reliabilities(),
            {StateID.VESPER: 2},
        )
        assert all(report.planted is False for report in batch.reports)


def _mean_abs_error_about_vesper(seed_offset: int, capability: float, concealment: float) -> float:
    errors: list[float] = []
    for i in range(DRAWS):
        world = _world(
            northstar=_country(intelligence_capability=capability),
            vesper=_country(concealment=concealment),
        )
        batch = generate_observations(
            world, _beliefs(), SimParams(), SeededRNG(seed_offset + i), i, _reliabilities(), {}
        )
        errors += [
            abs(report.value - TRUTH_VALUE)
            for report in batch.reports
            if report.about == StateID.VESPER
        ]
    assert errors
    return sum(errors) / len(errors)


def test_lower_intelligence_capability_is_noisier() -> None:
    weak = _mean_abs_error_about_vesper(1000, capability=10.0, concealment=0.0)
    strong = _mean_abs_error_about_vesper(1000, capability=90.0, concealment=0.0)
    assert weak > strong


def test_higher_concealment_is_noisier() -> None:
    hidden = _mean_abs_error_about_vesper(5000, capability=50.0, concealment=0.8)
    exposed = _mean_abs_error_about_vesper(5000, capability=50.0, concealment=0.0)
    assert hidden > exposed


def _readiness_values_about_vesper(exercise_turns: int, imint: bool) -> list[float]:
    values: list[float] = []
    for i in range(DRAWS):
        batch = generate_observations(
            _world(),
            _beliefs(),
            SimParams(),
            SeededRNG(7000 + i),
            i,
            _reliabilities(),
            {StateID.VESPER: exercise_turns} if exercise_turns else {},
        )
        values += [
            report.value
            for report in batch.reports
            if report.about == StateID.VESPER
            and report.attribute == "readiness"
            and (report.source == IntelSource.IMINT) == imint
        ]
    assert values
    return values


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def test_exercise_phantom_inflates_imint_readiness() -> None:
    with_exercise = _mean(_readiness_values_about_vesper(2, imint=True))
    without = _mean(_readiness_values_about_vesper(0, imint=True))
    assert without < TRUTH_VALUE + 4.0
    assert with_exercise > TRUTH_VALUE + 4.0
    assert with_exercise - without > 4.0
    non_imint_with = _readiness_values_about_vesper(2, imint=False)
    non_imint_without = _readiness_values_about_vesper(0, imint=False)
    assert non_imint_with == non_imint_without


def test_reliability_drift_bounded_and_deterministic() -> None:
    params = SimParams()
    world, beliefs = _world(), _beliefs()
    reliabilities = {
        StateID.NORTHSTAR: {source: 0.94 for source in IntelSource},
        StateID.VESPER: {source: 0.31 for source in IntelSource},
    }
    for turn in range(10):
        batch = generate_observations(
            world, beliefs, params, SeededRNG(99), turn, reliabilities, {}
        )
        for per_source in batch.reliabilities.values():
            for value in per_source.values():
                assert 0.3 <= value <= 0.95

    again = generate_observations(world, beliefs, params, SeededRNG(99), 4, reliabilities, {})
    expected = generate_observations(world, beliefs, params, SeededRNG(99), 4, reliabilities, {})
    assert again.reliabilities == expected.reliabilities


def test_drift_starts_from_passed_reliabilities() -> None:
    reliabilities = _reliabilities()
    batch = generate_observations(
        _world(), _beliefs(), SimParams(), SeededRNG(7), 0, reliabilities, {}
    )
    for state, per_source in batch.reliabilities.items():
        for source, value in per_source.items():
            assert abs(value - reliabilities[state][source]) < 0.1
