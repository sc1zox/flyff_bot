"""Offline RL transition export from recorded farming telemetry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from flyff_bot.features.policy.action_payloads import TargetAction
from flyff_bot.features.rl.actions import TacticalActionCatalog
from flyff_bot.features.rl.masking import build_action_mask
from flyff_bot.features.rl.models import ObservationSpace, Transition
from flyff_bot.features.rl.rewards import RewardConfig, RewardEngine, RewardEvent
from flyff_bot.features.telemetry.models import (
    CandidateFeatures,
    TelemetryEventKind,
)
from flyff_bot.features.telemetry.storage import SqliteTelemetryStore

PARQUET_COMPRESSION = "zstd"
RL_TRANSITIONS_FILE = "rl_transitions.parquet"
RL_PROVENANCE_FILE = "rl_provenance.json"
RL_TRANSITION_SCHEMA_VERSION = "us077-v2"
DEFAULT_EXPORT_PATROL_RADIUS = 1000.0


class TelemetryTransitionExporter:
    """Convert recorded decisions into offline MDP transitions without live access."""

    def __init__(
        self,
        store: SqliteTelemetryStore,
        *,
        reward_config: RewardConfig | None = None,
    ) -> None:
        self._store = store
        self.reward_config = reward_config or RewardConfig()

    def export(self, output_directory: Path) -> tuple[Path, Path]:
        """Write transition and provenance artifacts, returning both paths."""

        transitions = self.transitions()
        if not transitions:
            raise ValueError("No complete recorded decision transition was found.")
        output_directory.mkdir(parents=True, exist_ok=True)
        transitions_path = output_directory / RL_TRANSITIONS_FILE
        provenance_path = output_directory / RL_PROVENANCE_FILE
        pq.write_table(self._table(transitions), transitions_path, compression=PARQUET_COMPRESSION)
        provenance_path.write_text(self.provenance(), encoding="utf-8")
        return transitions_path, provenance_path

    def provenance(self) -> str:
        return json.dumps(
            {
                "schema_version": RL_TRANSITION_SCHEMA_VERSION,
                "reward_config_json": self.reward_config.as_json(),
            },
            sort_keys=True,
        )

    def transitions(self) -> list[Transition]:
        snapshots = self._store.events(TelemetryEventKind.WORLD_SNAPSHOT)
        decisions = self._store.events(TelemetryEventKind.TARGET_SELECTED)
        cycles = {
            payload.get("target_decision_timestamp_ns"): payload
            for event in self._store.events(TelemetryEventKind.KILL_CYCLE)
            if isinstance((payload := event["payload"]).get("target_decision_timestamp_ns"), int)
        }
        transitions: list[Transition] = []

        for index, event in enumerate(decisions):
            timestamp_ns = int(event["timestamp_ns"])
            previous_snapshot = max(
                (item for item in snapshots if int(item["timestamp_ns"]) < timestamp_ns),
                key=lambda item: int(item["timestamp_ns"]),
                default=None,
            )
            next_snapshot = min(
                (item for item in snapshots if int(item["timestamp_ns"]) > timestamp_ns),
                key=lambda item: int(item["timestamp_ns"]),
                default=None,
            )
            if previous_snapshot is None or next_snapshot is None:
                continue

            observation = ObservationSpace.from_telemetry_snapshot(
                previous_snapshot["payload"], self._candidates(event)
            )
            next_observation = ObservationSpace.from_telemetry_snapshot(next_snapshot["payload"])
            cycle = cycles.get(timestamp_ns, {})
            travel_seconds = (int(next_snapshot["timestamp_ns"]) - timestamp_ns) / 1_000_000_000.0
            reward_event = RewardEvent(
                verified_kill=bool(cycle.get("verified_kill", False)),
                travel_seconds=max(travel_seconds, 0.0),
            )
            mask = build_action_mask(
                observation,
                patrol_center=(
                    observation.kinematics.position_x,
                    observation.kinematics.position_y,
                    observation.kinematics.position_z,
                ),
                patrol_radius=DEFAULT_EXPORT_PATROL_RADIUS,
            )
            action_payload = TargetAction(
                index,
                None,
            )
            action_index = TacticalActionCatalog.encode(action_payload)
            reward = RewardEngine(self.reward_config).reward(reward_event)
            terminated = bool(cycle.get("verified_kill", False))
            transitions.append(
                Transition(observation, action_index, reward, next_observation, mask, terminated)
            )
        return transitions

    @staticmethod
    def _candidates(event: dict[str, Any]) -> tuple[CandidateFeatures, ...]:
        payload = event["payload"]
        return tuple(
            CandidateFeatures(
                candidate["candidate_index"],
                candidate["class_id"],
                candidate["class_name"],
                candidate["confidence"],
                candidate["x"],
                candidate["y"],
                candidate["width"],
                candidate["height"],
                candidate.get("center_x", 0.0),
                candidate.get("center_y", 0.0),
                candidate.get("screen_distance_to_center"),
                candidate.get("bbox_area", 0),
                None,
                candidate.get("relative_distance"),
                candidate.get("relative_elevation"),
                candidate.get("target_navmesh_polygon_id"),
                candidate.get("path_distance"),
                candidate.get("is_locked_out", False),
            )
            for candidate in payload["candidates"]
        )

    @staticmethod
    def _table(transitions: list[Transition]) -> pa.Table:
        schema = pa.schema(
            [
                pa.field("observation", pa.list_(pa.float64()), nullable=False),
                pa.field("action", pa.int32(), nullable=False),
                pa.field("reward", pa.float64(), nullable=False),
                pa.field("next_observation", pa.list_(pa.float64()), nullable=False),
                pa.field("action_mask", pa.list_(pa.bool_()), nullable=False),
                pa.field("terminated", pa.bool_(), nullable=False),
                pa.field("readiness_state", pa.string(), nullable=False),
                pa.field("readiness_primary_reason", pa.string()),
                pa.field("failed_source_codes", pa.list_(pa.string()), nullable=False),
                pa.field("sample_ages_seconds_json", pa.string(), nullable=False),
                pa.field("action_blocked", pa.bool_(), nullable=False),
                pa.field("next_readiness_state", pa.string(), nullable=False),
                pa.field("next_readiness_primary_reason", pa.string()),
                pa.field("next_failed_source_codes", pa.list_(pa.string()), nullable=False),
                pa.field("next_sample_ages_seconds_json", pa.string(), nullable=False),
                pa.field("next_action_blocked", pa.bool_(), nullable=False),
            ]
        )
        rows = [
            {
                "observation": ObservationSpace.encode(item.observation).tolist(),
                "action": item.action,
                "reward": item.reward,
                "next_observation": ObservationSpace.encode(item.next_observation).tolist(),
                "action_mask": list(item.action_mask),
                "terminated": item.terminated,
                "readiness_state": item.observation.readiness.state,
                "readiness_primary_reason": item.observation.readiness.primary_reason,
                "failed_source_codes": list(item.observation.readiness.failed_source_codes),
                "sample_ages_seconds_json": json.dumps(
                    dict(item.observation.readiness.sample_ages_seconds), sort_keys=True
                ),
                "action_blocked": item.observation.readiness.action_blocked,
                "next_readiness_state": item.next_observation.readiness.state,
                "next_readiness_primary_reason": item.next_observation.readiness.primary_reason,
                "next_failed_source_codes": list(
                    item.next_observation.readiness.failed_source_codes
                ),
                "next_sample_ages_seconds_json": json.dumps(
                    dict(item.next_observation.readiness.sample_ages_seconds), sort_keys=True
                ),
                "next_action_blocked": item.next_observation.readiness.action_blocked,
            }
            for item in transitions
        ]
        return pa.Table.from_pylist(rows, schema=schema)
