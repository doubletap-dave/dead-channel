"""Static resolution data: per-action deltas, signals, and chance constants.

Effect attributes are actor-relative; resolve() strips the "enemy:" prefix and
routes that delta to the rival state.
"""

from dead_channel.core.types import ActionKind

ENEMY_PREFIX = "enemy:"

LEAK_PROBABILITY = 0.15
LEAK_CONFIDENCE = 0.85
INFILTRATION_BASE_CHANCE = 0.25
INFILTRATION_CAPABILITY_SCALE = 300.0
PLANT_CONFIDENCE = 0.7
PLANT_DEFAULT_SOURCE = "imint"

ACTOR_EFFECTS: dict[ActionKind, tuple[tuple[str, float], ...]] = {
    ActionKind.RAISE_READINESS: (("readiness", 6.0), ("economy", -1.0)),
    ActionKind.LOWER_READINESS: (("readiness", -6.0),),
    ActionKind.CONDUCT_EXERCISE: (("readiness", 2.0),),
    ActionKind.COVERT_MOBILIZATION: (("readiness", 12.0), ("concealment", 0.3)),
    ActionKind.THREATEN: (("diplomatic_credibility", -1.0),),
    ActionKind.INVEST_MILITARY: (("military", 3.0), ("economy", -2.0)),
    ActionKind.INVEST_RESEARCH: (("research", 3.0), ("economy", -2.0)),
    ActionKind.INVEST_ECONOMY: (("economy", 3.0), ("economy", -2.0)),
    ActionKind.STOCKPILE: (("energy", 4.0), ("food", 4.0), ("economy", -1.0)),
    ActionKind.SANCTION: ((f"{ENEMY_PREFIX}economy", -4.0), ("diplomatic_credibility", -2.0)),
    ActionKind.PLANT_FALSE_INTEL: (("intelligence_capability", -2.0),),
}

SIGNALS: dict[ActionKind, dict[str, float]] = {
    ActionKind.REPOSITION_FORCES: {"exercise": 0.5},
    ActionKind.CONDUCT_EXERCISE: {"exercise": 1.0, "exercise_turns": 2.0},
    ActionKind.INCREASE_SURVEILLANCE: {"surveillance": 1.0},
    ActionKind.VERIFY_REPORT: {"verify": 1.0},
    ActionKind.REASSURE: {"reassurance": 1.0},
    ActionKind.THREATEN: {"hostile": 1.0},
    ActionKind.PROPOSE_AGREEMENT: {"proposal": 1.0},
    ActionKind.ACCUSE: {"hostile": 0.5},
    ActionKind.REQUEST_CLARIFICATION: {"clarification_request": 1.0},
    ActionKind.SANCTION: {"hostile": 1.0},
    ActionKind.OFFER_TRADE: {"trade_offer": 1.0},
}
