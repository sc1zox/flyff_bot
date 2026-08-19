from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from flyff_bot.features.telemetry import SqliteTelemetryStore, TelemetryDatasetExporter


def test_exporter_writes_dataframe_compatible_parquet_tables(tmp_path: Path) -> None:
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
            "event_kind": "navigation_episode",
            "session_id": "one",
            "timestamp_ns": 3,
            "payload": {
                "started_at_ns": 3,
                "planned_length": 2.0,
                "actual_travel_distance": 4.0,
                "outcome": "reached_target",
                "trajectory": [[3, {"x": 1.0, "y": 2.0, "z": 3.0}, 1.0]],
            },
        }
    )
    store.persist(
        {
            "event_kind": "kill_cycle",
            "session_id": "one",
            "timestamp_ns": 4,
            "payload": {
                "timestamp_ns": 4,
                "decision_seconds": 1.0,
                "navigation_seconds": 1.0,
                "combat_seconds": 1.0,
                "idle_seconds": 1.0,
                "damage_taken": 0.0,
                "stall_seconds": 0.0,
                "verified_kill": True,
                "reward": 1.0,
            },
        }
    )
    target, navigation, cycles = TelemetryDatasetExporter(store).export(tmp_path / "rl")
    assert [path.name for path in (target, navigation, cycles)] == [
        "target_decisions.parquet",
        "navigation_trajectories.parquet",
        "kill_cycles.parquet",
    ]
    assert pq.read_table(target).to_pylist()[0]["selected"] is True
    assert pq.read_table(navigation).to_pylist()[0]["path_efficiency"] == 0.5
    assert pq.read_table(cycles).to_pylist()[0]["reward"] == 1.0
