"""Fail-safe per-session structured event logging (US-049)."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from flyff_bot.features.diagnostics.models import SessionEvent, SessionEventKind

DEFAULT_SESSION_LOG_DIRECTORY = Path("logs/sessions")
# Bounds both the in-memory history the dashboard renders and the JSONL growth per tick;
# older events remain on disk, only the live ring buffer is capped.
DEFAULT_EVENT_HISTORY_LIMIT = 200
SESSION_LOG_FILENAME_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%f"


def _default_now() -> datetime:
    return datetime.now(UTC)


class SessionEventLogger:
    """Record structured session events to a per-session JSONL file, never raising.

    Disk I/O and formatting failures are swallowed rather than propagated, so a full disk
    or an unwritable directory can never interrupt the farming loop or the Qt event loop
    that ticks it (US-049 acceptance criterion: logging is fail-safe).
    """

    def __init__(
        self,
        log_directory: Path = DEFAULT_SESSION_LOG_DIRECTORY,
        *,
        now: Callable[[], datetime] = _default_now,
        history_limit: int = DEFAULT_EVENT_HISTORY_LIMIT,
    ) -> None:
        self._now = now
        self._history: deque[SessionEvent] = deque(maxlen=history_limit)
        session_start = now()
        log_path: Path | None = log_directory / (
            f"session_{session_start.strftime(SESSION_LOG_FILENAME_TIMESTAMP_FORMAT)}.jsonl"
        )
        try:
            log_directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            log_path = None
        self._log_path = log_path

    @property
    def log_path(self) -> Path | None:
        """Return the active session log file, or None when it could not be created."""

        return self._log_path

    @property
    def recent_events(self) -> tuple[SessionEvent, ...]:
        """Return recorded events, most recent first."""

        return tuple(reversed(self._history))

    def record(
        self,
        kind: SessionEventKind,
        new_mode: str,
        *,
        previous_mode: str,
        reason: str | None = None,
        foreground_window_title: str | None = None,
        foreground_window_process: str | None = None,
    ) -> SessionEvent:
        """Append one event to memory and disk, swallowing any I/O or formatting failure."""

        event = SessionEvent(
            timestamp=self._now().isoformat(),
            kind=kind,
            previous_mode=previous_mode,
            new_mode=new_mode,
            reason=reason,
            foreground_window_title=foreground_window_title,
            foreground_window_process=foreground_window_process,
        )
        self._history.append(event)
        self._write(event)
        return event

    def _write(self, event: SessionEvent) -> None:
        if self._log_path is None:
            return
        # Fail-safe by design: a disk-full or formatting failure must never interrupt the
        # farming loop that is ticking this logger.
        with suppress(OSError, ValueError), self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False))
            handle.write("\n")
