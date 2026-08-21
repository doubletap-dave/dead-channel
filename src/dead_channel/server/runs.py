"""Run lifecycle for the API layer: create, start, stop, stream, catch-up, observe."""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from dead_channel.core.config import RunConfig
from dead_channel.engine.bus import EventBus
from dead_channel.engine.projections import project_beliefs, project_world
from dead_channel.engine.runner import TurnRunner
from dead_channel.engine.store import EventStore
from dead_channel.providers.caller import Caller

_RUNS_DIR = Path("runs")


class CallerFactory(Protocol):
    """Builds the Caller for a run. Tests inject fakes; production hits real LLMs."""

    def __call__(self) -> Caller: ...


def live_caller_factory() -> Caller:
    from dead_channel.providers.caller import PydanticAICaller

    return PydanticAICaller()


@dataclass
class RunHandle:
    config: RunConfig
    run_dir: Path
    bus: EventBus = field(default_factory=EventBus)
    task: asyncio.Task[None] | None = None
    runner: TurnRunner | None = None


class RunManager:
    """Owns in-memory handles for runs started this process; the log is the rest."""

    def __init__(
        self, runs_dir: Path = _RUNS_DIR, caller_factory: CallerFactory = live_caller_factory
    ) -> None:
        self._runs_dir = runs_dir
        self._caller_factory = caller_factory
        self._runs: dict[str, RunHandle] = {}

    def _run_dir(self, run_id: str) -> Path:
        if "/" in run_id or "\\" in run_id or run_id in (".", ".."):
            raise LookupError(f"invalid run id: {run_id!r}")
        return self._runs_dir / run_id

    def create(self, config: RunConfig, *, run_id: str | None = None) -> str:
        final_id = run_id or f"api-{config.seed}-{time.strftime('%Y%m%d-%H%M%S')}"
        run_dir = self._run_dir(final_id)
        if final_id in self._runs or (run_dir / "events.db").exists():
            raise KeyError(f"run id already exists: {final_id!r}")
        run_dir.mkdir(parents=True, exist_ok=True)
        self._runs[final_id] = RunHandle(config=config, run_dir=run_dir)
        return final_id

    def handle(self, run_id: str) -> RunHandle:
        handle = self._runs.get(run_id)
        if handle is None:
            raise KeyError(f"unknown or not-started-here run: {run_id!r}")
        return handle

    @staticmethod
    def _remaining_turns(handle: RunHandle) -> int:
        with EventStore(handle.run_dir / "events.db") as store:
            done = project_world(store.replay()).turn
        return max(0, handle.config.turns - done)

    async def start(self, run_id: str) -> dict[str, object]:
        handle = self.handle(run_id)
        if handle.task and not handle.task.done():
            return {"status": "already-running"}
        store = EventStore(handle.run_dir / "events.db")
        caller: Caller = self._caller_factory()
        runner = TurnRunner(store, handle.bus, caller, handle.config, self._runs_dir)
        handle.runner = runner
        # Resume semantics: config.turns is the TOTAL for the run, never a
        # top-up. Replaying the log tells us where the story actually stands.
        remaining = self._remaining_turns(handle)

        async def drive() -> None:
            try:
                await runner.run(remaining)
            except Exception as exc:
                # A dead run must be visible in the story, not just the console:
                # log run.failed so SSE clients (and replays) see why it halted.
                runner.log_failure(f"{type(exc).__name__}: {exc}")
            finally:
                store.close()

        handle.task = asyncio.create_task(drive())
        return {"status": "started", "remaining": remaining}

    async def stop(self, run_id: str) -> dict[str, object]:
        """Request a stop and return immediately: the in-flight turn (possibly a
        slow LLM call) finishes in the background, then the loop halts without
        run.ended and logs run.stopped instead."""
        handle = self.handle(run_id)
        if handle.runner is None or handle.task is None:
            return {"status": "not-running"}
        if handle.task.done():
            return {"status": "finished"}
        handle.runner.request_stop()
        return {"status": "stopping"}

    def stream(self, run_id: str) -> EventBus:
        return self.handle(run_id).bus

    def catch_up(self, run_id: str, after_seq: int) -> list:
        run_dir = self._run_dir(run_id)
        if not (run_dir / "events.db").exists():
            return []
        with EventStore(run_dir / "events.db") as store:
            return store.events_since(after_seq)

    def observer_state(self, run_id: str) -> dict[str, object]:
        run_dir = self._run_dir(run_id)
        if not (run_dir / "events.db").exists():
            raise LookupError(f"unknown run: {run_id!r}")
        with EventStore(run_dir / "events.db") as store:
            log = store.replay()
        world = project_world(log)
        return {
            "runId": run_id,
            "turn": world.turn,
            "trueWorld": world.model_dump(),
            "beliefs": {
                observer.value: project_beliefs(log, observer).model_dump()
                for observer in world.countries
            },
        }
