import pydantic
import pytest

from dead_channel.core.config import SimParams
from dead_channel.engine.threat import DefconState, Signals, derive_defcon, update_threat

PARAMS = SimParams()

ALL_DRIVER_KEYS = {
    "readiness_delta",
    "hostile",
    "exercise",
    "betrayal",
    "reassurance",
    "decay",
}


def _step(
    threat: float,
    delta: float = 0.0,
    signals: Signals | None = None,
    own_readiness: float = 50.0,
    credibility: float = 100.0,
    hotline: bool = False,
):
    return update_threat(
        threat,
        believed_readiness_delta=delta,
        signals=signals or Signals(),
        own_readiness=own_readiness,
        actor_credibility=credibility,
        hotline_active=hotline,
        params=PARAMS,
    )


def _settled_defcon(composite: float, conflict: bool = False) -> int:
    state = DefconState(defcon=5, hold=0)
    for _ in range(2):
        state = derive_defcon(composite, composite, conflict, state, PARAMS)
    return state.defcon


def test_signal_and_result_models_are_frozen():
    with pytest.raises(pydantic.ValidationError):
        Signals(hostile_messages=1).hostile_messages = 2
    update = _step(40.0, delta=1.0)
    with pytest.raises(pydantic.ValidationError):
        update.new_threat = 99.0
    with pytest.raises(pydantic.ValidationError):
        DefconState(defcon=3, hold=0).defcon = 1


def test_spiral_mutual_readiness_raises_threat():
    threat_a = 20.0
    threat_b = 20.0
    series_a: list[float] = []
    series_b: list[float] = []
    for _ in range(20):
        update_a = _step(threat_a, delta=6.0, own_readiness=threat_a)
        update_b = _step(threat_b, delta=6.0, own_readiness=threat_b)
        threat_a = update_a.new_threat
        threat_b = update_b.new_threat
        series_a.append(threat_a)
        series_b.append(threat_b)
    assert series_a == sorted(series_a)
    assert series_b == sorted(series_b)
    assert series_a[-1] > 80.0
    assert series_b[-1] > 80.0


def test_reassurance_scales_with_credibility():
    signals = Signals(reassurance_messages=2)
    trusted = _step(50.0, signals=signals, credibility=90.0)
    distrusted = _step(50.0, signals=signals, credibility=20.0)
    assert trusted.new_threat < distrusted.new_threat
    sensitivity = 1.3 - 50.0 / 250.0
    assert trusted.drivers["reassurance"] == pytest.approx(-12.0 * 2 * 0.9 * sensitivity)
    assert distrusted.drivers["reassurance"] == pytest.approx(-12.0 * 2 * 0.2 * sensitivity)


def test_hotline_halves_signal_terms_only():
    signals = Signals(hostile_messages=2, exercises_detected=1, betrayals=1, reassurance_messages=1)
    off = _step(40.0, signals=signals, credibility=50.0)
    on = _step(40.0, signals=signals, credibility=50.0, hotline=True)
    for key in ("hostile", "exercise", "betrayal", "reassurance"):
        assert on.drivers[key] == pytest.approx(off.drivers[key] * 0.5)
    assert on.drivers["decay"] == pytest.approx(off.drivers["decay"])
    assert on.drivers["readiness_delta"] == pytest.approx(off.drivers["readiness_delta"])


def test_low_own_readiness_amplifies_signal_terms():
    signals = Signals(hostile_messages=1)
    calm = _step(30.0, signals=signals, own_readiness=90.0)
    jumpy = _step(30.0, signals=signals, own_readiness=10.0)
    assert calm.drivers["hostile"] == pytest.approx(6.0 * (1.3 - 90.0 / 250.0))
    assert jumpy.drivers["hostile"] == pytest.approx(6.0 * (1.3 - 10.0 / 250.0))
    assert jumpy.drivers["hostile"] > calm.drivers["hostile"]
    assert jumpy.new_threat > calm.new_threat


def test_signals_accept_fractional_strengths():
    half = _step(40.0, signals=Signals(hostile_messages=0.5))
    full = _step(40.0, signals=Signals(hostile_messages=1.0))
    assert half.drivers["hostile"] == pytest.approx(full.drivers["hostile"] * 0.5)
    expected = 40.0 + full.drivers["hostile"] * 0.5 + half.drivers["decay"]
    assert half.new_threat == pytest.approx(expected)


def test_decay_pulls_threat_down_without_signals():
    update = _step(70.0)
    assert update.new_threat < 70.0
    assert update.drivers["decay"] == pytest.approx(-2.0 * (1.0 - 70.0 / 100.0))
    low = _step(5.0)
    assert low.new_threat == pytest.approx(5.0 - 2.0 * 0.95)
    assert _step(0.5).new_threat == pytest.approx(0.0)


def test_negative_believed_delta_adds_nothing():
    update = _step(50.0, delta=-10.0)
    assert update.drivers["readiness_delta"] == 0.0
    assert update.new_threat < 50.0


def test_hysteresis_needs_two_consecutive_turns():
    prev = DefconState(defcon=5, hold=0)
    first = derive_defcon(90.0, 20.0, False, prev, PARAMS)
    assert first.defcon == 5
    assert first.hold == 1
    second = derive_defcon(90.0, 20.0, False, first, PARAMS)
    assert second.defcon == 2
    assert second.hold == 0


def test_hysteresis_target_matches_prev_resets_hold():
    prev = DefconState(defcon=5, hold=1)
    relaxed = derive_defcon(30.0, 20.0, False, prev, PARAMS)
    assert relaxed.defcon == 5
    assert relaxed.hold == 0


@pytest.mark.parametrize(
    ("composite", "expected"),
    [(34.9, 5), (35.0, 4), (59.9, 4), (60.0, 3), (79.9, 3), (80.0, 2)],
)
def test_defcon_bands(composite: float, expected: int):
    assert _settled_defcon(composite) == expected


def test_defcon_1_requires_conflict_and_both_sides_hot():
    prev = DefconState(defcon=2, hold=0)
    assert derive_defcon(90.0, 90.0, False, prev, PARAMS).defcon == 2
    assert derive_defcon(90.0, 84.9, True, prev, PARAMS).defcon == 2
    immediate = derive_defcon(86.0, 90.0, True, DefconState(defcon=5, hold=0), PARAMS)
    assert immediate.defcon == 1
    assert immediate.hold == 0


def test_drivers_sum_with_prior_threat_matches_new_threat():
    signals = Signals(hostile_messages=2, exercises_detected=1, reassurance_messages=1)
    update = _step(45.0, delta=4.0, signals=signals, credibility=70.0, hotline=True)
    assert set(update.drivers) == ALL_DRIVER_KEYS
    raw = 45.0 + sum(update.drivers.values())
    assert update.new_threat == pytest.approx(min(100.0, max(0.0, raw)))
    huge = _step(99.0, delta=50.0, signals=Signals(hostile_messages=10))
    assert huge.new_threat == 100.0
