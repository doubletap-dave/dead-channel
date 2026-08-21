import asyncio
import json
from pathlib import Path

import pytest

from dead_channel.cli.app import main
from dead_channel.core.events import Event
from dead_channel.core.types import (
    ActionKind,
    ActionSpec,
    Assessment,
    Claim,
    Decision,
    Direction,
)
from dead_channel.engine.store import EventStore
from dead_channel.providers.caller import RecordingCaller, persist_prompt


def _run_log(runs_dir, run_id):
    with EventStore(runs_dir / run_id / "events.db") as store:
        return store.replay()


def _fake_caller_factory():
    def _call(model_str: str, prompt: str, call_site: str) -> object:
        if call_site == "report_render":
            return "Routine product; no anomalies noted."
        if call_site == "hos_decision":
            return Decision(
                action=ActionSpec(kind=ActionKind.STAY_SILENT),
                rationale="holding posture",
            )
        role = call_site.removeprefix("assessment_")
        return Assessment(
            role=role,
            interpretation="steady",
            claim=Claim(subject="enemy.readiness", direction=Direction.STABLE, magnitude=5.0),
            recommended_action=ActionSpec(kind=ActionKind.STAY_SILENT),
            urgency=2,
        )

    caller = RecordingCaller(_call)
    return lambda: caller


def test_cli_run_with_injected_caller(tmp_path, capsys):
    exit_code = main(
        ["--seed", "7", "--turns", "3", "--runs-dir", str(tmp_path), "--model", "test"],
        caller_factory=_fake_caller_factory(),
    )
    assert exit_code == 0
    log = _run_log(tmp_path, _latest_run_id(tmp_path))
    types = [event.type for event in log]
    assert types.count("turn.started") == 3
    assert types[-1] == "run.ended"
    assert types.count("decision.made") == 6
    assert types.count("report.rendered") > 0
    assert types.count("threat.updated") == 6
    out = capsys.readouterr().out
    assert "TURN" in out and "decides:" in out


def _latest_run_id(runs_dir):
    return sorted(path.name for path in runs_dir.iterdir())[-1]


def test_console_formats_events():
    from dead_channel.cli.console_impl import defcon_banner, format_event

    report = Event(
        seq=1,
        turn=2,
        type="report.rendered",
        payload={
            "observer": "northstar",
            "about": "vesper",
            "attribute": "readiness",
            "value": 61.5,
            "confidence": 0.7,
            "age_turns": 1,
            "source": "sigint",
            "text": "Vesper readiness climbing.",
        },
    )
    line = format_event(report)
    assert line is not None and "sigint on vesper.readiness = 61.5" in line
    assert format_event(Event(seq=2, turn=2, type="world.ticked", payload={})) is None
    assert "DEFCON 2" in defcon_banner(2) and "FAST PACE" in defcon_banner(2)


def test_prompt_persistence_writes_files(tmp_path):
    target = persist_prompt(
        tmp_path,
        "run-x",
        turn=3,
        call_site="hos_decision",
        model_str="m",
        prompt="p",
        response={"a": 1},
        state="northstar",
    )
    record = json.loads(Path(target).read_text(encoding="utf-8"))
    assert record["call_site"] == "hos_decision" and record["response"] == {"a": 1}


def test_cli_requires_model():
    with pytest.raises(SystemExit):
        main(["--turns", "1"])


def test_recording_caller_shapes():
    caller = RecordingCaller(
        lambda model_str, prompt, call_site: (
            "prose"
            if call_site == "report_render"
            else Decision(action=ActionSpec(kind=ActionKind.STAY_SILENT), rationale="r")
        )
    )

    async def collect():
        prose = await caller.call("m", str, "<packet>readiness 55</packet>", "report_render")
        decision = await caller.call("m", Decision, "", "hos_decision")
        return prose, decision

    prose, decision = asyncio.run(collect())
    assert prose == "prose"
    assert decision.action.kind is ActionKind.STAY_SILENT
