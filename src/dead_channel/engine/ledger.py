"""Claim ledger and trust scoring: makes agent memory consequential."""

import math
from collections.abc import Sequence
from typing import Literal

import pydantic

from dead_channel.core.config import SimParams
from dead_channel.core.types import Claim, Direction, StateID

_TRUST_FLOOR = 0.1
_TRUST_CEIL = 0.95
_BURNED_OUTCOME = 0.3
_EMOTIONAL_MULTIPLIER = 2.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _recency_weight(age_turns: float, half_life: float) -> float:
    return 0.5 ** (age_turns / half_life)


class ClaimRecord(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    claim_id: str
    claim: Claim
    author_role: str
    state: StateID
    opened_turn: int
    status: Literal["open", "scored"] = "open"
    outcome: float | None = None
    scored_turn: int | None = None
    was_dissent: bool = False


class Ledger:
    def __init__(self, params: SimParams) -> None:
        self.params = params
        self._records: dict[str, ClaimRecord] = {}

    def open(
        self,
        claim: Claim,
        author_role: str,
        state: StateID,
        turn: int,
        claim_id: str,
        was_dissent: bool = False,
    ) -> ClaimRecord:
        record = ClaimRecord(
            claim_id=claim_id,
            claim=claim,
            author_role=author_role,
            state=state,
            opened_turn=turn,
            was_dissent=was_dissent,
        )
        self._records[claim_id] = record
        return record

    def adjudicate(
        self,
        claim_id: str,
        realized: float,
        direction_realized: Direction | None,
        turn: int,
    ) -> ClaimRecord:
        record = self._records[claim_id]
        if record.status == "scored":
            raise ValueError(f"claim {claim_id} already adjudicated")

        outcome = self._score(record, realized, direction_realized)
        scored = record.model_copy(
            update={"status": "scored", "outcome": outcome, "scored_turn": turn}
        )
        self._records[claim_id] = scored
        return scored

    def _score(
        self, record: ClaimRecord, realized: float, direction_realized: Direction | None
    ) -> float:
        direction = record.claim.direction
        if (
            direction in (Direction.RISING, Direction.FALLING, Direction.STABLE)
            and direction_realized is not None
            and direction_realized != direction
        ):
            return 0.0
        error = abs(record.claim.magnitude - realized) / self.params.claim_error_scale
        return 1.0 - _clamp(error, 0.0, 1.0)

    def records_for(self, state: StateID, role: str | None = None) -> list[ClaimRecord]:
        return [
            r
            for r in self._records.values()
            if r.state == state and (role is None or r.author_role == role)
        ]

    def open_claims(self) -> list[ClaimRecord]:
        return [r for r in self._records.values() if r.status == "open"]


class TrustTracker:
    def __init__(self, params: SimParams) -> None:
        self.params = params
        self._history: dict[str, list[tuple[float, int]]] = {}

    def update(self, role: str, outcome: float, turn: int) -> None:
        self._history.setdefault(role, []).append((outcome, turn))

    def trust(self, role: str, now_turn: int) -> float:
        history = self._history.get(role)
        if not history:
            return 0.5
        weighted = sum(
            _recency_weight(now_turn - t, self.params.trust_half_life) * outcome
            for outcome, t in history
        )
        total = sum(_recency_weight(now_turn - t, self.params.trust_half_life) for _, t in history)
        score = weighted / total
        return _clamp(0.5 + math.tanh(1.5 * (score - 0.5)), _TRUST_FLOOR, _TRUST_CEIL)

    def salient(self, records: Sequence[ClaimRecord], k: int, now_turn: int) -> list[ClaimRecord]:
        def rank_key(record: ClaimRecord) -> tuple[float, int, str]:
            recency = _recency_weight(now_turn - record.opened_turn, self.params.trust_half_life)
            emotional = _EMOTIONAL_MULTIPLIER if self._is_emotional(record) else 1.0
            return (-recency * emotional, -record.opened_turn, record.claim_id)

        return sorted(records, key=rank_key)[:k]

    @staticmethod
    def _is_emotional(record: ClaimRecord) -> bool:
        burned = record.outcome is not None and record.outcome < _BURNED_OUTCOME
        return burned or record.claim.direction is Direction.DECEPTION
