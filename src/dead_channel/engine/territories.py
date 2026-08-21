"""Fictional territory geometry: hand-authored boxes on the real Earth.

Northstar ≈ Scandinavia/Baltic, Vesper ≈ Southern Cone. Contacts get deterministic
coordinates sampled from the actor's territory box so the map has a truthful
*shape* (where activity happens) while remaining observer-side fiction.
"""

from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import StateID

# (min_lon, min_lat, max_lon, max_lat)
TERRITORIES: dict[StateID, tuple[float, float, float, float]] = {
    StateID.NORTHSTAR: (10.0, 55.0, 28.0, 66.0),  # Scandinavia/Baltic
    StateID.VESPER: (-73.0, -50.0, -65.0, -33.0),  # Southern Cone
}


def contact_position(actor: StateID, turn: int, kind: str, rng: SeededRNG) -> tuple[float, float]:
    """Deterministic (lon, lat) inside the actor's territory box."""
    min_lon, min_lat, max_lon, max_lat = TERRITORIES[actor]
    stream = rng.stream("contact-position", turn, actor=actor.value, kind=kind)
    lon = stream.uniform(min_lon, max_lon)
    lat = stream.uniform(min_lat, max_lat)
    return round(lon, 3), round(lat, 3)
