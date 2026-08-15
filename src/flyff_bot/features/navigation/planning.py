"""Route and patrol-circuit planning over the learned navigation graph."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from flyff_bot.features.navigation.spatial import GridCell, SpatialMap

DEFAULT_MINIMUM_HOTSPOT_WEIGHT = 1.0
DEFAULT_TRAVEL_COST_BIAS = 1.0
DEFAULT_MAXIMUM_CIRCUIT_STOPS = 4


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
    ) -> Route:
        """Return the least-cost recorded route between two cells, if one exists."""

        if start == goal:
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
            if cell == goal:
                return Route(_reconstruct(previous, start, goal), cost)
            for neighbor in self._map.neighbors(cell):
                if neighbor in settled or (neighbor in avoided and neighbor != goal):
                    continue
                candidate = cost + self._map.move_cost(cell, neighbor)
                if candidate < costs.get(neighbor, float("inf")):
                    costs[neighbor] = candidate
                    previous[neighbor] = cell
                    heapq.heappush(queue, (candidate, neighbor))
        return Route()

    def best_spawn_route(
        self,
        start: GridCell,
        at_seconds: float,
        *,
        avoided: frozenset[GridCell] = frozenset(),
        excluded: frozenset[GridCell] = frozenset(),
    ) -> Route:
        """Return the route to the spawn cluster with the best density-per-cost yield."""

        best_route = Route()
        best_score = 0.0
        for cell, weight in self._map.hotspots(at_seconds, self._config.minimum_hotspot_weight):
            if cell == start or cell in excluded or cell in avoided:
                continue
            route = self.plan(start, cell, avoided=avoided)
            if route.is_empty:
                continue
            score = weight / (1.0 + self._config.travel_cost_bias * route.cost)
            if score > best_score:
                best_route, best_score = route, score
        return best_route

    def circuit(
        self, start: GridCell, at_seconds: float, *, avoided: frozenset[GridCell] = frozenset()
    ) -> Route:
        """Return a recurring patrol over the densest reachable clusters back to the start."""

        cells: list[GridCell] = [start]
        cost = 0.0
        visited: set[GridCell] = {start}
        current = start
        for _stop in range(self._config.maximum_circuit_stops):
            leg = self.best_spawn_route(
                current, at_seconds, avoided=avoided, excluded=frozenset(visited)
            )
            if leg.is_empty:
                break
            cells.extend(leg.waypoints)
            cost += leg.cost
            current = leg.cells[-1]
            visited.add(current)
        if current == start:
            return Route()
        return_leg = self.plan(current, start, avoided=avoided)
        if not return_leg.is_empty:
            cells.extend(return_leg.waypoints)
            cost += return_leg.cost
        return Route(tuple(cells), cost)


def _reconstruct(
    previous: dict[GridCell, GridCell], start: GridCell, goal: GridCell
) -> tuple[GridCell, ...]:
    path = [goal]
    cell = goal
    while cell != start:
        cell = previous[cell]
        path.append(cell)
    return tuple(reversed(path))
