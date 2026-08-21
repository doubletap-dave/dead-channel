import copy

import pydantic
import pytest

from dead_channel.core.config import ModelMatrix
from dead_channel.providers.matrix import resolve_model


def test_role_override_wins_over_state_default_and_global():
    matrix = ModelMatrix(
        default="openai:global",
        states={"red": {"default": "openai:state-default", "observer": "openai:role"}},
    )
    assert resolve_model("red", "observer", matrix) == "openai:role"


def test_state_default_used_when_role_absent():
    matrix = ModelMatrix(
        default="openai:global",
        states={"red": {"default": "openai:state-default"}},
    )
    assert resolve_model("red", "observer", matrix) == "openai:state-default"


def test_global_used_when_state_has_no_entries():
    matrix = ModelMatrix(default="openai:global", states={"red": {}})
    assert resolve_model("red", "observer", matrix) == "openai:global"


def test_global_used_when_state_unknown():
    matrix = ModelMatrix(default="openai:global")
    assert resolve_model("blue", "observer", matrix) == "openai:global"


def test_empty_states_dict_falls_back_to_global():
    matrix = ModelMatrix(default="openai:global", states={})
    assert resolve_model("red", "observer", matrix) == "openai:global"


def test_resolve_model_is_pure():
    matrix = ModelMatrix(
        default="openai:global",
        states={"red": {"observer": "openai:role"}},
    )
    snapshot = copy.deepcopy(matrix.model_dump())
    resolve_model("red", "observer", matrix)
    resolve_model("red", "analyst", matrix)
    resolve_model("unknown", "observer", matrix)
    assert matrix.model_dump() == snapshot


def test_matrix_is_frozen():
    matrix = ModelMatrix()
    with pytest.raises(pydantic.ValidationError):
        matrix.default = "openai:other"
