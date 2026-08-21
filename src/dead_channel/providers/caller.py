"""The single LLM call site: structured calls, prompt persistence, test doubles.

Every LLM interaction in Dead Channel routes through a `Caller`. Prompts are
persisted per AGENTS.md prime directive 4; PydanticAI is used only here.
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

T = TypeVar("T")

_PROMPTS_SUBDIR = "prompts"
_RETRIES = 2


class Caller(Protocol):
    def call(
        self, model_str: str, result_type: type[T], prompt: str, call_site: str
    ) -> Awaitable[T]: ...


class PydanticAICaller:
    """Structured-output caller; agents are constructed per call to avoid state bleed."""

    def __init__(self, model_resolver: Callable[[str], Model | str] = lambda m: m) -> None:
        self._model_resolver = model_resolver

    async def call(self, model_str: str, result_type: type[T], prompt: str, call_site: str) -> T:
        agent = pydantic_ai.Agent(
            self._model_resolver(model_str),
            output_type=result_type,
            retries=_RETRIES,
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
