import pydantic
import pytest

from dead_channel.core.events import EVENT_TYPES, Event, make_event


def test_event_roundtrip_and_ordering():
    e = make_event("threat.updated", seq=7, turn=3, state="northstar", threat=41.0, drivers={})
    assert e.type == "threat.updated" and e.turn == 3
    assert Event.model_validate(e.model_dump()).payload == e.payload


def test_seq_is_required():
    with pytest.raises(TypeError):
        make_event("turn.started", turn=1)
    with pytest.raises(pydantic.ValidationError):
        Event(turn=1, type="turn.started", payload={})


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError):
        make_event("nukes.launched", seq=0, turn=1)


def test_all_catalogued_types_accepted():
    for event_type in sorted(EVENT_TYPES):
        assert make_event(event_type, seq=0, turn=1).type == event_type


def test_event_types_is_frozenset():
    assert isinstance(EVENT_TYPES, frozenset)
    with pytest.raises((AttributeError, TypeError)):
        EVENT_TYPES.add("nukes.launched")  # type: ignore[attr-defined]


def test_event_payload_typed():
    e = make_event("message.sent", seq=1, turn=2, sender="northstar")
    assert e.payload == {"sender": "northstar"}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: setattr(m, "seq", 99),
        lambda m: setattr(m, "turn", 99),
        lambda m: setattr(m, "type", "run.ended"),
        lambda m: setattr(m, "payload", {}),
    ],
)
def test_event_is_frozen(mutation):
    e = make_event("threat.updated", seq=1, turn=2, threat=41.0)
    with pytest.raises(pydantic.ValidationError):
        mutation(e)
