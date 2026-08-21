import json

import httpx
import pydantic
import pytest

from dead_channel.providers.catalog import (
    _CACHE_TTL_SECONDS,
    ModelInfo,
    _catalog_cache,
    clear_catalog_cache,
    fetch_catalog,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_catalog_cache()
    yield
    clear_catalog_cache()


def test_model_info_is_frozen():
    info = ModelInfo(id="openai:gpt-5-mini", provider="openai", context=None)
    with pytest.raises(pydantic.ValidationError):
        info.id = "other"


async def test_unknown_provider_rejected():
    with pytest.raises(ValueError, match="unknown provider"):
        _ = await fetch_catalog("anthropic")


async def test_openai_missing_key_rejected():
    with pytest.raises(ValueError, match="missing OPENAI_API_KEY"):
        _ = await fetch_catalog("openai", api_key=None)
    with pytest.raises(ValueError, match="missing OPENAI_API_KEY"):
        _ = await fetch_catalog("openai", api_key="  ")


def _mock_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(client, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(client, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


async def test_openai_payload_mapped_via_mock_transport(monkeypatch: pytest.MonkeyPatch):
    payload = {"data": [{"id": "gpt-5-mini"}, {"id": "gpt-5"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/models"
        assert request.headers["Authorization"] == "Bearer k-123"
        return httpx.Response(200, content=json.dumps(payload).encode())

    _mock_client(monkeypatch, handler)

    models = await fetch_catalog("openai", api_key="k-123")
    assert models == [
        ModelInfo(id="openai:gpt-5-mini", provider="openai", context=None),
        ModelInfo(id="openai:gpt-5", provider="openai", context=None),
    ]
    assert _catalog_cache["openai"][1] == models


async def test_openrouter_payload_mapped_via_mock_transport(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "data": [
            {"id": "meta-llama/llama-3.1-70b-instruct", "context_length": 131072},
            {"id": "qwen/qwen3-235b", "context_length": None},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://openrouter.ai/api/v1/models"
        return httpx.Response(200, content=json.dumps(payload).encode())

    _mock_client(monkeypatch, handler)

    models = await fetch_catalog("openrouter")
    assert models == [
        ModelInfo(
            id="openrouter:meta-llama/llama-3.1-70b-instruct",
            provider="openrouter",
            context=131072,
        ),
        ModelInfo(id="openrouter:qwen/qwen3-235b", provider="openrouter", context=None),
    ]


async def test_perplexity_returns_curated_static_list():
    models = await fetch_catalog("perplexity")
    ids = {m.id for m in models}
    assert {
        "perplexity:sonar",
        "perplexity:sonar-pro",
        "perplexity:sonar-reasoning-pro",
        "perplexity:sonar-deep-research",
    } <= ids
    assert all(m.provider == "perplexity" for m in models)
    assert all(m.context is not None for m in models)


async def test_second_fetch_within_ttl_serves_cache(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=json.dumps({"data": [{"id": "gpt-5-mini"}]}).encode())

    _mock_client(monkeypatch, handler)

    first = await fetch_catalog("openai", api_key="k")
    second = await fetch_catalog("openai", api_key="k")
    assert calls["n"] == 1
    assert second is first


async def test_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=json.dumps({"data": [{"id": "gpt-5-mini"}]}).encode())

    _mock_client(monkeypatch, handler)

    _ = await fetch_catalog("openai", api_key="k")
    stamp = _catalog_cache["openai"][0]
    monkeypatch.setattr(
        "dead_channel.providers.catalog.time.monotonic",
        lambda: stamp + _CACHE_TTL_SECONDS + 1,
    )
    _ = await fetch_catalog("openai", api_key="k")
    assert calls["n"] == 2
