"""Elevation-aware A* routing over extracted Flyff ``.lnd`` height fields."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.world_extractor import WorldCoordinate, WorldVectorMap

DEFAULT_MAXIMUM_WALKABLE_GRADIENT = 1.0
DEFAULT_SLOPE_PENALTY_WEIGHT = 3.0
DEFAULT_ROUTE_GRID_STRIDE = 2
DEFAULT_TEMPORARY_BLOCK_RADIUS_UNITS = 3.0
STRAFE_TURN_THRESHOLD_DEGREES = 20.0


@dataclass(frozen=True, slots=True)
class TerrainRouteConfig:
    """Traversal limits and cost weights for terrain routing."""

    maximum_walkable_gradient: float = DEFAULT_MAXIMUM_WALKABLE_GRADIENT
    slope_penalty_weight: float = DEFAULT_SLOPE_PENALTY_WEIGHT
    grid_stride: int = DEFAULT_ROUTE_GRID_STRIDE
    temporary_block_radius_units: float = DEFAULT_TEMPORARY_BLOCK_RADIUS_UNITS

    def __post_init__(self) -> None:
        if self.maximum_walkable_gradient <= 0.0:
            raise ValueError("Maximum walkable terrain gradient must be positive.")
        if self.slope_penalty_weight < 0.0:
            raise ValueError("Terrain slope penalty must not be negative.")
        if self.grid_stride <= 0:
            raise ValueError("Terrain route grid stride must be positive.")
        if self.temporary_block_radius_units <= 0.0:
            raise ValueError("Temporary terrain block radius must be positive.")


@dataclass(frozen=True, slots=True)
class TerrainWaypoint:
    """One 3D route station and its optional lateral contouring angle."""

    position: WorldPosition
    strafe_angle_degrees: float = 0.0


@dataclass(frozen=True, slots=True)
class TerrainRoute:
    """A terrain route, or an explicit blocked result."""

    waypoints: tuple[TerrainWaypoint, ...] = ()
    blocked: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.waypoints


class TerrainRoutePlanner:
    """Plan walkable 3D routes using elevation deltas in every A* edge cost."""

    _NEIGHBOURS = (
        (-1, -1),
        (0, -1),
        (1, -1),
        (-1, 0),
        (1, 0),
        (-1, 1),
        (0, 1),
        (1, 1),
    )

    def __init__(self, world_map: WorldVectorMap, config: TerrainRouteConfig | None = None) -> None:
        self._map = world_map
        self._terrain = world_map.terrain
        self._config = config or TerrainRouteConfig()
        self._spacing = world_map.dimensions.meters_per_unit * self._config.grid_stride

    def plan(
        self,
        start: WorldPosition,
        goal: WorldPosition,
        *,
        temporary_blocks: tuple[WorldPosition, ...] = (),
    ) -> TerrainRoute:
        """Return the lowest-cost walkable route between two live world positions."""

        if self._terrain.is_empty:
            return TerrainRoute(blocked=True)
        start_node = self._node_for(start)
        goal_node = self._node_for(goal)
        if not self._walkable_node(start_node, ()):
            return TerrainRoute(blocked=True)
        if not self._walkable_node(goal_node, temporary_blocks):
            return TerrainRoute(blocked=True)
        if start_node == goal_node:
            return TerrainRoute((TerrainWaypoint(self._position_for(goal_node)),))

        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        costs = {start_node: 0.0}
        open_nodes: list[tuple[float, tuple[int, int]]] = [
            (self._heuristic(start_node, goal_node), start_node)
        ]
        closed: set[tuple[int, int]] = set()
        while open_nodes:
            _score, current = heapq.heappop(open_nodes)
            if current in closed:
                continue
            if current == goal_node:
                nodes = self._reconstruct(came_from, current)
                return TerrainRoute(self._waypoints(self._smooth(nodes, temporary_blocks)))
            closed.add(current)
            for offset_x, offset_z in self._NEIGHBOURS:
                neighbour = (current[0] + offset_x, current[1] + offset_z)
                if neighbour in closed or not self._walkable_edge(
                    current, neighbour, temporary_blocks
                ):
                    continue
                cost = costs[current] + self._edge_cost(current, neighbour)
                if cost >= costs.get(neighbour, math.inf):
                    continue
                came_from[neighbour] = current
                costs[neighbour] = cost
                heapq.heappush(
                    open_nodes, (cost + self._heuristic(neighbour, goal_node), neighbour)
                )
        return TerrainRoute(blocked=True)

    def _node_for(self, position: WorldPosition) -> tuple[int, int]:
        return (round(position.x / self._spacing), round(position.z / self._spacing))

    def _position_for(self, node: tuple[int, int]) -> WorldPosition:
        point = WorldCoordinate(node[0] * self._spacing, node[1] * self._spacing)
        height = self._terrain.height_at(point)
        if height is None:
            raise ValueError("A route node must be covered by extracted terrain.")
        return WorldPosition(point.x, height, point.z)

    def _walkable_node(
        self, node: tuple[int, int], temporary_blocks: tuple[WorldPosition, ...]
    ) -> bool:
        point = WorldCoordinate(node[0] * self._spacing, node[1] * self._spacing)
        if not self._terrain.covers(point):
            return False
        if any(obstacle.contains(point) for obstacle in self._map.obstacles):
            return False
        radius = self._config.temporary_block_radius_units
        return all(
            math.hypot(point.x - block.x, point.z - block.z) > radius for block in temporary_blocks
        )

    def _walkable_edge(
        self,
        origin: tuple[int, int],
        destination: tuple[int, int],
        temporary_blocks: tuple[WorldPosition, ...],
    ) -> bool:
        if not self._walkable_node(destination, temporary_blocks):
            return False
        delta_x = destination[0] - origin[0]
        delta_z = destination[1] - origin[1]
        if abs(delta_x) == 1 and abs(delta_z) == 1:
            # A diagonal may not cut through the touching corner of a rectangle or blocked
            # terrain node; both cardinal shoulders need to be traversable as well.
            if not self._walkable_edge(origin, (origin[0] + delta_x, origin[1]), temporary_blocks):
                return False
            if not self._walkable_edge(origin, (origin[0], origin[1] + delta_z), temporary_blocks):
                return False
        start = self._position_for(origin)
        end = self._position_for(destination)
        horizontal = math.hypot(end.x - start.x, end.z - start.z)
        return (
            horizontal > 0.0
            and abs(end.y - start.y) / horizontal <= self._config.maximum_walkable_gradient
        )

    def _edge_cost(self, origin: tuple[int, int], destination: tuple[int, int]) -> float:
        start = self._position_for(origin)
        end = self._position_for(destination)
        horizontal = math.hypot(end.x - start.x, end.z - start.z)
        vertical = abs(end.y - start.y)
        gradient = vertical / horizontal
        return math.hypot(horizontal, vertical) * (
            1.0 + self._config.slope_penalty_weight * gradient
        )

    def _heuristic(self, origin: tuple[int, int], goal: tuple[int, int]) -> float:
        return math.hypot(goal[0] - origin[0], goal[1] - origin[1]) * self._spacing

    @staticmethod
    def _reconstruct(
        came_from: dict[tuple[int, int], tuple[int, int]], current: tuple[int, int]
    ) -> list[tuple[int, int]]:
        nodes = [current]
        while current in came_from:
            current = came_from[current]
            nodes.append(current)
        nodes.reverse()
        return nodes

    def _smooth(
        self,
        nodes: list[tuple[int, int]],
        temporary_blocks: tuple[WorldPosition, ...],
    ) -> list[tuple[int, int]]:
        """Remove grid zig-zags while retaining sampled slope and obstacle guarantees."""

        if len(nodes) <= 2:
            return nodes
        smoothed = [nodes[0]]
        anchor = 0
        while anchor < len(nodes) - 1:
            candidate = len(nodes) - 1
            while candidate > anchor + 1 and not self._line_walkable(
                nodes[anchor], nodes[candidate], temporary_blocks
            ):
                candidate -= 1
            smoothed.append(nodes[candidate])
            anchor = candidate
        return smoothed

    def _line_walkable(
        self,
        origin: tuple[int, int],
        destination: tuple[int, int],
        temporary_blocks: tuple[WorldPosition, ...],
    ) -> bool:
        delta_x = destination[0] - origin[0]
        delta_z = destination[1] - origin[1]
        steps = max(abs(delta_x), abs(delta_z))
        previous = origin
        for step in range(1, steps + 1):
            fraction = step / steps
            current = (
                round(origin[0] + delta_x * fraction),
                round(origin[1] + delta_z * fraction),
            )
            if current == previous:
                continue
            if not self._walkable_edge(previous, current, temporary_blocks):
                return False
            previous = current
        return True

    def _waypoints(self, nodes: list[tuple[int, int]]) -> tuple[TerrainWaypoint, ...]:
        positions = [self._position_for(node) for node in nodes]
        result: list[TerrainWaypoint] = []
        for index, position in enumerate(positions):
            strafe = 0.0
            if 0 < index < len(positions) - 1:
                incoming = _bearing(positions[index - 1], position)
                outgoing = _bearing(position, positions[index + 1])
                turn = _signed_angle(outgoing - incoming)
                if abs(turn) >= STRAFE_TURN_THRESHOLD_DEGREES:
                    strafe = 90.0 if turn > 0.0 else -90.0
            result.append(TerrainWaypoint(position, strafe))
        return tuple(result)


def _bearing(origin: WorldPosition, destination: WorldPosition) -> float:
    return math.degrees(math.atan2(destination.x - origin.x, destination.z - origin.z))


def _signed_angle(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0
