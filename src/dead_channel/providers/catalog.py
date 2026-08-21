"""Dynamic provider model catalogs with short-lived caching.

OpenAI and OpenRouter expose list endpoints; Perplexity has none, so its
catalog is a curated static list kept in sync with current docs.
"""

import time
from typing import Final

import httpx
import pydantic

_CACHE_TTL_SECONDS: Final = 300.0
_OPENAI_MODELS_URL: Final = "https://api.openai.com/v1/models"
_OPENROUTER_MODELS_URL: Final = "https://openrouter.ai/api/v1/models"
_REMOTE_PROVIDERS: Final = ("openai", "openrouter")

_catalog_cache: dict[str, tuple[float, list[ModelInfo]]] = {}


class ModelInfo(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    id: str
    provider: str
    context: int | None = None
    supported_parameters: tuple[str, ...] | None = None


_PERPLEXITY_CATALOG: Final = (
    ModelInfo(
        id="perplexity:sonar",
        provider="perplexity",
        context=128_000,
        supported_parameters=("temperature",),
    ),
    ModelInfo(
        id="perplexity:sonar-pro",
        provider="perplexity",
        context=200_000,
        supported_parameters=("temperature",),
    ),
    ModelInfo(
        id="perplexity:sonar-reasoning",
        provider="perplexity",
        context=128_000,
        supported_parameters=("temperature",),
    ),
    ModelInfo(
        id="perplexity:sonar-reasoning-pro",
        provider="perplexity",
        context=128_000,
        supported_parameters=("temperature",),
    ),
    ModelInfo(
        id="perplexity:sonar-deep-research",
        provider="perplexity",
        context=128_000,
    ),
)


def _build_client(api_key: str | None) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return httpx.AsyncClient(headers=headers, timeout=30.0)


def _to_model_info(provider: str, entry: dict[str, object]) -> ModelInfo:
    raw_context = entry.get("context_length")
    raw_params = entry.get("supported_parameters")
    params = tuple(raw_params) if isinstance(raw_params, list) else None
    return ModelInfo(
        id=f"{provider}:{entry['id']}",
        provider=provider,
        context=int(raw_context) if raw_context is not None else None,
        supported_parameters=params,
    )


async def _fetch_remote_catalog(provider: str, api_key: str | None) -> list[ModelInfo]:
    if provider == "openai" and not (api_key and api_key.strip()):
        raise ValueError("missing OPENAI_API_KEY")
    url = _OPENAI_MODELS_URL if provider == "openai" else _OPENROUTER_MODELS_URL
    async with _build_client(api_key) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    return [_to_model_info(provider, entry) for entry in payload.get("data", [])]


async def fetch_catalog(provider: str, api_key: str | None = None) -> list[ModelInfo]:
    if provider not in (*_REMOTE_PROVIDERS, "perplexity"):
        raise ValueError(f"unknown provider: {provider!r}")

    cached = _catalog_cache.get(provider)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    if provider == "perplexity":
        models = list(_PERPLEXITY_CATALOG)
    else:
        models = await _fetch_remote_catalog(provider, api_key)
    _catalog_cache[provider] = (time.monotonic(), models)
    return models


def clear_catalog_cache() -> None:
    _catalog_cache.clear()
