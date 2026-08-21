"""Terminal rendering of engine events: one line per event, DEFCON banner on change."""

from collections.abc import Callable

from dead_channel.core.events import Event

_BANNER_WIDTH = 62


def _bar(value: float, width: int = 20) -> str:
    filled = max(0, min(width, round(value / 100 * width)))
    return "#" * filled + "." * (width - filled)


def _truncate(text: str, limit: int = 96) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fmt_report(payload: dict[str, object]) -> str:
    return (
        f"{payload.get('observer')} <- {payload.get('source')} on "
        f"{payload.get('about')}.{payload.get('attribute')} = "
        f"{payload.get('value')} (conf {payload.get('confidence')}) "
        f'"{_truncate(str(payload.get("text", "")))}"'
    )


def _fmt_assessment(payload: dict[str, object]) -> str:
    claim = payload.get("claim") or {}
    action = payload.get("recommended_action") or {}
    dissent = " [DISSENT]" if payload.get("dissent") else ""
    return (
        f"{payload.get('state')}.{payload.get('role')}: "
        f'"{_truncate(str(payload.get("interpretation", "")))}" '
        f"-> {action.get('kind')} (urgency {payload.get('urgency')}, "
        f"claims {claim.get('subject')} {claim.get('direction')}){dissent}"
    )


def _fmt_decision(payload: dict[str, object]) -> str:
    action = payload.get("action") or {}
    return (
        f"{payload.get('state')} decides: {action.get('kind')} "
        f'{action.get("params") or ""} -- "{_truncate(str(payload.get("rationale", "")))}"'
    )


def _fmt_threat(payload: dict[str, object]) -> str:
    return (
        f"{payload.get('state')} threat={payload.get('threat')} "
        f"[{_bar(float(payload.get('threat', 0)))}]"
    )


def _fmt_message(payload: dict[str, object]) -> str:
    return f"{payload.sender} -> {_truncate(str(payload.get('text', '')))}"


def _fmt_contact(payload: dict[str, object]) -> str:
    return (
        f"{payload.get('observer')} detects {payload.get('kind')} "
        f"@({payload.get('lat')},{payload.get('lon')}) conf={payload.get('confidence')}"
    )


def _fmt_claim_scored(payload: dict[str, object]) -> str:
    outcome = payload.get("outcome", 0.5)
    return f"{payload.get('state')}.{payload.get('role')} claim scored {outcome:.2f}"


_FORMATTERS: dict[str, Callable[[dict[str, object]], str]] = {
    "report.rendered": _fmt_report,
    "assessment.made": _fmt_assessment,
    "decision.made": _fmt_decision,
    "threat.updated": _fmt_threat,
    "message.sent": _fmt_message,
    "contact.detected": _fmt_contact,
    "claim.scored": _fmt_claim_scored,
}


def format_event(event: Event) -> str | None:
    """One-line summary for the terminal; None for events without a line format."""
    if event.type == "turn.started":
        return f"--- TURN {event.turn} " + "-" * (_BANNER_WIDTH - 11)
    formatter = _FORMATTERS.get(event.type)
    if formatter is None:
        return None
    try:
        return formatter(event.payload)
    except KeyError, TypeError, ValueError, AttributeError:
        return f"{event.type}: {_truncate(str(event.payload))}"


def defcon_banner(defcon: int) -> str:
    label = {1: "COCKED PISTOL", 2: "FAST PACE", 3: "ROUND HOUSE", 4: "DOUBLE TAKE", 5: "FADE OUT"}
    name = label.get(defcon, "?")
    marks = "!" * (6 - defcon)
    return f"*** DEFCON {defcon} - {name} {marks}"
