# Dead Channel V0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this task-by-task, or superpowers:subagent-driven-development for parallel subagent execution. Follow AGENTS.md at all times.

**Goal:** Build Dead Channel V0 per `docs/superpowers/specs/2026-08-20-dead-channel-v0-design.md`: a deterministic event-sourced simulation engine, four isolated LLM agents per state, mechanical intelligence pipeline, and a live CRT-styled observer UI with a real-Earth map.

**Architecture:** Event-sourced SQLite core; agents as pure functions of assembled context packets (push, never pull); PydanticAI for LLM calls only; custom TurnRunner pipeline; FastAPI + SSE; React 19 + Vite + MapLibre viewer. Waves of disjoint-file tasks for maximum parallelism.

**Tech Stack:** Python 3.14 + uv, Pydantic v2, PydanticAI, FastAPI, sse-starlette, pytest, ruff. React 19, Vite, TypeScript, MapLibre, zustand, openapi-typescript.

---

## Parallel Execution Protocol

- Tasks are grouped into **waves**. Within a wave, tasks touch **disjoint files** — dispatch as parallel subagents.
- **Parallel workers never run `git commit`** (index.lock races). Workers: implement, make tests pass, report. The orchestrator reviews diffs and commits per task sequentially after the wave.
- `src/dead_channel/core/` is **frozen after Wave 1**. Contract changes require orchestrator approval.
- Every worker: read AGENTS.md first. Type hints everywhere. Files ≤ ~200 LOC. No narrating comments. TDD.
- Commit identity (orchestrator only): `git -c user.name="Dave M." -c user.email="25110228+doubletap-dave@users.noreply.github.com" commit ...`

---

## Wave 0 — Bootstrap (orchestrator, sequential)

**T0.1 Install uv + scaffold Python project (tools only — never manual scaffold)**

1. `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` then refresh PATH (`$env:Path += ";$env:USERPROFILE\.local\bin"`).
2. In repo root: `uv init --bare --package --name dead-channel --python 3.14` (creates pyproject.toml + src layout; no stray files).
3. `uv add pydantic pydantic-ai fastapi "uvicorn[standard]" sse-starlette pydantic-settings httpx`
4. `uv add --dev pytest pytest-asyncio ruff`
5. Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

6. Verify: `uv run python -c "import dead_channel; print('ok')"`.
7. Commit: `chore: bootstrap python project with uv`.

**T0.2 Scaffold viewer with Vite (tools only)**

1. `npm create vite@latest viewer -- --template react-ts`
2. `cd viewer; npm install; npm i maplibre-gl zustand; npm i -D openapi-typescript`
3. Add to `viewer/package.json` scripts: `"gen:api": "openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts"`.
4. Verify: `npm run build` passes.
5. Commit: `chore: scaffold react viewer with vite`.

---

## Wave 1 — Core Contracts (single agent; everything depends on this)

**T1.1 Core types, RNG, events, config**

Files:
- Create: `src/dead_channel/core/__init__.py`, `types.py`, `rng.py`, `events.py`, `config.py`
- Test: `tests/core/test_types.py`, `tests/core/test_rng.py`, `tests/core/test_events.py`

**Step 1 — failing tests** (key cases):

```python
# tests/core/test_rng.py
from dead_channel.core.rng import SeededRNG


def test_substreams_are_deterministic_and_independent():
    a, b = SeededRNG(7), SeededRNG(7)
    sa, sb = a.stream("obs", turn=1), b.stream("obs", turn=1)
    assert [sa.gauss(0, 1) for _ in range(5)] == [sb.gauss(0, 1) for _ in range(5)]
    other = SeededRNG(7).stream("obs", turn=2)
    assert [other.gauss(0, 1) for _ in range(5)] != [sb.gauss(0, 1) for _ in range(5)]


def test_named_streams_independent_same_turn():
    r = SeededRNG(1)
    x = r.stream("obs", turn=1).random()
    y = r.stream("threat", turn=1).random()
    assert x != y
```

