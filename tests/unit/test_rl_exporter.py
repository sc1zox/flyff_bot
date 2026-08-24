from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from flyff_bot.features.rl.exporter import TelemetryTransitionExporter
from flyff_bot.features.telemetry import SqliteTelemetryStore


def test_exporter_writes_transition_batch(tmp_path: Path) -> None:
    store = SqliteTelemetryStore(tmp_path / "telemetry.sqlite3")
    store.persist(
        {"event_kind": "session_header", "session_id": "one", "timestamp_ns": 0, "payload": {}}
    )
    store.persist(
        {
            "event_kind": "world_snapshot",
            "session_id": "one",
            "timestamp_ns": 1,
            "payload": {
                "player_position": {"x": 1, "y": 2, "z": 3},
                "player_velocity": {"x": 0, "y": 0, "z": 0},
                "hp_percentage": 100,
                "mp_percentage": 90,
                "fp_percentage": 80,
            },
        }
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
            "event_kind": "world_snapshot",
            "session_id": "one",
            "timestamp_ns": 3,
            "payload": {
                "player_position": {"x": 1, "y": 2, "z": 3},
                "player_velocity": {"x": 0, "y": 0, "z": 0},
                "hp_percentage": 100,
                "mp_percentage": 90,
                "fp_percentage": 80,
            },
        }
    )

    path, provenance = TelemetryTransitionExporter(store).export(tmp_path / "rl")
    row = pq.read_table(path).to_pylist()[0]
    assert row["action"] == 0
    assert len(row["observation"]) == len(row["next_observation"]) == 52
    assert len(row["action_mask"]) == 7
    assert provenance.exists()
