"""Route and patrol-circuit planning over the learned navigation graph."""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from flyff_bot.features.navigation.spatial import GridCell, SpatialMap, WorldPoint

DEFAULT_MINIMUM_HOTSPOT_WEIGHT = 1.0
DEFAULT_TRAVEL_COST_BIAS = 1.0
DEFAULT_MAXIMUM_CIRCUIT_STOPS = 4

# Every navigation position is expressed relative to the point the session started at
# (US-035), so the origin of that relative frame is the session anchor the leash is measured
# from. There is no second anchor to configure.
SESSION_ANCHOR = WorldPoint(0.0, 0.0)


@dataclass(frozen=True, slots=True)
class LeashBound:
    """The circular patrol bound around the session anchor that planning may not leave."""

    radius_pixels: float
    anchor: WorldPoint = field(default=SESSION_ANCHOR)

    def __post_init__(self) -> None:
        if self.radius_pixels <= 0.0:
            raise ValueError("Leash radius must be positive.")

    def contains(self, point: WorldPoint) -> bool:
        """Return whether a continuous position lies inside the leash."""

        return math.hypot(point.x - self.anchor.x, point.y - self.anchor.y) <= self.radius_pixels


@dataclass(frozen=True, slots=True)
class RouteConfig:
    """How strongly travel cost competes with spawn density during planning."""

    minimum_hotspot_weight: float = DEFAULT_MINIMUM_HOTSPOT_WEIGHT
    travel_cost_bias: float = DEFAULT_TRAVEL_COST_BIAS
    maximum_circuit_stops: int = DEFAULT_MAXIMUM_CIRCUIT_STOPS

    def __post_init__(self) -> None:
        if self.minimum_hotspot_weight <= 0.0:
            raise ValueError("Minimum hotspot weight must be positive.")
        if self.travel_cost_bias < 0.0:
            raise ValueError("Travel cost bias must not be negative.")
        if self.maximum_circuit_stops <= 0:
            raise ValueError("Maximum circuit stops must be positive.")


@dataclass(frozen=True, slots=True)
class Route:
    """An ordered cell sequence starting at the planning origin and its total cost."""

    cells: tuple[GridCell, ...] = ()
    cost: float = 0.0

    @property
    def is_empty(self) -> bool:
        """Return whether this route requires no movement."""

        return len(self.cells) < 2

    @property
    def waypoints(self) -> tuple[GridCell, ...]:
        """Return the cells still to be reached after the planning origin."""

        return self.cells[1:]


