"""Model assignment resolution: role override → state default → global default."""

from dead_channel.core.config import ModelMatrix


def resolve_model(state: str, role: str, matrix: ModelMatrix) -> str:
    state_overrides = matrix.states.get(state, {})
    return state_overrides.get(role) or state_overrides.get("default") or matrix.default