```python
# tests/core/test_events.py
from dead_channel.core.events import Event, make_event


def test_event_roundtrip_and_ordering():
    e = make_event("threat.updated", turn=3, state="northstar", threat=41.0, drivers={})
    assert e.type == "threat.updated" and e.turn == 3
    assert Event.model_validate(e.model_dump()).payload == e.payload


def test_unknown_event_type_rejected():
    import pytest, pydantic

    with pytest.raises(ValueError):
        make_event("nukes.launched", turn=1)
```

**Step 2 — implement.** Full contracts (frozen after this wave):

```python
# src/dead_channel/core/types.py
from enum import StrEnum
import pydantic


class ResourceKind(StrEnum):
    ECONOMY = "economy"
    ENERGY = "energy"
    FOOD = "food"
    MILITARY = "military"
    RESEARCH = "research"


class IntelSource(StrEnum):
    SIGINT = "sigint"
    IMINT = "imint"
    HUMINT = "humint"
    OSINT = "osint"
    DEFECTOR = "defector"


class StateID(StrEnum):
    NORTHSTAR = "northstar"
    VESPER = "vesper"


class ActionKind(StrEnum):  # 19 actions
    RAISE_READINESS = "raise_readiness"
    LOWER_READINESS = "lower_readiness"
    REPOSITION_FORCES = "reposition_forces"
    CONDUCT_EXERCISE = "conduct_exercise"
    COVERT_MOBILIZATION = "covert_mobilization"
    INCREASE_SURVEILLANCE = "increase_surveillance"
    VERIFY_REPORT = "verify_report"
    PLANT_FALSE_INTEL = "plant_false_intel"
    ATTEMPT_INFILTRATION = "attempt_infiltration"
    REASSURE = "reassure"
    THREATEN = "threaten"
    PROPOSE_AGREEMENT = "propose_agreement"
    ACCUSE = "accuse"
    REQUEST_CLARIFICATION = "request_clarification"
    STAY_SILENT = "stay_silent"
    INVEST_MILITARY = "invest_military"
    INVEST_RESEARCH = "invest_research"
    INVEST_ECONOMY = "invest_economy"
    STOCKPILE = "stockpile"
    SANCTION = "sanction"
    OFFER_TRADE = "offer_trade"


class ActionSpec(pydantic.BaseModel):
    kind: ActionKind
    params: dict[str, float | str] = {}


class Claim(pydantic.BaseModel):
    subject: str  # e.g. "vesper.readiness"
    direction: str  # "rising" | "falling" | "stable" | "hostile_intent" | "deception"
    magnitude: float = 0.0  # claimed size of change, 0-100 scale
    horizon_turns: int = 3


class Assessment(pydantic.BaseModel):
    role: str
    interpretation: str  # 2-3 operational sentences, NOT chain-of-thought
    claim: Claim
    recommended_action: ActionSpec
    urgency: int  # 1-5
    dissent: str | None = None


class Decision(pydantic.BaseModel):
    action: ActionSpec
    rationale: str


class CountryState(pydantic.BaseModel):
    resources: dict[ResourceKind, float]
    readiness: float
    stability: float
    intelligence_capability: float
    diplomatic_credibility: float
    concealment: float = 0.0  # counter-intel posture, raises enemy noise


class TrueWorld(pydantic.BaseModel):
    turn: int = 0
    countries: dict[StateID, CountryState]


class IntelPayload(pydantic.BaseModel):
    attribute: str  # e.g. "readiness"
    value: float
    confidence: float  # 0-1
    age_turns: int
    source: IntelSource
    about: StateID
    planted: bool = False  # internal; stripped from agent packets by policy
```

```python
# src/dead_channel/core/rng.py
import hashlib, random


class SeededRNG:
    def __init__(self, seed: int):
        self.seed = seed

    def stream(self, name: str, turn: int = 0, **scope) -> random.Random:
        key = f"{self.seed}:{name}:{turn}:" + ":".join(f"{k}={v}" for k, v in sorted(scope.items()))
        derived = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
        return random.Random(derived)
```

