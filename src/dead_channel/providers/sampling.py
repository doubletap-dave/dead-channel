"""Per-model sampling rules: temperature only where the model accepts it.

OpenRouter exposes `supported_parameters` per model, so that is the source of
truth. Reasoning models (o-series, gpt-5 family) reject temperature outright —
they get no temperature even when a provider forgets to say so. Everything else
gets the default.
"""

import os
from typing import Final

import pydantic

from dead_channel.providers.catalog import ModelInfo, fetch_catalog

DEFAULT_TEMPERATURE: Final = 0.7
_REASONING_MARKERS: Final = ("gpt-5", "o1", "o3", "o4")


class SamplingRules(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    default_temperature: float = DEFAULT_TEMPERATURE


def _is_reasoning_model(model_id: str) -> bool:
    local = model_id.split(":", 1)[-1].lower()
    return any(marker in local for marker in _REASONING_MARKERS)


async def _model_info(model_str: str, api_keys: dict[str, str]) -> ModelInfo | None:
    provider = model_str.split(":", 1)[0]
    if provider not in ("openai", "openrouter"):
        return None
    env_name = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(provider)
    api_key = api_keys.get(provider) or (os.environ.get(env_name, "") if env_name else "")
    try:
        catalog = await fetch_catalog(provider, api_key or None)
    except Exception:  # noqa: BLE001 - rules degrade gracefully to defaults
        return None
    for info in catalog:
        if info.id == model_str:
            return info
    return None


async def resolve_sampling(
    model_str: str,
    *,
    catalog_entry: ModelInfo | None = None,
    api_keys: dict[str, str] | None = None,
    rules: SamplingRules | None = None,
) -> dict[str, object]:
    """Settings dict for pydantic-ai's model_settings; {} means provider default."""
    effective_rules = rules or SamplingRules()
    entry = catalog_entry
    if entry is None and not _is_reasoning_model(model_str):
        entry = await _model_info(model_str, api_keys or {})
    if entry is None:
        # No metadata (or known reasoning model): omit temperature entirely.
        return {}
    params = entry.supported_parameters
    # Unknown metadata -> omit: an unsupported-argument 400 kills a live call,
    # while a missing temperature never does.
    if params is None or "temperature" not in params:
        return {}
    return {"temperature": effective_rules.default_temperature}
