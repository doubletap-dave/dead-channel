# AGENTS.md — Dead Channel

Rules for every AI agent (and human) writing code in this repo. Read fully before touching code.

**Source of truth for behavior:** `docs/superpowers/specs/2026-08-20-dead-channel-v0-design.md`. If code and spec disagree, the spec wins — flag the conflict, don't silently pick one.

## Prime Directives (architecture invariants)

1. **Truth isolation.** Agent-facing code must never access `TrueWorldState`. Agents receive assembled context packets, period. Push, never pull — no tools, no retrieval APIs, no query access in agent code. A leak is a bug of the highest severity.
2. **Event-sourced.** Every state mutation goes through the append-only event log (`engine/store.py`). No direct writes to projections. Projections are always rebuildable from events.
3. **Deterministic engine.** The mechanical engine (observation, resolution, threat, ledger) uses only seeded RNG from `core/rng.py`. No global `random`, no wall-clock time in engine logic, no dict-ordering dependence. LLM calls exist only in the rendering and assessment layers and must be mockable.
4. **Prompts are persisted.** Every LLM call's full prompt is written to the run directory. If you add an LLM call, you persist its prompt.
5. **PydanticAI for LLM calls only.** No agent-framework orchestration. The `TurnRunner` owns all flow. Never add ambient agent state, shared memory, or inter-agent channels.

## Code Rules

- **DRY.** Before writing anything, search for an existing implementation. Shared concepts live in `core/`. Duplicated logic is a review defect.
- **SRP.** One module, one responsibility. **Keep files around 200 LOC where feasible** — split before you grow past it.
- **Modular.** Communicate through the typed contracts in `core/`, not by reaching into other modules' internals.
- **Modern tooling only.** Python 3.14 + uv + Pydantic v2 + PydanticAI + FastAPI. React 19 + Vite + TypeScript + MapLibre. No deprecated APIs (`datetime.utcnow` → `datetime.now(UTC)`, no `distutils`, no legacy class components). If a linter flags deprecated usage, fix it, don't suppress it.
- **Type hints everywhere.** Pydantic models for all data crossing module or network boundaries. `ruff check` and `ruff format` clean is the bar for commit.
- **No narrating comments.** Comments explain non-obvious intent or constraints only.
- **TDD.** Failing test first, minimal implementation, refactor. Engine tests must be pure and fast (no network, no LLM).

## Commands

```powershell
# Python (root)
uv sync                      # install deps
uv run pytest                # all tests
uv run pytest tests/engine/test_threat.py -v
uv run ruff check . ; uv run ruff format .
uv run uvicorn dead_channel.server.app:app --reload --port 8000

# Viewer
cd viewer
npm install
npm run dev                  # Vite dev server
npm run build
npm run gen:api              # regenerate API types from backend OpenAPI (backend must be running)

# Full pipeline smoke (no LLM keys needed)
uv run python -m dead_channel.eval.smoke
```

## Git

- Conventional commits: `feat:`, `test:`, `fix:`, `docs:`, `chore:`, `refactor:`.
- **Identity:** this machine's git config has a private email that GitHub rejects on push. Always commit with the noreply identity:

```powershell
git -c user.name="Dave M." -c user.email="25110228+doubletap-dave@users.noreply.github.com" commit -m "feat: ..."
```

## Parallel Execution

- Tasks are organized in waves in `docs/plans/2026-08-20-dead-channel-v0.md`. Within a wave, tasks touch **disjoint files** — only touch files listed in your task.
- `core/` is frozen after Wave 1. Changes to core contracts require coordinating with all parallel workers — don't do it unilaterally.
- Never edit another task's files to "fix" something; report it instead.

## Secrets

- API keys live in `.env` (gitignored): `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `PPLX_API_KEY`. Never commit keys. `.env.example` documents the shape.
