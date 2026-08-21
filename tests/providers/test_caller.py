import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pydantic
import pytest
from pydantic_ai.models.test import TestModel

from dead_channel.providers.caller import (
    PydanticAICaller,
    RecordingCaller,
    persist_prompt,
)


class Verdict(pydantic.BaseModel):
    stance: str
    confidence: float


async def test_pydantic_caller_offline_via_test_model_instance():
    caller = PydanticAICaller(
        model_resolver=lambda _model_str: TestModel(
            custom_output_args={"stance": "de-escalate", "confidence": 0.5}
        )
    )
    verdict = await caller.call(
        "openai:gpt-5-mini", Verdict, "assess the hotline", call_site="assessment"
    )
    assert verdict == Verdict(stance="de-escalate", confidence=0.5)


async def test_pydantic_caller_test_model_string():
    caller = PydanticAICaller()
    verdict = await caller.call("test", Verdict, "assess", call_site="assessment")
    assert isinstance(verdict, Verdict)


async def test_recording_caller_pops_canned_outputs_in_order():
    caller = RecordingCaller(
        outputs={
            "openai:gpt-5-mini": [
                Verdict(stance="a", confidence=0.1),
                Verdict(stance="b", confidence=0.2),
            ]
        }
    )
    first = await caller.call("openai:gpt-5-mini", Verdict, "p1", call_site="s1")
    second = await caller.call("openai:gpt-5-mini", Verdict, "p2", call_site="s2")
    assert first.stance == "a"
    assert second.stance == "b"
    assert len(caller.calls) == 2
    assert caller.calls[0] == ("openai:gpt-5-mini", "p1", "s1")
    assert caller.calls[1] == ("openai:gpt-5-mini", "p2", "s2")


async def test_recording_caller_callable_fallback():
    caller = RecordingCaller(outputs=lambda model_str, prompt, call_site: f"{model_str}:{prompt}")
    out = await caller.call("openai:x", str, "ping", call_site="s")
    assert out == "openai:x:ping"


async def test_recording_caller_raises_when_canned_outputs_exhausted():
    caller = RecordingCaller(outputs={"openai:x": []})
    with pytest.raises(RuntimeError, match="no canned output"):
        await caller.call("openai:x", Verdict, "p", call_site="s")


async def test_recording_caller_raises_for_unlisted_model():
    caller = RecordingCaller(outputs={"openai:x": [Verdict(stance="a", confidence=0.1)]})
    with pytest.raises(RuntimeError, match="no canned output"):
        await caller.call("openrouter:y", Verdict, "p", call_site="s")


def test_persist_prompt_creates_dirs_and_expected_keys(tmp_path: Path):
    ts_before = datetime.now(UTC)
    path = persist_prompt(
        runs_dir=tmp_path,
        run_id="run-1",
        turn=7,
        call_site="assessment",
        model_str="openai:gpt-5-mini",
        prompt="assess the channel",
        response=Verdict(stance="hold", confidence=0.9),
    )
    ts_after = datetime.now(UTC)

    assert path.parent == tmp_path / "run-1" / "prompts"
    assert re.fullmatch(r"turn_007_assessment_[0-9a-f]{8}\.json", path.name)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["turn"] == 7
    assert data["call_site"] == "assessment"
    assert data["model"] == "openai:gpt-5-mini"
    assert data["prompt"] == "assess the channel"
    assert data["response"] == {"stance": "hold", "confidence": 0.9}
    written_ts = datetime.fromisoformat(data["ts"])
    assert ts_before <= written_ts <= ts_after


def test_persist_prompt_identical_calls_produce_distinct_files(tmp_path: Path):
    paths = [
        persist_prompt(
            runs_dir=tmp_path,
            run_id="run-1",
            turn=3,
            call_site="hos_decision",
            model_str="openai:gpt-5-mini",
            prompt="decide",
            response={"action": "hold"},
            state="northstar",
        )
        for _ in range(2)
    ]

    assert len({p.name for p in paths}) == 2
    for path in paths:
        assert re.fullmatch(r"turn_003_northstar_hos_decision_[0-9a-f]{8}\.json", path.name)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["turn"] == 3
        assert data["call_site"] == "hos_decision"
        assert data["prompt"] == "decide"
        assert data["response"] == {"action": "hold"}


def test_persist_prompt_omits_state_segment_when_none(tmp_path: Path):
    path = persist_prompt(
        runs_dir=tmp_path,
        run_id="run-1",
        turn=1,
        call_site="report_render",
        model_str="m",
        prompt="p",
        response=None,
    )
    assert re.fullmatch(r"turn_001_report_render_[0-9a-f]{8}\.json", path.name)


def test_persist_prompt_sanitizes_state_and_call_site(tmp_path: Path):
    path = persist_prompt(
        runs_dir=tmp_path,
        run_id="run-1",
        turn=2,
        call_site="../../evil/site",
        model_str="m",
        prompt="p",
        response=None,
        state="north star",
    )
    assert path.parent == tmp_path / "run-1" / "prompts"
    assert re.fullmatch(r"turn_002_north_star_{7}evil_site_[0-9a-f]{8}\.json", path.name)


async def test_recording_caller_accepts_arbitrary_payload_types():
    caller = RecordingCaller(outputs={"openai:x": ["plain text", {"k": 1}]})
    assert await caller.call("openai:x", str, "p1", call_site="s") == "plain text"
    assert await caller.call("openai:x", dict[str, Any], "p2", call_site="s") == {"k": 1}
