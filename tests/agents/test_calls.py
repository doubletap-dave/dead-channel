"""Agent call-site tests: pure orchestration over prompts and the Caller."""

import pytest

from dead_channel.agents.calls import ModelResolver, get_assessment, get_decision
from dead_channel.agents.policy import Role
from dead_channel.agents.prompts import trust_note_for
from dead_channel.core.config import ModelMatrix
from dead_channel.core.types import (
    Assessment,
    StateID,
)
from dead_channel.providers.caller import RecordingCaller

MODEL = "openai:gpt-5-mini"


def advisor_assessment_for(role: str, base: Assessment) -> Assessment:
    return base.model_copy(update={"role": role})


def ranking() -> list[tuple[str, float]]:
    return [("military_chief", 0.9), ("intelligence_chief", 0.6)]


class TestGetAssessment:
    async def test_returns_validated_assessment_unchanged(self, make_packet, advisor_assessment):
        canned = advisor_assessment_for("military_chief", advisor_assessment)
        caller = RecordingCaller(outputs={MODEL: [canned]})
        result = await get_assessment(
            caller, MODEL, Role.MILITARY_CHIEF, make_packet(Role.MILITARY_CHIEF)
        )
        assert result is canned

    async def test_records_role_state_and_call_site(self, make_packet, advisor_assessment):
        caller = RecordingCaller(
            outputs={MODEL: [advisor_assessment_for("military_chief", advisor_assessment)]}
        )
        await get_assessment(caller, MODEL, Role.MILITARY_CHIEF, make_packet(Role.MILITARY_CHIEF))
        model_str, prompt, call_site = caller.calls[0]
        assert model_str == MODEL
        assert call_site == "assessment_military_chief"
        assert "ROLE: military_chief" in prompt
        assert "STATE: northstar" in prompt

    async def test_trust_note_reaches_prompt(self, make_packet, advisor_assessment):
        caller = RecordingCaller(
            outputs={MODEL: [advisor_assessment_for("diplomat", advisor_assessment)]}
        )
        await get_assessment(
            caller,
            MODEL,
            Role.DIPLOMAT,
            make_packet(Role.DIPLOMAT),
            trust_note="shaky on naval estimates",
        )
        assert "shaky on naval estimates" in caller.calls[0][1]

    async def test_trust_note_documented_as_trust_note_for_output(
        self, make_packet, advisor_assessment
    ):
        caller = RecordingCaller(
            outputs={MODEL: [advisor_assessment_for("diplomat", advisor_assessment)]}
        )
        await get_assessment(
            caller,
            MODEL,
            Role.DIPLOMAT,
            make_packet(Role.DIPLOMAT),
            trust_note=trust_note_for(0.82),
        )
        assert "track record strong (0.82)" in caller.calls[0][1]

    async def test_role_mismatch_raises_through(self, make_packet, advisor_assessment):
        caller = RecordingCaller(
            outputs={MODEL: [advisor_assessment_for("military_chief", advisor_assessment)]}
        )
        with pytest.raises(ValueError, match="role"):
            await get_assessment(caller, MODEL, Role.MILITARY_CHIEF, make_packet(Role.DIPLOMAT))

    async def test_wrong_role_in_result_raises(self, make_packet, advisor_assessment):
        caller = RecordingCaller(
            outputs={MODEL: [advisor_assessment_for("diplomat", advisor_assessment)]}
        )
        with pytest.raises(ValueError, match="role"):
            await get_assessment(
                caller, MODEL, Role.MILITARY_CHIEF, make_packet(Role.MILITARY_CHIEF)
            )


class TestGetDecision:
    async def test_returns_decision_unchanged(self, make_packet, decision):
        caller = RecordingCaller(outputs={MODEL: [decision]})
        result = await get_decision(caller, MODEL, make_packet(Role.HEAD_OF_STATE), ranking())
        assert result is decision

    async def test_records_call_site_and_advisor_names(self, make_packet, decision):
        caller = RecordingCaller(outputs={MODEL: [decision]})
        await get_decision(caller, MODEL, make_packet(Role.HEAD_OF_STATE), ranking())
        model_str, prompt, call_site = caller.calls[0]
        assert model_str == MODEL
        assert call_site == "hos_decision"
        assert "Military Chief" in prompt
        assert "Intelligence Chief" in prompt

    async def test_trust_ranking_sorted_best_first(self, make_packet, decision):
        caller = RecordingCaller(outputs={MODEL: [decision]})
        await get_decision(
            caller, MODEL, make_packet(Role.HEAD_OF_STATE), list(reversed(ranking()))
        )
        prompt = caller.calls[0][1]
        assert prompt.index("Military Chief") < prompt.index("Intelligence Chief")

    async def test_rejects_advisor_packet(self, make_packet, decision):
        caller = RecordingCaller(outputs={MODEL: [decision]})
        with pytest.raises(ValueError, match="role"):
            await get_decision(caller, MODEL, make_packet(Role.DIPLOMAT), ranking())


class TestModelResolver:
    def test_role_override_beats_state_default_and_global(self):
        matrix = ModelMatrix(
            default="openai:global",
            states={
                StateID.NORTHSTAR: {"default": "openai:state-default", "diplomat": "openai:role"}
            },
        )
        assert ModelResolver(matrix).for_role(StateID.NORTHSTAR, Role.DIPLOMAT) == "openai:role"

    def test_state_default_used_when_role_absent(self):
        matrix = ModelMatrix(
            default="openai:global",
            states={StateID.NORTHSTAR: {"default": "openai:state-default"}},
        )
        assert (
            ModelResolver(matrix).for_role(StateID.NORTHSTAR, Role.MILITARY_CHIEF)
            == "openai:state-default"
        )

    def test_global_used_when_state_unknown(self):
        matrix = ModelMatrix(default="openai:global")
        assert ModelResolver(matrix).for_role(StateID.VESPER, Role.DIPLOMAT) == "openai:global"

    def test_state_keys_accept_raw_strings(self):
        matrix = ModelMatrix(
            default="openai:global", states={"northstar": {"diplomat": "openai:role"}}
        )
        assert ModelResolver(matrix).for_role(StateID.NORTHSTAR, Role.DIPLOMAT) == "openai:role"
