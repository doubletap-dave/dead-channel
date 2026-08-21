"""TurnRunner: the full turn pipeline over the event store.

Restart guarantee is BETWEEN-TURN determinism: replaying the log reproduces
TurnState at every turn boundary; a crash mid-turn loses that turn's remainder
(conscious V0 deferral).
"""

from pathlib import Path

from dead_channel.agents.calls import ModelResolver
from dead_channel.core.config import RunConfig
from dead_channel.core.events import Event, make_event
from dead_channel.core.rng import SeededRNG
from dead_channel.core.types import (
    ActionSpec,
    Decision,
    IntelPayload,
    StateID,
    TrueWorldState,
)
from dead_channel.engine.adjudicate import adjudicate_horizon, score_claims_on_attribute
from dead_channel.engine.beliefs import BeliefState
from dead_channel.engine.bus import EventBus
from dead_channel.engine.decide import hos_decision
from dead_channel.engine.observation import generate_observations
from dead_channel.engine.projections import project_beliefs, project_world
from dead_channel.engine.rebuild import rebuild_state
from dead_channel.engine.resolution import ResolutionResult, resolve
from dead_channel.engine.resolve_ops import (
    apply_resolution,
    handle_agreements,
    handle_violations,
    threat_event,
)
from dead_channel.engine.store import EventStore
from dead_channel.engine.support import (
    TurnHost,
    action_of,
    advance_defcon,
    apply_decision_side_effects,
    other,
)
from dead_channel.engine.turn_ops import advisor_assessments, render_reports
from dead_channel.engine.verification import verify_attribute
from dead_channel.providers.caller import Caller, persist_prompt