```python
# src/dead_channel/core/events.py  (discriminated union; append-only log schema)
import pydantic

EVENT_TYPES = {
    "run.started",
    "turn.started",
    "world.ticked",
    "observation.generated",
    "report.rendered",
    "assessment.made",
    "decision.made",
    "effect.applied",
    "threat.updated",
    "claim.scored",
    "message.sent",
    "contact.detected",
    "deception.planted",
    "agreement.formed",
    "agreement.violated",
    "conflict.threshold_crossed",
    "run.ended",
}


class Event(pydantic.BaseModel):
    seq: int
    turn: int
    type: str
    payload: dict

    @pydantic.field_validator("type")
    @classmethod
    def _known(cls, v):
        if v not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {v}")
        return v


def make_event(type: str, *, seq: int = 0, turn: int, **payload) -> Event:
    return Event(seq=seq, turn=turn, type=type, payload=payload)
```

`core/config.py`: `RunConfig` (seed, turns, model_matrix: `dict` with `default`, `states: {state: {role: model}}`), `SimParams` (all tuning knobs from spec §10: `noise_sigma={SIGINT:6, IMINT:8, HUMINT:10, OSINT:12, DEFECTOR:25}`, `source_reliability_init={...0.8/0.75/0.6/0.7/0.4}`, `threat_weights={readiness_delta:0.8, hostile_msg:6.0, exercise:5.0, betrayal:8.0, reassurance:12.0, decay:2.0}`, `defcon_bands=[35,60,80]`, `trust_half_life=8`, `claim_error_scale=30.0`). One `Params` object, injected everywhere — no module-level constants.

**Step 3:** `uv run pytest tests/core -v` → PASS. **Step 4:** commit `feat: core contracts — types, seeded rng, event schema, config`.

---

## Wave 2 — Engine (6 parallel agents, disjoint files; all import only `core/`)

**T2.1 Event store + bus** — `src/dead_channel/engine/store.py`, `engine/bus.py`; test `tests/engine/test_store.py`.
`EventStore`: SQLite WAL (`runs/<run_id>/log.db`), table `events(seq PK, turn, type, payload JSON)`; `append(event) -> seq` (assigns seq), `replay() -> list[Event]`, `events_since(seq)`. `EventBus`: asyncio pub/sub, `publish(event)`, `subscribe() -> async iterator` (for SSE). Tests: append/replay roundtrip, seq monotonic, bus fan-out to 2 subscribers. Commit: `feat: event store and async bus`.

**T2.2 World + projections** — `engine/world.py`, `engine/projections.py`; test `tests/engine/test_world.py`.
`initial_world(seed) -> TrueWorld` (both states ~55 resources, readiness 40, credibility 70, intel_cap 50). `apply_effects(world, effects) -> TrueWorld` (pure). `BeliefState`: per observer state — believed enemy attribute values with confidence + last-verified values; `project_beliefs(events, state) -> BeliefState` (from `report.rendered` + verification events only — never truth). Tests: beliefs derive from reports not truth; planted reports enter beliefs (agents can be deceived) but flagged internally. Commit: `feat: world state and belief projections`.

**T2.3 Observation model** — `engine/observation.py`; test `tests/engine/test_observation.py`.
Formulas (from `Params`): `sigma_eff = base[source] * (0.5 + target.concealment) * (1.4 - observer.intelligence_capability/250)`, clamped `[0.3*base, 3*base]`; `reported = clamp(truth + gauss(0, sigma_eff), 0, 100)`; `confidence = clamp((0.9 - abs(noise)/(3*sigma_eff)) * reliability[source] * 0.9**age, 0.05, 0.95)`; reliability drifts `±N(0, 0.02)` per turn clamped `[0.3, 0.95]`. Exercise phantom: active exercises add `+8` to IMINT readiness observations. `generate_observations(world, beliefs, params, rng, turn) -> list[IntelPayload]` — 3-5 reports/turn targeting the attributes with largest believed-uncertainty. Planted reports are NOT generated here (injected by resolution). Deterministic given seed. Tests: same seed same payloads; low intel_cap → higher noise; concealment widens sigma; phantom exercise shifts IMINT. Commit: `feat: mechanical observation model`.

