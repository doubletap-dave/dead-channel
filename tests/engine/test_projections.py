from dead_channel.core.events import Event, make_event
from dead_channel.core.types import ResourceKind, StateID
from dead_channel.engine.projections import project_beliefs, project_world
from dead_channel.engine.world import initial_world


def rendered(seq: int, turn: int, observer: str = "northstar", **payload: object) -> Event:
    return make_event("report.rendered", seq=seq, turn=turn, observer=observer, **payload)


class TestProjectBeliefs:
    def test_empty_stream_gives_empty_beliefs(self):
        state = project_beliefs([], StateID.NORTHSTAR)
        assert state.observer == StateID.NORTHSTAR
        assert state.target == StateID.VESPER
        assert state.attributes == {}

    def test_builds_from_report_rendered_only(self):
        events = [
            rendered(1, 1, about="vesper", attribute="readiness", value=42.0, confidence=0.6),
            make_event("observation.generated", seq=2, turn=1, about="vesper"),
            make_event("decision.made", seq=3, turn=1, actor="northstar"),
        ]
        beliefs = project_beliefs(events, StateID.NORTHSTAR)
        assert set(beliefs.attributes) == {"readiness"}
        assert beliefs.attributes["readiness"].value == 42.0

    def test_latest_report_wins(self):
        events = [
            rendered(1, 1, about="vesper", attribute="readiness", value=42.0, confidence=0.6),
            rendered(2, 3, about="vesper", attribute="readiness", value=55.0, confidence=0.9),
        ]
        believed = project_beliefs(events, StateID.NORTHSTAR).attributes["readiness"]
        assert believed.value == 55.0
        assert believed.confidence == 0.9
        assert believed.last_report_turn == 3

    def test_verified_sets_last_verified_turn(self):
        events = [
            rendered(
                1,
                2,
                about="vesper",
                attribute="military",
                value=30.0,
                confidence=0.5,
                verified=True,
            ),
            rendered(2, 5, about="vesper", attribute="military", value=33.0, confidence=0.7),
        ]
        believed = project_beliefs(events, StateID.NORTHSTAR).attributes["military"]
        assert believed.last_verified_turn == 2
        assert believed.last_report_turn == 5
        assert believed.value == 33.0

    def test_planted_reports_enter_beliefs(self):
        events = [
            rendered(
                1,
                4,
                about="vesper",
                attribute="stability",
                value=15.0,
                confidence=0.8,
                planted=True,
            ),
        ]
        believed = project_beliefs(events, StateID.NORTHSTAR).attributes["stability"]
        assert believed.value == 15.0
        assert believed.confidence == 0.8

    def test_ignores_reports_about_other_targets(self):
        events = [
            rendered(1, 1, about="northstar", attribute="readiness", value=99.0, confidence=0.9),
        ]
        beliefs = project_beliefs(events, StateID.NORTHSTAR)
        assert beliefs.attributes == {}

    def test_ignores_reports_by_other_observers(self):
        events = [
            rendered(1, 1, about="vesper", attribute="readiness", value=42.0, confidence=0.6),
            rendered(2, 1, about="vesper", attribute="readiness", value=50.0, confidence=0.5),
            rendered(
                3,
                2,
                observer="vesper",
                about="vesper",
                attribute="readiness",
                value=10.0,
                confidence=0.9,
            ),
        ]
        beliefs = project_beliefs(events, StateID.NORTHSTAR)
        assert beliefs.attributes["readiness"].value == 50.0

    def test_unknown_attributes_still_tracked(self):
        events = [
            rendered(1, 1, about="vesper", attribute="cyber", value=70.0, confidence=0.4),
        ]
        believed = project_beliefs(events, StateID.NORTHSTAR).attributes["cyber"]
        assert believed.value == 70.0


class TestProjectWorld:
    def test_empty_stream_defaults(self):
        world = project_world([])
        assert world.turn == 0
        assert set(world.countries) == set(StateID)
        assert world == initial_world(0)

    def test_roundtrips_effects(self):
        events = [
            make_event(
                "effect.applied",
                seq=1,
                turn=1,
                state="northstar",
                attribute="readiness",
                delta=12.0,
            ),
            make_event(
                "effect.applied",
                seq=2,
                turn=1,
                state="vesper",
                attribute="economy",
                delta=-8.0,
            ),
            make_event(
                "effect.applied",
                seq=3,
                turn=2,
                state="northstar",
                attribute="readiness",
                delta=-2.0,
            ),
        ]
        world = project_world(events)
        baseline = initial_world(0)
        north = world.countries[StateID.NORTHSTAR]
        assert north.readiness == 50.0
        assert (
            north.resources[ResourceKind.ECONOMY]
            == baseline.countries[StateID.NORTHSTAR].resources[ResourceKind.ECONOMY]
        )
        assert (
            world.countries[StateID.VESPER].resources[ResourceKind.ECONOMY]
            == baseline.countries[StateID.VESPER].resources[ResourceKind.ECONOMY] - 8.0
        )
        assert world.turn == 2

    def test_clamps_on_replay(self):
        events = [
            make_event(
                "effect.applied",
                seq=1,
                turn=1,
                state="northstar",
                attribute="stability",
                delta=-100.0,
            ),
        ]
        assert project_world(events).countries[StateID.NORTHSTAR].stability == 0.0

    def test_run_started_snapshot_seeds_world(self):
        events = [
            make_event(
                "run.started",
                seq=0,
                turn=0,
                initial_world={
                    "turn": 0,
                    "countries": {
                        "northstar": {
                            "resources": {
                                "economy": 60.0,
                                "energy": 50.0,
                                "food": 50.0,
                                "military": 50.0,
                                "research": 50.0,
                            },
                            "readiness": 45.0,
                            "stability": 55.0,
                            "intelligence_capability": 50.0,
                            "diplomatic_credibility": 70.0,
                            "concealment": 0.1,
                        },
                        "vesper": {
                            "resources": {
                                "economy": 50.0,
                                "energy": 55.0,
                                "food": 50.0,
                                "military": 50.0,
                                "research": 50.0,
                            },
                            "readiness": 40.0,
                            "stability": 60.0,
                            "intelligence_capability": 50.0,
                            "diplomatic_credibility": 70.0,
                            "concealment": 0.0,
                        },
                    },
                },
            ),
            make_event(
                "effect.applied",
                seq=1,
                turn=1,
                state="northstar",
                attribute="readiness",
                delta=5.0,
            ),
        ]
        world = project_world(events)
        assert world.countries[StateID.NORTHSTAR].readiness == 50.0
        assert world.countries[StateID.NORTHSTAR].concealment == 0.1

    def test_world_ticked_advances_turn(self):
        events = [
            make_event("world.ticked", seq=1, turn=1),
            make_event("world.ticked", seq=2, turn=3),
        ]
        assert project_world(events).turn == 3
