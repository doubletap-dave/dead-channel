from pathlib import Path

import pytest

from dead_channel.core.events import make_event
from dead_channel.engine.store import EventStore


def test_append_assigns_monotonic_seq_ignoring_incoming(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "log.db")
    first = store.append(make_event("run.started", seq=42, turn=0))
    second = store.append(make_event("turn.started", seq=0, turn=1))
    assert (first.seq, second.seq) == (1, 2)
    store.close()


def test_replay_roundtrip_preserves_payload(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "log.db")
    body = {"text": "mobilization", "scores": [1, 2.5, None, True], "nested": {"a": 1}}
    appended = store.append(
        make_event("observation.generated", seq=0, turn=3, report_id="r-1", body=body)
    )
    replayed = store.replay()
    assert replayed == [appended]
    assert isinstance(replayed[0].payload, dict)
    assert replayed[0].payload == {"report_id": "r-1", "body": body}
    store.close()


def test_events_since_filters_exclusively(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "log.db")
    for turn in range(1, 4):
        store.append(make_event("world.ticked", seq=0, turn=turn))
    assert [e.seq for e in store.events_since(0)] == [1, 2, 3]
    assert [e.seq for e in store.events_since(1)] == [2, 3]
    assert store.events_since(3) == []
    store.close()


def test_empty_store_replays_nothing(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "log.db")
    assert store.replay() == []
    assert store.events_since(0) == []
    store.close()


def test_persistence_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "log.db"
    first = EventStore(path)
    first.append(make_event("run.started", seq=0, turn=0))
    first.append(make_event("turn.started", seq=0, turn=1))
    first.close()

    reopened = EventStore(path)
    assert [e.seq for e in reopened.replay()] == [1, 2]
    assert reopened.append(make_event("world.ticked", seq=0, turn=2)).seq == 3
    reopened.close()


def test_context_manager_closes_connection(tmp_path: Path) -> None:
    with EventStore(tmp_path / "log.db") as store:
        assert store.replay() == []
    assert store._conn is None  # noqa: SLF001 - asserting the close contract
    with pytest.raises(AttributeError):
        # A closed store's connection is gone; double-close is a no-op.
        store.replay()


def test_double_close_is_a_no_op(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "log.db")
    store.close()
    store.close()
