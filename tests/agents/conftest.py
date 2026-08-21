"""Shared agent-test fixtures: report events, packets, and canned domain objects."""

import pytest

from dead_channel.agents.packets import AgentPacket, assemble_packet
from dead_channel.agents.policy import Role
from dead_channel.core.events import Event, make_event
from dead_channel.core.types import (
    ActionKind,
    ActionSpec,
    Assessment,
    Claim,
    Decision,
    Direction,
    IntelSource,
    StateID,
)
from dead_channel.engine.beliefs import BeliefState, BelievedValue


def _report_event(seq: int = 1, turn: int = 3, planted: bool = False) -> Event:
    payload: dict[str, object] = {
        "observer": "northstar",
        "about": "vesper",
        "attribute": "readiness",
        "value": 42.0,
        "confidence": 0.8,
        "age_turns": 0,
        "source": IntelSource.HUMINT.value,
    }
    if planted:
        payload["planted"] = True
    return make_event("report.rendered", seq=seq, turn=turn, **payload)


@pytest.fixture
def report_event() -> Event:
    return _report_event()


@pytest.fixture
def beliefs() -> BeliefState:
    return BeliefState(
        observer=StateID.NORTHSTAR,
        target=StateID.VESPER,
        attributes={"readiness": BelievedValue(value=42.0, confidence=0.8, last_report_turn=3)},
    )


@pytest.fixture
def make_packet():
    def _make(
        role: Role, *, beliefs: BeliefState | None = None, planted: bool = False
    ) -> AgentPacket:
        return assemble_packet(
            role, StateID.NORTHSTAR, 3, [_report_event(planted=planted)], beliefs, []
        )

    return _make


@pytest.fixture
def advisor_assessment() -> Assessment:
    return Assessment(
        role="intelligence_chief",
        interpretation="Enemy readiness is rising.",
        claim=Claim(subject="enemy.readiness", direction=Direction.RISING, magnitude=55.0),
        recommended_action=ActionSpec(kind=ActionKind.RAISE_READINESS),
        urgency=3,
    )


@pytest.fixture
def decision() -> Decision:
    return Decision(
        action=ActionSpec(kind=ActionKind.RAISE_READINESS),
        rationale="The threat picture demands preparation.",
    )
