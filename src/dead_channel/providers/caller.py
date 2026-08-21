"""The single LLM call site: structured calls, prompt persistence, test doubles.

Every LLM interaction routes through a `Caller`. Live runs use PydanticAICaller
with per-model sampling rules; tests use RecordingCaller or pydantic-ai's
TestModel. Prompts are persisted per AGENTS.md prime directive 4.
"""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeVar, cast

import pydantic_ai
import pydantic_core
from pydantic_ai.models import Model
from pydantic_ai.output import PromptedOutput

from dead_channel.providers.catalog import ModelInfo, fetch_catalog
from dead_channel.providers.sampling import resolve_sampling

T = TypeVar("T")

_PROMPTS_SUBDIR = "prompts"
_RETRIES = 2
# Providers whose models commonly lack reliable tool-call structured output;
# they get JSON-schema-in-prompt instead of pydantic-ai's default tool output.
_PROMPTED_OUTPUT_PROVIDERS = frozenset({"openrouter", "perplexity"})
_CACHE_TTL_SECONDS = 300.0


class Caller(Protocol):
    def call(
        self, model_str: str, result_type: type[T], prompt: str, call_site: str
    ) -> Awaitable[T]: ...


def _provider_of(model_str: str) -> str:
    return model_str.split(":", 1)[0]


class PydanticAICaller:
    """Structured-output caller; agents are constructed per call to avoid state bleed.

    Sampling settings are resolved per model (temperature only where the model
    accepts it) and cached briefly so catalogs aren't refetched every call.
    """

    def __init__(self, model_resolver: Callable[[str], Model | str] | None = None) -> None:
        self._model_resolver = model_resolver or (lambda m: m)
        self._sampling_cache: dict[str, tuple[float, dict[str, object]]] = {}

    @staticmethod
    def _output_spec(model_str: str, result_type: type[object]) -> object:
        if _provider_of(model_str) in _PROMPTED_OUTPUT_PROVIDERS and result_type is not str:
            return PromptedOutput(result_type)
        return result_type

    async def _settings_for(self, model_str: str) -> dict[str, object]:
        import time

        cached = self._sampling_cache.get(model_str)
        if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        entry: ModelInfo | None = None
        provider = _provider_of(model_str)
        if provider in ("openai", "openrouter"):
            try:
                catalog = await fetch_catalog(provider)
                entry = next((info for info in catalog if info.id == model_str), None)
            except Exception:  # noqa: BLE001 - missing metadata degrades to defaults
                entry = None
        settings = await resolve_sampling(model_str, catalog_entry=entry)
        self._sampling_cache[model_str] = (time.monotonic(), settings)
        return settings

    async def call(self, model_str: str, result_type: type[T], prompt: str, call_site: str) -> T:
        agent = pydantic_ai.Agent(
            self._model_resolver(model_str),
            output_type=self._output_spec(model_str, result_type),
            retries=_RETRIES,
            model_settings=await self._settings_for(model_str),
        )
        result = await agent.run(prompt)
        return cast(T, result.output)


class RecordingCaller:
    """Test double: pops canned outputs in order or delegates to a callable."""

    def __init__(
        self,
        outputs: dict[str, list[object]] | Callable[[str, str, str], object],
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, str, str]] = []

    async def call(self, model_str: str, result_type: type[T], prompt: str, call_site: str) -> T:
        self.calls.append((model_str, prompt, call_site))
        if callable(self._outputs):
            return cast(T, self._outputs(model_str, prompt, call_site))
        queue = self._outputs.get(model_str, [])
        if not queue:
            raise RuntimeError(f"no canned output for model {model_str!r}")
        return cast(T, queue.pop(0))


def _sanitize(component: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", component)
    return cleaned or "_"


def persist_prompt(
    runs_dir: Path,
    run_id: str,
    turn: int,
    call_site: str,
    model_str: str,
    prompt: str,
    response: object,
    state: str | None = None,
) -> Path:
    parts = [f"turn_{turn:03d}"]
    if state is not None:
        parts.append(_sanitize(state))
    parts += [_sanitize(call_site), uuid.uuid4().hex[:8]]
    target = runs_dir / run_id / _PROMPTS_SUBDIR / f"{'_'.join(parts)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "turn": turn,
        "call_site": call_site,
        "model": model_str,
        "prompt": prompt,
        "response": response,
        "ts": datetime.now(UTC).isoformat(),
    }
    target.write_text(
        json.dumps(record, default=pydantic_core.to_jsonable_python), encoding="utf-8"
    )
    return target
