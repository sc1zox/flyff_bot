from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from flyff_bot.features.policy.action_payloads import TacticalAction
from flyff_bot.features.rl.exporter import TelemetryTransitionExporter
from flyff_bot.features.rl.models import OBSERVATION_DIMENSION
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
                "readiness_state": "blocked",
                "readiness_primary_reason": "stale",
                "failed_source_codes": ["gps"],
                "sample_ages_seconds": [["gps", 1.25]],
                "action_blocked": True,
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
                "readiness_state": "ready",
                "readiness_primary_reason": None,
                "failed_source_codes": [],
                "sample_ages_seconds": [["gps", 0.1]],
                "action_blocked": False,
            },
        }
    )

    path, provenance = TelemetryTransitionExporter(store).export(tmp_path / "rl")
    row = pq.read_table(path).to_pylist()[0]
    assert row["session_id"] == "one"
    assert row["episode_index"] == 0
    assert row["action"] == int(TacticalAction.SELECT_TARGET)
    # The chosen candidate stays identifiable: a constant action index would not be trainable.
    assert row["action_candidate_index"] == 0
    assert row["action_target_class_id"] == 1
    assert json.loads(row["action_parameters_json"])["candidate_index"] == 0
    assert len(row["observation"]) == len(row["next_observation"]) == OBSERVATION_DIMENSION
    assert len(row["action_mask"]) == len(row["next_action_mask"]) == 7
    assert row["action_mask"] == [False, False, False, False, False, False, True]
    assert row["candidate_mask"] == [False]
    assert row["terminated"] is False
    assert row["truncated"] is True
    assert row["readiness_state"] == "blocked"
    assert row["readiness_primary_reason"] == "stale"
    assert row["failed_source_codes"] == ["gps"]
    assert row["sample_ages_seconds_json"] == '{"gps": 1.25}'
    assert row["action_blocked"] is True
    assert row["next_readiness_state"] == "ready"
    assert row["next_action_blocked"] is False
    assert provenance.exists()
