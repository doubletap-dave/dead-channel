"""TurnRunner pipeline tests: fully offline via RecordingCaller, contract-checked."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from dead_channel.agents.packets import assemble_packet
from dead_channel.agents.policy import Role
from dead_channel.core.config import RunConfig, SimParams
from dead_channel.core.events import Event, make_event
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    ActionKind,
    ActionSpec,
    Assessment,
    Claim,
    CountryState,
    Decision,
    Direction,
    IntelSource,
    ResourceKind,
    StateID,
    TrueWorldState,
)
from dead_channel.engine.adjudicate import adjudicate_horizon
from dead_channel.engine.beliefs import BeliefState
from dead_channel.engine.bus import EventBus
from dead_channel.engine.projections import project_beliefs
from dead_channel.engine.rebuild import rebuild_state
from dead_channel.engine.resolution import resolve
from dead_channel.engine.runner import TurnRunner
from dead_channel.engine.store import EventStore
from dead_channel.engine.territories import TERRITORIES
from dead_channel.engine.turn_state import TurnState
from dead_channel.providers.caller import RecordingCaller

SEED = 42
TURNS = 3

STAY = ActionSpec(kind=ActionKind.STAY_SILENT)
COVERT = ActionSpec(kind=ActionKind.COVERT_MOBILIZATION)
ActionRule = ActionSpec | Callable[[int], ActionSpec]


def _action(kind: ActionKind, **params: float | str) -> ActionSpec:
    return ActionSpec(kind=kind, params=params)


DEFAULT_CLAIM = Claim(subject="enemy.readiness", direction=Direction.STABLE, magnitude=40.0)


def _canned_caller(actions: dict[str, ActionRule], claim: Claim | None = None) -> RecordingCaller:
    canned = claim or DEFAULT_CLAIM

    def _call(model_str: str, prompt: str, call_site: str) -> object:
        if call_site == "report_render":
            return "Routine product; no anomalies noted."
        if call_site == "hos_decision":
            state = "northstar" if "STATE: northstar" in prompt else "vesper"
            turn_match = re.search(r"TURN: (\d+)", prompt)
            assert turn_match is not None
            turn = int(turn_match.group(1))
            rule = actions[state]
            return Decision(
                action=rule(turn) if callable(rule) else rule, rationale=f"{state} acts."
            )
        role = call_site.removeprefix("assessment_")
        return Assessment(
            role=role,
            interpretation="Situation read complete.",
            claim=canned,
            recommended_action=STAY,
            urgency=1,
        )

    return RecordingCaller(_call)


def _make_runner(
    tmp_path: Path,
    actions: dict[str, ActionRule],
    seed: int = SEED,
    turns: int = TURNS,
    claim: Claim | None = None,
) -> tuple[TurnRunner, RecordingCaller, EventStore]:
    store_dir = tmp_path / "run-abc"
    store_dir.mkdir(parents=True, exist_ok=True)
    store = EventStore(store_dir / "events.db")
    caller = _canned_caller(actions, claim)
    config = RunConfig(seed=seed, turns=turns)
    runner = TurnRunner(store, EventBus(), caller, config, tmp_path / "runs")
    return runner, caller, store


async def _run(
    tmp_path: Path,
    actions: dict[str, ActionRule],
    turns: int = TURNS,
    seed: int = SEED,
    claim: Claim | None = None,
) -> tuple[RecordingCaller, EventStore]:
    runner, caller, store = _make_runner(tmp_path, actions, seed, turns, claim)
    await runner.run(turns)
    return caller, store


async def test_three_turn_run_produces_contract_log(tmp_path: Path) -> None:
    caller, store = await _run(tmp_path, {"northstar": STAY, "vesper": STAY})
    events = store.replay()

    assert len(events) >= 60
    assert events[0].type == "run.started"
    assert events[0].payload["seed"] == SEED
    assert events[0].payload["turns"] == TURNS
    assert "initial_world" in events[0].payload
    assert events[-1].type == "run.ended"
    assert events[-1].payload["turn"] == TURNS

    seqs = [event.seq for event in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)

    for event in events:
        payload = event.payload
        match event.type:
            case "report.rendered":
                assert {
                    "observer",
                    "about",
                    "attribute",
                    "value",
                    "confidence",
                    "age_turns",
                    "source",
                    "text",
                } <= set(payload)
            case "assessment.made":
                assert {
                    "state",
                    "role",
                    "interpretation",
                    "claim",
                    "recommended_action",
                    "urgency",
                    "dissent",
                } <= set(payload)
            case "decision.made":
                assert {"state", "action", "rationale", "turn"} <= set(payload)
            case "threat.updated":
                assert {"state", "threat", "drivers", "defcon", "hold"} <= set(payload)
            case "effect.applied":
                assert {"state", "attribute", "delta", "reason"} <= set(payload)
            case "claim.scored":
                assert {"state", "claim_id", "role", "outcome", "turn"} <= set(payload)
            case "observation.generated":
                assert isinstance(payload.get("observer"), str)
                assert isinstance(payload.get("reports"), list)
                reliabilities = payload.get("reliabilities")
                assert isinstance(reliabilities, dict)
                assert set(reliabilities) == {source.value for source in IntelSource}
                assert all(
                    isinstance(value, float) and 0.3 <= value <= 0.95
                    for value in reliabilities.values()
                )

    assert sum(1 for e in events if e.type == "assessment.made") == 8 * TURNS
    assert sum(1 for e in events if e.type == "decision.made") == 2 * TURNS
    assert sum(1 for e in events if e.type == "message.sent") == 2 * TURNS
    assert sum(1 for e in events if e.type == "threat.updated") == 2 * TURNS

    assert [(e.type, e.turn, e.payload) for e in events] == [
        (e.type, e.turn, e.payload) for e in store.replay()
    ]

    prompts = list((tmp_path / "runs" / "run-abc" / "prompts").glob("*.json"))
    assert len(prompts) >= 40
    assert len(caller.calls) == len(prompts)


async def test_prompts_carry_no_truth_and_no_plant_flag(tmp_path: Path) -> None:
    plant = _action(ActionKind.PLANT_FALSE_INTEL, target_attribute="readiness", value=90.0)
    caller, store = await _run(tmp_path, {"northstar": plant, "vesper": STAY}, turns=2)

    for _, prompt, _ in caller.calls:
        assert '"planted"' not in prompt
        assert "planted=true" not in prompt.lower().replace(" ", "")
        assert "concealment" not in prompt
        assert "TrueWorldState" not in prompt
        assert "initial_world" not in prompt

    events = store.replay()
    for observer in StateID:
        allowed = {
            f"{event.payload['value']:.1f}"
            for event in events
            if event.type == "report.rendered"
            and event.payload["observer"] == observer.value
            and event.payload["attribute"] == "readiness"
        }
        for _, prompt, _ in caller.calls:
            if f"STATE: {observer.value}" not in prompt:
                continue
            for match in re.finditer(r"readiness=([0-9.]+)", prompt):
                assert match.group(1) in allowed


async def test_exercises_raise_threat_and_emit_contacts(tmp_path: Path) -> None:
    exercise = _action(ActionKind.CONDUCT_EXERCISE)
    _, store = await _run(tmp_path, {"northstar": exercise, "vesper": exercise})
    events = store.replay()

    series: dict[str, list[float]] = {}
    for event in events:
        if event.type == "threat.updated":
            series.setdefault(str(event.payload["state"]), []).append(
                float(event.payload["threat"])
            )
    assert set(series) == {state.value for state in StateID}
    for values in series.values():
        assert values[0] < values[1] < values[2]

    contacts = [event for event in events if event.type == "contact.detected"]
    pairs = {(event.payload["observer"], event.payload["about"]) for event in contacts}
    assert ("vesper", "northstar") in pairs
    assert ("northstar", "vesper") in pairs
    assert all(event.payload["kind"] == "exercise" for event in contacts)


async def test_planted_intel_poisons_victim_beliefs(tmp_path: Path) -> None:
    plant = _action(ActionKind.PLANT_FALSE_INTEL, target_attribute="readiness", value=90.0)
    _, store = await _run(tmp_path, {"northstar": plant, "vesper": STAY}, turns=1)
    events = store.replay()

    plants = [event for event in events if event.type == "deception.planted"]
    assert len(plants) == 1
    assert plants[0].payload["state"] == "northstar"
    assert plants[0].payload["about"] == "vesper"
    assert plants[0].payload["value"] == 90.0

    planted_reports = [
        event
        for event in events
        if event.type == "report.rendered" and event.payload.get("planted") is True
    ]
    assert len(planted_reports) == 1
    assert planted_reports[0].payload["observer"] == "vesper"
    assert planted_reports[0].payload["about"] == "northstar"
    assert planted_reports[0].payload["value"] == 90.0

    beliefs = project_beliefs(events, StateID.VESPER)
    assert beliefs.attributes["readiness"].value == 90.0


async def test_verification_renders_verified_report_and_scores_claims(tmp_path: Path) -> None:
    verify = _action(ActionKind.VERIFY_REPORT, target_attribute="readiness")
    actions: dict[str, ActionRule] = {
        "northstar": lambda turn: verify if turn == 1 else STAY,
        "vesper": STAY,
    }
    _, store = await _run(tmp_path, actions)
    events = store.replay()

    verified = [
        event
        for event in events
        if event.type == "report.rendered" and event.payload.get("verified") is True
    ]
    assert len(verified) == 1
    payload = verified[0].payload
    assert payload["observer"] == "northstar"
    assert payload["about"] == "vesper"
    assert payload["attribute"] == "readiness"
    assert payload["source"] == "imint"
    assert payload["confidence"] >= 0.8

    scored = [
        event
        for event in events
        if event.type == "claim.scored" and event.payload["state"] == "northstar"
    ]
    assert scored
    assert all(str(event.payload["claim_id"]).endswith(":1") for event in scored)
    assert all(event.payload["turn"] == 2 for event in scored)


async def test_agreement_forms_and_hotline_halves_hostile_signals(tmp_path: Path) -> None:
    propose = _action(ActionKind.PROPOSE_AGREEMENT)
    threaten = _action(ActionKind.THREATEN)

    def actions_for(own: ActionSpec) -> dict[str, ActionRule]:
        return {
            "northstar": propose if own is propose else STAY,
            "vesper": lambda turn: threaten if turn == 2 else STAY,
        }

    hotline_store: EventStore | None = None
    control_store: EventStore | None = None
    for seed in range(40):
        base = tmp_path / f"seed-{seed}"
        _, candidate = await _run(base / "hotline", actions_for(propose), seed=seed)
        if any(event.type == "agreement.formed" for event in candidate.replay()):
            hotline_store = candidate
            _, control_store = await _run(base / "control", actions_for(STAY), seed=seed)
            break
    assert hotline_store is not None
    assert control_store is not None

    events = hotline_store.replay()
    formed = [event for event in events if event.type == "agreement.formed"]
    assert len(formed) == 1
    assert set(formed[0].payload["states"]) == {"northstar", "vesper"}
    assert formed[0].payload["kind"] == "hotline"
    assert not any(event.type == "agreement.violated" for event in events)

    def hostile_threat_driver(store: EventStore) -> float:
        return next(
            float(event.payload["drivers"]["hostile"])
            for event in store.replay()
            if event.type == "threat.updated"
            and event.payload["state"] == "northstar"
            and event.turn == 2
        )

    hotline = hostile_threat_driver(hotline_store)
    control = hostile_threat_driver(control_store)
    assert control > 0.0
    assert hotline == pytest.approx(control / 2)


async def test_trust_notes_reach_hos_prompts(tmp_path: Path) -> None:
    runner, caller, _ = _make_runner(tmp_path, {"northstar": STAY, "vesper": STAY})
    runner._state.trust.update("intelligence_chief", 1.0, turn=0)
    await runner.run(1)

    hos_prompts = [prompt for _, prompt, site in caller.calls if site == "hos_decision"]
    assert len(hos_prompts) == 2
    assert all("Intelligence Chief — track record strong (0.95)" in p for p in hos_prompts)

    baseline_runner, baseline_caller, _ = _make_runner(
        tmp_path / "baseline", {"northstar": STAY, "vesper": STAY}
    )
    await baseline_runner.run(1)
    baseline_prompts = [
        prompt for _, prompt, site in baseline_caller.calls if site == "hos_decision"
    ]
    assert all("track record mixed (0.50)" in p for p in baseline_prompts)


async def test_same_seed_same_outputs_identical_log(tmp_path: Path) -> None:
    actions: dict[str, ActionRule] = {"northstar": STAY, "vesper": STAY}
    _, store_a = await _run(tmp_path / "a", actions)
    _, store_b = await _run(tmp_path / "b", actions)
    assert store_a.replay() == store_b.replay()


async def test_restart_preserves_pending_verification(tmp_path: Path) -> None:
    verify = _action(ActionKind.VERIFY_REPORT, target_attribute="readiness")
    actions: dict[str, ActionRule] = {
        "northstar": lambda turn: verify if turn == 1 else STAY,
        "vesper": STAY,
    }
    _, reference = await _run(tmp_path / "ref", actions)

    runner, _, store = _make_runner(tmp_path / "restart", actions)
    await runner.run(1)
    resumed, _, _ = _make_runner(tmp_path / "restart", actions)
    await resumed.run(TURNS - 1)

    events = store.replay()
    verified = [
        event
        for event in events
        if event.type == "report.rendered" and event.payload.get("verified") is True
    ]
    assert len(verified) == 1, "pending verification was lost across the restart"
    assert verified[0].turn == 2
    assert [event for event in events if event.type == "claim.scored"] == [
        event for event in reference.replay() if event.type == "claim.scored"
    ]


LEAK_SEED = 16


def _leaking_seed() -> int:
    world = TrueWorldState(
        turn=1,
        countries={
            state: CountryState(
                resources={kind: 50.0 for kind in ResourceKind},
                readiness=40.0,
                stability=60.0,
                intelligence_capability=50.0,
                diplomatic_credibility=50.0,
            )
            for state in StateID
        },
    )
    covert = ActionSpec(kind=ActionKind.COVERT_MOBILIZATION)
    if resolve(covert, StateID.NORTHSTAR, world, SimParams(), SeededRNG(LEAK_SEED), 1).intel:
        return LEAK_SEED
    return next(
        seed
        for seed in range(500)
        if resolve(covert, StateID.NORTHSTAR, world, SimParams(), SeededRNG(seed), 1).intel
    )


async def test_leaked_intel_reaches_enemy_without_deception_event(tmp_path: Path) -> None:
    _, store = await _run(
        tmp_path / "leak",
        {"northstar": COVERT, "vesper": STAY},
        seed=_leaking_seed(),
        turns=1,
    )
    events = store.replay()

    reports = [
        event
        for event in events
        if event.type == "report.rendered" and event.payload.get("planted") is False
    ]
    assert len(reports) == 1
    assert reports[0].payload["observer"] == "vesper"
    assert reports[0].payload["about"] == "northstar"
    assert reports[0].payload["attribute"] == "readiness"
    assert not [event for event in events if event.type == "deception.planted"]


async def test_restarted_run_matches_uninterrupted_run(tmp_path: Path) -> None:
    actions: dict[str, ActionRule] = {"northstar": STAY, "vesper": STAY}
    _, reference = await _run(tmp_path / "ref", actions)

    runner, _, store = _make_runner(tmp_path / "restart", actions)
    await runner.run(1)
    resumed, _, _ = _make_runner(tmp_path / "restart", actions)
    await resumed.run(TURNS - 1)

    reference_tail = reference.replay()[-(len(store.replay()) - 1) :]
    continued = store.replay()[1:]
    assert continued == reference_tail


async def test_restart_spanning_claim_expiry_matches_uninterrupted_run(tmp_path: Path) -> None:
    expiring = Claim(
        subject="enemy.readiness",
        direction=Direction.STABLE,
        magnitude=40.0,
        horizon_turns=1,
    )
    actions: dict[str, ActionRule] = {"northstar": STAY, "vesper": STAY}
    _, reference = await _run(tmp_path / "ref", actions, claim=expiring)

    runner, _, store = _make_runner(tmp_path / "restart", actions, claim=expiring)
    await runner.run(2)
    resumed, _, _ = _make_runner(tmp_path / "restart", actions, claim=expiring)
    await resumed.run(TURNS - 2)

    reference_tail = reference.replay()[-(len(store.replay()) - 1) :]
    continued = store.replay()[1:]
    assert continued == reference_tail

    scored = [event for event in continued if event.type == "claim.scored"]
    assert scored
    assert len({str(event.payload["claim_id"]) for event in scored}) == len(scored)
    assert any(event.turn == 2 for event in scored), "claims must score before the restart"


async def test_restart_continues_exercise_phantom_window(tmp_path: Path) -> None:
    exercise = _action(ActionKind.CONDUCT_EXERCISE)
    actions: dict[str, ActionRule] = {
        "northstar": lambda turn: exercise if turn == 1 else STAY,
        "vesper": STAY,
    }
    _, reference = await _run(tmp_path / "ref", actions, seed=6)

    runner, _, store = _make_runner(tmp_path / "restart", actions, seed=6)
    await runner.run(1)
    resumed, _, _ = _make_runner(tmp_path / "restart", actions, seed=6)
    assert resumed._state.active_exercises == {StateID.NORTHSTAR: 2}, (
        "exercise timer must survive the restart"
    )
    await resumed.run(TURNS - 1)

    reference_tail = reference.replay()[-(len(store.replay()) - 1) :]
    continued = store.replay()[1:]
    assert continued == reference_tail, "exercise window diverged across restart"

    window_sightings = [
        event
        for event in continued
        if event.type == "observation.generated"
        and event.turn == 2
        and event.payload["observer"] == "vesper"
        and any(
            report["source"] == "imint" and report["attribute"] == "readiness"
            for report in event.payload["reports"]
        )
    ]
    assert window_sightings, "no IMINT sighting occurred inside the surviving phantom window"


async def test_restart_keeps_hotline_armed_for_violation_detection(tmp_path: Path) -> None:
    propose = _action(ActionKind.PROPOSE_AGREEMENT)
    betray = _action(ActionKind.COVERT_MOBILIZATION)

    def actions_for() -> dict[str, ActionRule]:
        return {
            "northstar": lambda turn: propose if turn == 1 else STAY,
            "vesper": lambda turn: betray if turn == 2 else STAY,
        }

    seed = -1
    for candidate_seed in range(40):
        _, candidate = await _run(
            tmp_path / f"probe-{candidate_seed}" / "ref", actions_for(), seed=candidate_seed
        )
        types = {event.type for event in candidate.replay()}
        if "agreement.formed" in types and "agreement.violated" in types:
            seed = candidate_seed
            break
    assert seed >= 0, "no seed formed a hotline and detected a violation"

    _, reference = await _run(tmp_path / "ref", actions_for(), seed=seed)

    runner, _, store = _make_runner(tmp_path / "restart", actions_for(), seed=seed)
    await runner.run(1)
    resumed, _, _ = _make_runner(tmp_path / "restart", actions_for(), seed=seed)
    assert resumed._state.hotline_active, "hotline must be active after the restart"
    await resumed.run(TURNS - 1)

    continued = store.replay()
    formed = [event for event in continued if event.type == "agreement.formed"]
    violated = [event for event in continued if event.type == "agreement.violated"]
    assert [event.turn for event in formed] == [1]
    assert [event.turn for event in violated] == [2], "violation must be caught after restart"

    reference_tail = reference.replay()[-(len(continued) - 1) :]
    assert continued[1:] == reference_tail


async def test_rebuild_restores_reliabilities_from_latest_event(tmp_path: Path) -> None:
    runner, _, store = _make_runner(tmp_path, {"northstar": STAY, "vesper": STAY})
    await runner.run(2)

    latest: dict[str, dict[str, float]] = {}
    for event in store.replay():
        if event.type == "observation.generated":
            reliabilities = event.payload["reliabilities"]
            assert isinstance(reliabilities, dict)
            latest[str(event.payload["observer"])] = {
                source: float(value) for source, value in reliabilities.items()
            }
    assert latest

    rebuilt = rebuild_state(store.replay(), RunConfig(seed=SEED).params)
    for observer, expected in latest.items():
        assert rebuilt.reliabilities[StateID(observer)] == expected


async def test_rebuild_falls_back_to_params_without_observations(tmp_path: Path) -> None:
    params = RunConfig(seed=SEED).params
    state = TurnState(params)
    assert state.reliabilities == {
        observer: {source.value: value for source, value in params.source_reliability_init.items()}
        for observer in StateID
    }

    events = [make_event("run.started", seq=0, turn=0, seed=SEED, turns=1, initial_world={})]
    rebuilt = rebuild_state(events, params)
    assert rebuilt.reliabilities == {
        observer: {source.value: value for source, value in params.source_reliability_init.items()}
        for observer in StateID
    }


class _FakeRunner:
    def __init__(self, events: list[Event]) -> None:
        self._events = events

    def beliefs(self, observer: StateID) -> BeliefState:
        return project_beliefs(self._events, observer)

    def emit_payload(self, event_type: str, turn: int, payload: dict[str, object]) -> Event:
        event = Event(seq=0, turn=turn, type=event_type, payload={**payload, "turn": turn})
        self._events.append(event)
        return event


def _report(observer: StateID, turn: int, value: float) -> Event:
    return make_event(
        "report.rendered",
        seq=0,
        turn=turn,
        observer=observer.value,
        about="vesper" if observer is StateID.NORTHSTAR else "northstar",
        attribute="readiness",
        value=value,
        confidence=0.9,
        age_turns=0,
        source="imint",
        text="t",
    )


def test_horizon_adjudication_uses_prior_belief_for_trend(tmp_path: Path) -> None:
    observer = StateID.NORTHSTAR
    events = [_report(observer, 1, 40.0), _report(observer, 3, 55.0)]
    runner = _FakeRunner(events)
    params = RunConfig(seed=SEED).params
    state = TurnState(params)
    state.ledger.open(
        Claim(
            subject="enemy.readiness",
            direction=Direction.RISING,
            magnitude=55.0,
            horizon_turns=2,
        ),
        author_role="intelligence_chief",
        state=observer,
        turn=1,
        claim_id="northstar:intelligence_chief:1",
    )

    adjudicate_horizon(runner, state, turn=3, log=events)

    scored = [event for event in events if event.type == "claim.scored"]
    assert scored, "horizon adjudication never scored the expired claim"
    assert scored[0].payload["outcome"] == pytest.approx(1.0)


def test_horizon_adjudication_stable_trend_scores_zero_on_mismatch(tmp_path: Path) -> None:
    observer = StateID.NORTHSTAR
    events = [_report(observer, 1, 40.0), _report(observer, 3, 55.0)]
    runner = _FakeRunner(events)
    params = RunConfig(seed=SEED).params
    state = TurnState(params)
    state.ledger.open(
        Claim(
            subject="enemy.readiness",
            direction=Direction.STABLE,
            magnitude=55.0,
            horizon_turns=2,
        ),
        author_role="intelligence_chief",
        state=observer,
        turn=1,
        claim_id="northstar:intelligence_chief:1",
    )

    adjudicate_horizon(runner, state, turn=3, log=events)

    scored = [event for event in events if event.type == "claim.scored"]
    assert scored, "horizon adjudication never scored the expired claim"
    assert scored[0].payload["outcome"] == 0.0


async def test_request_stop_halts_between_turns_and_stays_resumable(tmp_path: Path) -> None:
    actions: dict[str, ActionRule] = {"northstar": STAY, "vesper": STAY}
    _, reference = await _run(tmp_path / "ref", actions)

    runner, _, store = _make_runner(tmp_path / "stop", actions)
    runner.request_stop()
    await runner.run(TURNS)
    halted_log = store.replay()
    assert [event.type for event in halted_log if event.type == "turn.started"] == [], (
        "run after request_stop must not execute any turn"
    )
    assert any(event.type == "run.stopped" for event in halted_log), (
        "halted run must log run.stopped"
    )
    assert not any(event.type == "run.ended" for event in halted_log), (
        "halted run must not claim completion"
    )

    resumed, _, store = _make_runner(tmp_path / "stop", actions)
    await resumed.run(TURNS)
    content = lambda e: (e.turn, e.type, e.payload)  # noqa: E731
    resumed_story = [content(e) for e in store.replay() if e.type != "run.stopped"]
    assert resumed_story == [content(e) for e in reference.replay()]


async def test_contact_events_carry_territory_coordinates(tmp_path: Path) -> None:
    exercise = _action(ActionKind.CONDUCT_EXERCISE)
    surveillance = _action(ActionKind.INCREASE_SURVEILLANCE)
    actions: dict[str, ActionRule] = {
        "northstar": lambda turn: exercise if turn == 1 else STAY,
        "vesper": lambda turn: surveillance if turn == 1 else STAY,
    }
    _, store = await _run(tmp_path, actions)

    contacts = [event for event in store.replay() if event.type == "contact.detected"]
    assert contacts, "exercise/surveillance turns must produce contacts"
    boxes = {
        "northstar": TERRITORIES[StateID.NORTHSTAR],
        "vesper": TERRITORIES[StateID.VESPER],
    }
    for contact in contacts:
        about = str(contact.payload["about"])
        min_lon, min_lat, max_lon, max_lat = boxes[about]
        lon, lat = float(contact.payload["lon"]), float(contact.payload["lat"])
        assert min_lon <= lon <= max_lon, f"{lon} outside {about} territory"
        assert min_lat <= lat <= max_lat, f"{lat} outside {about} territory"


async def test_every_llm_call_emits_agent_activity(tmp_path: Path) -> None:
    actions: dict[str, ActionRule] = {"northstar": STAY, "vesper": STAY}
    _, store = await _run(tmp_path, actions)
    events = store.replay()

    activity = [event for event in events if event.type == "agent.activity"]
    assert activity, "LLM calls must emit agent.activity telemetry"
    starts = [e for e in activity if not str(e.payload["action"]).startswith("done:")]
    dones = [e for e in activity if str(e.payload["action"]).startswith("done:")]
    assert len(starts) == len(dones), "every call needs a start and a done"
    assert all(e.payload["state"] in ("northstar", "vesper") for e in starts)
    roles = {str(e.payload["role"]) for e in activity}
    assert roles == {
        "intelligence_chief",
        "military_chief",
        "diplomat",
        "head_of_state",
    }, roles
    assert all(str(e.payload["model"]) for e in activity), "model id must be surfaced"

    # Truth isolation: activity telemetry carries states/roles/models only.
    for event in activity:
        assert set(event.payload) <= {"turn", "state", "role", "model", "action", "phase"}


async def test_agent_activity_is_visible_in_agent_packets(tmp_path: Path) -> None:
    """Activity is deliberately observer-visible; packets must not break on it."""
    actions: dict[str, ActionRule] = {"northstar": STAY, "vesper": STAY}
    _, store = await _run(tmp_path, actions)
    events = store.replay()
    for observer in StateID:
        packet = assemble_packet(
            Role.HEAD_OF_STATE,
            observer,
            2,
            events,
            BeliefState(observer=observer, target=observer, attributes={}),
            [],
        )
        assert packet is not None
