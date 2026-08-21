import asyncio
import json
from pathlib import Path

import httpx
import pytest

from dead_channel.core.types import ActionKind, ActionSpec, Assessment, Claim, Decision, Direction
from dead_channel.providers.caller import RecordingCaller
from dead_channel.server.app import create_app


def _fake_caller_factory():
    def _call(model_str: str, prompt: str, call_site: str) -> object:
        if call_site == "report_render":
            return "Routine product; no anomalies noted."
        if call_site == "hos_decision":
            return Decision(action=ActionSpec(kind=ActionKind.STAY_SILENT), rationale="holding")
        role = call_site.removeprefix("assessment_")
        return Assessment(
            role=role,
            interpretation="steady",
            claim=Claim(subject="enemy.readiness", direction=Direction.STABLE, magnitude=5.0),
            recommended_action=ActionSpec(kind=ActionKind.STAY_SILENT),
            urgency=2,
        )

    return lambda: RecordingCaller(_call)


class _GatedCaller:
    """Canned Caller whose first HoS decision awaits an asyncio.Event, parking the
    run mid-turn so a stop can be requested deterministically. Shares one gate
    across every instance from the same factory, so resumed runs never park."""

    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate
        self._released = gate.is_set()

    async def call(self, model_str: str, result_type: type, prompt: str, call_site: str) -> object:
        if call_site == "hos_decision" and not self._released:
            self._released = True
            await self._gate.wait()
        if call_site == "report_render":
            return "Routine product; no anomalies noted."
        if call_site == "hos_decision":
            return Decision(action=ActionSpec(kind=ActionKind.STAY_SILENT), rationale="holding")
        role = call_site.removeprefix("assessment_")
        return Assessment(
            role=role,
            interpretation="steady",
            claim=Claim(subject="enemy.readiness", direction=Direction.STABLE, magnitude=5.0),
            recommended_action=ActionSpec(kind=ActionKind.STAY_SILENT),
            urgency=2,
        )


@pytest.fixture(autouse=True)
def _scrub_key_env(monkeypatch):
    # Other tests (and this machine's .env) leak keys through os.environ; the
    # keys endpoints must be judged against their own env file only.
    import os

    for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "PPLX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
        os.environ.pop(name, None)
    yield


@pytest.fixture
async def client(tmp_path: Path):
    test_app = create_app(runs_dir=tmp_path, caller_factory=_fake_caller_factory())
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def keys_client(tmp_path: Path):
    test_app = create_app(runs_dir=tmp_path / "runs", env_file=tmp_path / ".env")

    return test_app, tmp_path / ".env"


async def _wait_for_run_end(client, run_id: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for _ in range(200):
        events = (await client.get(f"/runs/{run_id}/events")).json()
        if events and events[-1]["type"] == "run.ended":
            return events
        await asyncio.sleep(0.1)
    raise AssertionError(f"run {run_id} never ended; got {[e['type'] for e in events]}")


async def test_create_start_and_catch_up(client):
    created = await client.post("/runs", json={"seed": 5, "turns": 2, "runId": "t-run"})
    assert created.status_code == 200
    assert created.json() == {"runId": "t-run"}

    assert (await client.post("/runs/t-run/start")).status_code == 200

    types = [e["type"] for e in await _wait_for_run_end(client, "t-run")]
    assert types[-1] == "run.ended"
    assert types.count("turn.started") == 2
    assert types.count("decision.made") == 4

    after = (await client.get("/runs/t-run/events?after=2")).json()
    assert all(e["seq"] > 2 for e in after)


async def test_stream_replays_then_follows(client):
    await client.post("/runs", json={"seed": 6, "turns": 2, "runId": "sse"})
    assert (await client.post("/runs/sse/start")).status_code == 200
    await _wait_for_run_end(client, "sse")

    seen = []
    transport = client._transport
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as raw,
        raw.stream("GET", "/runs/sse/stream") as response,
    ):
        async for chunk in response.aiter_text():
            for line in chunk.splitlines():
                if line.startswith("data:"):
                    seen.append(json.loads(line[5:].strip()))
            if len(seen) >= 5:
                break
    assert seen[0]["type"] == "run.started"
    assert [e["seq"] for e in seen] == sorted(e["seq"] for e in seen)


async def test_create_conflicts_on_existing_id(client):
    body = {"seed": 1, "turns": 1, "runId": "dup"}
    assert (await client.post("/runs", json=body)).status_code == 200
    assert (await client.post("/runs", json=body)).status_code == 409


async def test_unknown_run_404s(client):
    assert (await client.post("/runs/nope/start")).status_code == 404
    assert (await client.post("/runs/nope/stop")).status_code == 404
    assert (await client.get("/runs/nope/observer/state")).status_code == 400


async def test_observer_state_shape(client):
    await client.post("/runs", json={"seed": 9, "turns": 1, "runId": "obs"})
    await client.post("/runs/obs/start")
    await _wait_for_run_end(client, "obs")
    state = (await client.get("/runs/obs/observer/state")).json()
    assert state["runId"] == "obs"
    assert set(state["trueWorld"]["countries"]) == {"northstar", "vesper"}
    assert set(state["beliefs"]) == {"northstar", "vesper"}


