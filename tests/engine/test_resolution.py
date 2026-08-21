import pytest

from dead_channel.core.config import SimParams
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    ActionKind,
    ActionSpec,
    CountryState,
    IntelPayload,
    IntelSource,
    ResourceKind,
    StateID,
    TrueWorldState,
)
from dead_channel.engine.effects import Effect
from dead_channel.engine.resolution import ResolutionResult, resolve

TURN = 3


def make_country(**overrides: float) -> CountryState:
    values: dict[str, object] = {
        "resources": {kind: 50.0 for kind in ResourceKind},
        "readiness": 40.0,
        "stability": 60.0,
        "intelligence_capability": 50.0,
        "diplomatic_credibility": 50.0,
    }
    values.update(overrides)
    return CountryState(**values)  # type: ignore[arg-type]


def make_world() -> TrueWorldState:
    return TrueWorldState(
        turn=TURN,
        countries={
            StateID.NORTHSTAR: make_country(),
            StateID.VESPER: make_country(),
        },
    )


def resolve_kind(
    kind: ActionKind,
    *,
    actor: StateID = StateID.NORTHSTAR,
    seed: int = 0,
    world: TrueWorldState | None = None,
    deception_active: dict[StateID, str] | None = None,
    **params: float | str,
) -> ResolutionResult:
    action = ActionSpec(kind=kind, params=params)
    return resolve(
        action,
        actor,
        world or make_world(),
        SimParams(),
        SeededRNG(seed),
        TURN,
        deception_active=deception_active,
    )


def fx(state: StateID, attribute: str, delta: float, reason: str) -> Effect:
    return Effect(state=state, attribute=attribute, delta=delta, reason=reason)


def test_raise_readiness_effects_and_reasons():
    result = resolve_kind(ActionKind.RAISE_READINESS)
    assert result.effects == [
        fx(StateID.NORTHSTAR, "readiness", 6.0, "raise_readiness"),
        fx(StateID.NORTHSTAR, "economy", -1.0, "raise_readiness"),
    ]
    assert result.signals == {}
    assert result.intel == []


def test_lower_readiness_effect():
    result = resolve_kind(ActionKind.LOWER_READINESS)
    assert result.effects == [fx(StateID.NORTHSTAR, "readiness", -6.0, "lower_readiness")]


def test_reposition_forces_is_activity_signal_only():
    result = resolve_kind(ActionKind.REPOSITION_FORCES)
    assert result.effects == []
    assert result.signals == {"exercise": 0.5}


def test_conduct_exercise_effects_and_phantom_window_signal():
    result = resolve_kind(ActionKind.CONDUCT_EXERCISE)
    assert result.effects == [fx(StateID.NORTHSTAR, "readiness", 2.0, "conduct_exercise")]
    assert result.signals == {"exercise": 1.0, "exercise_turns": 2.0}


def test_covert_mobilization_conceals_and_leaks_true_post_effect_readiness():
    leaking = next(
        seed for seed in range(500) if resolve_kind(ActionKind.COVERT_MOBILIZATION, seed=seed).intel
    )
    result = resolve_kind(ActionKind.COVERT_MOBILIZATION, seed=leaking)
    assert result.effects == [
        fx(StateID.NORTHSTAR, "readiness", 12.0, "covert_mobilization"),
        fx(StateID.NORTHSTAR, "concealment", 0.3, "covert_mobilization"),
    ]
    assert result.intel == [
        IntelPayload(
            attribute="readiness",
            value=52.0,
            confidence=0.85,
            age_turns=0,
            source=IntelSource.HUMINT,
            about=StateID.NORTHSTAR,
            planted=False,
        )
    ]


def test_covert_mobilization_clean_seed_emits_no_intel():
    clean = next(
        seed
        for seed in range(500)
        if not resolve_kind(ActionKind.COVERT_MOBILIZATION, seed=seed).intel
    )
    result = resolve_kind(ActionKind.COVERT_MOBILIZATION, seed=clean)
    assert result.intel == []
    assert result.signals == {}


def test_increase_surveillance_signal_only():
    result = resolve_kind(ActionKind.INCREASE_SURVEILLANCE)
    assert result.effects == []
    assert result.signals == {"surveillance": 1.0}


def test_verify_report_carries_target_and_signal():
    result = resolve_kind(ActionKind.VERIFY_REPORT, target_attribute="military")
    assert result.verify_target == "military"
    assert result.signals == {"verify": 1.0}
    assert result.effects == []
    assert result.intel == []


def test_plant_false_intel_payload_is_planted_and_about_actor():
    result = resolve_kind(
        ActionKind.PLANT_FALSE_INTEL,
        target_attribute="readiness",
        value=85.0,
        source="sigint",
    )
    assert result.intel == [
        IntelPayload(
            attribute="readiness",
            value=85.0,
            confidence=0.7,
            age_turns=0,
            source=IntelSource.SIGINT,
            about=StateID.NORTHSTAR,
            planted=True,
        )
    ]
    assert result.effects == [
        fx(StateID.NORTHSTAR, "intelligence_capability", -2.0, "plant_false_intel")
    ]


def test_plant_false_intel_defaults_to_imint():
    result = resolve_kind(ActionKind.PLANT_FALSE_INTEL, target_attribute="economy", value=10.0)
    assert result.intel[0].source == IntelSource.IMINT


def test_infiltration_success_and_failure_branches_both_reachable():
    outcomes = {
        resolve_kind(ActionKind.ATTEMPT_INFILTRATION, seed=seed).signals.get("infiltrated")
        for seed in range(300)
    }
    assert outcomes == {1.0, None}


