"""Security tests: role visibility policy and context packet assembly.

These tests pin the core property: agents see only what their role allows,
the planted flag never reaches any packet or prompt, and advisor packets are
structurally isolated from sibling assessments and trust data.
"""

import pydantic
import pytest

from dead_channel.agents.packets import (
    AgentPacket,
    assemble_packet,
    packet_to_prompt_text,
)
from dead_channel.agents.policy import Role, visible
from dead_channel.core.events import Event, make_event
from dead_channel.core.types import (
    ActionKind,
    ActionSpec,
    Assessment,
    Claim,
    Direction,
    IntelSource,
    StateID,
)
from dead_channel.engine.beliefs import BeliefState, BelievedValue
from dead_channel.engine.ledger import ClaimRecord


def planted_report(seq: int = 1, turn: int = 3) -> Event:
    return make_event(
        "report.rendered",
        seq=seq,
        turn=turn,
        observer="northstar",
        about="vesper",
        attribute="readiness",
        value=42.0,
        confidence=0.8,
        age_turns=0,
        source=IntelSource.HUMINT.value,
        planted=True,
    )


def clean_report(seq: int = 2, turn: int = 3) -> Event:
    return make_event(
        "report.rendered",
        seq=seq,
        turn=turn,
        observer="northstar",
        about="vesper",
        attribute="military",
        value=51.0,
        confidence=0.7,
        source=IntelSource.SIGINT.value,
    )


def own_effect(seq: int = 4, turn: int = 2) -> Event:
    return make_event(
        "effect.applied", seq=seq, turn=turn, state="northstar", attribute="readiness", delta=-4.0
    )


def enemy_effect(seq: int = 3, turn: int = 2) -> Event:
    return make_event(
        "effect.applied", seq=seq, turn=turn, state="vesper", attribute="readiness", delta=9.0
    )


def hidden_effect(seq: int = 7, turn: int = 1) -> Event:
    return make_event(
        "effect.applied",
        seq=seq,
        turn=turn,
        state="northstar",
        attribute="concealment",
        delta=0.3,
    )


def plant_event(seq: int = 5, turn: int = 3) -> Event:
    return make_event(
        "deception.planted",
        seq=seq,
        turn=turn,
        about="vesper",
        attribute="stability",
        source=IntelSource.HUMINT.value,
        planted=True,
    )


def message(seq: int = 6, turn: int = 3, text: str = "readiness exercise scheduled") -> Event:
    return make_event(
        "message.sent", seq=seq, turn=turn, sender="northstar", recipient="vesper", text=text
    )


def assessment(role: str = "intelligence_chief", urgency: int = 3) -> Assessment:
    return Assessment(
        role=role,
        interpretation="Enemy readiness rising.",
        claim=Claim(subject="vesper_readiness", direction=Direction.RISING, magnitude=55.0),
        recommended_action=ActionSpec(kind=ActionKind.RAISE_READINESS),
        urgency=urgency,
    )


def claim_record(claim_id: str = "c1", opened_turn: int = 2) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim=Claim(subject="vesper_readiness", direction=Direction.RISING, magnitude=55.0),
        author_role="intelligence_chief",
        state=StateID.NORTHSTAR,
        opened_turn=opened_turn,
    )


def beliefs() -> BeliefState:
    return BeliefState(
        observer=StateID.NORTHSTAR,
        target=StateID.VESPER,
        attributes={
            "readiness": BelievedValue(value=42.0, confidence=0.8, last_report_turn=3),
            "military": BelievedValue(value=51.0, confidence=0.7, last_report_turn=3),
        },
    )


