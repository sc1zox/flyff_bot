"""Read-only camera-to-NavMesh geometry used by target-decision telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, dist, sqrt

from flyff_bot.features.navigation.live_camera import CameraState, unproject_screen_ray
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshPolygon
from flyff_bot.features.navigation.world_geometry import WorldVertex

RAY_INTERSECTION_EPSILON = 1e-8


@dataclass(frozen=True, slots=True)
class ProjectedCandidate:
    """One measured bottom-centre ray hit on the loaded walkable NavMesh."""

    position: WorldPosition
    polygon_id: int
    relative_distance: float
    relative_elevation: float
    path_distance: float | None


def project_candidate(
    *,
    camera: CameraState | None,
    navmesh: BakedNavMesh | None,
    player_position: WorldPosition | None,
    viewport_width: int,
    viewport_height: int,
    screen_x: float,
    screen_bottom_y: float,
) -> ProjectedCandidate | None:
    """Raycast a detector's bottom-centre against a loaded NavMesh, or return no estimate.

    A missing camera, mesh, player GPS, or ray hit intentionally has no numerical fallback:
    screen-space measurements must never be represented as client-world coordinates.
    """

    if (
        camera is None
        or navmesh is None
        or player_position is None
        or viewport_width <= 0
        or viewport_height <= 0
        or not 0.0 <= screen_x <= viewport_width
        or not 0.0 <= screen_bottom_y <= viewport_height
    ):
        return None
    try:
        ray = unproject_screen_ray(
            screen_x, screen_bottom_y, viewport_width, viewport_height, camera
        )
    except ValueError:
        return None
    hit = _nearest_hit(navmesh, ray.origin, ray.direction.x, ray.direction.y, ray.direction.z)
    if hit is None:
        return None
    polygon, position = hit
    return ProjectedCandidate(
        position=position,
        polygon_id=polygon.polygon_id,
        relative_distance=dist(
            (player_position.x, player_position.y, player_position.z),
            (position.x, position.y, position.z),
        ),
        relative_elevation=position.y - player_position.y,
        path_distance=navmesh.path_distance(player_position, position),
    )


def navmesh_slope(navmesh: BakedNavMesh | None, position: WorldPosition | None) -> float | None:
    """Return the local walkable-surface slope in radians for a measured player position."""

    if navmesh is None or position is None:
        return None
    polygon_id = navmesh.polygon_or_region_id(position)
    if polygon_id is None:
        return None
    polygon = next((item for item in navmesh.polygons if item.polygon_id == polygon_id), None)
    if polygon is None:
        return None
    first, second, third = polygon.triangle.first, polygon.triangle.second, polygon.triangle.third
    normal_x, normal_y, normal_z = _normal(first, second, third)
    horizontal = sqrt(normal_x**2 + normal_z**2)
    if normal_y == 0.0:
        return None
    return atan2(horizontal, abs(normal_y))


def _nearest_hit(
    navmesh: BakedNavMesh,
    origin: WorldPosition,
    direction_x: float,
    direction_y: float,
    direction_z: float,
) -> tuple[NavMeshPolygon, WorldPosition] | None:
    nearest: tuple[float, NavMeshPolygon, WorldPosition] | None = None
    for polygon in navmesh.polygons:
        hit_distance = _ray_triangle_distance(
            origin,
            direction_x,
            direction_y,
            direction_z,
            polygon.triangle.first,
            polygon.triangle.second,
            polygon.triangle.third,
        )
        if hit_distance is None or (nearest is not None and hit_distance >= nearest[0]):
            continue
        nearest = (
            hit_distance,
            polygon,
            WorldPosition(
                origin.x + direction_x * hit_distance,
                origin.y + direction_y * hit_distance,
                origin.z + direction_z * hit_distance,
            ),
        )
    return None if nearest is None else (nearest[1], nearest[2])


def _ray_triangle_distance(
    origin: WorldPosition,
    direction_x: float,
    direction_y: float,
    direction_z: float,
    first: WorldVertex,
    second: WorldVertex,
    third: WorldVertex,
) -> float | None:
    """Return a positive Moller-Trumbore intersection distance, if one exists."""

    edge_one = (second.x - first.x, second.y - first.y, second.z - first.z)
    edge_two = (third.x - first.x, third.y - first.y, third.z - first.z)
    cross_x = direction_y * edge_two[2] - direction_z * edge_two[1]
    cross_y = direction_z * edge_two[0] - direction_x * edge_two[2]
    cross_z = direction_x * edge_two[1] - direction_y * edge_two[0]
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
    v = (direction_x * cross_x + direction_y * cross_y + direction_z * cross_z) * inverse
    if v < 0.0 or u + v > 1.0:
        return None
    distance = (edge_two[0] * cross_x + edge_two[1] * cross_y + edge_two[2] * cross_z) * inverse
    return distance if distance > RAY_INTERSECTION_EPSILON else None


def _normal(
    first: WorldVertex, second: WorldVertex, third: WorldVertex
) -> tuple[float, float, float]:
    edge_one = (second.x - first.x, second.y - first.y, second.z - first.z)
    edge_two = (third.x - first.x, third.y - first.y, third.z - first.z)
    return (
        edge_one[1] * edge_two[2] - edge_one[2] * edge_two[1],
        edge_one[2] * edge_two[0] - edge_one[0] * edge_two[2],
        edge_one[0] * edge_two[1] - edge_one[1] * edge_two[0],
    )