def test_infiltration_success_grants_low_noise_signal_only():
    seed = next(
        s
        for s in range(300)
        if "infiltrated" in resolve_kind(ActionKind.ATTEMPT_INFILTRATION, seed=s).signals
    )
    result = resolve_kind(ActionKind.ATTEMPT_INFILTRATION, seed=seed)
    assert result.signals == {"infiltrated": 1.0}
    assert result.effects == []


def test_infiltration_failure_costs_credibility_and_signals_hostile():
    seed = next(
        s
        for s in range(300)
        if "infiltrated" not in resolve_kind(ActionKind.ATTEMPT_INFILTRATION, seed=s).signals
    )
    result = resolve_kind(ActionKind.ATTEMPT_INFILTRATION, seed=seed)
    assert result.signals == {"hostile": 0.5}
    assert result.effects == [
        fx(StateID.NORTHSTAR, "diplomatic_credibility", -3.0, "attempt_infiltration_failed")
    ]


@pytest.mark.parametrize(
    ("kind", "signals"),
    [
        (ActionKind.REASSURE, {"reassurance": 1.0}),
        (ActionKind.PROPOSE_AGREEMENT, {"proposal": 1.0}),
        (ActionKind.REQUEST_CLARIFICATION, {"clarification_request": 1.0}),
        (ActionKind.OFFER_TRADE, {"trade_offer": 1.0}),
    ],
)
def test_diplomatic_signals_only(kind: ActionKind, signals: dict[str, float]):
    result = resolve_kind(kind)
    assert result.signals == signals
    assert result.effects == []
    assert result.intel == []


def test_threaten_costs_credibility_and_signals_hostile():
    result = resolve_kind(ActionKind.THREATEN)
    assert result.signals == {"hostile": 1.0}
    assert result.effects == [fx(StateID.NORTHSTAR, "diplomatic_credibility", -1.0, "threaten")]


def test_stay_silent_is_a_noop():
    assert resolve_kind(ActionKind.STAY_SILENT) == ResolutionResult()


def test_accuse_with_active_enemy_deception_hits_enemy():
    result = resolve_kind(ActionKind.ACCUSE, deception_active={StateID.VESPER: "phantom readiness"})
    assert result.effects == [
        fx(StateID.VESPER, "diplomatic_credibility", -8.0, "accuse_confirmed_deception")
    ]
    assert result.signals == {"hostile": 0.5}


def test_accuse_without_enemy_deception_backfires_on_actor():
    result = resolve_kind(ActionKind.ACCUSE, deception_active=None)
    assert result.effects == [
        fx(StateID.NORTHSTAR, "diplomatic_credibility", -5.0, "accuse_unsubstantiated")
    ]


def test_accuse_ignores_actor_own_active_deception():
    result = resolve_kind(
        ActionKind.ACCUSE, deception_active={StateID.NORTHSTAR: "phantom readiness"}
    )
    assert result.effects[0].state == StateID.NORTHSTAR
    assert result.effects[0].delta == -5.0


@pytest.mark.parametrize(
    ("kind", "resource"),
    [
        (ActionKind.INVEST_MILITARY, "military"),
        (ActionKind.INVEST_RESEARCH, "research"),
        (ActionKind.INVEST_ECONOMY, "economy"),
    ],
)
def test_invest_gains_resource_and_pays_economy(kind: ActionKind, resource: str):
    result = resolve_kind(kind)
    assert result.effects == [
        fx(StateID.NORTHSTAR, resource, 3.0, kind.value),
        fx(StateID.NORTHSTAR, "economy", -2.0, kind.value),
    ]


def test_stockpile_builds_energy_and_food():
    result = resolve_kind(ActionKind.STOCKPILE)
    assert result.effects == [
        fx(StateID.NORTHSTAR, "energy", 4.0, "stockpile"),
        fx(StateID.NORTHSTAR, "food", 4.0, "stockpile"),
        fx(StateID.NORTHSTAR, "economy", -1.0, "stockpile"),
    ]


def test_sanction_hits_enemy_economy_and_own_credibility():
    result = resolve_kind(ActionKind.SANCTION)
    assert result.effects == [
        fx(StateID.VESPER, "economy", -4.0, "sanction"),
        fx(StateID.NORTHSTAR, "diplomatic_credibility", -2.0, "sanction"),
    ]
    assert result.signals == {"hostile": 1.0}


def test_enemy_is_the_other_state():
    result = resolve_kind(ActionKind.SANCTION, actor=StateID.VESPER)
    assert result.effects[0].state == StateID.NORTHSTAR


def test_resolve_is_deterministic_across_all_kinds():
    for kind in ActionKind:
        params: dict[str, float | str] = (
            {"target_attribute": "readiness", "value": 70.0}
            if kind in {ActionKind.VERIFY_REPORT, ActionKind.PLANT_FALSE_INTEL}
            else {}
        )
        runs = [resolve_kind(kind, seed=11, **params) for _ in range(2)]
        assert runs[0] == runs[1]


def test_leak_and_infiltration_branches_are_seed_deterministic():
    for kind in (ActionKind.COVERT_MOBILIZATION, ActionKind.ATTEMPT_INFILTRATION):
        for seed in (7, 42, 1234):
            assert resolve_kind(kind, seed=seed) == resolve_kind(kind, seed=seed)


def test_resolve_never_mutates_world_and_always_reasons_effects():
    world = make_world()
    snapshot = world.model_dump()
    for kind in ActionKind:
        result = resolve_kind(kind, world=world, target_attribute="readiness", value=70.0)
        assert all(effect.reason for effect in result.effects)
    assert world.model_dump() == snapshot
