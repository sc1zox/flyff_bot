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
        for event in self._store.events(TelemetryEventKind.TARGET_SELECTED):
            payload = event["payload"]
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
                        "decision_latency_ms": payload["decision_latency_ms"],
                        "class_id": candidate["class_id"],
                        "class_name": candidate["class_name"],
                        "confidence": candidate["confidence"],
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
                timestamp_ns, position, speed = point
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
                        "outcome": payload["outcome"],
                        "path_efficiency": _path_efficiency(payload),
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