**T2.4 Threat + DEFCON** — `engine/threat.py`; test `tests/engine/test_threat.py`.
`update_threat(state_threat, beliefs, own_readiness, messages, exercises, betrayals, params) -> (threat, drivers)`:
`threat' = clamp(threat + w_r*max(0, believed_readiness_delta) + w_m*hostile + w_e*exercise + w_b*betrayal - w_p*reassurance*credibility/100 - decay*(1 - threat/100), 0, 100)`, signals scaled by `(1.3 - own_readiness/250)`. Hotline active → signal weights × 0.5.
`derive_defcon(threat_a, threat_b, conflict_crossed, prev_defcon, band_hold, params) -> (defcon, hold)`: composite bands `[35,60,80]` → 4/3/2; DEFCON 1 iff both ≥85 and conflict event; **hysteresis**: band change only after held 2 consecutive turns. Tests: spiral case (both raise readiness → both threats rise), reassurance scaled by credibility, hysteresis blocks flicker. Commit: `feat: emergent threat model and defcon derivation`.

**T2.5 Ledger + trust** — `engine/ledger.py`; test `tests/engine/test_ledger.py`.
`Ledger.open(claim, author, turn)`, `adjudicate(claim_id, realized_value, turn) -> ClaimScored` with `error = clamp(|claimed - realized| / claim_error_scale, 0, 1)`, `outcome = 1 - error`; direction wrong → outcome 0. `TrustTracker.update(role, outcome, turn)`: exponential recency weights `0.5^(age/half_life)`; `trust(role) = clamp(0.5 + tanh(1.5*(score - 0.5)), 0.1, 0.95)`. `salient_entries(agent, k, turn)`: rank by recency + emotional weight (betrayals/failures ×2). Tests: accurate claim raises trust, stale failures fade, overridden-then-right dissent boosts. Commit: `feat: claim ledger and trust scoring`.

**T2.6 Action resolution** — `engine/resolution.py`; test `tests/engine/test_resolution.py`.
`resolve(action, world, state, rng, params) -> list[Effect]` + emitted observation/deception events. Table (deltas on 0-100):
raise_readiness +6 readiness, −1 economy, visible; lower_readiness −6, visible; reposition: visible movement event; exercise: readiness +2, phantom IMINT signal 2 turns, high visibility; covert_mobilization: readiness +12, concealment +0.3 (3 turns), leak 15%/turn → HUMINT true-value report; increase_surveillance: noise ×0.8 (3 turns); verify_report: tight re-observation (σ×0.4) next turn, adjudicates target claim; plant_false_intel: injects attacker-valued payload into enemy queue (planted=True), caught if enemy verifies (σ×0.4 roll vs value) → source burned + ledger entry; attempt_infiltration: 25% + intel_cap/300 chance → 3 turns of low-noise intel, fail → credibility −3, enemy threat +4; reassure: enemy threat −w_p×cred/100; threaten: enemy threat +w_m, own credibility −1; propose_agreement: accept_prob `clamp(0.8 − enemy_threat/150 + own_cred/200, 0.05, 0.9)` → hotline (signal weights ×0.5); accuse: enemy threat +4, if accusation true (target had deception active) target credibility −8 else own credibility −5; request_clarification: forces enemy next-turn message; stay_silent: emits silence event (enemy threat +1 if their threat >60 else 0); invest_*: +3 resource, −2 economy; stockpile: energy/food +4; sanction: enemy economy −4, enemy threat +6, own cred −2; offer_trade: both economy +2 if accepted (accept if enemy threat <50).
Every effect → `effect.applied` event; observable side → `contact.detected`/`deception.planted`/`message.sent`. Tests per action family; deception leak determinism; agreement violation detection (covert mobilization while hotline → `agreement.violated`). Commit: `feat: action resolution with deception economics`.

