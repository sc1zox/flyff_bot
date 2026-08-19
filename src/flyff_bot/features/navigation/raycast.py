"""Chunk-accelerated ray casting against baked walkable surfaces.

Every screen-space observation becomes a world position through this module, so one
Moller-Trumbore implementation decides which surface a ray actually meets.  The horizontal
chunk index keeps a cast proportional to the cells the ray crosses instead of to the size
of the loaded mesh, and walking those cells in order lets a multi-layer hit stop the scan
before it can fall through to occluded ground below a bridge or platform.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from flyff_bot.features.navigation.live_camera import Vector3D
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex

# Below this the ray is parallel to the triangle plane, or the hit lies behind the eye.
RAY_INTERSECTION_EPSILON = 1e-8
# A ray with no movement along one horizontal axis never crosses a cell boundary on it.
NO_CELL_CROSSING = math.inf


@dataclass(frozen=True, slots=True)
class RayHit:
    """One measured intersection between a world ray and a walkable polygon."""

    position: WorldPosition
    polygon_id: int
    ray_distance: float


class NavMeshRayIndex:
    """Index walkable triangles by horizontal cell so a cast scans only crossed chunks."""

    def __init__(
        self, surfaces: tuple[tuple[int, WorldTriangle], ...], cell_size_units: float
    ) -> None:
        if cell_size_units <= 0.0:
            raise ValueError("A navmesh ray index needs a positive cell size.")
        self._cell_size_units = cell_size_units
        cells: dict[tuple[int, int], list[tuple[int, WorldTriangle]]] = defaultdict(list)
        lowest_x = lowest_z = math.inf
        highest_x = highest_z = -math.inf
        for polygon_id, triangle in surfaces:
            vertices = (triangle.first, triangle.second, triangle.third)
            first_x = min(vertex.x for vertex in vertices)
            last_x = max(vertex.x for vertex in vertices)
            first_z = min(vertex.z for vertex in vertices)
            last_z = max(vertex.z for vertex in vertices)
            lowest_x, highest_x = min(lowest_x, first_x), max(highest_x, last_x)
            lowest_z, highest_z = min(lowest_z, first_z), max(highest_z, last_z)
            for cell_x in range(
                self._cell_of(first_x), self._cell_of(last_x) + 1
            ):  # a triangle wider than one cell must answer for every cell it covers
                for cell_z in range(self._cell_of(first_z), self._cell_of(last_z) + 1):
                    cells[(cell_x, cell_z)].append((polygon_id, triangle))
        self._cells = {cell: tuple(surface) for cell, surface in cells.items()}
        self._bounds = None if not surfaces else (lowest_x, lowest_z, highest_x, highest_z)

    def nearest_hit(self, origin: WorldPosition, direction: Vector3D) -> RayHit | None:
        """Return the closest surface ahead of the eye, or ``None`` for a clean miss."""

        if self._bounds is None:
            return None
        lowest_x, lowest_z, highest_x, highest_z = self._bounds
        entry = _slab_entry(origin.x, direction.x, lowest_x, highest_x)
        exit_at = _slab_exit(origin.x, direction.x, lowest_x, highest_x)
        entry = max(entry, _slab_entry(origin.z, direction.z, lowest_z, highest_z))
        exit_at = min(exit_at, _slab_exit(origin.z, direction.z, lowest_z, highest_z))
        if math.isnan(entry) or math.isnan(exit_at) or entry > exit_at:
            return None
        cell_x = self._cell_of(origin.x + direction.x * entry)
        cell_z = self._cell_of(origin.z + direction.z * entry)
        if direction.x == 0.0 and direction.z == 0.0:
            # A perfectly vertical ray stays inside one chunk for its whole length.
            return self._nearest_in_cells(origin, direction, ((cell_x, cell_z),))
        return self._traverse(origin, direction, cell_x, cell_z, entry, exit_at)

    def _traverse(
        self,
        origin: WorldPosition,
        direction: Vector3D,
        cell_x: int,
        cell_z: int,
        entry: float,
        exit_at: float,
    ) -> RayHit | None:
        """Walk crossed chunks in order (Amanatides and Woo) and stop at the first hit."""

        step_x, next_x, span_x = self._axis_traversal(origin.x, direction.x, cell_x, entry)
        step_z, next_z, span_z = self._axis_traversal(origin.z, direction.z, cell_z, entry)
        travelled = entry
        nearest: RayHit | None = None
        while travelled <= exit_at:
            nearest = self._nearest_in_cells(origin, direction, ((cell_x, cell_z),), nearest)
            boundary = min(next_x, next_z)
            if nearest is not None and nearest.ray_distance <= boundary:
                # No later chunk can hold a closer surface, so an elevated deck wins here
                # instead of being replaced by the terrain it occludes.
                return nearest
            travelled = boundary
            if next_x <= next_z:
                cell_x += step_x
                next_x += span_x
            else:
                cell_z += step_z
                next_z += span_z
        return nearest

    def _nearest_in_cells(
        self,
        origin: WorldPosition,
        direction: Vector3D,
        cells: tuple[tuple[int, int], ...],
        nearest: RayHit | None = None,
    ) -> RayHit | None:
        for cell in cells:
            for polygon_id, triangle in self._cells.get(cell, ()):
                distance = ray_triangle_distance(
                    origin, direction, triangle.first, triangle.second, triangle.third
                )
                if distance is None or (nearest is not None and distance >= nearest.ray_distance):
                    continue
                nearest = RayHit(
                    WorldPosition(
                        origin.x + direction.x * distance,
                        origin.y + direction.y * distance,
                        origin.z + direction.z * distance,
                    ),
                    polygon_id,
                    distance,
                )
        return nearest

    def _axis_traversal(
        self, start: float, direction: float, cell: int, entry: float
    ) -> tuple[int, float, float]:
        """Return the step, next boundary distance, and per-cell distance of one axis."""

        if direction == 0.0:
            return 0, NO_CELL_CROSSING, NO_CELL_CROSSING
        step = 1 if direction > 0.0 else -1
        boundary = (cell + (1 if step > 0 else 0)) * self._cell_size_units
        next_boundary = entry + (boundary - (start + direction * entry)) / direction
        return step, next_boundary, abs(self._cell_size_units / direction)

    def _cell_of(self, value: float) -> int:
        return math.floor(value / self._cell_size_units)


def ray_triangle_distance(
    origin: WorldPosition,
    direction: Vector3D,
    first: WorldVertex,
    second: WorldVertex,
    third: WorldVertex,
) -> float | None:
    """Return a positive Moller-Trumbore intersection distance, if one exists."""

    edge_one = (second.x - first.x, second.y - first.y, second.z - first.z)
    edge_two = (third.x - first.x, third.y - first.y, third.z - first.z)
    cross_x = direction.y * edge_two[2] - direction.z * edge_two[1]
    cross_y = direction.z * edge_two[0] - direction.x * edge_two[2]
    cross_z = direction.x * edge_two[1] - direction.y * edge_two[0]
    determinant = edge_one[0] * cross_x + edge_one[1] * cross_y + edge_one[2] * cross_z
    if abs(determinant) <= RAY_INTERSECTION_EPSILON:
        return None
    inverse = 1.0 / determinant
    origin_offset = (origin.x - first.x, origin.y - first.y, origin.z - first.z)
    origin_cross = (
        origin_offset[0] * cross_x + origin_offset[1] * cross_y + origin_offset[2] * cross_z
    )
    u = origin_cross * inverse
    if not 0.0 <= u <= 1.0:
        return None
    cross_x = origin_offset[1] * edge_one[2] - origin_offset[2] * edge_one[1]
    cross_y = origin_offset[2] * edge_one[0] - origin_offset[0] * edge_one[2]
    cross_z = origin_offset[0] * edge_one[1] - origin_offset[1] * edge_one[0]
    v = (direction.x * cross_x + direction.y * cross_y + direction.z * cross_z) * inverse
    if v < 0.0 or u + v > 1.0:
        return None
    distance = (edge_two[0] * cross_x + edge_two[1] * cross_y + edge_two[2] * cross_z) * inverse
    return distance if distance > RAY_INTERSECTION_EPSILON else None


def _slab_entry(start: float, direction: float, lowest: float, highest: float) -> float:
    """Return where the ray enters one axis slab, or NaN when it never does."""

    if direction == 0.0:
        return 0.0 if lowest <= start <= highest else math.nan
    return max(0.0, min((lowest - start) / direction, (highest - start) / direction))


def _slab_exit(start: float, direction: float, lowest: float, highest: float) -> float:
    """Return where the ray leaves one axis slab, or NaN when it never enters it."""

    if direction == 0.0:
        return math.inf if lowest <= start <= highest else math.nan
    return max((lowest - start) / direction, (highest - start) / direction)