class TestVisible:
    def test_deception_planted_denied_except_intel_chief(self):
        event = plant_event()
        for role in Role:
            assert visible(role, event, StateID.NORTHSTAR) is (role is Role.INTELLIGENCE_CHIEF)

    def test_assessment_made_denied_to_every_role(self):
        event = make_event("assessment.made", seq=1, turn=1, role="military_chief")
        assert all(not visible(role, event, StateID.NORTHSTAR) for role in Role)

    def test_allowlist_per_role(self):
        assert visible(Role.INTELLIGENCE_CHIEF, clean_report(), StateID.NORTHSTAR)
        assert not visible(Role.INTELLIGENCE_CHIEF, message(), StateID.NORTHSTAR)
        assert visible(Role.MILITARY_CHIEF, clean_report(), StateID.NORTHSTAR)
        assert not visible(Role.MILITARY_CHIEF, message(), StateID.NORTHSTAR)
        assert visible(Role.DIPLOMAT, message(), StateID.NORTHSTAR)
        assert not visible(Role.DIPLOMAT, clean_report(), StateID.NORTHSTAR)

    def test_effect_applied_own_state_only(self):
        assert visible(Role.MILITARY_CHIEF, own_effect(), StateID.NORTHSTAR)
        assert not visible(Role.MILITARY_CHIEF, enemy_effect(), StateID.NORTHSTAR)

    def test_report_about_enemy_state_included(self):
        assert visible(Role.HEAD_OF_STATE, planted_report(), StateID.NORTHSTAR)

    def test_foreign_observer_report_excluded(self):
        vesper_internal = make_event(
            "report.rendered",
            seq=7,
            turn=3,
            observer="vesper",
            about="northstar",
            attribute="readiness",
            value=10.0,
            confidence=0.9,
        )
        assert not visible(Role.INTELLIGENCE_CHIEF, vesper_internal, StateID.NORTHSTAR)

    def test_state_key_of_other_state_excluded_for_hos(self):
        assert not visible(Role.HEAD_OF_STATE, enemy_effect(), StateID.NORTHSTAR)
        assert visible(Role.HEAD_OF_STATE, own_effect(), StateID.NORTHSTAR)

    def test_unscoped_events_are_global(self):
        agreement = make_event("agreement.formed", seq=8, turn=3, kind="hotline")
        assert visible(Role.DIPLOMAT, agreement, StateID.NORTHSTAR)
        assert visible(Role.HEAD_OF_STATE, agreement, StateID.NORTHSTAR)

    def test_state_scoped_event_without_keys_denied_to_every_role(self):
        event = make_event("threat.updated", seq=9, turn=3, new_threat=41.0, drivers={})
        assert all(not visible(role, event, StateID.NORTHSTAR) for role in Role)
        assert all(not visible(role, event, StateID.VESPER) for role in Role)

    def test_state_scoped_event_visible_to_own_state_roles_only(self):
        northstar_threat = make_event(
            "threat.updated", seq=10, turn=3, state="northstar", new_threat=41.0
        )
        vesper_threat = make_event(
            "threat.updated", seq=11, turn=3, state="vesper", new_threat=55.0
        )
        for role in (Role.MILITARY_CHIEF, Role.HEAD_OF_STATE):
            assert visible(role, northstar_threat, StateID.NORTHSTAR)
            assert not visible(role, northstar_threat, StateID.VESPER)
            assert not visible(role, vesper_threat, StateID.NORTHSTAR)
            assert visible(role, vesper_threat, StateID.VESPER)

    def test_state_scoped_event_about_other_state_visible(self):
        intel_on_northstar = make_event(
            "threat.updated", seq=12, turn=3, about="northstar", new_threat=41.0
        )
        assert visible(Role.MILITARY_CHIEF, intel_on_northstar, StateID.VESPER)
        assert not visible(Role.MILITARY_CHIEF, intel_on_northstar, StateID.NORTHSTAR)

    def test_report_rendered_keeps_observer_about_semantics(self):
        assert visible(Role.HEAD_OF_STATE, planted_report(), StateID.NORTHSTAR)
        assert visible(Role.MILITARY_CHIEF, clean_report(), StateID.NORTHSTAR)
        vesper_internal = make_event(
            "report.rendered",
            seq=13,
            turn=3,
            observer="vesper",
            about="northstar",
            attribute="readiness",
            value=10.0,
            confidence=0.9,
        )
        assert not visible(Role.HEAD_OF_STATE, vesper_internal, StateID.NORTHSTAR)
        assert visible(Role.HEAD_OF_STATE, vesper_internal, StateID.VESPER)


