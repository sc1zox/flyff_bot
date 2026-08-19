"""SQLite kill log backing per-monster quota progress across pauses and restarts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from datetime import datetime
from pathlib import Path

from flyff_bot.features.automation.kill_goals import MobKillQuota

DEFAULT_KILL_LOG_PATH = Path("data/kill_log.sqlite3")

_KILL_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS kill_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    class_name TEXT NOT NULL,
    recorded_at TEXT NOT NULL
)
"""
_KILL_EVENTS_SESSION_INDEX = """
CREATE INDEX IF NOT EXISTS kill_events_session_idx ON kill_events (session_id)
"""
_KILL_QUOTAS_TABLE = """
CREATE TABLE IF NOT EXISTS kill_quotas (
    session_id TEXT NOT NULL,
    class_name TEXT NOT NULL,
    required_kills INTEGER NOT NULL,
    PRIMARY KEY (session_id, class_name)
)
"""


class SqliteKillLog:
    """Append verified kills and the quotas they count towards to a local database.

    Every operation opens its own short-lived connection: kills arrive at most once per
    engagement, and a connection per write keeps the store safe to call from the session
    worker thread and the Qt thread alike without owning a lock.
    """

    def __init__(self, path: Path = DEFAULT_KILL_LOG_PATH) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(_KILL_EVENTS_TABLE)
            connection.execute(_KILL_EVENTS_SESSION_INDEX)
            connection.execute(_KILL_QUOTAS_TABLE)

    @property
    def path(self) -> Path:
        """Return the database file backing this log."""

        return self._path

    def record_kill(self, session_id: str, class_name: str, recorded_at: datetime) -> None:
        """Append one verified kill of a monster class to the session's history."""

        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO kill_events (session_id, class_name, recorded_at) VALUES (?, ?, ?)",
                (session_id, class_name, recorded_at.isoformat()),
            )

    def record_quotas(self, session_id: str, quotas: Iterable[MobKillQuota]) -> None:
        """Replace the stored quotas of one session with the current selection."""

        entries = [(session_id, quota.class_name, quota.required_kills) for quota in quotas]
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM kill_quotas WHERE session_id = ?", (session_id,))
            connection.executemany(
                "INSERT INTO kill_quotas (session_id, class_name, required_kills) VALUES (?, ?, ?)",
                entries,
            )

    def kill_counts(self, session_id: str) -> Mapping[str, int]:
        """Return the kills logged per monster class for one session."""

        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT class_name, COUNT(*) FROM kill_events "
                "WHERE session_id = ? GROUP BY class_name",
                (session_id,),
            ).fetchall()
        return {str(class_name): int(count) for class_name, count in rows}

    def quotas(self, session_id: str) -> tuple[MobKillQuota, ...]:
        """Return the quotas stored for one session."""

        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT class_name, required_kills FROM kill_quotas WHERE session_id = ? "
                "ORDER BY class_name",
                (session_id,),
            ).fetchall()
        return tuple(MobKillQuota(str(name), int(required)) for name, required in rows)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)
