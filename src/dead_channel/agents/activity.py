"""Agent activity events: what each LLM-hatted mind is doing, as it happens.

`agent.activity` is observer-visible telemetry (safe: names states/roles/models,
never prompt content) and is the data source for the ops-room live agent feeds.
"""

from typing import Protocol

from dead_channel.core.events import Event
from dead_channel.core.types import StateID

EVENT_TYPE = "agent.activity"

# call_site -> present-tense phrase for the feed. One entry per LLM call site.
_CALL_SITE_VERBS = {
    "report_render": "rendering intelligence report",
    "assessment_intelligence_chief": "intel chief assessing the picture",
    "assessment_military_chief": "military chief assessing posture",
    "assessment_diplomat": "diplomat reading diplomatic traffic",
    "assessment_head_of_state": "head of state weighing options",
    "hos_decision": "head of state deciding",
}


def verb_for(call_site: str) -> str:
    return _CALL_SITE_VERBS.get(call_site, f"working ({call_site})")


class ActivitySink(Protocol):
    def emit_activity(self, state: str, role: str, model: str, action: str) -> Event: ...


async def tracked_call(
    sink: ActivitySink,
    call,
    *,
    state: StateID | None,
    role: str,
    model: str,
    result_type: type,
    prompt: str,
    call_site: str,
):
    """Emit start/done activity around one LLM call; failures surface as failed."""
    await sink.emit_activity(
        state.value if state else "observer",
        role,
        model,
        verb_for(call_site),
    )
    try:
        return await call(model, result_type, prompt, call_site)
    except Exception:
        await sink.emit_activity(state.value if state else "observer", role, model, "failed")
        raise
