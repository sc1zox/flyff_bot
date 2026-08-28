from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from flyff_bot.features.policy.action_payloads import AttackPointAction, TacticalAction
from flyff_bot.features.rl.actions import TacticalActionCatalog
from flyff_bot.features.rl.exporter import (
    TelemetryTransitionExporter,
    _decision_tactical_parameter_digest,
)
from flyff_bot.features.rl.models import OBSERVATION_DIMENSION
from flyff_bot.features.tactical_parameters import DEFAULT_TACTICAL_PARAMETERS
from flyff_bot.features.telemetry import SqliteTelemetryStore


def test_exporter_writes_transition_batch(tmp_path: Path) -> None:
    store = SqliteTelemetryStore(tmp_path / "telemetry.sqlite3")
    executed_action = TacticalActionCatalog.encode(
        AttackPointAction(1, (4.0, 0.0, 5.0), 45.0, 0, 6.0)
    )
    store.persist(
        {
            "event_kind": "session_header",
            "session_id": "one",
            "timestamp_ns": 0,
            "payload": {"tactical_parameter_digest": DEFAULT_TACTICAL_PARAMETERS.content_digest},
        }
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
                "tactical_parameter_digest": DEFAULT_TACTICAL_PARAMETERS.content_digest,
                "executed_action": asdict(executed_action),
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
    assert row["tactical_parameter_digest"] == DEFAULT_TACTICAL_PARAMETERS.content_digest
    assert row["action"] == int(TacticalAction.GO_TO_ATTACK_POINT)
    # The chosen candidate stays identifiable: a constant action index would not be trainable.
    assert row["action_candidate_index"] == 0
    assert row["action_target_class_id"] == 1
    action_parameters = json.loads(row["action_parameters_json"])
    assert action_parameters["candidate_index"] == 0
    assert action_parameters["attack_point"] == [4.0, 0.0, 5.0]
    assert action_parameters["approach_distance_units"] == 6.0
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
    provenance_payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert provenance_payload["tactical_parameter_digests"] == [
        DEFAULT_TACTICAL_PARAMETERS.content_digest
    ]


def test_exporter_refuses_a_decision_without_exact_parameter_provenance() -> None:
    with pytest.raises(ValueError, match="Decision tactical parameter provenance"):
        _decision_tactical_parameter_digest({"payload": {}})
