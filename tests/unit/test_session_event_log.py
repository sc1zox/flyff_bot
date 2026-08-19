"""Unit tests for the fail-safe per-session diagnostics event logger (US-049)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from flyff_bot.features.diagnostics import SessionEventLogger
from flyff_bot.features.diagnostics.event_log import SESSION_LOG_FILENAME_TIMESTAMP_FORMAT
from flyff_bot.features.diagnostics.models import SessionEventKind

FIXED_NOW = datetime(2026, 8, 19, 12, 30, 0, tzinfo=UTC)


def _now() -> datetime:
    return FIXED_NOW


def test_creates_a_dedicated_per_session_log_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "sessions"
    logger = SessionEventLogger(log_dir, now=_now)

    assert logger.log_path is not None
    assert logger.log_path.parent == log_dir
    expected_name = f"session_{FIXED_NOW.strftime(SESSION_LOG_FILENAME_TIMESTAMP_FORMAT)}.jsonl"
    assert logger.log_path.name == expected_name


def test_record_appends_a_structured_jsonl_line(tmp_path: Path) -> None:
    logger = SessionEventLogger(tmp_path / "sessions", now=_now)

    logger.record(
        SessionEventKind.FOCUS_LOST,
        "paused",
        previous_mode="searching",
        reason="focus_lost",
        foreground_window_title="Notepad",
        foreground_window_process="notepad.exe",
    )

    assert logger.log_path is not None
    lines = logger.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "focus_lost"
    assert record["previous_mode"] == "searching"
    assert record["new_mode"] == "paused"
    assert record["reason"] == "focus_lost"
    assert record["foreground_window_title"] == "Notepad"
    assert record["foreground_window_process"] == "notepad.exe"
    assert record["timestamp"] == FIXED_NOW.isoformat()


def test_recent_events_returns_most_recent_first(tmp_path: Path) -> None:
    logger = SessionEventLogger(tmp_path / "sessions", now=_now)

    logger.record(SessionEventKind.MODE_TRANSITION, "searching", previous_mode="paused")
    logger.record(SessionEventKind.MODE_TRANSITION, "targeting", previous_mode="searching")
    logger.record(SessionEventKind.MODE_TRANSITION, "combat", previous_mode="targeting")

    events = logger.recent_events

    assert [event.new_mode for event in events] == ["combat", "targeting", "searching"]


def test_history_limit_bounds_the_in_memory_ring_buffer(tmp_path: Path) -> None:
    logger = SessionEventLogger(tmp_path / "sessions", now=_now, history_limit=2)

    logger.record(SessionEventKind.MODE_TRANSITION, "searching", previous_mode="paused")
    logger.record(SessionEventKind.MODE_TRANSITION, "targeting", previous_mode="searching")
    logger.record(SessionEventKind.MODE_TRANSITION, "combat", previous_mode="targeting")

    assert [event.new_mode for event in logger.recent_events] == ["combat", "targeting"]


def test_an_undconstructible_directory_never_raises_and_keeps_the_in_memory_history(
    tmp_path: Path,
) -> None:
    """A log directory that cannot be created must not interrupt the farming loop."""

    blocking_file = tmp_path / "not_a_directory"
    blocking_file.write_text("occupied", encoding="utf-8")

    logger = SessionEventLogger(blocking_file / "sessions", now=_now)

    assert logger.log_path is None
    event = logger.record(SessionEventKind.MODE_TRANSITION, "searching", previous_mode="paused")

    assert event.new_mode == "searching"
    assert logger.recent_events == (event,)


def test_a_write_failure_never_raises(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Fail-safe per US-049: disk I/O errors must never escape ``record``."""

    logger = SessionEventLogger(tmp_path / "sessions", now=_now)
    assert logger.log_path is not None

    def _raise_open(*_args: object, **_kwargs: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", _raise_open)

    event = logger.record(SessionEventKind.MODE_TRANSITION, "searching", previous_mode="paused")

    assert event.new_mode == "searching"
    assert logger.recent_events == (event,)
