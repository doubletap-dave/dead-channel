import pytest

from dead_channel.core.types import ResourceKind, StateID
from dead_channel.engine.effects import Effect
from dead_channel.engine.world import apply_effects, initial_world


def test_initial_world_deterministic_per_seed():
    assert initial_world(42) == initial_world(42)


def test_initial_world_shape_and_baseline():
    world = initial_world(7)
    assert world.turn == 0
    assert set(world.countries) == set(StateID)
    for country in world.countries.values():
        assert country.readiness == 40.0
        assert country.stability == 60.0
        assert country.intelligence_capability == 50.0
        assert country.diplomatic_credibility == 70.0
        assert country.concealment == 0.0
        assert set(country.resources) == set(ResourceKind)
        for value in country.resources.values():
            assert 50.0 <= value <= 60.0


def test_initial_world_varies_by_seed():
    a = initial_world(1).countries[StateID.NORTHSTAR].resources
    b = initial_world(2).countries[StateID.NORTHSTAR].resources
    assert a != b


def test_initial_world_varies_by_state():
    world = initial_world(1)
    assert world.countries[StateID.NORTHSTAR].resources != world.countries[StateID.VESPER].resources


def test_apply_effects_is_pure():
    world = initial_world(3)
    before = world.model_dump()
    apply_effects(
        world,
        [Effect(state=StateID.NORTHSTAR, attribute="readiness", delta=10.0, reason="mobilize")],
    )
    assert world.model_dump() == before


def test_apply_effects_routes_resources_and_hidden_attributes():
    world = initial_world(3)
    out = apply_effects(
        world,
        [
            Effect(state=StateID.NORTHSTAR, attribute="economy", delta=-10.0, reason="sanction"),
            Effect(state=StateID.NORTHSTAR, attribute="readiness", delta=15.0, reason="mobilize"),
            Effect(state=StateID.VESPER, attribute="concealment", delta=0.5, reason="hide"),
        ],
    )
    assert (
        out.countries[StateID.NORTHSTAR].resources[ResourceKind.ECONOMY]
        == world.countries[StateID.NORTHSTAR].resources[ResourceKind.ECONOMY] - 10.0
    )
    assert out.countries[StateID.NORTHSTAR].readiness == 55.0
    assert out.countries[StateID.VESPER].concealment == 0.5


def test_apply_effects_clamps_at_bounds():
    world = initial_world(3)
    out = apply_effects(
        world,
        [
            Effect(state=StateID.NORTHSTAR, attribute="readiness", delta=-100.0, reason="collapse"),
            Effect(state=StateID.NORTHSTAR, attribute="stability", delta=100.0, reason="boom"),
            Effect(state=StateID.NORTHSTAR, attribute="economy", delta=-100.0, reason="crash"),
            Effect(state=StateID.NORTHSTAR, attribute="concealment", delta=2.0, reason="mask"),
        ],
    )
    north = out.countries[StateID.NORTHSTAR]
    assert north.readiness == 0.0
    assert north.stability == 100.0
    assert north.resources[ResourceKind.ECONOMY] == 0.0
    assert north.concealment == 1.0


def test_apply_effects_only_touches_targeted_state():
    world = initial_world(3)
    out = apply_effects(
        world,
        [Effect(state=StateID.NORTHSTAR, attribute="stability", delta=5.0, reason="aid")],
    )
    assert out.countries[StateID.VESPER] == world.countries[StateID.VESPER]
    assert out.countries[StateID.NORTHSTAR].stability == 65.0


def test_apply_effects_leaves_turn_alone():
    world = initial_world(5).model_copy(update={"turn": 4})
    out = apply_effects(
        world,
        [Effect(state=StateID.NORTHSTAR, attribute="readiness", delta=1.0, reason="drill")],
    )
    assert out.turn == 4


def test_apply_effects_unknown_attribute_raises():
    world = initial_world(3)
    with pytest.raises(ValueError, match="morale"):
        apply_effects(
            world,
            [Effect(state=StateID.NORTHSTAR, attribute="morale", delta=50.0, reason="??")],
        )