---

## Wave 3 — Agents + Providers (4 parallel agents; depend on `core/` only)

**T3.1 Visibility policy + packet assembler** — `src/dead_channel/agents/policy.py`, `agents/packets.py`; test `tests/agents/test_packets.py`.
`ROLE_POLICY: dict[role, allowed event types + redactions]` (spec §4: intel chief sees `report.rendered`+verifications; military sees own readiness + HoS-shared estimates + contacts; diplomat sees messages/agreements; HoS sees assessments + messages + elevated intel summaries). `assemble_packet(role, state, events, ledger_slice, memory_slice) -> AgentPacket` (typed model; **takes projections only — no TrueWorld param exists on the function**). Redactions: strip `planted` flags; planted reports appear as ordinary products. Tests: policy denies `deception.planted` to every role; planted flag never in packet JSON; HoS packet contains all four assessments (current turn) but advisors' packets do NOT contain sibling assessments. Commit: `feat: visibility policy and context packets`.

**T3.2 Prompts** — `agents/prompts.py`; test `tests/agents/test_prompts.py`.
One builder per call site: `render_report_prompt(payload)`, `assessment_prompt(role, packet, personality, trust_note)`, `hos_prompt(packet, advisor_assessments, trust_ranking)`. Personalities: dict of trait blocks per role (spec §4). Output contracts embedded (JSON schema of Assessment/Decision). Trust presentation: higher-trust advisors first, track-record line appended. Tests: prompt contains packet data, never contains "planted", trust ordering reflected. Commit: `feat: prompt builders with personalities and trust ordering`.

**T3.3 Provider layer + model matrix** — `providers/catalog.py`, `providers/matrix.py`, `providers/caller.py`; test `tests/providers/test_matrix.py`, `test_caller.py`.
`catalog.py`: async fetch model lists — OpenAI `GET /v1/models` (key), OpenRouter `GET /api/v1/models` (key), Perplexity static modern list (no list endpoint) — cached, returns `ModelInfo{id, provider, context}`. `matrix.py`: `resolve(state, role, matrix) -> str` (role → state → default fallback). `caller.py`: thin PydanticAI wrapper `call(model_str, result_type, prompt) -> Result` using `pydantic_ai.Agent`; model strings `openai:…`, `openrouter:…` (OpenAI-compatible base_url), `perplexity:…`; captures messages → `persist_prompt(run_dir, turn, call_site, messages)`. Tests use `pydantic_ai.models.test.TestModel` (no keys, no network). Tests: fallback chain, prompt persistence writes JSON, TestModel returns valid Assessment. Commit: `feat: multi-provider LLM layer with model matrix`.

**T3.4 Report renderer + agent calls** — `agents/renderer.py`, `agents/calls.py`; test `tests/agents/test_renderer.py`.
`render_report(payload) -> str`: 1-3 sentence operational prose from payload only (TestModel in tests). `get_assessment(role, packet, ...) -> Assessment`, `get_decision(hos_packet) -> Decision` via caller; validation retry via PydanticAI. Tests: renderer output nonempty, mentions value band; assessment parses into schema with TestModel. Commit: `feat: report rendering and structured agent calls`.

---

## Wave 4 — Orchestration + Server + Viewer panels (6 parallel agents)

**T4.1 TurnRunner** — `engine/runner.py`; test `tests/engine/test_runner.py`.
`async run_turn(run_id)`: tick world → observations (T2.3) → render reports (T3.4) → 8 assessments parallel (`asyncio.gather`) → 2 HoS decisions → resolve actions (T2.6) → threat update + DEFCON (T2.4) → ledger adjudication + trust (T2.5) → memory slices → append all events to store, publish on bus. Persists every prompt (T3.3). Uses injected `Caller` protocol so tests run fully offline (TestModel). Test: 3-turn run with TestModel produces ≥60 events, threat rises after exercise, all events replay. Commit: `feat: turn runner pipeline`.

