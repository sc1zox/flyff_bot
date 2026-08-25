"""Pure feature geometry and matrix construction for the offline farming value models.

Every value produced here is derived from an observed US-054 telemetry record. When an input
observation is unavailable the derived feature stays ``None`` and later becomes ``NaN`` in the
model matrix, so a missing measurement is never silently replaced with a fabricated number.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, isfinite, sin, sqrt

import numpy as np
import numpy.typing as npt

# One evaluated candidate is described by these observed or derived quantities. The order is
# part of the exported model contract and must never be reordered without a new artifact
# version, because the ONNX graphs index their input columns positionally.
FEATURE_NAMES: tuple[str, ...] = (
    "path_distance",
    "relative_distance",
    "relative_elevation",
    "player_heading",
    "target_bearing",
    "heading_error",
    "terrain_slope",
    "corridor_length",
    "corridor_waypoint_count",
    "corridor_turn_angle_total",
    "corridor_max_turn_angle",
    "corridor_detour_ratio",
    "target_class_id",
    "detection_confidence",
    "visible_mob_count",
    "reachable_mob_count",
    "nearby_targetable_mob_count",
    "recent_kill_rate",
    "recent_stuck_rate",
    "decision_latency_ms",
)

# A prepared matrix column carrying this suffix states whether the paired raw feature was
# missing for that sample, so an imputed median is always distinguishable from a measurement.
MISSING_INDICATOR_SUFFIX = "__is_missing"

# World units within which another candidate counts as part of the same local cluster.
NEARBY_CANDIDATE_DISTANCE_UNITS = 40.0

WorldPoint = tuple[float, float, float]


def prepared_feature_names(feature_names: tuple[str, ...] = FEATURE_NAMES) -> tuple[str, ...]:
    """Return the imputed columns followed by their paired missing indicators."""

    return feature_names + tuple(f"{name}{MISSING_INDICATOR_SUFFIX}" for name in feature_names)


@dataclass(frozen=True, slots=True)
class CorridorMetrics:
    """Geometry of one planned NavMesh corridor as recorded for a navigation episode."""

    length: float | None
    waypoint_count: int
    turn_angle_total: float | None
    max_turn_angle: float | None
    detour_ratio: float | None


def bearing(delta_x: float, delta_z: float) -> float | None:
    """Return the world-plane heading of a horizontal displacement, or ``None`` if undefined."""

    if not (isfinite(delta_x) and isfinite(delta_z)):
        return None
    if delta_x == 0.0 and delta_z == 0.0:
        return None
    return atan2(delta_z, delta_x)


def angular_difference(first: float | None, second: float | None) -> float | None:
    """Return the unsigned angle between two headings, wrapped into ``[0, pi]``."""

    if first is None or second is None:
        return None
    difference = atan2(sin(first - second), cos(first - second))
    return abs(difference)


def horizontal_distance(start: WorldPoint, end: WorldPoint) -> float:
    """Return the ground-plane distance between two world points."""

    return hypot(end[0] - start[0], end[2] - start[2])


def point_distance(start: WorldPoint, end: WorldPoint) -> float:
    """Return the 3D distance between two world points."""

    return sqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2 + (end[2] - start[2]) ** 2)


def route_slope(start: WorldPoint | None, end: WorldPoint | None) -> float | None:
    """Return the average terrain gradient along a route, or ``None`` without ground truth."""

    if start is None or end is None:
        return None
    ground = horizontal_distance(start, end)
    if ground <= 0.0:
        return None
    return (end[1] - start[1]) / ground


def corridor_metrics(route: tuple[WorldPoint, ...]) -> CorridorMetrics:
    """Summarize a planned funnel corridor into length, shape, and detour geometry."""

    waypoint_count = len(route)
    if waypoint_count < 2:
        return CorridorMetrics(None, waypoint_count, None, None, None)
    length = sum(
        point_distance(route[index], route[index + 1]) for index in range(waypoint_count - 1)
    )
    straight_line = point_distance(route[0], route[-1])
    detour_ratio = length / straight_line if straight_line > 0.0 else None
    bearings = [
        heading
        for index in range(waypoint_count - 1)
        if (
            heading := bearing(
                route[index + 1][0] - route[index][0], route[index + 1][2] - route[index][2]
            )
        )
        is not None
    ]
    if len(bearings) < 2:
        return CorridorMetrics(length, waypoint_count, None, None, detour_ratio)
    turns = [
        difference
        for index in range(len(bearings) - 1)
        if (difference := angular_difference(bearings[index + 1], bearings[index])) is not None
    ]
    if not turns:
        return CorridorMetrics(length, waypoint_count, None, None, detour_ratio)
    return CorridorMetrics(length, waypoint_count, sum(turns), max(turns), detour_ratio)


def candidate_feature_row(
    *,
    path_distance: float | None,
    relative_distance: float | None,
    relative_elevation: float | None,
    player_heading: float | None,
    target_bearing: float | None,
    terrain_slope: float | None,
    corridor: CorridorMetrics | None,
    target_class_id: float | None,
    detection_confidence: float | None,
    visible_mob_count: float | None,
    reachable_mob_count: float | None,
    nearby_targetable_mob_count: float | None,
    recent_kill_rate: float | None,
    recent_stuck_rate: float | None,
    decision_latency_ms: float | None,
) -> dict[str, float | None]:
    """Assemble one candidate's feature row in the single order the artifacts index by.

    Both the offline trainer and the live policy build their rows here, so a served vector can
    never disagree with the vector the same state produced during training (BUG-031). An input
    that was not observed stays ``None`` and later becomes ``NaN`` with a missing indicator.
    """

    return {
        "path_distance": path_distance,
        "relative_distance": relative_distance,
        "relative_elevation": relative_elevation,
        "player_heading": player_heading,
        "target_bearing": target_bearing,
        "heading_error": angular_difference(player_heading, target_bearing),
        "terrain_slope": terrain_slope,
        "corridor_length": None if corridor is None else corridor.length,
        "corridor_waypoint_count": (None if corridor is None else float(corridor.waypoint_count)),
        "corridor_turn_angle_total": None if corridor is None else corridor.turn_angle_total,
        "corridor_max_turn_angle": None if corridor is None else corridor.max_turn_angle,
        "corridor_detour_ratio": None if corridor is None else corridor.detour_ratio,
        "target_class_id": target_class_id,
        "detection_confidence": detection_confidence,
        "visible_mob_count": visible_mob_count,
        "reachable_mob_count": reachable_mob_count,
        "nearby_targetable_mob_count": nearby_targetable_mob_count,
        "recent_kill_rate": recent_kill_rate,
        "recent_stuck_rate": recent_stuck_rate,
        "decision_latency_ms": decision_latency_ms,
    }


def feature_matrix(
    rows: tuple[dict[str, float | None], ...],
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> npt.NDArray[np.float64]:
    """Stack feature dictionaries into a matrix whose missing measurements stay ``NaN``."""

    matrix = np.full((len(rows), len(feature_names)), np.nan, dtype=np.float64)
    for row_index, row in enumerate(rows):
        for column_index, name in enumerate(feature_names):
            value = row.get(name)
            if value is not None and isfinite(value):
                matrix[row_index, column_index] = float(value)
    return matrix


def label_vector(values: tuple[float | None, ...]) -> npt.NDArray[np.float64]:
    """Stack observed labels into a vector whose unobserved entries stay ``NaN``."""

    return np.array(
        [np.nan if value is None or not isfinite(value) else float(value) for value in values],
        dtype=np.float64,
    )
