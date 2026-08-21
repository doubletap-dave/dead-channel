"""Tests for the claim ledger and trust scoring."""

import pydantic
import pytest

from dead_channel.core.config import SimParams
from dead_channel.core.types import Claim, Direction, StateID
from dead_channel.engine.ledger import ClaimRecord, Ledger, TrustTracker


def make_claim(direction: Direction = Direction.RISING, magnitude: float = 50.0) -> Claim:
    return Claim(subject="military readiness", direction=direction, magnitude=magnitude)


def make_record(
    claim_id: str,
    opened_turn: int,
    direction: Direction = Direction.RISING,
    outcome: float | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim=make_claim(direction=direction),
        author_role="analyst",
        state=StateID.VESPER,
        opened_turn=opened_turn,
        status="scored" if outcome is not None else "open",
        outcome=outcome,
    )


def test_accurate_claim_scores_perfect_and_raises_trust() -> None:
    params = SimParams()
    ledger = Ledger(params)
    tracker = TrustTracker(params)
    ledger.open(make_claim(), "analyst", StateID.VESPER, turn=4, claim_id="c1")

    record = ledger.adjudicate("c1", realized=50.0, direction_realized=Direction.RISING, turn=6)

    assert record.outcome == pytest.approx(1.0)
    assert record.status == "scored"
    assert record.scored_turn == 6
    tracker.update("analyst", record.outcome, turn=6)
    trust = tracker.trust("analyst", now_turn=6)
    assert trust > 0.5
    assert trust == pytest.approx(0.95)


def test_wrong_direction_scores_exactly_zero() -> None:
    ledger = Ledger(SimParams())
    ledger.open(
        make_claim(direction=Direction.RISING), "analyst", StateID.VESPER, turn=2, claim_id="c1"
    )

    record = ledger.adjudicate("c1", realized=50.0, direction_realized=Direction.FALLING, turn=4)

    assert record.outcome == 0.0


def test_stable_claim_against_moving_reality_scores_zero() -> None:
    ledger = Ledger(SimParams())
    ledger.open(
        make_claim(direction=Direction.STABLE), "analyst", StateID.VESPER, turn=2, claim_id="c1"
    )

    record = ledger.adjudicate("c1", realized=50.0, direction_realized=Direction.RISING, turn=4)

    assert record.outcome == 0.0


def test_direction_check_skipped_without_realized_direction() -> None:
    ledger = Ledger(SimParams())
    ledger.open(
        make_claim(direction=Direction.STABLE), "analyst", StateID.VESPER, turn=2, claim_id="c1"
    )

    record = ledger.adjudicate("c1", realized=50.0, direction_realized=None, turn=4)

    assert record.outcome == pytest.approx(1.0)


def test_non_directional_claims_ignore_direction_mismatch() -> None:
    ledger = Ledger(SimParams())
    ledger.open(
        make_claim(direction=Direction.DECEPTION, magnitude=40.0),
        "analyst",
        StateID.VESPER,
        turn=2,
        claim_id="c1",
    )

    record = ledger.adjudicate("c1", realized=40.0, direction_realized=Direction.RISING, turn=4)

    assert record.outcome == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("realized", "expected"),
    [(20.0, 0.0), (35.0, 0.5), (65.0, 0.5), (0.0, 0.0), (100.0, 0.0), (50.0, 1.0)],
)
def test_magnitude_error_scales_outcome(realized: float, expected: float) -> None:
    ledger = Ledger(SimParams())
    ledger.open(make_claim(magnitude=50.0), "analyst", StateID.VESPER, turn=2, claim_id="c1")

    record = ledger.adjudicate("c1", realized=realized, direction_realized=Direction.RISING, turn=4)

    assert record.outcome == pytest.approx(expected)


def test_stale_failures_fade_as_successes_accumulate() -> None:
    tracker = TrustTracker(SimParams())
    for turn in (5, 6, 7, 8):
        tracker.update("analyst", 1.0, turn)
    tracker.update("analyst", 0.0, turn=9)

    early = tracker.trust("analyst", now_turn=10)
    for turn in (20, 25, 30, 35, 38):
        tracker.update("analyst", 1.0, turn)
    late = tracker.trust("analyst", now_turn=40)

    assert early == pytest.approx(0.877, abs=1e-2)
    assert late > early
    assert late == pytest.approx(0.95)


