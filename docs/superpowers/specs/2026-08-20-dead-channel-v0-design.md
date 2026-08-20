# Dead Channel — V0 Design

Date: 2026-08-20
Status: Approved (brainstorming session)

Dead Channel is a Cold War-style AI simulation about distrust, deception, incomplete information, and escalation. Two rival states compete under uncertainty. The design goal is not strategic balance or feature depth — it is producing stories worth watching: moments where both sides behave rationally from their own perspective while collectively drifting toward disaster.

**Optimization target:** uncertainty + personality + memory + deception + consequences = stories we didn't write.

**V0 success gate:** two AI-controlled fictional states run 30–50 turns and produce at least one genuinely interesting strategic situation caused by incomplete information, disagreement, deception, misinterpretation, or memory. Human test: watch 5 runs; if at least one makes you want to watch another, pass.

---

## 1. Architecture Overview

Deterministic event-sourced simulation core (Approach A), agents as pure functions of their information, with live streaming to the observer.

- The engine is a seeded, deterministic simulation kernel. Every mutation of true state goes through an append-only event log.
- A turn executes as a fixed pipeline: world tick → mechanical observation generation → LLM report rendering → four isolated advisor assessments (parallel) → Head of State decision → mechanical action resolution → memory/trust update → event emission.
- Agents are stateless functions of (role, information packet, memory slice). They cannot see truth because it is never in their inputs.
- Turns run asynchronously in the background; the viewer streams events live as they resolve. Runs are resumable and fully replayable from the log.
- Same seed + same config = same world skeleton and same observation rolls. LLM non-determinism means decisions vary — that is fine; the world stays comparable across model-assignment experiments.