def _gated_caller_factory():
    gate = asyncio.Event()

    def _factory() -> _GatedCaller:
        return _GatedCaller(gate)

    return _factory


async def test_stop_then_resume_completes_at_total_turns(tmp_path):
    """Stop mid-turn; resume must target the run TOTAL (3), not a fresh 3 turns."""
    test_app = create_app(runs_dir=tmp_path, caller_factory=_gated_caller_factory())
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        await client.post("/runs", json={"seed": 11, "turns": 3, "runId": "stoppable"})
        await client.post("/runs/stoppable/start")

        # Wait until turn 1 has started and the runner is parked inside its
        # first HoS call (the gated caller), then request the stop.
        for _ in range(200):
            events = (await client.get("/runs/stoppable/events")).json()
            if any(e["type"] == "turn.started" for e in events):
                break
            await asyncio.sleep(0.05)
        assert any(e["type"] == "turn.started" for e in events), "run never started"

        stopped = (await client.post("/runs/stoppable/stop")).json()
        assert stopped["status"] == "stopping", stopped

        # Release the gate; the in-flight turn finishes, then the loop halts and
        # logs run.stopped (never run.ended). The gated caller parks the runner
        # at the first HoS decision of turn 1, so the released turn completes
        # and no further turns may run.
        handle = test_app.state.run_manager.handle("stoppable")
        caller = handle.runner.caller if handle.runner else None
        assert caller is not None, "runner missing"
        while hasattr(caller, "_inner"):
            caller = caller._inner  # unwrap telemetry decorator
        assert hasattr(caller, "_gate"), "gated caller missing"
        caller._gate.set()  # noqa: SLF001 - test reaches into its own double
        for _ in range(200):
            events_after_stop = (await client.get("/runs/stoppable/events")).json()
            if any(e["type"] == "run.stopped" for e in events_after_stop):
                break
            await asyncio.sleep(0.05)
        assert handle.task.done(), "run did not halt after stop request"
        assert not any(e["type"] == "run.ended" for e in events_after_stop), (
            "stopped run must not emit run.ended"
        )
        turns_done = [e for e in events_after_stop if e["type"] == "turn.started"]
        assert len(turns_done) <= 1, f"stop must halt between turns; got {len(turns_done)}"

        assert (await client.post("/runs/stoppable/start")).json() == {"status": "started"}
        final = await _wait_for_run_end(client, "stoppable")
        assert [e["type"] for e in final].count("turn.started") <= 3
        assert final[-1]["payload"]["turn"] == 3


async def test_stop_without_start_is_not_running(client):
    await client.post("/runs", json={"seed": 12, "turns": 2, "runId": "idle"})
    assert (await client.post("/runs/idle/stop")).json() == {"status": "not-running"}


class _ExplodingCaller:
    """Caller whose first real call raises — simulates a missing/invalid key."""

    async def call(self, model_str: str, result_type: type, prompt: str, call_site: str) -> object:
        raise RuntimeError("Set the `OPENROUTER_API_KEY` environment variable")

    async def fail(self) -> None:
        return None


async def test_caller_failure_surfaces_as_run_failed(tmp_path):
    """A dead LLM call must land in the event log as run.failed, not vanish."""
    test_app = create_app(runs_dir=tmp_path, caller_factory=lambda: _ExplodingCaller())
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        await client.post("/runs", json={"seed": 13, "turns": 2, "runId": "doomed"})
        await client.post("/runs/doomed/start")
        for _ in range(200):
            events = (await client.get("/runs/doomed/events")).json()
            if any(e["type"] == "run.failed" for e in events):
                break
            await asyncio.sleep(0.05)
        failed = [e for e in events if e["type"] == "run.failed"]
        assert failed, f"run.failed missing; got {[e['type'] for e in events]}"
        assert "OPENROUTER_API_KEY" in str(failed[0]["payload"]["error"])
        # And the failure is replayable for the observer endpoint.
        state = (await client.get("/runs/doomed/observer/state")).json()
        assert state["runId"] == "doomed"


async def test_catalog_unknown_provider_400(client):
    assert (await client.get("/providers/catalogs", params={"provider": "nope"})).status_code == 400


async def test_catalog_without_key_returns_empty(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    response = await client.get("/providers/catalogs", params={"provider": "openrouter"})
    assert response.status_code == 200
    assert response.json() == []


async def test_keys_roundtrip_masked(keys_client):
    app, env_file = keys_client
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        empty = (await ac.get("/providers/keys")).json()["providers"]
        assert all(not entry["set"] for entry in empty.values())

        posted = (
            await ac.post(
                "/providers/keys",
                json={"provider": "openrouter", "value": "sk-or-v1-abcdef1234567890"},
            )
        ).json()["providers"]
        assert posted["openrouter"]["set"] is True
        assert posted["openrouter"]["masked"] is not None
        assert "sk-or-v1-abcdef1234567890" not in json.dumps(posted)

        on_disk = env_file.read_text(encoding="utf-8")
        assert "OPENROUTER_API_KEY=sk-or-v1-abcdef1234567890" in on_disk


async def test_keys_rejects_unknown_provider(keys_client):
    app, _ = keys_client
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/providers/keys", json={"provider": "nope", "value": "x"})
        assert response.status_code == 400
