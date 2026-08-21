# Dead Channel

A Cold War-style AI simulation about distrust, deception, incomplete information, and escalation.

Two AI-controlled rival states — the **Northstar Republic** and the **Vesper Union** — run under conditions of uncertainty. Neither side sees the truth. They see estimates, probabilities, rumors, stale satellite reads, intercepted chatter, and the occasional lie planted by the enemy. Intelligent actors make high-stakes decisions on incomplete, noisy, delayed, manipulated, or false information — and rationally drift toward disaster.

**Optimization target:** uncertainty + personality + memory + deception + consequences = stories we didn't write.

## How it works

- **Mechanical intelligence pipeline.** Every report is a deterministic transform of true world state plus seeded noise, source reliability, and staleness. Enemy deception actions mutate the observation stream itself. An LLM renders the payload into prose — and never sees the truth.
- **Four independent agents per state.** Head of State, Intelligence Chief, Military Chief, Diplomat. Advisors assess in isolation, disagree structurally, and file dissents when overridden.
- **Memory that matters.** Every recommendation makes a falsifiable claim. Claims get scored as truth emerges; advisor trust rises and falls with their track record.
- **Emergent escalation.** No scripted ladder. Perceived threat drives behavior; behavior drives the enemy's perceived threat. DEFCON is a readout of the spiral, not a script.
- **Omniscient observer.** You hold the truth while the states fumble. Watch live, or replay any run turn by turn.

Everything is event-sourced: a run is an append-only SQLite log (`runs/<run-id>/events.db`), every LLM prompt/response is archived alongside it (`runs/<run-id>/prompts/`), and any run can be replayed or resumed.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs and manages Python for you)
- Node 20+ (only needed for the web viewer)
- At least one provider API key: OpenRouter, OpenAI, and/or Perplexity

Dead Channel is **live-LLM only** — there are no canned responses. Every agent mind is a real model call.

## Quickstart

1. Start the full stack (FastAPI + SSE on :8000, Vite viewer on :5173):

   ```bash
   uv run dead-channel-dev
   ```

2. Open http://localhost:5173. First run only: `npm install` inside `viewer/`.
3. In the config screen:
   - Click **load openrouter models** (or openai / perplexity) to pull the *live* model catalog from that provider — nothing is hardcoded.
   - Set **API Keys** right there in the UI; keys are saved to your gitignored `.env` and shown only masked afterwards.
   - Pick or type a global default model (e.g. `openrouter:stealth/ox-alpha`), optionally override models per state/per role to pit LLMs against each other.
4. Hit **▶ Start Run** and watch the simulation stream onto the map, feeds, and timeline. **■ Stop** halts the run cleanly between turns; **▶ Resume** picks the same run back up from its log.

Prefer editing files? Put keys in `.env` manually (`cp .env.example .env`) — but note uvicorn doesn't auto-load `.env`, so launch with:

```bash
uv run --env-file .env dead-channel-dev
```

### Temperature rules per model

Sampling is resolved per model from provider metadata: temperature is sent **only** when the model's catalog entry advertises `temperature` support (`supported_parameters`). Reasoning families (gpt-5, o1/o3/o4) never receive it regardless. Everything else gets the configured default (0.7). This lives in `src/dead_channel/providers/sampling.py`.

### The CLI

```bash
uv run --env-file .env dead-channel --model openrouter:stealth/ox-alpha --seed 3 --turns 12
```

You'll get a live event stream in the terminal:

```
[  34] T2   northstar decides: verify_report {'target_attribute': 'military'} -- ...
[  39] T2   vesper threat=18.4 [####................]
*** DEFCON 3 - ROUND HOUSE !!!
```

A full turn is ~10–20 LLM calls across both states. A run is resumable: rerun with the same `--run-id` and the engine rebuilds state from the log and continues.

Each run writes to `runs/<run-id>/` — `events.db` (the full log) plus `prompts/` (every prompt/response pair as JSON).

### Pitting two states' minds against each other

Set the global default to one model and override the other state per-role (or wholesale via its state-level `default`) — in the UI under the state's details, or in Python:

