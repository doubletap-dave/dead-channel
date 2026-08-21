import pydantic
import pytest

from dead_channel.core.config import ModelMatrix, RunConfig, SimParams, ThreatWeights
from dead_channel.core.types import IntelSource


def test_sim_params_defaults_match_spec():
    params = SimParams()
    assert params.noise_sigma == {
        IntelSource.SIGINT: 6.0,
        IntelSource.IMINT: 8.0,
        IntelSource.HUMINT: 10.0,
        IntelSource.OSINT: 12.0,
        IntelSource.DEFECTOR: 25.0,
    }
    assert params.source_reliability_init == {
        IntelSource.SIGINT: 0.8,
        IntelSource.IMINT: 0.75,
        IntelSource.HUMINT: 0.6,
        IntelSource.OSINT: 0.7,
        IntelSource.DEFECTOR: 0.4,
    }
    assert params.threat_weights == ThreatWeights(
        readiness_delta=0.8,
        hostile_msg=6.0,
        exercise=5.0,
        betrayal=8.0,
        reassurance=12.0,
        decay=2.0,
    )
    assert params.defcon_bands == [35.0, 60.0, 80.0]
    assert params.trust_half_life == 8.0
    assert params.claim_error_scale == 30.0
    assert params.reports_per_turn_range == (3, 5)


def test_defcon_bands_validated():
    with pytest.raises(pydantic.ValidationError):
        SimParams(defcon_bands=[80.0, 60.0, 35.0])
    with pytest.raises(pydantic.ValidationError):
        SimParams(defcon_bands=[35.0, 60.0])
    with pytest.raises(pydantic.ValidationError):
        SimParams(defcon_bands=[35.0, 60.0, 60.0])


def test_reports_per_turn_range_validated():
    with pytest.raises(pydantic.ValidationError):
        SimParams(reports_per_turn_range=(0, 5))
    with pytest.raises(pydantic.ValidationError):
        SimParams(reports_per_turn_range=(5, 3))


def test_positive_scale_params_validated():
    with pytest.raises(pydantic.ValidationError):
        SimParams(trust_half_life=0.0)
    with pytest.raises(pydantic.ValidationError):
        SimParams(trust_half_life=-1.0)
    with pytest.raises(pydantic.ValidationError):
        SimParams(claim_error_scale=0.0)
    with pytest.raises(pydantic.ValidationError):
        SimParams(claim_error_scale=-5.0)


def test_model_matrix_default():
    assert ModelMatrix().default == "openai:gpt-5-mini"
    assert ModelMatrix().states == {}


def test_run_config_defaults():
    config = RunConfig(seed=42)
    assert config.turns == 40
    assert config.model_matrix == ModelMatrix()
    assert config.params == SimParams()


@pytest.mark.parametrize(
    ("model", "mutation"),
    [
        (SimParams(), lambda m: setattr(m, "trust_half_life", 4.0)),
        (ThreatWeights(), lambda m: setattr(m, "decay", 0.0)),
        (ModelMatrix(), lambda m: setattr(m, "default", "other")),
        (RunConfig(seed=1), lambda m: setattr(m, "seed", 2)),
    ],
)
def test_config_models_are_frozen(model: pydantic.BaseModel, mutation) -> None:
    with pytest.raises(pydantic.ValidationError):
        mutation(model)
