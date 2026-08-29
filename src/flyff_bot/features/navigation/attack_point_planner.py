"""Deterministic attack-point sampling and local corridor refinement (US-070)."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from flyff_bot.features.navigation.empirical_routing import ExperienceRoutingConfig
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh

MELEE_ATTACK_MINIMUM_DISTANCE_UNITS = 2.5
MELEE_ATTACK_MAXIMUM_DISTANCE_UNITS = 3.5
RANGED_ATTACK_MINIMUM_DISTANCE_UNITS = 12.0
RANGED_ATTACK_MAXIMUM_DISTANCE_UNITS = 15.0
DEFAULT_ATTACK_SAMPLE_COUNT = 24
DEFAULT_TURN_WEIGHT = 0.02 / 180.0
DEFAULT_FOLLOW_UP_WEIGHT = 0.01
MINIMUM_CORRIDOR_WIDTH_UNITS = 1.0
CORRIDOR_CLEARANCE_WEIGHT = 0.5
# A recorded obstacle is a place that already stopped the character. Standing inside this
# radius of one is refused outright, and standing within the influence radius is ranked worse
# than the same point in the open, so an attack point is chosen safely clear of it (US-091).
OBSTACLE_CLEARANCE_UNITS = 3.0
OBSTACLE_INFLUENCE_UNITS = 6.0
OBSTACLE_PENALTY_WEIGHT = 1.0
TARGET_MOVE_REPLAN_DISTANCE_UNITS = 2.0
ATTACK_POINT_PLANNING_BUDGET_SECONDS = 0.0008
FULL_TURN_DEGREES = 360.0
HALF_TURN_DEGREES = 180.0


@dataclass(frozen=True, slots=True)
class EngagementRadii:
    """The walkable annulus in which a class can engage its target."""

    minimum_units: float
    maximum_units: float

    def __post_init__(self) -> None:
        values = (self.minimum_units, self.maximum_units)
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("Attack engagement radii must be finite and positive.")
        if self.maximum_units < self.minimum_units:
            raise ValueError("Maximum attack radius must not be below the minimum.")


MELEE_ENGAGEMENT_RADII = EngagementRadii(
    MELEE_ATTACK_MINIMUM_DISTANCE_UNITS,
    MELEE_ATTACK_MAXIMUM_DISTANCE_UNITS,
)
RANGED_ENGAGEMENT_RADII = EngagementRadii(
    RANGED_ATTACK_MINIMUM_DISTANCE_UNITS,
    RANGED_ATTACK_MAXIMUM_DISTANCE_UNITS,
)


@dataclass(frozen=True, slots=True)
class AttackPointCandidate:
    """One strictly contained sampled position and its decomposed cost."""

    position: WorldPosition
    polygon_id: int
    angle_degrees: float
    radius_units: float
    travel_seconds: float
    obstacle_penalty: float
    turn_cost: float
    follow_up_distance: float
    score: float


@dataclass(frozen=True, slots=True)
class AttackPointPlan:
    """A validated local approach route and its deterministic diagnostics."""

    target: WorldPosition
    selected: AttackPointCandidate
    candidates_considered: int
    waypoints: tuple[WorldPosition, ...]
    used_fallback: bool = False


@dataclass(frozen=True, slots=True)
class _ScoredCandidate:
    candidate: AttackPointCandidate
    corridor: tuple[int, ...]


class AttackPointPlanner:
    """Sample, score, and validate attack points inside a loaded NavMesh."""

    def __init__(
        self,
        mesh: BakedNavMesh,
        *,
        sample_count: int = DEFAULT_ATTACK_SAMPLE_COUNT,
        turn_weight: float = DEFAULT_TURN_WEIGHT,
        follow_up_weight: float = DEFAULT_FOLLOW_UP_WEIGHT,
    ) -> None:
        if sample_count < 3:
            raise ValueError("Attack point planning needs at least three samples.")
        if not math.isfinite(turn_weight) or turn_weight < 0.0:
            raise ValueError("Attack point turn weight must be finite and non-negative.")
        if not math.isfinite(follow_up_weight) or follow_up_weight < 0.0:
            raise ValueError("Attack point follow-up weight must be finite and non-negative.")
        self._mesh = mesh
        self._sample_count = sample_count
        self._turn_weight = turn_weight
        self._follow_up_weight = follow_up_weight

    def plan(
        self,
        player: WorldPosition,
        target: WorldPosition,
        radii: EngagementRadii,
        *,
        heading_degrees: float,
        follow_ups: Sequence[WorldPosition] = (),
        obstacles: Sequence[WorldPosition] = (),
        routing_config: ExperienceRoutingConfig | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        timeout_seconds: float = ATTACK_POINT_PLANNING_BUDGET_SECONDS,
    ) -> AttackPointPlan | None:
        """Return one contained attack point and its route, or ``None`` on fallback."""

        started_at = monotonic()
        if not _finite_position(player) or not _finite_position(target):
            return None
        if not math.isfinite(heading_degrees) or timeout_seconds <= 0.0:
            return None
        player_surface = self._mesh.contained_surface(player)
        target_surface = self._mesh.contained_surface(target)
        if player_surface is None:
            return None
        if target_surface is None:
            return None
        scored: list[_ScoredCandidate] = []
        for sample_index in range(self._sample_count * len(radii_values(radii))):
            angle_index, ring_index = divmod(sample_index, len(radii_values(radii)))
            radius = radii_values(radii)[ring_index]
            angle = FULL_TURN_DEGREES * angle_index / self._sample_count
            radians = math.radians(angle)
            candidate = WorldPosition(
                target.x + math.sin(radians) * radius,
                target.y,
                target.z + math.cos(radians) * radius,
            )
            surface = self._mesh.contained_surface(candidate)
            if surface is None:
                continue
            polygon, position = surface
            obstacle_gap = _nearest_obstacle_distance(position, obstacles)
            if obstacle_gap <= OBSTACLE_CLEARANCE_UNITS:
                continue
            corridor = self._mesh.find_polygon_path(player, position)
            if not corridor:
                continue
            travel_seconds = math.dist(
                (player.x, player.y, player.z), (position.x, position.y, position.z)
            )
            clearance_penalty = CORRIDOR_CLEARANCE_WEIGHT * max(
                0.0,
                MINIMUM_CORRIDOR_WIDTH_UNITS - min(radius, MINIMUM_CORRIDOR_WIDTH_UNITS),
            ) + OBSTACLE_PENALTY_WEIGHT * max(0.0, OBSTACLE_INFLUENCE_UNITS - obstacle_gap)
            bearing = (
                math.degrees(math.atan2(target.x - position.x, target.z - position.z))
                % FULL_TURN_DEGREES
            )
            heading_error = abs(
                (bearing - heading_degrees + HALF_TURN_DEGREES) % FULL_TURN_DEGREES
                - HALF_TURN_DEGREES
            )
            follow_up_distance = (
                min(
                    math.dist(
                        (position.x, position.y, position.z),
                        (item.x, item.y, item.z),
                    )
                    for item in follow_ups
                )
                if follow_ups
                else 0.0
            )
            score = (
                travel_seconds
                + clearance_penalty
                + (self._turn_weight * heading_error)
                + self._follow_up_weight * follow_up_distance
            )
            if monotonic() - started_at >= timeout_seconds:
                return None
            candidate_record = AttackPointCandidate(
                position=position,
                polygon_id=polygon.polygon_id,
                angle_degrees=angle,
                radius_units=radius,
                travel_seconds=travel_seconds,
                obstacle_penalty=clearance_penalty,
                turn_cost=self._turn_weight * heading_error,
                follow_up_distance=follow_up_distance,
                score=score,
            )
            scored.append(_ScoredCandidate(candidate_record, corridor))
        if not scored:
            return None
        best = min(
            scored,
            key=lambda item: (
                item.candidate.score,
                item.candidate.polygon_id,
                item.candidate.angle_degrees,
                item.candidate.radius_units,
            ),
        )
        route = self._mesh.find_path(player, best.candidate.position, routing_config=routing_config)
        if not route:
            return None
        return AttackPointPlan(target, best.candidate, len(scored), route)


def radii_values(radii: EngagementRadii) -> tuple[float, ...]:
    """Return deterministic sample radii across the valid engagement annulus."""

    if radii.maximum_units == radii.minimum_units:
        return (radii.minimum_units,)
    return (
        radii.minimum_units,
        (radii.minimum_units + radii.maximum_units) / 2.0,
        radii.maximum_units,
    )


def should_replan_attack_target(previous: WorldPosition, current: WorldPosition) -> bool:
    """Report whether target movement exceeds the US-070 replan threshold."""

    return math.dist((previous.x, previous.y, previous.z), (current.x, current.y, current.z)) > (
        TARGET_MOVE_REPLAN_DISTANCE_UNITS
    )


def _nearest_obstacle_distance(
    position: WorldPosition, obstacles: Sequence[WorldPosition]
) -> float:
    """Return the ground distance to the closest recorded obstacle, or infinity."""

    if not obstacles:
        return math.inf
    return min(math.hypot(position.x - item.x, position.z - item.z) for item in obstacles)


def _finite_position(position: WorldPosition) -> bool:
    return all(math.isfinite(value) for value in (position.x, position.y, position.z))