```python
import asyncio
from pathlib import Path

from dead_channel.core.config import ModelMatrix, RunConfig
from dead_channel.engine.bus import EventBus
from dead_channel.engine.runner import TurnRunner
from dead_channel.engine.store import EventStore
from dead_channel.providers.caller import PydanticAICaller


async def main() -> None:
    config = RunConfig(
        seed=42,
        turns=20,
        model_matrix=ModelMatrix(
            default="openrouter:stealth/ox-alpha",
            states={
                # every Vesper mind runs on a different model:
                "vesper": {"default": "openrouter:anthropic/claude-sonnet-4.5"},
            },
        ),
    )
    runs_dir = Path("runs")
    (runs_dir / "pit").mkdir(parents=True, exist_ok=True)
    with EventStore(runs_dir / "pit" / "events.db") as store:
        runner = TurnRunner(store, EventBus(), PydanticAICaller(), config, runs_dir)
        await runner.run(20)


asyncio.run(main())
```

Run it with `uv run --env-file .env python pit.py`. Both states share your OpenRouter key; each state's roles resolve their model through role → state → global fallback.

### The API itself

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/runs` | create run (seed, turns, model) → `runId` |
| POST | `/runs/{id}/start` | start (or resume) the turn loop in the background |
| POST | `/runs/{id}/stop` | request a stop; the in-flight turn finishes, then the run halts (`run.stopped`) |
| GET | `/runs/{id}/stream` | SSE event stream (replays from seq 0, ends after `run.ended`/`run.stopped`) |
| GET | `/runs/{id}/events?after=N` | catch-up polling |
| GET | `/runs/{id}/observer/state` | omniscient projection (true world + beliefs) |
| GET | `/providers/catalogs?provider=openrouter` | live model catalog from the provider |
| GET | `/providers/keys` | which providers have keys (masked, e.g. `sk-or-…abcd`) |
| POST | `/providers/keys` | save/update a provider key (persists to `.env`, hot-reloads process env) |

Keys are never returned in clear text over the API — only presence and a masked preview.

## Testing

```bash
uv run pytest -q          # full suite (316 tests, fully offline)
uv run ruff check src tests
uv run ruff format --check src tests
```

Viewer lint/build:

```bash
cd viewer && npm run lint && npm run build
```

The test suite needs no API keys and makes no network calls — LLM call sites are exercised through an injected fake caller (server/CLI use the same dependency-injection seam), and engine tests use `RecordingCaller`.

## Architecture in one paragraph

An append-only SQLite event log is the single source of truth. Each turn: the engine generates noisy observations of the *true* world state, an LLM renders them into prose (seeing only the distorted payload, never the truth), four advisors per state assess their filtered packet independently and file falsifiable claims, each Head of State integrates advisor recommendations weighted by earned trust and picks one action, actions resolve deterministically into effects/signals/planted intel, perceived threat updates from observed signals, and DEFCON emerges from the composite. Restarting mid-run replays the log and resumes cleanly between turns. Agents never touch provider APIs directly; every LLM call goes through one `Caller` abstraction (see `src/dead_channel/providers/caller.py`) whose prompts are all persisted, whose model catalogs are fetched dynamically from each provider, and whose sampling settings respect what each model actually supports.

## Status & layout

V0 implementation in progress — design spec: [docs/superpowers/specs/2026-08-20-dead-channel-v0-design.md](docs/superpowers/specs/2026-08-20-dead-channel-v0-design.md).

```
src/dead_channel/
  core/       # immutable types, seeded RNG, event envelope, run config
  engine/     # world, observations, threat, ledger, resolution, TurnRunner
  agents/     # personalities, packets, prompts, LLM call sites
  providers/  # dynamic catalogs, key management, sampling rules, Caller
  server/     # FastAPI + SSE surface
  cli/        # terminal rendering, headless entry, unified dev launcher
viewer/       # React + MapLibre ops-room UI (Vite)
tests/        # offline pytest suite mirroring src layout
```
