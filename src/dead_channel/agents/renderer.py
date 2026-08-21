"""Report rendering: the one LLM call that turns an intel payload into prose.

The caller sees only the payload-derived prompt — the payload is already the
distorted observation, so no TrueWorldState ever reaches the prompt.
"""

from dead_channel.agents.prompts import render_report_prompt
from dead_channel.core.types import IntelPayload
from dead_channel.providers.caller import Caller


async def render_report(caller: Caller, model_str: str, payload: IntelPayload) -> str:
    return await caller.call(
        model_str,
        str,
        render_report_prompt(payload),
        call_site="report_render",
    )
