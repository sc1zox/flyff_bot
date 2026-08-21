"""Deterministic US-054 telemetry datasets used by the farming value model tests.

The fixtures write real telemetry events through the production SQLite store and Parquet
exporter, so every test reads exactly the schema a recorded farming session produces.
"""

from __future__ import annotations

from math import cos, sin
from pathlib import Path
from typing import Any

from flyff_bot.features.telemetry import SqliteTelemetryStore, TelemetryDatasetExporter

NANOSECONDS_PER_SECOND = 1_000_000_000
SESSION_BASE_TIMESTAMP_NS = 1_000_000_000_000
# Alternating kill spacing so the ten-second follow-up window observes both one and zero
# subsequent kills; a constant spacing would make that label degenerate.
SHORT_KILL_GAP_SECONDS = 8.0
LONG_KILL_GAP_SECONDS = 30.0
CANDIDATES_PER_DECISION = 3
TRAJECTORY_POINT_COUNT = 5
DEFAULT_CYCLES_PER_SESSION = 24


def write_dataset(
    directory: Path,
    *,
    session_ids: tuple[str, ...] = ("session-a", "session-b"),
    cycles_per_session: int = DEFAULT_CYCLES_PER_SESSION,
) -> Path:
    """Record synthetic-but-schema-true sessions and export them as Parquet tables."""

    store = SqliteTelemetryStore(directory / "telemetry.sqlite3")
    for session_index, session_id in enumerate(session_ids):
        _record_session(store, session_id, session_index, cycles_per_session)
    dataset_directory = directory / "rl"
    TelemetryDatasetExporter(store).export(dataset_directory)
    return dataset_directory


def telemetry_database(directory: Path) -> Path:
    """Return the database path :func:`write_dataset` records into."""

    return directory / "telemetry.sqlite3"


def _record_session(
    store: SqliteTelemetryStore, session_id: str, session_index: int, cycle_count: int
) -> None:
    store.persist(
        {
            "event_kind": "session_header",
            "session_id": session_id,
            "timestamp_ns": SESSION_BASE_TIMESTAMP_NS,
            "payload": {
                "area_id": "WdEden",
                "client_sha256": f"clienthash{session_index}",
                "session_id": session_id,
            },
        }
    )
    cycle_timestamp_ns = SESSION_BASE_TIMESTAMP_NS + _seconds(60.0)
    for index in range(cycle_count):
        timings = _timings(index)
        total_seconds = sum(timings.values())
        decision_timestamp_ns = cycle_timestamp_ns - _seconds(total_seconds)
        _record_cycle(
            store,
            session_id=session_id,
            session_index=session_index,
            index=index,
            decision_timestamp_ns=decision_timestamp_ns,
            cycle_timestamp_ns=cycle_timestamp_ns,
            timings=timings,
        )
        gap = SHORT_KILL_GAP_SECONDS if index % 2 == 0 else LONG_KILL_GAP_SECONDS
        cycle_timestamp_ns += _seconds(gap)


