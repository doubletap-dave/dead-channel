"""Per-run mutable state rebuilt event-sourced from the log on construction."""

import pydantic

from dead_channel.core.config import SimParams
from dead_channel.core.types import IntelSource, StateID
from dead_channel.engine.ledger import Ledger, TrustTracker
from dead_channel.engine.threat import DefconState


class PendingVerification(pydantic.BaseModel):
    attribute: str
    opened_turn: int


class TurnState:
    def __init__(self, params: SimParams | None = None) -> None:
        self.params = params or SimParams()
        self.ledger = Ledger(self.params)
        self.trust = TrustTracker(self.params)
        self.reliabilities: dict[StateID, dict[IntelSource, float]] = {
            observer: dict(self.params.source_reliability_init) for observer in StateID
        }
        self.active_exercises: dict[StateID, int] = {}
        self.deception_active: dict[StateID, int] = {}
        self.hotline_active = False
        self.pending_verification: dict[StateID, PendingVerification] = {}
        self.threats: dict[StateID, float] = {}
        self.defcon = DefconState(defcon=5, hold=0)
        self.conflict_crossed = False
        self.believed_readiness: dict[StateID, float | None] = {}

    def tick_timers(self) -> None:
        self.active_exercises = {
            state: turns - 1 for state, turns in self.active_exercises.items() if turns > 1
        }
        self.deception_active = {
            state: turns - 1 for state, turns in self.deception_active.items() if turns > 1
        }