class RoutePlanner:
    """Plan least-cost routes and recurring circuits over recorded traversals."""

    def __init__(self, spatial_map: SpatialMap, config: RouteConfig | None = None) -> None:
        self._map = spatial_map
        self._config = config or RouteConfig()

    def plan(
        self,
        start: GridCell,
        goal: GridCell,
        *,
        avoided: frozenset[GridCell] = frozenset(),
        leash: LeashBound | None = None,
    ) -> Route:
        """Return the least-cost recorded route between two cells, if one exists."""

        if leash is not None and not self._inside(goal, leash):
            return Route()
        return self._search(
            start,
            lambda cell: cell == goal,
            avoided=avoided,
            leash=leash,
            avoided_exception=goal,
        )

    def return_route(
        self,
        start: GridCell,
        leash: LeashBound,
        *,
        avoided: frozenset[GridCell] = frozenset(),
    ) -> Route:
        """Return the cheapest route from outside the leash back to the nearest cell inside it.

        Expansion is deliberately not leash-constrained here: a character that was pushed or
        resumed outside the bound can only walk back in through the cells it actually stands
        among, so refusing to leave the bound would strand it instead of recalling it.
        """

        return self._search(
            start,
            lambda cell: self._inside(cell, leash),
            avoided=avoided,
            leash=None,
        )

    def hotspots_outside(self, at_seconds: float, leash: LeashBound) -> int:
        """Return how many otherwise eligible spawn hotspots the leash excludes."""

        return sum(
            1
            for cell, _weight in self._map.hotspots(at_seconds, self._config.minimum_hotspot_weight)
            if not self._inside(cell, leash)
        )

    def best_spawn_route(
        self,
        start: GridCell,
        at_seconds: float,
        *,
        avoided: frozenset[GridCell] = frozenset(),
        excluded: frozenset[GridCell] = frozenset(),
        leash: LeashBound | None = None,
    ) -> Route:
        """Return the route to the spawn cluster with the best density-per-cost yield."""

        best_route = Route()
        best_score = 0.0
        for cell, weight in self._map.hotspots(at_seconds, self._config.minimum_hotspot_weight):
            if cell == start or cell in excluded or cell in avoided:
                continue
            if leash is not None and not self._inside(cell, leash):
                continue
            route = self.plan(start, cell, avoided=avoided, leash=leash)
            if route.is_empty:
                continue
            score = weight / (1.0 + self._config.travel_cost_bias * route.cost)
            if score > best_score:
                best_route, best_score = route, score
        return best_route

    def circuit(
        self,
        start: GridCell,
        at_seconds: float,
        *,
        avoided: frozenset[GridCell] = frozenset(),
        leash: LeashBound | None = None,
    ) -> Route:
        """Return a recurring patrol over the densest reachable clusters back to the start."""

        cells: list[GridCell] = [start]
        cost = 0.0
        visited: set[GridCell] = {start}
        current = start
        for _stop in range(self._config.maximum_circuit_stops):
            leg = self.best_spawn_route(
                current, at_seconds, avoided=avoided, excluded=frozenset(visited), leash=leash
            )
            if leg.is_empty:
                break
            cells.extend(leg.waypoints)
            cost += leg.cost
            current = leg.cells[-1]
            visited.add(current)
        if current == start:
            return Route()
        return_leg = self.plan(current, start, avoided=avoided, leash=leash)
        if not return_leg.is_empty:
            cells.extend(return_leg.waypoints)
            cost += return_leg.cost
        return Route(tuple(cells), cost)

    def _inside(self, cell: GridCell, leash: LeashBound) -> bool:
        """Return whether a cell counts as inside the leash, judged by its centre."""

        return leash.contains(self._map.center_of(cell))

    def _search(
        self,
        start: GridCell,
        is_goal: Callable[[GridCell], bool],
        *,
        avoided: frozenset[GridCell],
        leash: LeashBound | None,
        avoided_exception: GridCell | None = None,
    ) -> Route:
        """Return the cheapest recorded route from a cell to the nearest cell matching a goal."""

        if is_goal(start):
            return Route((start,), 0.0)
        costs: dict[GridCell, float] = {start: 0.0}
        previous: dict[GridCell, GridCell] = {}
        settled: set[GridCell] = set()
        queue: list[tuple[float, GridCell]] = [(0.0, start)]
        while queue:
            cost, cell = heapq.heappop(queue)
            if cell in settled:
                continue
            settled.add(cell)
            if is_goal(cell):
                return Route(_reconstruct(previous, start, cell), cost)
            for neighbor in self._map.neighbors(cell):
                if neighbor in settled or (neighbor in avoided and neighbor != avoided_exception):
                    continue
                if leash is not None and not self._inside(neighbor, leash):
                    continue
                candidate = cost + self._map.move_cost(cell, neighbor)
                if candidate < costs.get(neighbor, float("inf")):
                    costs[neighbor] = candidate
                    previous[neighbor] = cell
                    heapq.heappush(queue, (candidate, neighbor))
        return Route()


def _reconstruct(
    previous: dict[GridCell, GridCell], start: GridCell, goal: GridCell
) -> tuple[GridCell, ...]:
    path = [goal]
    cell = goal
    while cell != start:
        cell = previous[cell]
        path.append(cell)
    return tuple(reversed(path))
