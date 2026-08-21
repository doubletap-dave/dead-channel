"""FastAPI surface: run creation/start, SSE streaming, catch-up, observer, providers."""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from dead_channel.core.config import ModelMatrix, RunConfig
from dead_channel.core.events import Event
from dead_channel.providers.catalog import ModelInfo, fetch_catalog
from dead_channel.providers.keys import KEY_ENV_NAMES, mask, read_keys, write_key
from dead_channel.server.runs import RunManager, live_caller_factory

_SSE_HEARTBEAT_SECONDS = 15
_CATALOG_KEY_ENV = dict(KEY_ENV_NAMES)

manager = RunManager()


def create_app(
    runs_dir: Path | None = None,
    caller_factory=None,
    env_file: Path | None = None,
) -> FastAPI:
    """App factory; tests inject runs_dir, a fake caller factory, and an env file."""
    app = FastAPI(title="Dead Channel", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    factory = caller_factory if caller_factory is not None else live_caller_factory
    local_manager = (
        manager if runs_dir is None else RunManager(runs_dir=runs_dir, caller_factory=factory)
    )
    app.state.run_manager = local_manager
    register_routes(app, local_manager, env_file)
    return app


def register_routes(app: FastAPI, mgr: RunManager, env_file: Path | None = None) -> None:
    class CreateRunBody(BaseModel):
        seed: int
        turns: int = 40
        model: str | None = None
        runId: str | None = None

    class SetKeyBody(BaseModel):
        provider: str
        value: str

    def _event_dict(event: Event) -> dict[str, object]:
        return {"seq": event.seq, "turn": event.turn, "type": event.type, "payload": event.payload}

    @app.post("/runs")
    async def create_run(body: CreateRunBody) -> dict[str, str]:
        matrix = ModelMatrix(default=body.model) if body.model else ModelMatrix()
        config = RunConfig(seed=body.seed, turns=body.turns, model_matrix=matrix)
        try:
            run_id = mgr.create(config, run_id=body.runId)
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"runId": run_id}

    @app.post("/runs/{run_id}/start")
    async def start_run(run_id: str) -> dict[str, str]:
        try:
            await mgr.start(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "started"}

    @app.post("/runs/{run_id}/stop")
    async def stop_run(run_id: str) -> dict[str, object]:
        try:
            return await mgr.stop(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/events")
    async def events(run_id: str, after: int = 0) -> list[dict[str, object]]:
        try:
            found = mgr.catch_up(run_id, after)
        except LookupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [_event_dict(event) for event in found]

    @app.get("/runs/{run_id}/stream")
    async def stream(run_id: str) -> EventSourceResponse:
        try:
            bus = mgr.stream(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        async def generator() -> AsyncIterator[dict[str, str]]:
            # Subscribe BEFORE catching up: anything appended meanwhile lands in the
            # queue, and cursor-dedup makes the overlap harmless. The stream ends
            # once run.ended/run.stopped has been delivered — a finished or halted
            # run has no more story until resumed.
            async with bus.subscribe() as sub:
                cursor = 0
                for event in mgr.catch_up(run_id, 0):
                    cursor = event.seq
                    yield {"data": json.dumps(_event_dict(event))}
                    if event.type in ("run.ended", "run.stopped"):
                        return
                async for event in sub:
                    if event.seq <= cursor:
                        continue
                    cursor = event.seq
                    yield {"data": json.dumps(_event_dict(event))}
                    if event.type in ("run.ended", "run.stopped"):
                        return

        return EventSourceResponse(generator(), ping=_SSE_HEARTBEAT_SECONDS)

    @app.get("/runs/{run_id}/observer/state")
    async def observer_state(run_id: str) -> dict[str, object]:
        try:
            return mgr.observer_state(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/providers/catalogs")
    async def catalogs(provider: str = "openrouter") -> list[ModelInfo]:
        env_name = _CATALOG_KEY_ENV.get(provider)
        if env_name is None:
            raise HTTPException(status_code=400, detail=f"unknown provider: {provider!r}")
        api_key = os.environ.get(env_name, "")
        if provider != "perplexity" and not api_key.strip():
            return []
        try:
            return await fetch_catalog(provider, api_key)
        except OSError:
            return []

    @app.get("/providers/keys")
    async def get_keys() -> dict[str, object]:
        raw = read_keys(env_file)
        return {
            "providers": {
                provider: {"set": bool(value), "masked": mask(value)}
                for provider, value in raw.items()
            }
        }

    @app.post("/providers/keys")
    async def post_key(body: SetKeyBody) -> dict[str, object]:
        try:
            updated = write_key(body.provider, body.value, env_file=env_file)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "providers": {
                provider: {"set": bool(value), "masked": mask(value)}
                for provider, value in updated.items()
            }
        }


app = create_app()
