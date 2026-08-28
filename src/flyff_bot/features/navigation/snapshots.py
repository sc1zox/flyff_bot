"""Immutable navigation views the session publishes to whatever renders it.

These value objects are produced by `PathingController`, so they belong to the navigation
feature rather than to the dashboard that happens to draw them. Keeping them here is what
lets navigation stay free of any UI import, which the inward dependency rule requires.
"""

from __future__ import annotations

from dataclasses import dataclass

from flyff_bot.features.navigation.live_camera import CameraReadErrorCode, CameraState
from flyff_bot.features.navigation.live_position import (
    PositionReadErrorCode,
    PositionSource,
    WorldPosition,
)


@dataclass(frozen=True, slots=True)
class VectorZoneSnapshot:
    """Immutable view of the extracted spawn zone the session is currently bound to."""

    monster_name: str
    center_x: float
    center_y: float
    half_width_pixels: float
    half_depth_pixels: float
    capacity: int


@dataclass(frozen=True, slots=True)
class NavMeshMobSnapshot:
    """Read-only 3D candidate diagnostic projected onto the inspector's X/Z plane."""

    world_x: float
    world_z: float
    reachable: bool | None
    locked_out: bool = False
    selected: bool = False


@dataclass(frozen=True, slots=True)
class NavigationSnapshot:
    """Immutable view of authoritative 3D GPS, NavMesh, and active vector route."""

    player_x: float
    player_y: float
    heading_degrees: float
    waypoints: tuple[tuple[float, float], ...] = ()
    vector_zone: VectorZoneSnapshot | None = None
    vector_zones: tuple[VectorZoneSnapshot, ...] = ()
    position_source: PositionSource = PositionSource.UNAVAILABLE
    position_error_code: PositionReadErrorCode | None = None
    world_position: WorldPosition | None = None
    camera_state: CameraState | None = None
    camera_error_code: CameraReadErrorCode | None = None
    world_waypoints: tuple[WorldPosition, ...] = ()
    terrain_samples: tuple[tuple[float, float, float], ...] = ()
    navmesh_mobs: tuple[NavMeshMobSnapshot, ...] = ()
    navigation_trajectory: tuple[WorldPosition, ...] = ()
