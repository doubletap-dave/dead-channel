"""Ledger adjudication: verification scoring and claim-horizon expiry."""

from collections.abc import Iterable

from dead_channel.core.events import Event
from dead_channel.core.types import Direction, StateID
from dead_channel.engine.support import TurnHost
from dead_channel.engine.turn_state import TurnState

ENEMY_SUBJECT_PREFIX = "enemy."


def _subject_attribute(subject: str) -> str | None:
    # Claims are scoped to beliefs about the rival ("enemy.<attribute>"); a bare
    # subject has no observer-relative meaning, so it can never be scored.
    if not subject.startswith(ENEMY_SUBJECT_PREFIX):
        return None
    return subject.removeprefix(ENEMY_SUBJECT_PREFIX)


def score_claims_on_attribute(
    host: TurnHost,
    state: TurnState,
    observer: StateID,
    attribute: str,
    realized: float,
    turn: int,
) -> None:
    for record in state.ledger.records_for(observer):
        if record.status != "open" or _subject_attribute(record.claim.subject) != attribute:
            continue
        _score(host, state, record.claim_id, record.author_role, observer, realized, None, turn)


def adjudicate_horizon(host: TurnHost, state: TurnState, turn: int, log: list[Event]) -> None:
    for observer in StateID:
        beliefs = host.beliefs(observer)
        for record in state.ledger.records_for(observer):
            if record.status != "open":
                continue
            if record.opened_turn + record.claim.horizon_turns > turn:
                continue
            subject = _subject_attribute(record.claim.subject)
            if subject is None:
                continue
            believed = beliefs.attributes.get(subject)
            if believed is None:
                continue
            prior = _prior_belief(log, observer, subject, record.opened_turn)
            _score(
                host,
                state,
                record.claim_id,
                record.author_role,
                observer,
                believed.value,
                _trend(believed.value, prior),
                turn,
            )


def _prior_belief(
    log: Iterable[Event], observer: StateID, attribute: str, opened_turn: int
) -> float | None:
    latest: tuple[int, float] | None = None
    for event in log:
        if event.type != "report.rendered" or event.turn > opened_turn:
            continue
        payload = event.payload
        if (
            payload.get("observer") != observer.value
            or payload.get("attribute") != attribute
            or not isinstance(payload.get("value"), (int, float))
        ):
            continue
        if latest is None or event.turn >= latest[0]:
            latest = (event.turn, float(payload["value"]))
    return latest[1] if latest else None


def _trend(current: float, prior: float | None) -> Direction:
    if prior is None or current == prior:
        return Direction.STABLE
    return Direction.RISING if current > prior else Direction.FALLING


def _score(
    host: TurnHost,
    state: TurnState,
    claim_id: str,
    role: str,
    observer: StateID,
    realized: float,
    direction: Direction | None,
    turn: int,
) -> None:
    outcome = state.ledger.adjudicate(
        claim_id, realized=realized, direction_realized=direction, turn=turn
    )
    state.trust.update(role, outcome.outcome, turn)
    host.emit_payload(
        "claim.scored",
        turn,
        {
            "state": observer.value,
            "claim_id": claim_id,
            "role": role,
            "outcome": outcome.outcome,
            "turn": turn,
        },
    )
