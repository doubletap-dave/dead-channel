"""Renderer tests: prose call site passes only the payload-derived prompt."""

from typing import TypeVar

from dead_channel.agents.renderer import render_report
from dead_channel.core.types import IntelPayload, IntelSource, StateID
from dead_channel.providers.caller import RecordingCaller

T = TypeVar("T")

MODEL = "openai:gpt-5-mini"
PROSE = "Satellite imagery suggests sustained activity at the northern depot."


def payload() -> IntelPayload:
    return IntelPayload(
        attribute="readiness",
        value=42.0,
        confidence=0.8,
        age_turns=2,
        source=IntelSource.IMINT,
        about=StateID.VESPER,
    )


class TypeCapturingCaller:
    """RecordingCaller does not record result_type, so capture it separately."""

    def __init__(self, output: object) -> None:
        self._output = output
        self.calls: list[tuple[str, str, str]] = []
        self.result_types: list[object] = []

    async def call(self, model_str: str, result_type: type[T], prompt: str, call_site: str) -> T:
        self.calls.append((model_str, prompt, call_site))
        self.result_types.append(result_type)
        return self._output  # type: ignore[no-any-return]


async def test_render_report_returns_prose():
    caller = RecordingCaller(outputs={MODEL: [PROSE]})
    assert await render_report(caller, MODEL, payload()) == PROSE


async def test_prompt_carries_payload_data_and_call_site():
    caller = RecordingCaller(outputs={MODEL: [PROSE]})
    await render_report(caller, MODEL, payload())
    model_str, prompt, call_site = caller.calls[0]
    assert call_site == "report_render"
    assert str(payload().value) in prompt
    assert "readiness" in prompt
    assert "imint" in prompt
    assert "vesper" in prompt


async def test_model_str_passed_through():
    caller = RecordingCaller(outputs={MODEL: [PROSE]})
    await render_report(caller, MODEL, payload())
    assert caller.calls[0][0] == MODEL


async def test_result_type_is_plain_str():
    double = TypeCapturingCaller(PROSE)
    await render_report(double, MODEL, payload())
    assert double.result_types == [str]
