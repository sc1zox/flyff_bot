"""Read-only camera-to-NavMesh geometry used by target-decision telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, dist, sqrt

from flyff_bot.features.navigation.live_camera import CameraState, unproject_screen_ray
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh
from flyff_bot.features.navigation.world_geometry import WorldVertex


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
    hit = navmesh.raycast(ray.origin, ray.direction)
    if hit is None:
        return None
    position = hit.position
    return ProjectedCandidate(
        position=position,
        polygon_id=hit.polygon_id,
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
