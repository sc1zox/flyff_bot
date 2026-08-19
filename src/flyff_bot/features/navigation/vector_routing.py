"""Visibility-graph A* routing around the extracted world obstacle geometry.

A learned grid can only avoid what a session has already walked into. The extracted
passability rectangles (US-045) are known before the first step, so a route around them is a
geometry problem rather than a learning one: among axis-aligned rectangles the shortest
obstacle-free path between two points bends only at rectangle corners, which makes the
corners plus the two endpoints a complete vertex set for an exact search.

The graph is built per query over the obstacles inside the corridor between start and goal,
not over the whole region: Eden's terrain alone yields hundreds of rectangles, and an
all-pairs visibility graph over them would cost far more than the search it feeds. Within
one query the visibility of a vertex against every other vertex is evaluated as one
vectorised slab clip, so the search cost stays in the milliseconds the pathing tick has.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from flyff_bot.features.navigation.world_extractor import ObstacleRectangle, WorldCoordinate

# Half the width of the character's collision footprint, in world units. Routing along the
# exact edge of a cliff quad would leave no room for the heading tolerance the steering runs
# with, so every obstacle is inflated by this before the graph is built.
DEFAULT_CLEARANCE_UNITS = 6.0
# How far outside the start-to-goal bounding box an obstacle may sit and still force a
# detour, in world units. Eden's mapped terrain block is a quarter impassable, and the
# corridor width drives the search cost far harder than its length does: at eight terrain
# quads a 150-unit query costs about 3 ms and a 400-unit one about 60 ms, while quadrupling
# the margin quadruples both. A detour that would have to swing wider than this is reported
# blocked instead, which is the fallback to learned pathing rather than a wrong route.
DEFAULT_CORRIDOR_MARGIN_UNITS = 32.0
# Ceiling on the graph the search is allowed to build. Reaching it means the corridor is
# dense enough that proving an exact detour costs more than the tick has; the planner reports
# the query as blocked and the session falls back to its learned pathing.
DEFAULT_MAXIMUM_OBSTACLES = 192
# Two positions closer together than this are the same place for routing purposes.
COINCIDENT_POINT_EPSILON = 1e-6
# Segments are tested against the open interior of a rectangle, so a path that grazes a
# corner or runs along an edge stays visible.
INTERIOR_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class VectorRouteConfig:
    """Clearance, corridor width, and complexity ceiling of the visibility-graph search."""

    clearance_units: float = DEFAULT_CLEARANCE_UNITS
    corridor_margin_units: float = DEFAULT_CORRIDOR_MARGIN_UNITS
    maximum_obstacles: int = DEFAULT_MAXIMUM_OBSTACLES

    def __post_init__(self) -> None:
        if self.clearance_units < 0.0:
            raise ValueError("Vector routing clearance must not be negative.")
        if self.corridor_margin_units <= 0.0:
            raise ValueError("Vector routing corridor margin must be positive.")
        if self.maximum_obstacles <= 0:
            raise ValueError("Vector routing obstacle ceiling must be positive.")


@dataclass(frozen=True, slots=True)
class VectorRoute:
    """An obstacle-free polyline in world coordinates, or the reason there is none."""

    points: tuple[WorldCoordinate, ...] = ()
    length_units: float = 0.0
    # True when the corridor is obstructed and no detour was found within the search bounds,
    # which is what makes the caller fall back rather than walk a straight line into a cliff.
    blocked: bool = False

    @property
    def is_empty(self) -> bool:
        """Return whether this route requires no movement."""

        return len(self.points) < 2

    @property
    def waypoints(self) -> tuple[WorldCoordinate, ...]:
        """Return the points still to be reached after the start."""

        return self.points[1:]


class ObstacleField:
    """The obstacle rectangles of one query, held as arrays the slab clip can broadcast."""

    def __init__(self, obstacles: Sequence[ObstacleRectangle]) -> None:
        self._obstacles = tuple(obstacles)
        bounds = np.array(
            [
                (
                    obstacle.minimum_x,
                    obstacle.minimum_z,
                    obstacle.maximum_x,
                    obstacle.maximum_z,
                )
                for obstacle in self._obstacles
            ],
            dtype=np.float64,
        ).reshape(len(self._obstacles), 4)
        self._minimum_x = bounds[:, 0]
        self._minimum_z = bounds[:, 1]
        self._maximum_x = bounds[:, 2]
        self._maximum_z = bounds[:, 3]

    def __len__(self) -> int:
        return len(self._obstacles)

    @property
    def rectangles(self) -> tuple[ObstacleRectangle, ...]:
        """Return the rectangles this field was built from."""

        return self._obstacles

    def blocked_mask(
        self, origin: WorldCoordinate, targets: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.bool_]:
        """Return which of many segments out of one origin cross an obstacle interior.

        Each segment is parameterised over ``[0, 1]`` and every axis narrows the surviving
        interval (the Liang-Barsky slab clip). A surviving interval of positive length means
        the segment runs through a rectangle rather than merely grazing its boundary.
        """

        if len(self._obstacles) == 0:
            return np.zeros(targets.shape[0], dtype=np.bool_)
        entering = np.zeros((targets.shape[0], len(self._obstacles)), dtype=np.float64)
        leaving = np.ones_like(entering)
        for delta, low, high in (
            (
                targets[:, 0] - origin.x,
                self._minimum_x - origin.x,
                self._maximum_x - origin.x,
            ),
            (
                targets[:, 1] - origin.z,
                self._minimum_z - origin.z,
                self._maximum_z - origin.z,
            ),
        ):
            column = delta[:, np.newaxis]
            parallel = np.abs(column) <= INTERIOR_EPSILON
            safe = np.where(parallel, 1.0, column)
            first = np.minimum(low / safe, high / safe)
            second = np.maximum(low / safe, high / safe)
            # A segment parallel to this axis either sits strictly inside the slab, which
            # constrains nothing, or outside it, which empties the interval outright.
            inside = (low < 0.0) & (high > 0.0)
            first = np.where(parallel, np.where(inside, 0.0, 1.0), first)
            second = np.where(parallel, np.where(inside, 1.0, 0.0), second)
            entering = np.maximum(entering, first)
            leaving = np.minimum(leaving, second)
        crossings: npt.NDArray[np.bool_] = (leaving - entering) > INTERIOR_EPSILON
        return np.asarray(crossings.any(axis=1), dtype=np.bool_)

    def blocks(self, origin: WorldCoordinate, destination: WorldCoordinate) -> bool:
        """Return whether one straight segment crosses the interior of any obstacle."""

        targets = np.array([[destination.x, destination.z]], dtype=np.float64)
        return bool(self.blocked_mask(origin, targets)[0])


class VectorRoutePlanner:
    """Plan globally shortest obstacle-free routes over extracted world geometry."""

    def __init__(
        self,
        obstacles: Iterable[ObstacleRectangle] = (),
        config: VectorRouteConfig | None = None,
    ) -> None:
        self._config = config or VectorRouteConfig()
        self._obstacles = tuple(obstacles)

    @property
    def obstacle_count(self) -> int:
        """Return how many obstacle rectangles this planner routes around."""

        return len(self._obstacles)

    @property
    def config(self) -> VectorRouteConfig:
        """Return the clearance and search bounds this planner applies."""

        return self._config

    def plan(self, start: WorldCoordinate, goal: WorldCoordinate) -> VectorRoute:
        """Return the shortest obstacle-free polyline from one position to another."""

        if _distance(start, goal) <= COINCIDENT_POINT_EPSILON:
            return VectorRoute((start,))
        corridor = self._corridor(start, goal)
        field = ObstacleField(corridor.blockers)
        if not field.blocks(start, goal):
            return VectorRoute((start, goal), _distance(start, goal))
        if len(corridor.blockers) > self._config.maximum_obstacles:
            return VectorRoute(blocked=True)
        return _search(self._vertices(start, goal, corridor), field)

    def is_reachable(self, start: WorldCoordinate, goal: WorldCoordinate) -> bool:
        """Return whether a route exists between two positions."""

        return not self.plan(start, goal).blocked

    def _corridor(self, start: WorldCoordinate, goal: WorldCoordinate) -> _Corridor:
        """Return the search corridor between two positions and the obstacles inside it.

        The corridor is the endpoints' bounding box plus a margin, and it is what makes the
        search sound. Every route vertex is clipped to it (:meth:`_vertices`), the box is
        convex, so every leg between two vertices stays inside it as well - and every
        obstacle that overlaps it is a blocker. Nothing a leg can reach has been left out.

        An obstacle the start or the goal already stands inside is not treated as a blocker:
        the character is there, so blocking it would only make every query unsolvable.
        """

        margin = self._config.corridor_margin_units
        bounds = _Bounds(
            min(start.x, goal.x) - margin,
            min(start.z, goal.z) - margin,
            max(start.x, goal.x) + margin,
            max(start.z, goal.z) + margin,
        )
        blockers: list[ObstacleRectangle] = []
        for obstacle in self._obstacles:
            inflated = obstacle.inflated(self._config.clearance_units)
            if not bounds.overlaps(inflated):
                continue
            if inflated.contains(start) or inflated.contains(goal):
                continue
            blockers.append(inflated)
        return _Corridor(bounds, tuple(blockers))

    def _vertices(
        self, start: WorldCoordinate, goal: WorldCoordinate, corridor: _Corridor
    ) -> tuple[WorldCoordinate, ...]:
        """Return the endpoints plus every obstacle corner inside the search corridor.

        A corner outside the corridor is dropped rather than kept as an unreachable vertex:
        keeping it would let a leg leave the box, past the half of an obstacle that was never
        selected. Losing it can only make a detour unprovable, which the caller reports as
        blocked and falls back on.
        """

        vertices = [start, goal]
        seen = {(start.x, start.z), (goal.x, goal.z)}
        for obstacle in corridor.blockers:
            for corner in obstacle.corners:
                key = (corner.x, corner.z)
                if key in seen or not corridor.bounds.contains(corner):
                    continue
                if any(_strictly_inside(corner, other) for other in corridor.blockers):
                    continue
                seen.add(key)
                vertices.append(corner)
        return tuple(vertices)


@dataclass(frozen=True, slots=True)
class _Bounds:
    """One query's search corridor, as an axis-aligned box."""

    minimum_x: float
    minimum_z: float
    maximum_x: float
    maximum_z: float

    def overlaps(self, obstacle: ObstacleRectangle) -> bool:
        return not (
            obstacle.maximum_x < self.minimum_x
            or obstacle.minimum_x > self.maximum_x
            or obstacle.maximum_z < self.minimum_z
            or obstacle.minimum_z > self.maximum_z
        )

    def contains(self, point: WorldCoordinate) -> bool:
        return (
            self.minimum_x <= point.x <= self.maximum_x
            and self.minimum_z <= point.z <= self.maximum_z
        )


