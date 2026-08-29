"""Geometry-verified stall recovery: projected obstacles and NavMesh escape routing.

This module holds the value objects, in-memory registries, and pure geometry that
:class:`~flyff_bot.features.navigation.pathing.PathingController` uses to recover from a
movement stall without ever dispatching a blind key macro (US-093). Nothing here touches
Win32, process memory, telemetry, or the UI; the controller feeds it live coordinates and an
authoritative :class:`~flyff_bot.features.navigation.navmesh.BakedNavMesh` and reads back a
projected obstacle or an escape route in the same client world-coordinate frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh

# The obstacle is projected this far ahead of the character along the intended movement
# vector, so an A* replan from the current position never has to route around the start node
# itself (US-093).
DEFAULT_OBSTACLE_PROBE_DISTANCE_UNITS = 1.2
DEFAULT_TEMPORARY_OBSTACLE_RADIUS_UNITS = 1.5
# A projection that lands closer than this to the character is discarded rather than allowed
# to block the start coordinate.
MINIMUM_PROJECTION_OFFSET_UNITS = 0.35
# Dynamic time-to-live: a spot that only blocked once is forgiven quickly; one that keeps
# blocking is remembered for a full minute.
TEMPORARY_OBSTACLE_TTL_BY_HITS_SECONDS: dict[int, float] = {1: 15.0, 2: 30.0}
TEMPORARY_OBSTACLE_TTL_PERSISTENT_SECONDS = 60.0
# A new stall inside this radius of an existing obstacle is the same obstacle hit again.
OBSTACLE_MERGE_RADIUS_UNITS = 1.5

# Repeated-stall escalation: stalls this close together, this recently, are one local trap.
REPEATED_LOCAL_STALL_RADIUS_UNITS = 2.0
REPEATED_LOCAL_STALL_WINDOW_SECONDS = 10.0
REPEATED_LOCAL_STALL_HIT_COUNT = 2

# Escape sampling for a character wedged in a canyon or inside collision geometry.
ESCAPE_RING_RADII_UNITS = (0.75, 1.5, 2.5)
ESCAPE_RING_DIRECTIONS = 12
ESCAPE_MAXIMUM_SLOPE_DEGREES = 45.0
ESCAPE_MINIMUM_OBSTACLE_CLEARANCE_UNITS = 1.0
ESCAPE_MINIMUM_GOAL_PROGRESS_UNITS = 1.0
# Deterministic scoring weights: getting closer to the goal dominates, then a short hop, then
# standing clear of the recorded obstacles.
ESCAPE_GOAL_PROGRESS_WEIGHT = 1.0
ESCAPE_TRAVEL_DISTANCE_WEIGHT = 0.25
ESCAPE_CLEARANCE_WEIGHT = 0.5

FULL_TURN_DEGREES = 360.0


@dataclass(frozen=True, slots=True)
class StallObservation:
    """One structured record of a commanded move that produced no GPS displacement."""

    previous_position: WorldPosition
    current_position: WorldPosition
    intended_direction: tuple[float, float]
    intended_waypoint: WorldPosition | None
    current_polygon_id: int | None
    timestamp: float


@dataclass(frozen=True, slots=True)
class TemporaryObstacle:
    """A NavMesh-projected obstruction excluded from routing until it expires."""

    position: WorldPosition
    radius: float
    expires_at: float
    hit_count: int


@dataclass(frozen=True, slots=True)
class EscapeCandidate:
    """One validated walkable point a trapped character could route to."""

    position: WorldPosition
    route: tuple[WorldPosition, ...]
    goal_gap: float
    travel_distance: float
    obstacle_clearance: float

    @property
    def score(self) -> float:
        """Return the deterministic rank of this candidate; lower is better."""

        return (
            ESCAPE_GOAL_PROGRESS_WEIGHT * self.goal_gap
            + ESCAPE_TRAVEL_DISTANCE_WEIGHT * self.travel_distance
            - ESCAPE_CLEARANCE_WEIGHT * self.obstacle_clearance
        )


class RecoveryPhase(StrEnum):
    """Internal recovery progress; never surfaced as a :class:`PathingMode`."""

    NONE = "none"
    LOCAL_REPLAN = "local_replan"
    ESCAPE = "escape"


class RecoveryEventKind(StrEnum):
    """Structured recovery events the controller queues for the telemetry recorder."""

    STALL_DETECTED = "stall_detected"
    TEMPORARY_OBSTACLE_CREATED = "temporary_obstacle_created"
    LOCAL_REPLAN_REQUESTED = "local_replan_requested"
    LOCAL_REPLAN_SUCCEEDED = "local_replan_succeeded"
    REPEATED_LOCAL_STALL = "repeated_local_stall"
    ESCAPE_PLAN_SUCCEEDED = "escape_plan_succeeded"
    ESCAPE_PLAN_FAILED = "escape_plan_failed"


@dataclass(frozen=True, slots=True)
class RecoveryEvent:
    """One recovery milestone, drained by the orchestrator once per tick."""

    kind: RecoveryEventKind
    position: WorldPosition
    at_seconds: float
    obstacle_radius: float | None = None
    hit_count: int | None = None


@dataclass(slots=True)
class RecoveryContext:
    """Mutable in-memory recovery state for one active navigation route."""

    phase: RecoveryPhase = RecoveryPhase.NONE
    stall_count: int = 0
    last_observation: StallObservation | None = None
    escape_waypoint: WorldPosition | None = None
    original_goal: WorldPosition | None = None

    @property
    def is_recovering(self) -> bool:
        """Return whether a stall is currently being worked through."""

        return self.phase is not RecoveryPhase.NONE

    def reset(self) -> None:
        """Forget all recovery progress for the current or a discarded route."""

        self.phase = RecoveryPhase.NONE
        self.stall_count = 0
        self.last_observation = None
        self.escape_waypoint = None
        self.original_goal = None


def _temporary_obstacle_ttl_seconds(hit_count: int) -> float:
    return TEMPORARY_OBSTACLE_TTL_BY_HITS_SECONDS.get(
        hit_count, TEMPORARY_OBSTACLE_TTL_PERSISTENT_SECONDS
    )


class TemporaryObstacleRegistry:
    """Hold NavMesh-projected obstacles with a dynamic time-to-live (US-093)."""

    def __init__(self) -> None:
        self._obstacles: list[TemporaryObstacle] = []

    def register(
        self,
        observation: StallObservation,
        *,
        navmesh: BakedNavMesh | None,
        at_seconds: float,
        probe_distance: float = DEFAULT_OBSTACLE_PROBE_DISTANCE_UNITS,
        radius: float = DEFAULT_TEMPORARY_OBSTACLE_RADIUS_UNITS,
    ) -> TemporaryObstacle | None:
        """Project the obstruction ahead of the character and record it, or merge a repeat.

        The obstacle position is ``current_position + intended_direction * probe_distance``
        snapped onto the walkable surface, never the character's own coordinate, so the
        immediate replan routes around the actual obstruction instead of its start node.
        """

        direction_x, direction_z = observation.intended_direction
        magnitude = math.hypot(direction_x, direction_z)
        if magnitude <= 0.0:
            return None
        current = observation.current_position
        projected = WorldPosition(
            current.x + direction_x / magnitude * probe_distance,
            current.y,
            current.z + direction_z / magnitude * probe_distance,
        )
        if navmesh is not None:
            snapped = navmesh.nearest_walkable_position(projected)
            if snapped is not None:
                projected = snapped
        if math.hypot(projected.x - current.x, projected.z - current.z) < (
            MINIMUM_PROJECTION_OFFSET_UNITS
        ):
            return None
        self._purge(at_seconds)
        for index, existing in enumerate(self._obstacles):
            if (
                math.hypot(projected.x - existing.position.x, projected.z - existing.position.z)
                <= OBSTACLE_MERGE_RADIUS_UNITS
            ):
                merged = TemporaryObstacle(
                    existing.position,
                    max(existing.radius, radius),
                    at_seconds + _temporary_obstacle_ttl_seconds(existing.hit_count + 1),
                    existing.hit_count + 1,
                )
                self._obstacles[index] = merged
                return merged
        created = TemporaryObstacle(
            projected, radius, at_seconds + _temporary_obstacle_ttl_seconds(1), 1
        )
        self._obstacles.append(created)
        return created

    def active(self, at_seconds: float) -> tuple[TemporaryObstacle, ...]:
        """Return the obstacles still within their time-to-live, purging the rest."""

        self._purge(at_seconds)
        return tuple(self._obstacles)

    def circles(self, at_seconds: float) -> tuple[tuple[WorldPosition, float], ...]:
        """Return ``(position, radius)`` pairs for obstacle-aware A* routing."""

        return tuple((item.position, item.radius) for item in self.active(at_seconds))

    def positions(self, at_seconds: float) -> tuple[WorldPosition, ...]:
        """Return only the active obstacle centres."""

        return tuple(item.position for item in self.active(at_seconds))

    def clear(self) -> None:
        """Drop every recorded obstacle, e.g. on emergency stop."""

        self._obstacles.clear()

    def _purge(self, at_seconds: float) -> None:
        self._obstacles = [item for item in self._obstacles if item.expires_at > at_seconds]


class RepeatedLocalStallTracker:
    """Count how often the character stalled inside one local area recently (US-093)."""

    def __init__(
        self,
        *,
        radius_units: float = REPEATED_LOCAL_STALL_RADIUS_UNITS,
        window_seconds: float = REPEATED_LOCAL_STALL_WINDOW_SECONDS,
    ) -> None:
        self._radius_units = radius_units
        self._window_seconds = window_seconds
        self._events: list[tuple[WorldPosition, float]] = []

    def record(self, position: WorldPosition, at_seconds: float) -> int:
        """Record one stall and return the resulting local hit count."""

        self._events = [
            item for item in self._events if at_seconds - item[1] <= self._window_seconds
        ]
        self._events.append((position, at_seconds))
        return self.hit_count(position, at_seconds)

    def hit_count(self, position: WorldPosition, at_seconds: float) -> int:
        """Return recent stalls within the local radius and sliding time window."""

        return sum(
            1
            for recorded, recorded_at in self._events
            if at_seconds - recorded_at <= self._window_seconds
            and math.hypot(position.x - recorded.x, position.z - recorded.z) <= self._radius_units
        )

    def clear(self) -> None:
        """Forget every recorded local stall."""

        self._events.clear()


@dataclass(frozen=True, slots=True)
class EscapePlannerConfig:
    """Sampling, validation, and scoring limits for the geometric escape planner."""

    ring_radii_units: tuple[float, ...] = ESCAPE_RING_RADII_UNITS
    ring_directions: int = ESCAPE_RING_DIRECTIONS
    maximum_slope_degrees: float = ESCAPE_MAXIMUM_SLOPE_DEGREES
    minimum_obstacle_clearance_units: float = ESCAPE_MINIMUM_OBSTACLE_CLEARANCE_UNITS
    minimum_goal_progress_units: float = ESCAPE_MINIMUM_GOAL_PROGRESS_UNITS


def plan_escape_candidates(
    *,
    mesh: BakedNavMesh,
    live: WorldPosition,
    goal: WorldPosition,
    obstacles: tuple[tuple[WorldPosition, float], ...] = (),
    config: EscapePlannerConfig | None = None,
) -> tuple[EscapeCandidate, ...]:
    """Return every walkable, reachable escape point that makes progress towards the goal.

    Candidates are sampled on concentric radial rings around the trapped position, projected
    onto the mesh, and kept only when they clear the slope limit, stand far enough from every
    recorded obstacle, and shorten the distance to the goal.
    """

    resolved = config or EscapePlannerConfig()
    trapped_gap = math.hypot(goal.x - live.x, goal.z - live.z)
    seen: set[tuple[float, float]] = set()
    candidates: list[EscapeCandidate] = []
    for radius in resolved.ring_radii_units:
        for index in range(resolved.ring_directions):
            radians = math.radians(FULL_TURN_DEGREES * index / resolved.ring_directions)
            sample = WorldPosition(
                live.x + math.sin(radians) * radius,
                live.y,
                live.z + math.cos(radians) * radius,
            )
            node = mesh.nearest_walkable_position(sample)
            if node is None:
                continue
            key = (round(node.x, 3), round(node.z, 3))
            if key in seen:
                continue
            seen.add(key)
            if mesh.contained_surface(node, tolerance=1.0) is None:
                continue
            slope = mesh.surface_slope_degrees(node)
            if slope is not None and slope > resolved.maximum_slope_degrees:
                continue
            clearance = _obstacle_clearance(node, obstacles)
            if clearance < resolved.minimum_obstacle_clearance_units:
                continue
            goal_gap = math.hypot(goal.x - node.x, goal.z - node.z)
            if goal_gap > trapped_gap - resolved.minimum_goal_progress_units:
                continue
            route = mesh.find_path(live, node, obstacles=obstacles)
            if not route:
                continue
            candidates.append(
                EscapeCandidate(
                    node,
                    route,
                    goal_gap,
                    math.hypot(node.x - live.x, node.z - live.z),
                    clearance,
                )
            )
    return tuple(candidates)


def select_escape(candidates: tuple[EscapeCandidate, ...]) -> EscapeCandidate | None:
    """Return the best-scoring escape candidate, ties broken on its coordinates."""

    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate: (candidate.score, candidate.position.x, candidate.position.z),
    )


def _obstacle_clearance(
    position: WorldPosition, obstacles: tuple[tuple[WorldPosition, float], ...]
) -> float:
    if not obstacles:
        return math.inf
    return min(
        math.hypot(position.x - centre.x, position.z - centre.z) - radius
        for centre, radius in obstacles
    )