**T4.2 FastAPI + SSE** — `server/app.py`, `server/runs.py`; test `tests/server/test_api.py`.
`POST /runs` (RunConfig) → run_id; `POST /runs/{id}/start` (background task, turns loop); `GET /runs/{id}/stream` (SSE via bus, heartbeat 15s); `GET /runs/{id}/events?after=seq`; `GET /runs/{id}/observer/state` (omniscient projection: true world + beliefs + threats + defcon); `GET /providers/catalogs`. CORS for dev. httpx AsyncClient tests against app; SSE tested via first-event read. Commit: `feat: fastapi server with sse streaming`.

**T4.3 Eval harness + smoke** — `eval/harness.py`, `eval/report.py`, `eval/smoke.py` (`python -m dead_channel.eval.smoke`); test `tests/eval/test_report.py`.
Harness: N runs × model matrices, offline (TestModel) by default. Report: per-run threat curves, deception count, **misattribution detection** (deception.planted events where target state subsequently acted on the planted belief — join beliefs to decisions), DEFCON timeline. Smoke: 6-turn offline run, prints summary, exit 0. Commit: `feat: eval harness, run report, offline smoke`.

**T4.4 Viewer shell + config screen** — `viewer/src/App.tsx`, `src/styles/`, `src/store.ts`, `src/components/ConfigScreen.tsx`; fixtures `src/api/fixtures.ts`.
CRT/ops aesthetic: dark phosphor palette, scanline overlay, monospace (IBM Plex Mono), panel borders. zustand store: run state, events, defcon, selection. ConfigScreen: model matrix UI (global default + per-state + per-role selects fed by `/providers/catalogs`), seed, turns, start button. App routes config ↔ ops room. **Do not touch other panels' files.** Commit: `feat: viewer shell, crt styling, config screen`.

**T4.5 Map panel** — `viewer/src/panels/MapPanel.tsx`, `src/assets/territories.ts`.
MapLibre + CARTO dark raster basemap (no key). Northstar territory overlay ≈ Scandinavia/Baltic polygon; Vesper ≈ Southern Cone polygon (hand-authored GeoJSON, fictional fill). Force posture markers sized to *believed* strength; exercises/movements/contacts as transient markers; unverified contacts = dashed ghost marker + confidence ring (circle radius ∝ confidence). Renders **detected, not true** — data from observer events (`contact.detected`), never true world. Commit: `feat: map panel with fictional territories and uncertainty markers`.

**T4.6 State feeds + timeline + defcon + drawer** — `viewer/src/panels/StateFeed.tsx`, `Timeline.tsx`, `DefconMeter.tsx`, `EventDrawer.tsx`.
StateFeed (×2 via props): streaming assessment cards (role, interpretation, claim, recommendation, urgency bar), decision card with rationale, dissent lines, trust sparkline per advisor, resource/readiness strip. Timeline: event chips per turn, click → EventDrawer (full reports + prompts for that event). DefconMeter: 5→1 with hysteresis-aware display, color steps green→red. Commit: `feat: state feeds, timeline, defcon meter, event drawer`.

---

## Wave 5 — Integration (orchestrator + 1 agent, sequential)

**T5.1 Wire viewer to live API** — `viewer/src/api/client.ts` (typed fetch + EventSource), replace fixtures; `npm run gen:api` against running server; App integration test: start offline run (TestModel backend flag), panels populate.
**T5.2 Truth-leak scan** — `tests/agents/test_leak_scan.py`: replay all persisted prompts from a smoke run; assert forbidden fields (`"planted": true`, true-state attribute dumps) absent from every agent-facing prompt. CI gate.
**T5.3 Golden run** — commit `tests/engine/golden/run_seed42.jsonl` + `test_golden_replay.py` (replay determinism diff).
**T5.4 Polish + README** — final wiring, README quickstart, commit.

---

## Success Gate

`uv run python -m dead_channel.eval.smoke` passes offline; 5 seeded runs with real keys produce ≥1 run the user wants to keep watching (spec §10).
