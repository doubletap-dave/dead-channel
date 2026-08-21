"""Headless Dead Channel: run the simulation against live LLMs from the terminal."""

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from dead_channel.cli.console_impl import defcon_banner, format_event
from dead_channel.core.config import ModelMatrix, RunConfig
from dead_channel.engine.bus import EventBus, Subscription
from dead_channel.engine.projections import project_world
from dead_channel.engine.runner import TurnRunner
from dead_channel.engine.store import EventStore

_LIVE_TIMEOUT_SECONDS = 3600.0


class CallerFactory(Protocol):
    def __call__(self) -> object: ...


def default_caller_factory() -> object:
    from dead_channel.providers.caller import PydanticAICaller

    return PydanticAICaller()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dead-channel",
        description="Run the Dead Channel simulation headlessly (live LLMs).",
        epilog=(
            "examples:\n"
            "  dead-channel --model openrouter:stealth/ox-alpha --seed 3 --turns 12\n"
            "  dead-channel --run-id my-run            # resume an existing run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--seed", type=int, default=1, help="world seed (default: 1)")
    parser.add_argument("--turns", type=int, default=12, help="total turns for this run")
    parser.add_argument(
        "--model",
        required=True,
        metavar="ID",
        help="global model id, e.g. openrouter:stealth/ox-alpha",
    )
    parser.add_argument("--run-id", default=None, help="run directory name (default: auto)")
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("runs"),
        help="parent directory for run artifacts (default: ./runs)",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the event stream")
    return parser.parse_args(argv)


def _print(line: str) -> None:
    print(line, flush=True)


async def _pump(subscription: Subscription, turns: int, quiet: bool) -> None:
    last_defcon = 5
    async with subscription as sub:
        async for event in sub:
            if event.type == "run.ended":
                sub.close()
                break
            if quiet:
                continue
            line = format_event(event)
            if line:
                _print(f"[{event.seq:4d}] T{event.turn:<3d} {line}")
            new_defcon = event.payload.get("defcon") if event.type == "threat.updated" else None
            if isinstance(new_defcon, int) and new_defcon != last_defcon:
                _print(defcon_banner(new_defcon))
                last_defcon = new_defcon


async def _execute(args: argparse.Namespace, caller_factory: CallerFactory | None) -> int:
    config = RunConfig(
        seed=args.seed, turns=args.turns, model_matrix=ModelMatrix(default=args.model)
    )
    run_id = args.run_id or f"cli-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir = args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with EventStore(run_dir / "events.db") as store:
        resumed_turn = project_world(store.replay()).turn
        remaining = max(0, args.turns - resumed_turn)
        if resumed_turn:
            _print(f"resuming '{run_id}' at turn {resumed_turn}; {remaining} turns to go")
        _print(f"run '{run_id}' | seed={config.seed} | model={config.model_matrix.default}")

        bus = EventBus()
        caller = caller_factory() if caller_factory else default_caller_factory()
        runner = TurnRunner(store, bus, caller, config, args.runs_dir)
        pump_task = asyncio.create_task(_pump(bus.subscribe(), args.turns, args.quiet))
        try:
            await asyncio.wait_for(runner.run(remaining), timeout=_LIVE_TIMEOUT_SECONDS)
        finally:
            await asyncio.wait({pump_task}, timeout=10)

    _print(f"done. log: {run_dir / 'events.db'} | prompts: {run_dir / 'prompts'}")
    return 0


def main(argv: Sequence[str] | None = None, *, caller_factory: CallerFactory | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_execute(args, caller_factory))
    except KeyboardInterrupt:
        _print("interrupted; state is safe on disk — rerun with the same --run-id to resume")
        return 130


if __name__ == "__main__":
    sys.exit(main())
