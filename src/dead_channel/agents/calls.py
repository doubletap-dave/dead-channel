"""Agent call sites: build prompt, call the Caller, return the validated result.

Pure orchestration only — no retries (PydanticAICaller owns them) and no
prompt persistence (the TurnRunner wraps these with persist_prompt in Wave 4).
"""

from dead_channel.agents.packets import AgentPacket
from dead_channel.agents.policy import Role
from dead_channel.agents.prompts import assessment_prompt, hos_prompt
from dead_channel.core.config import ModelMatrix
from dead_channel.core.types import Assessment, Decision, StateID
from dead_channel.providers.caller import Caller
from dead_channel.providers.matrix import resolve_model


async def get_assessment(
    caller: Caller,
    model_str: str,
    role: Role,
    packet: AgentPacket,
    trust_note: str | None = None,
) -> Assessment:
    """trust_note: pass trust_note_for(trust_score) from dead_channel.agents.prompts."""
    prompt = assessment_prompt(role, packet, trust_note=trust_note)
    result = await caller.call(model_str, Assessment, prompt, call_site=f"assessment_{role.value}")
    if result.role != role.value:
        raise ValueError(
            f"model returned assessment for role {result.role!r}, expected {role.value!r}"
        )
    return result


async def get_decision(
    caller: Caller,
    model_str: str,
    packet: AgentPacket,
    trust_ranking: list[tuple[str, float]],
) -> Decision:
    prompt = hos_prompt(packet, trust_ranking)
    return await caller.call(model_str, Decision, prompt, call_site="hos_decision")


class ModelResolver:
    """The single place the model matrix is consulted."""

    def __init__(self, matrix: ModelMatrix) -> None:
        self._matrix = matrix

    def for_role(self, state: StateID, role: Role) -> str:
        return resolve_model(state.value, role.value, self._matrix)
