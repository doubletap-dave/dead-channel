"""Append-only SQLite event log. Sole mutation path for all engine state."""

import json
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Self

from dead_channel.core.events import Event

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    turn INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""


class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def append(self, event: Event) -> Event:
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO events (seq, turn, type, payload) VALUES (NULL, ?, ?, ?)",
                (event.turn, event.type, json.dumps(event.payload)),
            )
        return event.model_copy(update={"seq": int(cursor.lastrowid)})

    def replay(self) -> list[Event]:
        return self._query("SELECT seq, turn, type, payload FROM events ORDER BY seq")

    def events_since(self, seq: int) -> list[Event]:
        return self._query(
            "SELECT seq, turn, type, payload FROM events WHERE seq > ? ORDER BY seq", (seq,)
        )

    def _query(self, sql: str, params: tuple[object, ...] = ()) -> list[Event]:
        return [
            Event(seq=seq, turn=turn, type=type_, payload=json.loads(payload))
            for seq, turn, type_, payload in self._conn.execute(sql, params)
        ]

    def close(self) -> None:
        self._conn.close()