@dataclass(frozen=True, slots=True)
class _Corridor:
    """One query's search box and the inflated obstacles that overlap it."""

    bounds: _Bounds
    blockers: tuple[ObstacleRectangle, ...]


def segment_enters_rectangle(
    origin: WorldCoordinate, destination: WorldCoordinate, rectangle: ObstacleRectangle
) -> bool:
    """Return whether a straight segment passes through the interior of one rectangle."""

    return ObstacleField((rectangle,)).blocks(origin, destination)


def _search(vertices: Sequence[WorldCoordinate], field: ObstacleField) -> VectorRoute:
    """Run A* from the first vertex to the second over their mutual visibility."""

    start_index, goal_index = 0, 1
    goal = vertices[goal_index]
    positions = np.array([(vertex.x, vertex.z) for vertex in vertices], dtype=np.float64)
    heuristics = np.hypot(positions[:, 0] - goal.x, positions[:, 1] - goal.z)
    costs = {start_index: 0.0}
    previous: dict[int, int] = {}
    settled: set[int] = set()
    queue: list[tuple[float, int]] = [(float(heuristics[start_index]), start_index)]
    while queue:
        _estimate, index = heapq.heappop(queue)
        if index in settled:
            continue
        settled.add(index)
        if index == goal_index:
            return VectorRoute(_reconstruct(previous, vertices, goal_index), costs[index])
        blocked = field.blocked_mask(vertices[index], positions)
        steps = np.hypot(positions[:, 0] - vertices[index].x, positions[:, 1] - vertices[index].z)
        for neighbor in range(len(vertices)):
            if neighbor == index or neighbor in settled or blocked[neighbor]:
                continue
            candidate = costs[index] + float(steps[neighbor])
            if candidate < costs.get(neighbor, math.inf):
                costs[neighbor] = candidate
                previous[neighbor] = index
                heapq.heappush(queue, (candidate + float(heuristics[neighbor]), neighbor))
    return VectorRoute(blocked=True)


def _reconstruct(
    previous: dict[int, int], vertices: Sequence[WorldCoordinate], goal_index: int
) -> tuple[WorldCoordinate, ...]:
    path = [goal_index]
    index = goal_index
    while index in previous:
        index = previous[index]
        path.append(index)
    return tuple(vertices[step] for step in reversed(path))


def _strictly_inside(point: WorldCoordinate, obstacle: ObstacleRectangle) -> bool:
    return (
        obstacle.minimum_x + INTERIOR_EPSILON < point.x < obstacle.maximum_x - INTERIOR_EPSILON
        and obstacle.minimum_z + INTERIOR_EPSILON < point.z < obstacle.maximum_z - INTERIOR_EPSILON
    )


def _distance(origin: WorldCoordinate, destination: WorldCoordinate) -> float:
    return math.hypot(destination.x - origin.x, destination.z - origin.z)