def test_overridden_dissent_redeemed_ranks_salient_and_raises_trust() -> None:
    params = SimParams()
    ledger = Ledger(params)
    tracker = TrustTracker(params)
    ledger.open(make_claim(), "analyst", StateID.VESPER, turn=3, claim_id="c-old")
    old = ledger.adjudicate("c-old", realized=50.0, direction_realized=Direction.RISING, turn=6)
    ledger.open(
        make_claim(),
        "analyst",
        StateID.VESPER,
        turn=12,
        claim_id="c-dissent",
        was_dissent=True,
    )

    dissent = ledger.adjudicate(
        "c-dissent", realized=50.0, direction_realized=Direction.RISING, turn=14
    )

    assert dissent.was_dissent is True
    assert dissent.outcome == pytest.approx(1.0)
    top = tracker.salient([old, dissent], k=1, now_turn=14)
    assert [r.claim_id for r in top] == ["c-dissent"]
    tracker.update("analyst", dissent.outcome, turn=14)
    assert tracker.trust("analyst", now_turn=14) > 0.5


def test_double_adjudication_raises() -> None:
    ledger = Ledger(SimParams())
    ledger.open(make_claim(), "analyst", StateID.VESPER, turn=2, claim_id="c1")
    ledger.adjudicate("c1", realized=50.0, direction_realized=Direction.RISING, turn=4)

    with pytest.raises(ValueError):
        ledger.adjudicate("c1", realized=50.0, direction_realized=Direction.RISING, turn=6)


def test_unknown_claim_adjudication_raises() -> None:
    ledger = Ledger(SimParams())

    with pytest.raises(KeyError):
        ledger.adjudicate("missing", realized=50.0, direction_realized=Direction.RISING, turn=4)


def test_salient_tie_breaks_deterministically() -> None:
    tracker = TrustTracker(SimParams())
    records = [
        make_record("c-c", opened_turn=10),
        make_record("c-a", opened_turn=10),
        make_record("c-b", opened_turn=10),
    ]

    top = tracker.salient(records, k=2, now_turn=10)

    assert [r.claim_id for r in top] == ["c-a", "c-b"]


def test_salient_escalates_deception_and_burned_claims() -> None:
    tracker = TrustTracker(SimParams())
    plain = make_record("c-plain", opened_turn=12)
    deception = make_record("c-decep", opened_turn=6, direction=Direction.DECEPTION)
    burned = make_record("c-burn", opened_turn=6, outcome=0.2)

    ranked = tracker.salient([plain, deception, burned], k=3, now_turn=12)

    assert [r.claim_id for r in ranked] == ["c-burn", "c-decep", "c-plain"]


def test_trust_defaults_to_baseline_without_history() -> None:
    tracker = TrustTracker(SimParams())

    assert tracker.trust("ghost", now_turn=7) == 0.5


def test_trust_clamped_to_band() -> None:
    tracker = TrustTracker(SimParams())
    tracker.update("liar", 0.0, turn=1)
    tracker.update("hero", 1.0, turn=1)

    assert tracker.trust("liar", now_turn=1) == pytest.approx(0.1)
    assert tracker.trust("hero", now_turn=1) == pytest.approx(0.95)


def test_records_for_filters_by_state_and_role() -> None:
    ledger = Ledger(SimParams())
    ledger.open(make_claim(), "analyst", StateID.VESPER, turn=2, claim_id="c1")
    ledger.open(make_claim(), "chief", StateID.VESPER, turn=2, claim_id="c2")
    ledger.open(make_claim(), "analyst", StateID.NORTHSTAR, turn=2, claim_id="c3")

    assert {r.claim_id for r in ledger.records_for(StateID.VESPER)} == {"c1", "c2"}
    assert {r.claim_id for r in ledger.records_for(StateID.VESPER, role="analyst")} == {"c1"}
    assert ledger.records_for(StateID.VESPER, role="nobody") == []


def test_open_claims_excludes_scored() -> None:
    ledger = Ledger(SimParams())
    ledger.open(make_claim(), "analyst", StateID.VESPER, turn=2, claim_id="c1")
    ledger.open(make_claim(), "analyst", StateID.VESPER, turn=2, claim_id="c2")

    ledger.adjudicate("c1", realized=50.0, direction_realized=Direction.RISING, turn=4)

    assert [r.claim_id for r in ledger.open_claims()] == ["c2"]


def test_claim_record_is_frozen() -> None:
    record = make_record("c1", opened_turn=2)

    with pytest.raises(pydantic.ValidationError):
        record.status = "scored"