def _record_cycle(
    store: SqliteTelemetryStore,
    *,
    session_id: str,
    session_index: int,
    index: int,
    decision_timestamp_ns: int,
    cycle_timestamp_ns: int,
    timings: dict[str, float],
) -> None:
    path_distance = _path_distance(index)
    start = (float(index) * 3.0, 100.0 + float(index % 4), float(session_index) * 10.0)
    heading = float(index) * 0.7
    target = (
        start[0] + path_distance * cos(heading),
        start[1] + float(index % 3) * 0.5,
        start[2] + path_distance * sin(heading),
    )
    stall_seconds = _stall_seconds(index)
    store.persist(
        {
            "event_kind": "target_selected",
            "session_id": session_id,
            "timestamp_ns": decision_timestamp_ns,
            "payload": {
                "selected_candidate_index": 0,
                "decision_reason": "nearest_to_viewport_center",
                "decision_latency_ms": 20.0 + float(index % 7),
                "candidates": [
                    _candidate(index, offset) for offset in range(CANDIDATES_PER_DECISION)
                ],
            },
        }
    )
    episode_started_at_ns = decision_timestamp_ns + _seconds(0.05)
    store.persist(
        {
            "event_kind": "navigation_episode",
            "session_id": session_id,
            "timestamp_ns": episode_started_at_ns,
            "payload": {
                "started_at_ns": episode_started_at_ns,
                "planned_length": path_distance,
                "actual_travel_distance": path_distance * 1.05,
                "outcome": "reached_target",
                "trajectory": _trajectory(
                    episode_started_at_ns, timings["navigation_seconds"], start, target
                ),
                "start_position": _position(start),
                "target_position": _position(target),
                "planned_route": _planned_route(start, target, index),
                "stall_events": 1 if stall_seconds > 0.0 else 0,
                "collision_evasions": 1 if stall_seconds > 0.0 else 0,
            },
        }
    )
    store.persist(
        {
            "event_kind": "kill_cycle",
            "session_id": session_id,
            "timestamp_ns": cycle_timestamp_ns,
            "payload": {
                "timestamp_ns": cycle_timestamp_ns,
                "decision_seconds": timings["decision_seconds"],
                "navigation_seconds": timings["navigation_seconds"],
                "combat_seconds": timings["combat_seconds"],
                "idle_seconds": timings["idle_seconds"],
                "damage_taken": float(index % 5) * 2.0,
                "stall_seconds": stall_seconds,
                "verified_kill": True,
                "reward": -float(index % 4),
                "target_decision_timestamp_ns": decision_timestamp_ns,
            },
        }
    )


def _timings(index: int) -> dict[str, float]:
    """Return the four kill-cycle intervals, kept below the shortest kill gap."""

    return {
        "decision_seconds": 0.2,
        "navigation_seconds": _path_distance(index) / 25.0 + float(index % 4) * 0.1,
        "combat_seconds": 2.0 + float(index % 5) * 0.2,
        "idle_seconds": 0.3,
    }


def _path_distance(index: int) -> float:
    return 20.0 + float(index * 7 % 60)


def _stall_seconds(index: int) -> float:
    return 0.0 if index % 3 == 0 else 0.4 + float(index % 3) * 0.3


def _candidate(index: int, offset: int) -> dict[str, Any]:
    distance = _path_distance(index) + float(offset) * 11.0
    return {
        "candidate_index": offset,
        "class_id": (index + offset) % 3,
        "class_name": f"Mob{(index + offset) % 3}",
        "confidence": 0.5 + float((index + offset) % 5) * 0.08,
        "x": 100 + offset * 40,
        "y": 200,
        "width": 60,
        "height": 60,
        "center_x": 130.0 + float(offset) * 40.0,
        "center_y": 230.0,
        "screen_distance_to_center": 40.0 + float(offset) * 10.0,
        "bbox_area": 3600,
        "world_position": {"x": distance, "y": 100.0, "z": 0.0},
        "relative_distance": distance,
        "relative_elevation": float((index % 5) - 2) * 1.5,
        "target_navmesh_polygon_id": str(index % 9),
        "path_distance": distance * 1.02,
        "is_locked_out": offset == CANDIDATES_PER_DECISION - 1,
    }


def _trajectory(
    started_at_ns: int,
    duration_seconds: float,
    start: tuple[float, float, float],
    target: tuple[float, float, float],
) -> list[list[Any]]:
    points: list[list[Any]] = []
    for step in range(TRAJECTORY_POINT_COUNT):
        share = step / (TRAJECTORY_POINT_COUNT - 1)
        position = tuple(start[axis] + (target[axis] - start[axis]) * share for axis in range(3))
        points.append(
            [
                started_at_ns + _seconds(duration_seconds * share),
                {"x": position[0], "y": position[1], "z": position[2]},
                4.0,
            ]
        )
    return points


def _planned_route(
    start: tuple[float, float, float], target: tuple[float, float, float], index: int
) -> list[dict[str, float]]:
    middle = (
        (start[0] + target[0]) / 2.0 + float(index % 4),
        (start[1] + target[1]) / 2.0,
        (start[2] + target[2]) / 2.0 - float(index % 3),
    )
    return [_position(start), _position(middle), _position(target)]


def _position(point: tuple[float, float, float]) -> dict[str, float]:
    return {"x": point[0], "y": point[1], "z": point[2]}


def _seconds(value: float) -> int:
    return int(value * NANOSECONDS_PER_SECOND)
