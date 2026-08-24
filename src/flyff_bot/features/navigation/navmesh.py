"""Deterministic multi-layer surface navigation over offline world triangles.

This is an offline data/query layer.  It deliberately has no dependency on Win32 input,
process memory, or a running client; live routing continues to use the US-052 terrain
planner until a matching baked mesh is explicitly supplied by a later integration.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import count, pairwise
from typing import TYPE_CHECKING

from flyff_bot.features.navigation.live_camera import Vector3D
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.raycast import NavMeshRayIndex, RayHit
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex

if TYPE_CHECKING:
    from flyff_bot.features.navigation.empirical_routing import (
        EmpiricalCostIndex,
        ExperienceRoutingConfig,
    )

DEFAULT_MAXIMUM_WALKABLE_SLOPE_DEGREES = 45.0
DEFAULT_AGENT_RADIUS_UNITS = 1.0
DEFAULT_AGENT_HEIGHT_UNITS = 2.0
DEFAULT_MAXIMUM_STEP_HEIGHT_UNITS = 1.0
DEFAULT_NAVMESH_CELL_SIZE_UNITS = 4.0
STRICT_CONTAINMENT_TOLERANCE = 1e-9
NAVMESH_SCHEMA_VERSION = 1
_EDGE_PRECISION = 6


@dataclass(frozen=True, slots=True)
class AgentNavigationConfig:
    """Static traversal limits used to bake a deterministic navmesh."""

    maximum_walkable_slope_degrees: float = DEFAULT_MAXIMUM_WALKABLE_SLOPE_DEGREES
    agent_radius_units: float = DEFAULT_AGENT_RADIUS_UNITS
    agent_height_units: float = DEFAULT_AGENT_HEIGHT_UNITS
    maximum_step_height_units: float = DEFAULT_MAXIMUM_STEP_HEIGHT_UNITS
    cell_size_units: float = DEFAULT_NAVMESH_CELL_SIZE_UNITS

    def __post_init__(self) -> None:
        if not 0.0 < self.maximum_walkable_slope_degrees < 90.0:
            raise ValueError("Maximum walkable slope must be between zero and ninety degrees.")
        if (
            min(
                self.agent_radius_units,
                self.agent_height_units,
                self.maximum_step_height_units,
                self.cell_size_units,
            )
            <= 0.0
        ):
            raise ValueError("Agent dimensions and navmesh cell size must be positive.")


@dataclass(frozen=True, slots=True)
class NavMeshPolygon:
    """One stable walkable triangle and its connected-region identity."""

    polygon_id: int
    region_id: int
    triangle: WorldTriangle

    @property
    def centroid(self) -> WorldPosition:
        first, second, third = self.triangle.first, self.triangle.second, self.triangle.third
        return WorldPosition(
            (first.x + second.x + third.x) / 3.0,
            (first.y + second.y + third.y) / 3.0,
            (first.z + second.z + third.z) / 3.0,
        )


@dataclass(frozen=True, slots=True)
class SurfaceSpan:
    """Distinct walkable polygons crossing one horizontal navmesh cell."""

    cell_x: int
    cell_z: int
    polygon_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Portal:
    """The ordered shared edge between two successive corridor polygons."""

    left: WorldPosition
    right: WorldPosition


class BakedNavMesh:
    """A queryable multi-layer navmesh with deterministic polygon and region IDs."""

    def __init__(
        self,
        polygons: tuple[NavMeshPolygon, ...],
        adjacency: dict[int, tuple[int, ...]],
        spans: tuple[SurfaceSpan, ...],
        config: AgentNavigationConfig,
        empirical_costs: EmpiricalCostIndex | None = None,
    ) -> None:
        self._polygons = polygons
        self._by_id = {polygon.polygon_id: polygon for polygon in polygons}
        self._adjacency = adjacency
        self._spans = spans
        self.config = config
        # Built on the first cast and reused for the mesh's lifetime: indexing every
        # walkable triangle once is what keeps a batch of detections off a full scan.
        self._ray_index: NavMeshRayIndex | None = None
        self._containment_index: dict[tuple[int, int], tuple[NavMeshPolygon, ...]] | None = None
        self._empirical_costs = empirical_costs

    def attach_empirical_cost_index(
        self,
        index: EmpiricalCostIndex,
        *,
        mesh_digest: str,
    ) -> None:
        """Attach digest-matched empirical weights without changing mesh connectivity."""

        if index.mesh_digest != mesh_digest:
            raise ValueError("Empirical cost digest does not match the loaded NavMesh.")
        self._empirical_costs = index

    @property
    def polygons(self) -> tuple[NavMeshPolygon, ...]:
        """Return polygons in their stable ID order."""

        return self._polygons

    @property
    def surface_spans(self) -> tuple[SurfaceSpan, ...]:
        """Return the multi-layer X/Z index without flattening vertical surfaces."""

        return self._spans

    @property
    def adjacency(self) -> dict[int, tuple[int, ...]]:
        """Return the stable polygon graph without exposing its mutable backing mapping."""

        return dict(self._adjacency)

    def raycast(self, origin: WorldPosition, direction: Vector3D) -> RayHit | None:
        """Return the first walkable surface a world ray meets, nearest hit first."""

        if self._ray_index is None:
            self._ray_index = NavMeshRayIndex(
                tuple((polygon.polygon_id, polygon.triangle) for polygon in self._polygons),
                self.config.cell_size_units,
            )
        return self._ray_index.nearest_hit(origin, direction)

    def nearest_walkable_position(self, position: WorldPosition) -> WorldPosition | None:
        """Project to the nearest valid surface; ties use the stable polygon ID."""

        nearest = self._nearest(position)
        return None if nearest is None else nearest[1]

    def contained_surface(
        self, position: WorldPosition, *, tolerance: float = STRICT_CONTAINMENT_TOLERANCE
    ) -> tuple[NavMeshPolygon, WorldPosition] | None:
        """Return a polygon that strictly contains the X/Z point, without projecting it."""

        if not math.isfinite(tolerance) or tolerance < STRICT_CONTAINMENT_TOLERANCE:
            return None
        index = self._containment_index
        if index is None:
            grouped: defaultdict[tuple[int, int], list[NavMeshPolygon]] = defaultdict(list)
            for polygon in self._polygons:
                vertices = polygon.triangle.first, polygon.triangle.second, polygon.triangle.third
                minimum_x = min(vertex.x for vertex in vertices)
                maximum_x = max(vertex.x for vertex in vertices)
                minimum_z = min(vertex.z for vertex in vertices)
                maximum_z = max(vertex.z for vertex in vertices)
                for cell_x in range(
                    _containment_cell(minimum_x - tolerance, self.config.cell_size_units),
                    _containment_cell(maximum_x + tolerance, self.config.cell_size_units) + 1,
                ):
                    for cell_z in range(
                        _containment_cell(minimum_z - tolerance, self.config.cell_size_units),
                        _containment_cell(maximum_z + tolerance, self.config.cell_size_units) + 1,
                    ):
                        grouped[(cell_x, cell_z)].append(polygon)
            index = {cell: tuple(polys) for cell, polys in grouped.items()}
            self._containment_index = index
        candidates = index.get(
            _containment_key(position.x, position.z, self.config.cell_size_units)
        )
        matches: list[tuple[float, int, NavMeshPolygon, float]] = []
        for polygon in candidates or ():
            height = _height_at_xz(
                polygon.triangle,
                position.x,
                position.z,
            )
            if height is None or not math.isfinite(height):
                continue
            distance_to_point = abs(height - position.y)
            if distance_to_point > tolerance:
                continue
            matches.append((distance_to_point, polygon.polygon_id, polygon, height))
        if not matches:
            return None
        _, _, polygon, height = min(matches)
        return polygon, WorldPosition(position.x, height, position.z)

    def polygon_or_region_id(self, position: WorldPosition) -> int | None:
        """Return the stable polygon ID of the nearest walkable surface."""

        nearest = self._nearest(position)
        return None if nearest is None else nearest[0].polygon_id

    def navigation_region_id(self, position: WorldPosition) -> int | None:
        """Return the connected-region ID that telemetry can store when a mesh is loaded."""

        nearest = self._nearest(position)
        return None if nearest is None else nearest[0].region_id

    def is_reachable(self, start: WorldPosition, goal: WorldPosition) -> bool:
        """Return whether projected endpoints belong to one topological region."""

        endpoints = self._endpoints(start, goal)
        return endpoints is not None and endpoints[0][0].region_id == endpoints[1][0].region_id

    def find_path(
        self,
        start: WorldPosition,
        goal: WorldPosition,
        *,
        routing_config: ExperienceRoutingConfig | None = None,
    ) -> tuple[WorldPosition, ...]:
        """Return collision-surface waypoints, or an empty tuple when endpoints disconnect."""

        polygon_path = self.find_polygon_path(start, goal, routing_config=routing_config)
        if not polygon_path:
            return ()
        endpoints = self._endpoints(start, goal)
        if endpoints is None:
            return ()
        (_start_polygon, projected_start), (_goal_polygon, projected_goal) = endpoints
        portals: list[_Portal] = []
        for current, following in pairwise(polygon_path):
            portal = _portal_between(self._by_id[current], self._by_id[following])
            if portal is None:
                # A corridor edge must be a shared triangle edge. Retain the prior deterministic
                # centroid route rather than turning an unexpected malformed mesh into a shortcut.
                return _centroid_waypoints(
                    self._by_id, polygon_path, projected_start, projected_goal
                )
            portals.append(portal)
        return _string_pull(projected_start, tuple(portals), projected_goal)

    def find_polygon_path(
        self,
        start: WorldPosition,
        goal: WorldPosition,
        *,
        routing_config: ExperienceRoutingConfig | None = None,
    ) -> tuple[int, ...]:
        """Return the stable polygon corridor used by weighted A*, for diagnostics/tests."""

        endpoints = self._endpoints(start, goal)
        if endpoints is None:
            return ()
        (start_polygon, projected_start), (goal_polygon, projected_goal) = endpoints
        if start_polygon.region_id != goal_polygon.region_id:
            return ()
        # A* operates on stable IDs; projected endpoints are intentionally unused here.
        del projected_start, projected_goal
        return _a_star(
            self._adjacency,
            self._by_id,
            start_polygon.polygon_id,
            goal_polygon.polygon_id,
            self._empirical_costs,
            routing_config,
        )

    def path_distance(self, start: WorldPosition, goal: WorldPosition) -> float | None:
        """Return the exact sum of the returned 3D path segments, or ``None`` if blocked."""

        path = self.find_path(start, goal)
        if not path:
            return None
        return sum(_distance(first, second) for first, second in pairwise(path))

    def _nearest(self, position: WorldPosition) -> tuple[NavMeshPolygon, WorldPosition] | None:
        choices = [
            (
                math.dist((position.x, position.y, position.z), _point_tuple(projected)),
                polygon.polygon_id,
                polygon,
                projected,
            )
            for polygon in self._polygons
            for projected in (_closest_point(position, polygon.triangle),)
        ]
        if not choices:
            return None
        _distance_to_surface, _stable_id, polygon, projected = min(choices)
        return polygon, projected

    def _endpoints(
        self, start: WorldPosition, goal: WorldPosition
    ) -> tuple[tuple[NavMeshPolygon, WorldPosition], tuple[NavMeshPolygon, WorldPosition]] | None:
        first = self._nearest(start)
        second = self._nearest(goal)
        return None if first is None or second is None else (first, second)


class NavMeshBaker:
    """Bake static triangles into walkable, connected, multi-layer surface polygons."""

    def __init__(self, config: AgentNavigationConfig | None = None) -> None:
        self._config = config or AgentNavigationConfig()

    def bake(self, triangles: tuple[WorldTriangle, ...]) -> BakedNavMesh:
        """Bake only finite, sufficiently broad, upward-facing walkable triangles."""

        accepted = sorted(
            (triangle for triangle in triangles if self._walkable(triangle)), key=_triangle_key
        )
        clearance_candidates = _clearance_candidates(triangles, self._config.cell_size_units)
        accepted = [
            triangle
            for triangle in accepted
            if _has_vertical_clearance(
                triangle,
                clearance_candidates[
                    _clearance_cell(_triangle_centroid(triangle), self._config.cell_size_units)
                ],
                self._config.agent_height_units,
            )
        ]
        adjacency = _adjacency(accepted, self._config.maximum_step_height_units)
        region_by_index = _regions(adjacency)
        polygons = tuple(
            NavMeshPolygon(index + 1, region_by_index[index], triangle)
            for index, triangle in enumerate(accepted)
        )
        polygon_adjacency = {
            index + 1: tuple(neighbour + 1 for neighbour in sorted(neighbours))
            for index, neighbours in adjacency.items()
        }
        return BakedNavMesh(
            polygons,
            polygon_adjacency,
            _spans(polygons, self._config.cell_size_units),
            self._config,
        )

    def _walkable(self, triangle: WorldTriangle) -> bool:
        first, second, third = triangle.first, triangle.second, triangle.third
        normal = _normal(first, second, third)
        normal_length = math.sqrt(sum(value * value for value in normal))
        if normal_length == 0.0:
            return False
        upward = abs(normal[1]) / normal_length
        minimum_upward = math.cos(math.radians(self._config.maximum_walkable_slope_degrees))
        if upward < minimum_upward:
            return False
        edge_lengths = (
            _distance_vertex(first, second),
            _distance_vertex(second, third),
            _distance_vertex(third, first),
        )
        area_twice = normal_length
        narrowest_altitude = min(area_twice / edge for edge in edge_lengths if edge > 0.0)
        return narrowest_altitude >= self._config.agent_radius_units * 2.0


def _adjacency(triangles: list[WorldTriangle], maximum_step: float) -> dict[int, set[int]]:
    edges: dict[tuple[tuple[float, float, float], tuple[float, float, float]], list[int]] = (
        defaultdict(list)
    )
    for index, triangle in enumerate(triangles):
        vertices = (triangle.first, triangle.second, triangle.third)
        for first, second in zip(vertices, vertices[1:] + vertices[:1], strict=False):
            edges[_edge_key(first, second)].append(index)
    result: dict[int, set[int]] = {index: set() for index in range(len(triangles))}
    for indices in edges.values():
        for left in indices:
            for right in indices:
                if left >= right:
                    continue
                if (
                    abs(_centroid_y(triangles[left]) - _centroid_y(triangles[right]))
                    <= maximum_step
                ):
                    result[left].add(right)
                    result[right].add(left)
    return result


def _regions(adjacency: dict[int, set[int]]) -> dict[int, int]:
    regions: dict[int, int] = {}
    for initial in sorted(adjacency):
        if initial in regions:
            continue
        region_id = len(set(regions.values())) + 1
        stack = [initial]
        while stack:
            current = stack.pop()
            if current in regions:
                continue
            regions[current] = region_id
            stack.extend(adjacency[current] - regions.keys())
    return regions


def _spans(polygons: tuple[NavMeshPolygon, ...], cell_size: float) -> tuple[SurfaceSpan, ...]:
    grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
    for polygon in polygons:
        centroid = polygon.centroid
        grouped[(math.floor(centroid.x / cell_size), math.floor(centroid.z / cell_size))].append(
            polygon.polygon_id
        )
    return tuple(
        SurfaceSpan(cell_x, cell_z, tuple(sorted(ids)))
        for (cell_x, cell_z), ids in sorted(grouped.items())
    )


def _clearance_candidates(
    triangles: tuple[WorldTriangle, ...], cell_size: float
) -> dict[tuple[int, int], tuple[WorldTriangle, ...]]:
    """Index ceiling candidates by horizontal coverage before per-floor clearance checks."""

    candidates: dict[tuple[int, int], list[WorldTriangle]] = defaultdict(list)
    for triangle in triangles:
        vertices = triangle.first, triangle.second, triangle.third
        first_cell_x = math.floor(min(vertex.x for vertex in vertices) / cell_size)
        last_cell_x = math.floor(max(vertex.x for vertex in vertices) / cell_size)
        first_cell_z = math.floor(min(vertex.z for vertex in vertices) / cell_size)
        last_cell_z = math.floor(max(vertex.z for vertex in vertices) / cell_size)
        for cell_x in range(first_cell_x, last_cell_x + 1):
            for cell_z in range(first_cell_z, last_cell_z + 1):
                candidates[(cell_x, cell_z)].append(triangle)
    return {cell: tuple(value) for cell, value in candidates.items()}


def _clearance_cell(position: WorldPosition, cell_size: float) -> tuple[int, int]:
    return math.floor(position.x / cell_size), math.floor(position.z / cell_size)


def _has_vertical_clearance(
    floor: WorldTriangle, candidates: tuple[WorldTriangle, ...], agent_height: float
) -> bool:
    centroid = _triangle_centroid(floor)
    for possible_ceiling in candidates:
        if possible_ceiling == floor:
            continue
        ceiling_y = _height_at_xz(possible_ceiling, centroid.x, centroid.z)
        if ceiling_y is not None and 0.0 < ceiling_y - centroid.y < agent_height:
            return False
    return True


def _centroid_waypoints(
    polygons: dict[int, NavMeshPolygon],
    polygon_path: tuple[int, ...],
    start: WorldPosition,
    goal: WorldPosition,
) -> tuple[WorldPosition, ...]:
    """Return the conservative pre-funnel route for an invalid persisted corridor."""

    return _remove_repeated(
        [start, *(polygons[polygon_id].centroid for polygon_id in polygon_path[1:-1]), goal]
    )


def _portal_between(first: NavMeshPolygon, second: NavMeshPolygon) -> _Portal | None:
    """Return a consistently left/right oriented shared edge for two adjacent triangles."""

    first_vertices = (first.triangle.first, first.triangle.second, first.triangle.third)
    second_keys = {
        _vertex_key(vertex)
        for vertex in (second.triangle.first, second.triangle.second, second.triangle.third)
    }
    shared = tuple(vertex for vertex in first_vertices if _vertex_key(vertex) in second_keys)
    if len(shared) != 2:
        return None
    first_point, second_point = (WorldPosition(*_vertex_tuple(vertex)) for vertex in shared)
    direction_start = first.centroid
    direction_end = second.centroid
    orientation = _triarea2(direction_start, direction_end, first_point)
    if orientation > 0.0:
        return _Portal(second_point, first_point)
    if orientation < 0.0:
        return _Portal(first_point, second_point)
    # Coplanar/collinear centroids are unusual but deterministic ordering still gives the
    # funnel a valid portal instead of silently changing its route between equal bakes.
    if _point_key(first_point) <= _point_key(second_point):
        return _Portal(first_point, second_point)
    return _Portal(second_point, first_point)


def _string_pull(
    start: WorldPosition, portals: tuple[_Portal, ...], goal: WorldPosition
) -> tuple[WorldPosition, ...]:
    """Smooth a triangle corridor with the classic X/Z-plane funnel algorithm.

    The returned corners are actual portal vertices, preserving the mesh's authored 3D
    elevation rather than replacing a ramp with centroid-derived free-space waypoints.
    """

    if not portals:
        return _remove_repeated([start, goal])
    route: list[WorldPosition] = [start]
    apex = start
    left = portals[0].left
    right = portals[0].right
    left_index = right_index = 0
    portal_index = 1
    all_portals = (*portals, _Portal(goal, goal))
    while portal_index < len(all_portals):
        next_portal = all_portals[portal_index]
        next_left, next_right = next_portal.left, next_portal.right
        if _triarea2(apex, right, next_right) <= 0.0:
            if _same_xz(apex, right) or _triarea2(apex, left, next_right) > 0.0:
                right = next_right
                right_index = portal_index
            else:
                route.append(left)
                apex = left
                portal_index = left_index + 1
                left = apex
                right = apex
                left_index = right_index = portal_index - 1
                continue
        if _triarea2(apex, left, next_left) >= 0.0:
            if _same_xz(apex, left) or _triarea2(apex, right, next_left) < 0.0:
                left = next_left
                left_index = portal_index
            else:
                route.append(right)
                apex = right
                portal_index = right_index + 1
                left = apex
                right = apex
                left_index = right_index = portal_index - 1
                continue
        portal_index += 1
    route.append(goal)
    return _remove_repeated(route)


def _a_star(
    adjacency: dict[int, tuple[int, ...]],
    polygons: dict[int, NavMeshPolygon],
    start: int,
    goal: int,
    empirical_costs: EmpiricalCostIndex | None,
    routing_config: ExperienceRoutingConfig | None,
) -> tuple[int, ...]:
    queue: list[tuple[float, int, int]] = [(0.0, 0, start)]
    sequence = count(1)
    previous: dict[int, int] = {}
    cost = {start: 0.0}
    while queue:
        _score, _order, current = heapq.heappop(queue)
        if current == goal:
            path = [current]
            while current in previous:
                current = previous[current]
                path.append(current)
            return tuple(reversed(path))
        for neighbour in adjacency[current]:
            distance = _distance(polygons[current].centroid, polygons[neighbour].centroid)
            candidate = cost[current] + (
                empirical_costs.weighted_edge_cost(distance, current, neighbour, routing_config)
                if empirical_costs is not None
                else distance
            )
            if candidate >= cost.get(neighbour, math.inf):
                continue
            previous[neighbour] = current
            cost[neighbour] = candidate
            priority = candidate + _distance(polygons[neighbour].centroid, polygons[goal].centroid)
            heapq.heappush(queue, (priority, next(sequence), neighbour))
    return ()


def _closest_point(position: WorldPosition, triangle: WorldTriangle) -> WorldPosition:
    # Christer Ericson, *Real-Time Collision Detection*, closest-point-on-triangle region tests.
    point = (position.x, position.y, position.z)
    a, b, c = (
        _vertex_tuple(vertex) for vertex in (triangle.first, triangle.second, triangle.third)
    )
    ab, ac, ap = _subtract(b, a), _subtract(c, a), _subtract(point, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return WorldPosition(*a)
    bp = _subtract(point, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return WorldPosition(*b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        return WorldPosition(*_add(a, _scale(ab, d1 / (d1 - d3))))
    cp = _subtract(point, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return WorldPosition(*c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        return WorldPosition(*_add(a, _scale(ac, d2 / (d2 - d6))))
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
        return WorldPosition(*_add(b, _scale(_subtract(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)))))
    denominator = 1.0 / (va + vb + vc)
    return WorldPosition(*_add(a, _add(_scale(ab, vb * denominator), _scale(ac, vc * denominator))))


def _triangle_key(triangle: WorldTriangle) -> tuple[str, tuple[tuple[float, float, float], ...]]:
    return triangle.source, tuple(
        sorted(_vertex_key(vertex) for vertex in (triangle.first, triangle.second, triangle.third))
    )


def _edge_key(
    first: WorldVertex, second: WorldVertex
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return tuple(sorted((_vertex_key(first), _vertex_key(second))))  # type: ignore[return-value]


def _vertex_key(vertex: WorldVertex) -> tuple[float, float, float]:
    return tuple(round(value, _EDGE_PRECISION) for value in _vertex_tuple(vertex))  # type: ignore[return-value]


def _normal(
    first: WorldVertex, second: WorldVertex, third: WorldVertex
) -> tuple[float, float, float]:
    ab = _subtract(_vertex_tuple(second), _vertex_tuple(first))
    ac = _subtract(_vertex_tuple(third), _vertex_tuple(first))
    return (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )


def _centroid_y(triangle: WorldTriangle) -> float:
    return (triangle.first.y + triangle.second.y + triangle.third.y) / 3.0


def _triangle_centroid(triangle: WorldTriangle) -> WorldPosition:
    return WorldPosition(
        (triangle.first.x + triangle.second.x + triangle.third.x) / 3.0,
        _centroid_y(triangle),
        (triangle.first.z + triangle.second.z + triangle.third.z) / 3.0,
    )


def _height_at_xz(triangle: WorldTriangle, x: float, z: float) -> float | None:
    first, second, third = triangle.first, triangle.second, triangle.third
    determinant = (second.z - third.z) * (first.x - third.x) + (third.x - second.x) * (
        first.z - third.z
    )
    if determinant == 0.0:
        return None
    first_weight = (
        (second.z - third.z) * (x - third.x) + (third.x - second.x) * (z - third.z)
    ) / determinant
    second_weight = (
        (third.z - first.z) * (x - third.x) + (first.x - third.x) * (z - third.z)
    ) / determinant
    third_weight = 1.0 - first_weight - second_weight
    if min(first_weight, second_weight, third_weight) < 0.0:
        return None
    return first_weight * first.y + second_weight * second.y + third_weight * third.y


def _remove_repeated(points: list[WorldPosition]) -> tuple[WorldPosition, ...]:
    result: list[WorldPosition] = []
    for point in points:
        if not result or point != result[-1]:
            result.append(point)
    return tuple(result)


def _distance(first: WorldPosition, second: WorldPosition) -> float:
    return math.dist(_point_tuple(first), _point_tuple(second))


def _distance_vertex(first: WorldVertex, second: WorldVertex) -> float:
    return math.dist(_vertex_tuple(first), _vertex_tuple(second))


def _vertex_tuple(vertex: WorldVertex) -> tuple[float, float, float]:
    return vertex.x, vertex.y, vertex.z


def _point_tuple(point: WorldPosition) -> tuple[float, float, float]:
    return point.x, point.y, point.z


def _point_key(point: WorldPosition) -> tuple[float, float, float]:
    return tuple(round(value, _EDGE_PRECISION) for value in _point_tuple(point))  # type: ignore[return-value]


def _containment_cell(value: float, cell_size_units: float) -> int:
    return math.floor(value / cell_size_units)


def _containment_key(x: float, z: float, cell_size_units: float) -> tuple[int, int]:
    return _containment_cell(x, cell_size_units), _containment_cell(z, cell_size_units)


def _same_xz(first: WorldPosition, second: WorldPosition) -> bool:
    return first.x == second.x and first.z == second.z


def _triarea2(first: WorldPosition, second: WorldPosition, third: WorldPosition) -> float:
    """Return the signed doubled X/Z area used by the two-dimensional funnel."""

    return (second.x - first.x) * (third.z - first.z) - (third.x - first.x) * (second.z - first.z)


def _subtract(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return first[0] - second[0], first[1] - second[1], first[2] - second[2]


def _add(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return first[0] + second[0], first[1] + second[1], first[2] + second[2]


def _scale(value: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return value[0] * factor, value[1] * factor, value[2] * factor


def _dot(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]
