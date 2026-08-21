"""Role visibility policy: the declarative table deciding what each agent sees.

This module enforces the core security property — agent packets are built only
from events this table allows, with redactions applied. Truth never reaches an
agent packet because the assembler's inputs are events and projections only.
"""

from enum import StrEnum

import pydantic

from dead_channel.core.events import Event
from dead_channel.core.types import StateID


class Role(StrEnum):
    HEAD_OF_STATE = "head_of_state"
    INTELLIGENCE_CHIEF = "intelligence_chief"
    MILITARY_CHIEF = "military_chief"
    DIPLOMAT = "diplomat"


class RolePolicy(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    allowed_event_types: frozenset[str]
    redact_fields: frozenset[str] = frozenset()
    description: str = ""


_REPORT = "report.rendered"
_CONTACT = "contact.detected"
_PLANTED = "deception.planted"
_FORMED = "agreement.formed"
_VIOLATED = "agreement.violated"
_MESSAGE = "message.sent"
_EFFECT = "effect.applied"
_THREAT = "threat.updated"
_DECISION = "decision.made"

_PLANTED_FLAG = "planted"

_STATE_SCOPED_TYPES = frozenset[str](
    {
        _THREAT,
        _DECISION,
        _EFFECT,
        "assessment.made",
        _PLANTED,
        "observation.generated",
        _CONTACT,
        "agent.activity",
    }
)

ROLE_POLICY: dict[Role, RolePolicy] = {
    Role.INTELLIGENCE_CHIEF: RolePolicy(
        allowed_event_types=frozenset({_REPORT, _CONTACT, _PLANTED, _FORMED, _VIOLATED}),
        redact_fields=frozenset({_PLANTED_FLAG}),
        description=(
            "Full report inbox, detected enemy activity, and plant events "
            "(the planted flag itself is stripped: a planted report must look "
            "like an ordinary product, though its arrival is visible as suspicion)."
        ),
    ),
    Role.MILITARY_CHIEF: RolePolicy(
        allowed_event_types=frozenset({_REPORT, _CONTACT, _EFFECT, _THREAT}),
        redact_fields=frozenset({_PLANTED_FLAG}),
        description="Own force posture, detected enemy activity, threat picture.",
    ),
    Role.DIPLOMAT: RolePolicy(
        allowed_event_types=frozenset({_MESSAGE, _FORMED, _VIOLATED, _CONTACT}),
        redact_fields=frozenset({_PLANTED_FLAG}),
        description="Diplomatic traffic, agreements, public signals. No raw intelligence.",
    ),
    Role.HEAD_OF_STATE: RolePolicy(
        allowed_event_types=frozenset(
            {_REPORT, _MESSAGE, _FORMED, _VIOLATED, _CONTACT, _THREAT, _DECISION, _EFFECT}
        ),
        redact_fields=frozenset({_PLANTED_FLAG}),
        description=(
            "Elevated intelligence, diplomatic traffic, threat picture, and "
            "prior turns' own decisions for consistency."
        ),
    ),
}


def _concerns(event: Event, state: StateID) -> bool:
    other = StateID.VESPER if state is StateID.NORTHSTAR else StateID.NORTHSTAR
    payload = event.payload
    if event.type in _STATE_SCOPED_TYPES:
        own = payload.get("state") == state.value or payload.get("observer") == state.value
        about_other = payload.get("about") == other.value
        return own or about_other
    own_scoped = any(
        (value := payload.get(key)) is not None and value != state.value
        for key in ("state", "observer")
    )
    shared_scoped = any(
        (value := payload.get(key)) is not None and value not in (state.value, other.value)
        for key in ("about", "sender")
    )
    return not (own_scoped or shared_scoped)


def visible(role: Role, event: Event, state: StateID) -> bool:
    policy = ROLE_POLICY[role]
    return event.type in policy.allowed_event_types and _concerns(event, state)
