"""Fail-safe asynchronous JSONL and SQLite persistence for telemetry records."""

from __future__ import annotations

import json
import queue
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from flyff_bot.features.telemetry.models import TelemetryEventKind

DEFAULT_TELEMETRY_ROOT = Path("data/telemetry")
DEFAULT_TELEMETRY_DATABASE = Path("data/telemetry.sqlite3")
DEFAULT_QUEUE_CAPACITY = 1_000
WORKER_JOIN_TIMEOUT_SECONDS = 5.0
_AREA_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class SqliteTelemetryStore:
    """Small SQLite store using short-lived connections for safe worker ownership."""

    def __init__(self, path: Path = DEFAULT_TELEMETRY_DATABASE) -> None:
        self.path = path
        self._initialization_lock = Lock()
        self._initialized = False

    def initialize(self) -> None:
        """Create the query-oriented schema and its stable indexes exactly once."""

        with self._initialization_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS telemetry_sessions (
                        session_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS telemetry_events (
                        id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
                        timestamp_ns INTEGER NOT NULL, event_kind TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY(session_id) REFERENCES telemetry_sessions(session_id)
                    );
                    CREATE TABLE IF NOT EXISTS target_decisions (
                        id INTEGER PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        timestamp_ns INTEGER NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS navigation_episodes (
                        id INTEGER PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        timestamp_ns INTEGER NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS combat_episodes (
                        id INTEGER PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        timestamp_ns INTEGER NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS stall_events (
                        id INTEGER PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        timestamp_ns INTEGER NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS kill_cycles (
                        id INTEGER PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        timestamp_ns INTEGER NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_telemetry_events_session_time
                        ON telemetry_events(session_id, timestamp_ns);
                    CREATE INDEX IF NOT EXISTS idx_target_decisions_session_time
                        ON target_decisions(session_id, timestamp_ns);
                    CREATE INDEX IF NOT EXISTS idx_navigation_episodes_session_time
                        ON navigation_episodes(session_id, timestamp_ns);
                    CREATE INDEX IF NOT EXISTS idx_combat_episodes_session_time
                        ON combat_episodes(session_id, timestamp_ns);
                    """
                )
            self._initialized = True

    def persist(self, record: Mapping[str, Any]) -> None:
        """Store one envelope transactionally; called only by the background worker."""

        self.initialize()
        kind = str(record["event_kind"])
        session_id = str(record["session_id"])
        timestamp_ns = int(record["timestamp_ns"])
        payload = json.dumps(record["payload"], sort_keys=True, separators=(",", ":"))
        with self._connection() as connection:
            if kind == TelemetryEventKind.SESSION_HEADER.value:
                connection.execute(
                    "INSERT OR REPLACE INTO telemetry_sessions(session_id, metadata_json) "
                    "VALUES (?, ?)",
                    (session_id, payload),
                )
            connection.execute(
                "INSERT INTO telemetry_events(session_id, timestamp_ns, event_kind, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (session_id, timestamp_ns, kind, payload),
            )
            table_by_kind = {
                TelemetryEventKind.TARGET_SELECTED.value: "target_decisions",
                TelemetryEventKind.NAVIGATION_EPISODE.value: "navigation_episodes",
                TelemetryEventKind.COMBAT_EPISODE.value: "combat_episodes",
                TelemetryEventKind.STALL_EVENT.value: "stall_events",
                TelemetryEventKind.KILL_CYCLE.value: "kill_cycles",
            }
            table = table_by_kind.get(kind)
            if table is not None:
                connection.execute(
                    f"INSERT INTO {table}(session_id, timestamp_ns, payload_json) VALUES (?, ?, ?)",
                    (session_id, timestamp_ns, payload),
                )

    def events(self, kind: TelemetryEventKind) -> list[dict[str, Any]]:
        """Return one event family in timestamp order for offline export and diagnostics."""

        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT session_id, timestamp_ns, payload_json FROM telemetry_events "
                "WHERE event_kind = ? ORDER BY timestamp_ns, id",
                (kind.value,),
            ).fetchall()
        return [
            {"session_id": row[0], "timestamp_ns": row[1], "payload": json.loads(row[2])}
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


class JsonlTelemetryWorker:
    """A bounded, non-blocking producer queue with one append-only persistence thread."""

    def __init__(
        self,
        session_id: str,
        area_id: str,
        *,
        root: Path = DEFAULT_TELEMETRY_ROOT,
        store: SqliteTelemetryStore | None = None,
        capacity: int = DEFAULT_QUEUE_CAPACITY,
    ) -> None:
        if capacity <= 0:
            raise ValueError("Telemetry queue capacity must be positive.")
        component = _AREA_COMPONENT.sub("_", area_id).strip("._") or "unknown"
        day = datetime.now(UTC).date().isoformat()
        self.path = root / component / day / f"session_{session_id}.jsonl"
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=capacity)
        self._store = store
        self._stopped = Event()
        self._thread = Thread(target=self._run, name="flyff-telemetry", daemon=True)
        self.dropped_records = 0
        self.failed_records = 0
        self._thread.start()

    def submit(self, record: dict[str, Any]) -> bool:
        """Queue a record immediately, dropping it under load instead of blocking farming."""

        if self._stopped.is_set():
            return False
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self.dropped_records += 1
            return False
        return True

    def close(self) -> None:
        """Request an orderly drain without allowing teardown to stall indefinitely."""

        if self._stopped.is_set():
            return
        self._stopped.set()
        # The worker will drain existing records; no input/control path waits for it.
        with suppress(queue.Full):
            self._queue.put_nowait(None)
        self._thread.join(WORKER_JOIN_TIMEOUT_SECONDS)

    def _run(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                while True:
                    try:
                        record = self._queue.get(timeout=0.1)
                    except queue.Empty:
                        if self._stopped.is_set() and self._queue.empty():
                            return
                        continue
                    if record is None:
                        return
                    try:
                        stream.write(
                            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                        )
                        stream.flush()
                        if self._store is not None:
                            self._store.persist(record)
                    except OSError, TypeError, ValueError, sqlite3.DatabaseError:
                        self.failed_records += 1
        except OSError:
            self.failed_records += 1
