"""Emergent threat accumulation and observer DEFCON derivation."""

import pydantic

from dead_channel.core.config import SimParams

_HOTLINE_SIGNAL_SCALE = 0.5
_DEFCON_HOLD_TURNS = 2
_DEFCON_1_THRESHOLD = 85.0


class Signals(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    hostile_messages: float = 0.0
    exercises_detected: float = 0.0
    betrayals: float = 0.0
    reassurance_messages: float = 0.0


class ThreatUpdate(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    new_threat: float
    drivers: dict[str, float]


class DefconState(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    defcon: int
    hold: int


def _signal_scale(own_readiness: float) -> float:
    return 1.3 - own_readiness / 250.0


def update_threat(
    threat: float,
    believed_readiness_delta: float,
    signals: Signals,
    own_readiness: float,
    actor_credibility: float,
    hotline_active: bool,
    params: SimParams,
) -> ThreatUpdate:
    weights = params.threat_weights
    scale = _signal_scale(own_readiness)
    hotline = _HOTLINE_SIGNAL_SCALE if hotline_active else 1.0
    credibility = actor_credibility / 100.0

    readiness = weights.readiness_delta * max(0.0, believed_readiness_delta)
    hostile = weights.hostile_msg * signals.hostile_messages * scale * hotline
    exercise = weights.exercise * signals.exercises_detected * scale * hotline
    betrayal = weights.betrayal * signals.betrayals * scale * hotline
    reassurance = (
        -weights.reassurance * signals.reassurance_messages * scale * hotline * credibility
    )
    decay = -weights.decay * (1.0 - threat / 100.0)

    drivers: dict[str, float] = {
        "readiness_delta": readiness,
        "hostile": hostile,
        "exercise": exercise,
        "betrayal": betrayal,
        "reassurance": reassurance,
        "decay": decay,
    }
    new_threat = min(100.0, max(0.0, threat + sum(drivers.values())))
    return ThreatUpdate(new_threat=new_threat, drivers=drivers)


def _target_defcon(composite: float, bands: list[float]) -> int:
    crossed = sum(1 for edge in bands if composite >= edge)
    return len(bands) + 2 - crossed


def derive_defcon(
    threat_a: float,
    threat_b: float,
    conflict_crossed: bool,
    prev: DefconState,
    params: SimParams,
) -> DefconState:
    if conflict_crossed and threat_a >= _DEFCON_1_THRESHOLD and threat_b >= _DEFCON_1_THRESHOLD:
        return DefconState(defcon=1, hold=0)

    target = _target_defcon(max(threat_a, threat_b), params.defcon_bands)
    if target == prev.defcon:
        return DefconState(defcon=prev.defcon, hold=0)
    if prev.hold + 1 >= _DEFCON_HOLD_TURNS:
        return DefconState(defcon=target, hold=0)
    return DefconState(defcon=prev.defcon, hold=prev.hold + 1)