class TurnRunner(TurnHost):
    def __init__(
        self,
        store: EventStore,
        bus: EventBus,
        caller: Caller,
        config: RunConfig,
        runs_dir: Path,
    ) -> None:
        self.store = store
        self.bus = bus
        self.caller = caller
        self.config = config
        self.runs_dir = runs_dir
        self.rng = SeededRNG(config.seed)
        self.resolver = ModelResolver(config.model_matrix)
        self._stop_requested = False
        self._stop_logged = False
        log = store.replay()
        self._state = rebuild_state(log, config.params)
        self._started = bool(log)
        self._reliabilities = {
            observer: dict(reliabilities)
            for observer, reliabilities in self._state.reliabilities.items()
        }

    def emit(self, event_type: str, turn: int, **payload: object) -> Event:
        event = self.store.append(make_event(event_type, seq=0, turn=turn, **payload))
        self.bus.publish(event)
        return event

    def emit_payload(self, event_type: str, turn: int, payload: dict[str, object]) -> Event:
        event = Event(seq=0, turn=turn, type=event_type, payload={**payload, "turn": turn})
        stored = self.store.append(event)
        self.bus.publish(stored)
        return stored

    def _run_id(self) -> str:
        return self.store.path.parent.name

    def _persist(self, event: Event, response: object, model: str, prompt: str) -> None:
        state = event.payload.get("state") or event.payload.get("observer")
        persist_prompt(
            self.runs_dir,
            self._run_id(),
            event.turn,
            str(event.type.replace(".", "_")),
            model,
            prompt,
            response,
            str(state) if state else None,
        )

    def world(self) -> TrueWorldState:
        return project_world(self.store.replay())

    def beliefs(self, observer: StateID) -> BeliefState:
        return project_beliefs(self.store.replay(), observer)

    async def run(self, turns: int) -> None:
        if not self._started:
            self.emit(
                "run.started",
                0,
                seed=self.config.seed,
                turns=turns,
                initial_world=self.world().model_dump(),
            )
            self._started = True
        for _ in range(turns):
            if self._stop_requested:
                self._log_stop()
                return
            await self.run_turn()
        if self._stop_requested:
            self._log_stop()
            return
        if self._current_turn() >= self.config.turns:
            self.emit_payload("run.ended", self._current_turn(), {"turn": self._current_turn()})

    def request_stop(self) -> None:
        """Halt after the in-flight turn completes; the log stays resumable."""
        self._stop_requested = True

    def _log_stop(self) -> None:
        if not self._stop_logged:
            self._stop_logged = True
            self.emit_payload("run.stopped", self._current_turn(), {"turn": self._current_turn()})

    def _current_turn(self) -> int:
        return project_world(self.store.replay()).turn

    async def run_turn(self) -> None:
        turn = self._current_turn() + 1
        state = self._state
        self.emit_payload("turn.started", turn, {})
        state.tick_timers()
        self.emit_payload("world.ticked", turn, {})

        batch_reports = self._observations(turn)
        for observer in StateID:
            payloads = [r for r in batch_reports if r.about is other(observer)]
            await render_reports(self, turn, observer, payloads)
            await self._pending_verification(turn, observer)

        log = self.store.replay()
        advisor_events = {
            observer: await advisor_assessments(self, state, turn, log, observer)
            for observer in StateID
        }

        decisions = {
            state_id: await hos_decision(
                self, self._state, turn, self.store.replay(), state_id, advisor_events[state_id]
            )
            for state_id in StateID
        }
        results = self._resolve_all(turn, decisions)
        self._threat_and_diplomacy(turn, decisions, results, self.world())
        adjudicate_horizon(self, state, turn, self.store.replay())

        state.defcon = advance_defcon(state)
        if state.defcon.defcon == 1 and not state.conflict_crossed:
            state.conflict_crossed = True
            self.emit_payload("conflict.threshold_crossed", turn, {"turn": turn})

    def _resolve_all(
        self, turn: int, decisions: dict[StateID, Event]
    ) -> dict[StateID, ResolutionResult]:
        state = self._state
        world = self.world()
        results: dict[StateID, ResolutionResult] = {}
        actions: dict[StateID, ActionSpec] = {}
        for state_id in StateID:
            parsed = action_of(decisions[state_id].payload)
            if parsed is None:
                raise ValueError(f"decision.made payload has no action for {state_id}")
            actions[state_id] = ActionSpec(kind=parsed[0], params=parsed[1])
            results[state_id] = resolve(
                actions[state_id],
                state_id,
                world,
                self.config.params,
                self.rng,
                turn,
                deception_active=dict(state.deception_active),
            )
            apply_resolution(self, turn, state_id, results[state_id])
            action = actions[state_id]
            apply_decision_side_effects(state, state_id, action.kind, dict(action.params), turn)
        return results

    def _threat_and_diplomacy(
        self,
        turn: int,
        decisions: dict[StateID, Event],
        results: dict[StateID, ResolutionResult],
        world: TrueWorldState,
    ) -> None:
        state = self._state
        decision_models = {
            state_id: Decision.model_validate(decisions[state_id].payload) for state_id in StateID
        }
        for state_id in StateID:
            threat_event(self, state, turn, state_id, world, results, self.config.params)
        handle_violations(self, state, turn, decision_models)
        handle_agreements(self, state, turn, decision_models, state.threats, world, self.rng)

    def _observations(self, turn: int) -> list[IntelPayload]:
        state = self._state
        batch = generate_observations(
            self.world(),
            {observer: self.beliefs(observer) for observer in StateID},
            self.config.params,
            self.rng,
            turn,
            self._reliabilities,
            state.active_exercises,
        )
        for observer in StateID:
            reports = [r for r in batch.reports if r.about is other(observer)]
            self.emit(
                "observation.generated",
                turn,
                observer=observer.value,
                reports=[r.model_dump() for r in reports],
                reliabilities={
                    source.value: value for source, value in batch.reliabilities[observer].items()
                },
            )
        self._reliabilities = batch.reliabilities
        return batch.reports

    async def _pending_verification(self, turn: int, observer: StateID) -> None:
        pending = self._state.pending_verification.pop(observer, None)
        if pending is None:
            return
        payload = verify_attribute(self.world(), pending.attribute, observer, self.rng, turn)
        await render_reports(self, turn, observer, [payload], verified=True)
        score_claims_on_attribute(
            self, self._state, observer, pending.attribute, payload.value, turn
        )
