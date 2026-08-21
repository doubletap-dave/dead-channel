import asyncio
from pathlib import Path

import pytest

from dead_channel.providers.catalog import ModelInfo, clear_catalog_cache
from dead_channel.providers.keys import mask, read_keys, write_key
from dead_channel.providers.sampling import SamplingRules, resolve_sampling


def _info(model_id: str, params: tuple[str, ...] | None) -> ModelInfo:
    return ModelInfo(id=model_id, provider=model_id.split(":", 1)[0], supported_parameters=params)


def _run(awaitable):
    return asyncio.run(_wrap(awaitable))


async def _wrap(awaitable):
    return await awaitable


def test_reasoning_models_get_no_temperature():
    for model in ("openai:gpt-5-mini", "openai:o3", "openrouter:openai/o3-mini"):
        settings = _run(resolve_sampling(model))
        assert settings == {}, model


def test_temperature_only_when_supported():
    hot = _info("openrouter:x/y", ("temperature", "top_p"))
    cold = _info("openrouter:a/b", ("top_k", "repetition_penalty"))
    unknown = _info("openrouter:c/d", None)
    assert _run(resolve_sampling("openrouter:x/y", catalog_entry=hot)) == {"temperature": 0.7}
    assert _run(resolve_sampling("openrouter:a/b", catalog_entry=cold)) == {}
    assert _run(resolve_sampling("openrouter:c/d", catalog_entry=unknown)) == {}
    assert _run(
        resolve_sampling(
            "openrouter:x/y", catalog_entry=hot, rules=SamplingRules(default_temperature=0.2)
        )
    ) == {"temperature": 0.2}


def test_perplexity_static_catalog_supports_temperature():
    entry = _info("perplexity:sonar-pro", ("temperature",))
    assert _run(resolve_sampling("perplexity:sonar-pro", catalog_entry=entry)) == {
        "temperature": 0.7
    }


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_catalog_cache()
    yield
    clear_catalog_cache()


def test_mask_hides_secret_material():
    assert mask("") is None
    assert mask("short") == "*****"
    masked = mask("sk-or-v1-abcdef1234567890")
    assert masked is not None and "abcdef" not in masked


def test_env_roundtrip(tmp_path: Path):
    env_file = tmp_path / ".env"
    read = write_key("openrouter", "sk-or-v1-test-123", env_file=env_file)
    assert read["openrouter"] == "sk-or-v1-test-123"

    again = read_keys(env_file)
    assert again["openrouter"] == "sk-or-v1-test-123"
    assert again["openai"] == ""

    write_key("openai", "sk-openai-456", env_file=env_file)
    final = read_keys(env_file)
    assert final["openrouter"] == "sk-or-v1-test-123"
    assert final["openai"] == "sk-openai-456"
    text = env_file.read_text(encoding="utf-8")
    assert text.count("OPENROUTER_API_KEY=") == 1


def test_write_key_rejects_unknown_provider(tmp_path: Path):
    with pytest.raises(KeyError):
        write_key("nope", "x", env_file=tmp_path / ".env")
