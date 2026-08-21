"""Territory geometry for contact coordinates: boxes, determinism, containment."""

from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import StateID
from dead_channel.engine.territories import TERRITORIES, contact_position


def test_every_state_has_a_well_formed_territory():
    for state in StateID:
        min_lon, min_lat, max_lon, max_lat = TERRITORIES[state]
        assert min_lon < max_lon
        assert min_lat < max_lat
        assert min_lon >= -180 and max_lon <= 180
        assert min_lat >= -90 and max_lat <= 90


def test_contact_position_is_inside_actor_territory():
    rng = SeededRNG(7)
    for state in StateID:
        for turn in range(1, 6):
            lon, lat = contact_position(state, turn, "exercise", rng)
            min_lon, min_lat, max_lon, max_lat = TERRITORIES[state]
            assert min_lon >= -180 and max_lon <= 180
            assert min_lat >= -90 and max_lat <= 90
            assert min_lon <= lon <= max_lon
            assert min_lat <= lat <= max_lat


def test_contact_position_is_deterministic():
    a = contact_position(StateID.NORTHSTAR, 2, "surveillance", SeededRNG(9))
    b = contact_position(StateID.NORTHSTAR, 2, "surveillance", SeededRNG(9))
    assert a == b


def test_kinds_and_actors_differ():
    rng = SeededRNG(3)
    positions = {
        contact_position(state, turn, kind, rng)
        for state in StateID
        for turn in (1, 2, 3, 4)
        for kind in ("exercise", "surveillance")
    }
    assert len(positions) >= 12, "positions must vary by turn/kind/actor"