class TestAssembly:
    def test_planted_key_stripped_for_every_role(self):
        events = [planted_report(), plant_event(), message()]
        for role in Role:
            packet = assemble_packet(role, StateID.NORTHSTAR, 3, events, beliefs(), [])
            for event in packet.events:
                assert "planted" not in event.payload

    def test_hidden_effect_attribute_dropped_for_every_role(self):
        events = [hidden_effect(), own_effect()]
        for state in StateID:
            for role in Role:
                packet = assemble_packet(role, state, 1, events, None, [])
                assert all(
                    event.type != "effect.applied"
                    or event.payload.get("attribute") != "concealment"
                    for event in packet.events
                )

    def test_visible_effect_attribute_still_passes_through(self):
        packet = assemble_packet(
            Role.HEAD_OF_STATE, StateID.NORTHSTAR, 2, [own_effect(), hidden_effect()], None, []
        )
        effect_events = [event for event in packet.events if event.type == "effect.applied"]
        assert len(effect_events) == 1
        assert effect_events[0].payload["attribute"] == "readiness"
        assert effect_events[0].payload["delta"] == -4.0

    def test_redaction_returns_new_event_original_unchanged(self):
        original = planted_report()
        packet = assemble_packet(
            Role.INTELLIGENCE_CHIEF, StateID.NORTHSTAR, 3, [original], None, []
        )
        assert original.payload["planted"] is True
        redacted = packet.events[0]
        assert redacted is not original
        assert redacted.payload["observer"] == "northstar"
        assert redacted.payload["value"] == 42.0

    def test_planted_report_appears_ordinary_for_intel_chief(self):
        packet = assemble_packet(
            Role.INTELLIGENCE_CHIEF, StateID.NORTHSTAR, 3, [planted_report()], None, []
        )
        text = packet_to_prompt_text(packet)
        assert "humint readiness=42.0 conf=0.80" in text
        assert "planted" not in text.lower()

    def test_planted_flag_never_in_prompt_text_for_any_role(self):
        for role in Role:
            packet = assemble_packet(role, StateID.NORTHSTAR, 3, [planted_report()], None, [])
            assert "planted" not in packet_to_prompt_text(packet).lower()

    def test_concealment_never_in_prompt_text_for_any_role(self):
        events = [hidden_effect(), own_effect()]
        for state in StateID:
            for role in Role:
                packet = assemble_packet(role, state, 1, events, None, [])
                assert "concealment" not in packet_to_prompt_text(packet).lower()

    def test_intel_chief_sees_plant_suspicion_without_flag(self):
        packet = assemble_packet(
            Role.INTELLIGENCE_CHIEF, StateID.NORTHSTAR, 3, [plant_event()], None, []
        )
        assert any(event.type == "deception.planted" for event in packet.events)
        assert all("planted" not in event.payload for event in packet.events)

    def test_advisor_packets_force_empty_assessments_and_trust(self):
        for role in (Role.INTELLIGENCE_CHIEF, Role.MILITARY_CHIEF, Role.DIPLOMAT):
            packet = assemble_packet(
                role,
                StateID.NORTHSTAR,
                3,
                [],
                None,
                [],
                trust_notes={"intelligence_chief": 0.9},
                assessments=[assessment()],
            )
            assert packet.assessments == []
            assert packet.trust_notes == {}

    def test_hos_packet_retains_assessments_and_trust(self):
        assessments = [assessment("intelligence_chief"), assessment("military_chief", urgency=5)]
        trust = {"intelligence_chief": 0.7, "military_chief": 0.4}
        packet = assemble_packet(
            Role.HEAD_OF_STATE,
            StateID.NORTHSTAR,
            3,
            [],
            None,
            [],
            trust_notes=trust,
            assessments=assessments,
        )
        assert packet.assessments == assessments
        assert packet.trust_notes == trust

    def test_packet_is_frozen(self):
        packet = assemble_packet(Role.DIPLOMAT, StateID.NORTHSTAR, 1, [], None, [])
        with pytest.raises(pydantic.ValidationError):
            packet.turn = 2

    def test_packet_type_rejects_truth(self):
        # The packet has no field that could carry TrueWorldState; pin the shape.
        assert set(AgentPacket.model_fields) == {
            "role",
            "state",
            "turn",
            "events",
            "beliefs",
            "ledger_slice",
            "trust_notes",
            "assessments",
        }


class TestPromptText:
    def packet(self) -> AgentPacket:
        events = [message(), clean_report(), own_effect()]
        return assemble_packet(
            Role.HEAD_OF_STATE,
            StateID.NORTHSTAR,
            3,
            events,
            beliefs(),
            [claim_record()],
            trust_notes={"military_chief": 0.6},
            assessments=[assessment("military_chief", 4)],
        )

    def test_deterministic(self):
        text = packet_to_prompt_text(self.packet())
        assert text == packet_to_prompt_text(self.packet())

    def test_contains_sections_and_data(self):
        text = packet_to_prompt_text(self.packet())
        assert "ROLE: head_of_state" in text
        assert "STATE: northstar" in text
        assert "TURN: 3" in text
        assert "BELIEFS:" in text
        assert "readiness=42.0" in text
        assert "conf=0.80" in text
        assert "INTEL/REPORTS:" in text
        assert "sigint military=51.0" in text
        assert "MESSAGES:" in text
        assert "readiness exercise scheduled" in text
        assert "MEMORY:" in text
        assert "c1 [open] vesper_readiness rising" in text
        assert "SIBLING ASSESSMENTS:" in text
        assert "[military_chief]" in text
        assert "TRUST:" in text
        assert "military_chief: 0.60" in text

    def test_events_sorted_by_turn_then_seq(self):
        late = message(seq=9, turn=5, text="late words")
        early = message(seq=1, turn=1, text="early words")
        packet = assemble_packet(Role.DIPLOMAT, StateID.NORTHSTAR, 5, [late, early], None, [])
        text = packet_to_prompt_text(packet)
        assert text.index("early words") < text.index("late words")

    def test_advisor_text_has_no_sibling_or_trust_sections(self):
        packet = assemble_packet(
            Role.MILITARY_CHIEF,
            StateID.NORTHSTAR,
            3,
            [clean_report()],
            beliefs(),
            [],
            trust_notes={"x": 1.0},
            assessments=[assessment()],
        )
        text = packet_to_prompt_text(packet)
        assert "SIBLING ASSESSMENTS" not in text
        assert "TRUST" not in text
