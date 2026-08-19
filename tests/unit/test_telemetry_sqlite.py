from __future__ import annotations

from pathlib import Path

from flyff_bot.features.telemetry import SqliteTelemetryStore, TelemetryEventKind


def test_sqlite_store_persists_headers_and_indexed_target_events(tmp_path: Path) -> None:
    store = SqliteTelemetryStore(tmp_path / "telemetry.sqlite3")
    store.persist(
        {
            "event_kind": "session_header",
            "session_id": "one",
            "timestamp_ns": 1,
            "payload": {"area_id": "WdEden"},
        }
    )
    store.persist(
        {
            "event_kind": "target_selected",
            "session_id": "one",
            "timestamp_ns": 2,
            "payload": {"candidates": [], "selected_candidate_index": 0},
        }
    )
    assert store.events(TelemetryEventKind.TARGET_SELECTED) == [
        {
            "session_id": "one",
            "timestamp_ns": 2,
            "payload": {"candidates": [], "selected_candidate_index": 0},
        }
    ]
