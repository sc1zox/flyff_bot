from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from flyff_bot.features.telemetry import SqliteTelemetryStore, TelemetryDatasetExporter


def test_exporter_links_a_verified_kill_reward_to_its_decision(tmp_path: Path) -> None:
    store = SqliteTelemetryStore(tmp_path / "telemetry.sqlite3")
    store.persist(
        {"event_kind": "session_header", "session_id": "one", "timestamp_ns": 1, "payload": {}}
    )
    store.persist(
        {
            "event_kind": "target_selected",
            "session_id": "one",
            "timestamp_ns": 2,
            "payload": {
                "selected_candidate_index": 0,
                "decision_reason": "nearest",
                "decision_latency_ms": 1.0,
                "candidates": [
                    {
                        "candidate_index": 0,
                        "class_id": 1,
                        "class_name": "Aibatt",
                        "confidence": 0.9,
                        "x": 1,
                        "y": 2,
                        "width": 3,
                        "height": 4,
                    }
                ],
            },
        }
    )
    store.persist(
        {
            "event_kind": "kill_cycle",
            "session_id": "one",
            "timestamp_ns": 3,
            "payload": {"target_decision_timestamp_ns": 2, "reward": 1.5, "verified_kill": True},
        }
    )
    target, _navigation, _cycles = TelemetryDatasetExporter(store).export(tmp_path / "rl")
    row = pq.read_table(target).to_pylist()[0]
    assert row["reward"] == 1.5
    assert row["verified_kill"] is True
