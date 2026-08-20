"""Unit coverage for active Funnel target-approach state."""

from __future__ import annotations

from flyff_bot.features.automation.models import VisibleMob
from flyff_bot.features.navigation.live_camera import CameraState
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import NavMeshBaker
from flyff_bot.features.navigation.pathing import PathingController, PathingMode
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex


def _triangle(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> WorldTriangle:
    return WorldTriangle(WorldVertex(*first), WorldVertex(*second), WorldVertex(*third), "fixture")


def test_target_approach_follows_funnel_route_and_stops_at_engagement_range() -> None:
    mesh = NavMeshBaker().bake(
        (
            _triangle((0, 0, 0), (10, 0, 0), (0, 0, 10)),
            _triangle((10, 0, 0), (10, 0, 10), (0, 0, 10)),
        )
    )
    from flyff_bot.features.navigation.live_position import PositionSource

    pathing = PathingController(navmesh=mesh)
    pathing._live_position = WorldPosition(1.0, 0.0, 1.0)
    pathing._position_source = PositionSource.LIVE
    pathing._camera_state = CameraState(
        pitch_radians=0.0, yaw_radians=0.0, vertical_fov_radians=1.0
    )
    target = VisibleMob(
        1,
        "Flame",
        0.9,
        50,
        50,
        10,
        10,
        world_x=8.0,
        world_y=0.0,
        world_z=8.0,
        navmesh_polygon_id=1,
        navmesh_path_distance=10.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )

    assert pathing.begin_target_approach(target, 1.0)
    assert pathing.world_waypoints
    assert pathing.step(1.1).mode is PathingMode.TRAVELING

    pathing._live_position = WorldPosition(8.0, 0.0, 8.0)
    assert pathing.target_in_engagement_range()