Deliberately rejected: LangGraph/CrewAI/AutoGen-style autonomous agent loops (they solve a problem we don't have, endanger the no-truth-leak property, and complicate replay/observability). PydanticAI is used for the LLM-call layer only.

## 2. World Model

Two fictional states: **Northstar Republic** and **Vesper Union**. Fictional states on a real-Earth map (real coastlines/countries as basemap; fictional territories overlaid on real regions). Fictional names are deliberate: real countries would import LLM training-data priors and the agents would perform "what the US/Russia would do" instead of reasoning from given information.

True state per country (never shown to agents):

- Resources: economy, energy, food, military, research (0–100 scales)
- Hidden attributes: `readiness` (military posture, separate from size), `stability`, `intelligence_capability`, `diplomatic_credibility`
- Cut from brief: public confidence (overlaps stability, no distinct decision)

Global per-side: `perceived_threat` toward the other (0–100) — drives all escalation behavior. Observer-facing DEFCON derives from the composite of both sides' perceived threat.

One turn = abstract time period. 30–50 turns per run.

## 3. Intelligence Pipeline (the heart)

Truth exists internally; agents see only rendered reports.

**Observation model (mechanical, seeded):**

- Each turn, each side's intelligence apparatus produces reports about the enemy by rolling deterministic transforms of true enemy state: `reported = truth + noise`, noise scaled by enemy counter-intelligence posture and own `intelligence_capability`.
- Report payload: `{attribute, value, confidence, age_turns, source}`.
- Sources (fixed set): SIGINT (intercepts), IMINT (satellite), HUMINT (agents), OSINT (open press), defector (rare, high variance). Each source has base reliability that drifts over time.
- Deception mutates observation inputs, not narrative: covert mobilization raises true readiness but suppresses observability; staged exercises add phantom readiness signal to satellite observation for N turns; planted reports are injected directly into the enemy's queue with a plausible source label.

**Rendering (LLM, cheap):** payload → 1–3 sentence operational prose. The renderer sees only the payload, never true state. Agent-facing products show prose plus the numeric data line (value/confidence/age/source), like a real intelligence product. Truth-leak channel structurally closed.

**Verification:** "verify a suspicious report" re-observes the targeted attribute with a tighter noise roll; costs a turn of latency and a small resource cost. Verification results adjudicate ledger claims.

## 4. Agents & Decision Flow

Four agents per state: Head of State, Intelligence Chief, Military Chief, Diplomat. They are not one LLM wearing four hats.

**Information streams (push, never pull):**

- Intelligence Chief: full report inbox, source reliability history, verification results.
- Military Chief: own force state and readiness, enemy estimates shared by the HoS from *prior turns'* elevated summaries (current-turn advisor assessments are parallel and never cross-visible), detected enemy activity.
- Diplomat: diplomatic traffic, public signals, agreements, relationship history. No raw intelligence unless the HoS shares a summary.
- Head of State: advisor recommendations, diplomatic traffic, own resource state, Intelligence Chief's elevated summaries. Never raw truth.

**Turn flow within a state:** advisors produce assessments independently and in parallel — no advisor sees a colleague's current-turn opinion (structural disagreement; sycophancy drift impossible). Each assessment is structured output: interpretation note (2–3 operational sentences, not chain-of-thought), a falsifiable claim, a recommended action, an urgency level. HoS receives all four plus own context and selects the national action with a one-line rationale.

**Dissent:** when the HoS acts against an advisor's recommendation, the advisor may file a one-line dissent that enters the ledger. If an overridden advisor's claim later scores better than the chosen course, their trust weight rises.

**Personalities:** traits are prompt-level (cautious, aggressive, paranoid, conciliatory, analytical, ideological, risk-tolerant, skeptical, doctrine-loyal) plus one mechanical hook: trait-modulated interpretation bias in how the engine packages the inbox (e.g., paranoid Military Chief sees confidence displayed more prominently; analytical Intelligence Chief gets explicit contradiction flags). Bias shapes salience, never the numbers.

## 5. Memory & Trust

**Ledger:** append-only analytical layer over the event log. Every advisor assessment contributes a falsifiable claim (subject, direction, horizon). Claims stay open until adjudicated by: a verification result, a revealed enemy action (post-hoc estimates, detected exercises), or horizon expiry scored against the best later estimate. Scoring is mechanical (direction and magnitude of error, normalized). Advisors accumulate rolling per-domain track records.

**Trust weights:** trust = base personality affinity + rolling prediction score with recency weighting. Trust changes how the HoS prompt *presents* advisors (order, track-record annotations, dissent framing) — not a hard vote. The HoS still decides. "Trust in intelligence declines" emerges mechanically: repeated intel failures degrade the Intelligence Chief's standing and the HoS shifts to the Military Chief's reads.

**Retrieval:** agents never receive full transcripts. Each turn the engine selects top-k salient ledger entries per agent (recency, relevance, emotional weight — betrayals and failures weigh more) as a compact "recent history" block. Old betrayals resurface during crises; quiet stretches fade them.

## 6. Escalation (emergent, no ladder)

No scripted stages. Each state's `perceived_threat` (0–100) updates every turn from mechanical inputs: observed enemy readiness deltas (as believed, not as true), hostile diplomatic content, detected exercises near borders, memory of betrayals, and own current readiness (low readiness makes the same signal scarier).

**Escalation loop:** actions taken under high perceived threat (readiness increases, repositions, canceled talks) are themselves observable events. The enemy's intelligence sees them, their perceived threat rises, they respond — the loop tightens even when both leaders want calm. This is the mechanic; misinterpretation escalates without anyone intending it.

**De-escalation is real but has a trust prerequisite:** reassurance lowers enemy perceived threat proportional to your `diplomatic_credibility`. Deception spends credibility; betrayals crater it. A state caught lying must over-invest in reassurance later, and during a crisis with low credibility even genuine conciliation may not stop the spiral.

**Observer DEFCON (5→1):** derived mechanically from composite perceived threat, with hysteresis so single noisy turns don't flicker the meter; sustained pressure steps up, genuine de-escalation steps down.

- DEFCON 5 normal · 4 above-avg vigilance · 3 round-the-clock readiness · 2 mobilization watch · 1 active conflict threshold.

DEFCON is used (not a fictional clone) because audiences understand it instantly.

## 7. Actions & Deception

21 national actions (the brief's 19 plus raise/lower readiness split into one action with a direction parameter and three distinct invest targets — distinct members keep the resolver simple), one per turn, chosen by each HoS. Every action must change (a) true state, (b) the enemy's information environment, or (c) own future option space — ideally two of three. Actions that can't justify themselves on that rule get cut.

- **Military:** adjust readiness (one action with a direction parameter: raise/lower), reposition forces, conduct exercise, covert mobilization
- **Intelligence:** increase surveillance, verify report, plant false intelligence, attempt infiltration
- **Diplomacy:** reassure, threaten, propose agreement, accuse, request clarification, stay silent (silence is also a signal)
- **Strategic:** invest (military/research/economy), stockpile, sanction, offer trade

**Signals:** every action resolves mechanically, then emits observation events into the enemy's pipeline with visibility, delay, and ambiguity attributes. Exercise → high-visibility readiness signal for 2 turns (deterrence or cover?). Covert mobilization → large true readiness increase, low observability, leak risk (a HUMINT/defector report with real numbers may slip out). Plant false intelligence → fabricated report into enemy queue with plausible source; costs `intelligence_capability` standing if the enemy's verification catches it (they ledger "source X is enemy-controlled"). Reassure → lowers enemy perceived threat proportional to `diplomatic_credibility`.

**Deception economics:** wins are immediate (enemy misallocates); losses are delayed but compounding (reassurance channel degrades for the rest of the run). This asymmetry is what makes "broken trust" producible rather than scripted.

**Agreements (minimal):** "propose agreement" can produce a lightweight pact (non-mobilization, communication hotline) that mechanically suppresses specific threat signals while both sides comply; the ledger remembers violations forever. The hotline makes the détente scenario possible: with one established, a future false alarm has a channel through which it can be resolved.

## 8. Orchestration, Storage & Information Access

**Orchestration:** purpose-built `TurnRunner` (thin, explicit, a few hundred lines of asyncio), not an agent framework:

```
world_tick → observations → report_rendering →
  [advisor_assessments ×4 parallel (asyncio)] →
  hos_decision → action_resolution → ledger/trust_update → emit_events
```

PydanticAI handles the LLM-call layer only: provider normalization (OpenAI, OpenRouter, Perplexity), structured outputs with retry-on-validation, per-provider output-mode fallbacks, streaming. Everything that makes Dead Channel Dead Channel stays custom: TurnRunner, event store, projections, visibility policy, ledger.

**Model pitting:** provider catalogs fetch dynamically at startup. Pre-run configuration screen exposes a model assignment matrix: a global default ("same brain for everything"), overridable per state, overridable per role. Resolution: role override → state override → global default.

**Storage:** SQLite (single file, WAL mode). The event log is the only source of truth; everything else is a projection rebuilt from events: true world state, belief states, per-agent information streams, ledger, trust scores. Actions are events (`ActionSelected` with type, params, rationale, references to assessments and dissents); the resolver emits separate `Effect` events. Runs replay, fork from any turn, and diff against sibling runs with different model assignments.

**Access control — push, never pull:** agents have no tools, no retrieval API, no query access; nothing exists to leak through. The engine assembles a context packet per agent; the agent call is `packet → structured assessment`. Packets are built by projecting the event log through the role's visibility policy (declarative table: role → allowed event types, projections, redactions). Four packets per turn, each dumpable to disk.

**Enforcement in types:** `TrueWorldState` is a distinct type the context-assembler cannot emit for agent contexts — a leak is a type error, not a code-review catch. The report renderer accepts only `IntelPayload`. Every prompt sent to every LLM is persisted to the run directory: after any run, open exactly what the Intelligence Chief saw on turn 23.

**Observer exception:** the observer API reads the unfiltered log — omniscience is "no visibility policy applied."

## 9. Observer Experience

Full omniscience, live. The audience holds the truth while the states fumble; dramatic irony is the product.

**Stack:** Python (FastAPI + engine + agents) backend; React + MapLibre frontend; SSE event streaming.

**Layout (single screen):**

- **Top:** DEFCON indicator (5→1) with hysteresis, derived from composite perceived threat.
- **Center:** real-Earth map (dark satellite/CRT-styled tiles). Fictional territories overlaid on real regions; force posture icons sized to believed strength; exercises, movements, detected contacts as transient markers. The map renders **what was detected, not what is true** — unverified contacts get dashed/ghost markers with confidence rings.
- **Left/right:** Northstar and Vesper internal feeds — live advisor assessments (note, claim, recommendation, urgency), HoS decision with rationale, dissents, own resource/readiness strips.
- **Bottom:** turn timeline — event chips (exercise detected, message received, contradiction flagged, treaty proposed, verification failed), clickable to underlying reports and prompts. Doubles as the forensic tool.

**Uncertainty as visual language:** confidence rings on contacts, staleness badges, source-reliability tags, contradiction flags, claim-score sparklines next to advisor names. The observer feels the fog while holding the truth.

**Live, not batch:** a 40-turn run streams over minutes; assessments appear advisor by advisor, the decision lands, effects ripple onto the map. Completed runs replay with a scrubber.

**Agent presentation:** concise operational notes, never raw chain-of-thought (e.g., INTELLIGENCE CHIEF → "Satellite estimate may be overstating readiness due to ongoing exercises" → Recommendation: "Delay mobilization; increase surveillance").

## 10. Testing, Tuning & Success Gate

**Test layers:**

1. Engine tests — pure, fast, no LLM. Observation noise, deception mutations, threat updates, credibility decay, claim scoring, DEFCON bands: fully deterministic given seed; unit-tested hard.
2. Golden-run replays — committed seed with known event log; CI replays and diffs. World-mechanics changes surface as reviewable event-log diffs.
3. Agent contract tests — recorded LLM responses replayed against the packet assembler; an assertion pass scans every persisted prompt for forbidden fields (automated truth-leak check).
4. Story evaluation — harness runs N seeded runs across model assignments; run report includes escalation curves, deception counts, and mechanically detected misattribution events (action's true cause diverges from enemy's believed cause, and both sides act on the belief).

**V0 gate (human):** watch 5 runs; at least one must make you want to watch another.

**Tuning surface:** single config — noise magnitudes per source, credibility decay rates, threat-update weights, claim-score recency weighting, DEFCON band edges. Batch run reports make each knob's effect visible ("did misattributions go up"), not vibes.

## 11. Repository Layout

```
engine/    world model, observation model, action resolution, ledger, projections
agents/    context packets, prompts, schemas, visibility policy
providers/ PydanticAI layer, dynamic catalogs, model assignment matrix
server/    FastAPI app, SSE streaming, observer API
viewer/    React + MapLibre, CRT styling, timeline, replay
runs/      SQLite databases + persisted prompts per run
docs/      specs and design docs
```

## 12. Explicitly Out of Scope for V0

Multiplayer; real-world countries as actors; detailed military unit simulation; nuclear mechanics ("earn the nukes"); tech trees; complex economic modeling; character portraits; procedural maps; elaborate diplomacy trees; victory conditions; monetization; accounts; persistent campaigns; public confidence stat; agent-initiated tool use; multi-turn deliberation rounds.

## 13. Key Decisions Log

| Decision | Choice | Rationale |
|---|---|---|
| Agent minds | Full LLM-driven, isolated contexts | Emergent interpretation, disagreement, deception |
| Intel generation | Mechanical payload + LLM prose rendering | Reproducible, measurable deception, closed truth-leak channel |
| Decision flow | Independent assessments → HoS integrates | Structural disagreement, no sycophancy drift |
| Memory | Event ledger + falsifiable claim scoring | Memory that mechanically changes decisions and trust |
| Escalation | Emergent perceived threat, no ladder | Escalation as feedback loop, not script |
| Observer | Full omniscience, live | Dramatic irony is the product |
| Map | Fictional states on real Earth | Real geography, no LLM priors from real countries |
| Stack | Python backend, React frontend | User preference |
| LLM providers | OpenAI + Perplexity + OpenRouter, dynamic catalogs | Model pitting as core experiment |
| LLM call layer | PydanticAI | Multi-provider normalization + structured outputs without orchestrator baggage |
| Orchestration | Custom TurnRunner | Fixed pipeline, full observability, no ambient state channels |
| Storage | Event-sourced SQLite | Replay, fork, diff, audit |
| Escalation display | DEFCON 5→1 | Instant audience legibility |
