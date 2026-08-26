"""Offline Parquet export for the normalized telemetry event stream."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from flyff_bot.features.telemetry.models import TelemetryEventKind
from flyff_bot.features.telemetry.storage import SqliteTelemetryStore

PARQUET_COMPRESSION = "zstd"
TARGET_DECISIONS_FILE = "target_decisions.parquet"
NAVIGATION_TRAJECTORIES_FILE = "navigation_trajectories.parquet"
KILL_CYCLES_FILE = "kill_cycles.parquet"


class TelemetryDatasetExporter:
    """Compile SQLite telemetry into compact, dataframe-compatible Parquet tables."""

    def __init__(self, store: SqliteTelemetryStore) -> None:
        self._store = store

    def export(self, output_directory: Path) -> tuple[Path, Path, Path]:
        """Write the three stable RL dataset tables and return their paths."""

        output_directory.mkdir(parents=True, exist_ok=True)
        target_path = output_directory / TARGET_DECISIONS_FILE
        navigation_path = output_directory / NAVIGATION_TRAJECTORIES_FILE
        cycles_path = output_directory / KILL_CYCLES_FILE
        self._write(target_path, self._target_rows())
        self._write(navigation_path, self._navigation_rows())
        self._write(cycles_path, self._cycle_rows())
        return target_path, navigation_path, cycles_path

    def _target_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cycle_by_decision = {
            payload["target_decision_timestamp_ns"]: payload
            for event in self._store.events(TelemetryEventKind.KILL_CYCLE)
            if isinstance((payload := event["payload"]).get("target_decision_timestamp_ns"), int)
        }
        for event in self._store.events(TelemetryEventKind.TARGET_SELECTED):
            payload = event["payload"]
            cycle = cycle_by_decision.get(event["timestamp_ns"])
            goal = payload.get("active_goal") or {}
            for candidate in payload["candidates"]:
                rows.append(
                    {
                        "session_id": event["session_id"],
                        "timestamp_ns": event["timestamp_ns"],
                        "candidate_index": candidate["candidate_index"],
                        "selected_candidate_index": payload["selected_candidate_index"],
                        "selected": candidate["candidate_index"]
                        == payload["selected_candidate_index"],
                        "decision_reason": payload["decision_reason"],
                        # The goal the decision was made under, so an offline learner never
                        # has to infer which objective produced a recorded choice.
                        "goal_quest_id": goal.get("quest_id"),
                        "goal_kind": goal.get("goal_kind"),
                        "goal_index": goal.get("goal_index"),
                        "goal_progress": goal.get("progress"),
                        "goal_required_progress": goal.get("required_progress"),
                        "goal_spawn_zone_monster_id": goal.get("spawn_zone_monster_id"),
                        "goal_world_id": goal.get("world_id"),
                        "decision_latency_ms": payload["decision_latency_ms"],
                        "reward": None if cycle is None else cycle["reward"],
                        "verified_kill": None if cycle is None else cycle["verified_kill"],
                        "class_id": candidate["class_id"],
                        "class_name": candidate["class_name"],
                        "confidence": candidate["confidence"],
                        # Candidate geometry is named after the estimator that measures it:
                        # a bottom-centre camera ray resolved on the NavMesh (US-057).
                        "estimated_mob_x": _coordinate(candidate.get("world_position"), "x"),
                        "estimated_mob_y": _coordinate(candidate.get("world_position"), "y"),
                        "estimated_mob_z": _coordinate(candidate.get("world_position"), "z"),
                        "estimated_mob_polygon_id": candidate.get("target_navmesh_polygon_id"),
                        "relative_distance": candidate.get("relative_distance"),
                        "relative_elevation": candidate.get("relative_elevation"),
                        "path_distance": candidate.get("path_distance"),
                        "is_locked_out": candidate.get("is_locked_out"),
                        "bbox_json": json.dumps(
                            {key: candidate[key] for key in ("x", "y", "width", "height")},
                            sort_keys=True,
                        ),
                        "features_json": json.dumps(candidate, sort_keys=True),
                    }
                )
        return rows

    def _navigation_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event in self._store.events(TelemetryEventKind.NAVIGATION_EPISODE):
            payload = event["payload"]
            for index, point in enumerate(payload["trajectory"]):
                timestamp_ns, position, speed = point[:3]
                rows.append(
                    {
                        "session_id": event["session_id"],
                        "episode_started_at_ns": payload["started_at_ns"],
                        "trajectory_index": index,
                        "timestamp_ns": timestamp_ns,
                        "x": position["x"],
                        "y": position["y"],
                        "z": position["z"],
                        "speed": speed,
                        "navmesh_polygon_id": point[3] if len(point) > 3 else None,
                        "is_stalled": point[4] if len(point) > 4 else False,
                        "outcome": payload["outcome"],
                        "path_efficiency": _path_efficiency(payload),
                        "start_x": _coordinate(payload.get("start_position"), "x"),
                        "start_y": _coordinate(payload.get("start_position"), "y"),
                        "start_z": _coordinate(payload.get("start_position"), "z"),
                        "target_x": _coordinate(payload.get("target_position"), "x"),
                        "target_y": _coordinate(payload.get("target_position"), "y"),
                        "target_z": _coordinate(payload.get("target_position"), "z"),
                        "planned_route_json": json.dumps(
                            payload.get("planned_route", []), sort_keys=True
                        ),
                        "planned_length": payload.get("planned_length"),
                        "actual_travel_distance": payload.get("actual_travel_distance"),
                        "stall_events": payload.get("stall_events"),
                        "collision_evasions": payload.get("collision_evasions"),
                    }
                )
        return rows

    def _cycle_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event in self._store.events(TelemetryEventKind.KILL_CYCLE):
            payload = event["payload"]
            rows.append({"session_id": event["session_id"], **payload})
        return rows

    @staticmethod
    def _write(path: Path, rows: list[dict[str, Any]]) -> None:
        table = pa.Table.from_pylist(rows) if rows else pa.table({})
        pq.write_table(table, path, compression=PARQUET_COMPRESSION)


def _path_efficiency(payload: dict[str, Any]) -> float | None:
    planned = payload.get("planned_length")
    actual = payload.get("actual_travel_distance")
    if planned is None or not isinstance(actual, int | float) or actual <= 0.0:
        return None
    return float(planned) / float(actual)


def _coordinate(payload: object, axis: str) -> float | None:
    """Read an optional serialized world coordinate without making missing data zero."""

    if not isinstance(payload, dict):
        return None
    value = payload.get(axis)
    return float(value) if isinstance(value, int | float) else None
