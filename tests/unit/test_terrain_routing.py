from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from world_fixtures import write_world_directory

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.terrain_routing import (
    TerrainRouteConfig,
    TerrainRoutePlanner,
)
from flyff_bot.features.navigation.world_extractor import (
    LAND_BLOCK_VERTICES_PER_SIDE,
    LandBlock,
    ObstacleKind,
    ObstacleRectangle,
    WorldDimensions,
    WorldVectorMap,
    extract_world,
)


def _map(
    height_at: Callable[[int, int], float],
    obstacles: tuple[ObstacleRectangle, ...] = (),
) -> WorldVectorMap:
    heights = tuple(
        float(height_at(column, row))
        for row in range(LAND_BLOCK_VERTICES_PER_SIDE)
        for column in range(LAND_BLOCK_VERTICES_PER_SIDE)
    )
    return WorldVectorMap(
        "WdTest",
        WorldDimensions(1, 1, 1.0),
        obstacles=obstacles,
        terrain_blocks=(LandBlock(0, 0, heights),),
    )


def test_flat_terrain_uses_the_direct_3d_route() -> None:
    planner = TerrainRoutePlanner(_map(lambda _x, _z: 7.0))

    route = planner.plan(WorldPosition(0.0, 7.0, 0.0), WorldPosition(12.0, 7.0, 12.0))

    assert route.blocked is False
    assert [waypoint.position for waypoint in route.waypoints] == [
        WorldPosition(0.0, 7.0, 0.0),
        WorldPosition(12.0, 7.0, 12.0),
    ]


def test_gradient_over_one_is_not_walkable() -> None:
    terrain = _map(lambda x, _z: 0.0 if x < 2 else 10.0)
    planner = TerrainRoutePlanner(terrain, TerrainRouteConfig(grid_stride=2))

    route = planner.plan(WorldPosition(0.0, 0.0, 4.0), WorldPosition(4.0, 10.0, 4.0))

    assert route.blocked is True


def test_route_rounds_an_obstacle_and_carries_lateral_strafe_metadata() -> None:
    obstacle = ObstacleRectangle(4.0, 2.0, 8.0, 10.0, ObstacleKind.OBJECT)
    planner = TerrainRoutePlanner(_map(lambda _x, _z: 0.0, (obstacle,)))

    route = planner.plan(WorldPosition(2.0, 0.0, 6.0), WorldPosition(10.0, 0.0, 6.0))

    assert route.blocked is False
    assert len(route.waypoints) >= 3
    assert any(abs(waypoint.strafe_angle_degrees) == 90.0 for waypoint in route.waypoints)


def test_temporary_world_coordinate_is_excluded_from_a_replan() -> None:
    planner = TerrainRoutePlanner(
        _map(lambda _x, _z: 0.0),
        TerrainRouteConfig(grid_stride=2, temporary_block_radius_units=2.1),
    )

    route = planner.plan(
        WorldPosition(0.0, 0.0, 4.0),
        WorldPosition(8.0, 0.0, 4.0),
        temporary_blocks=(WorldPosition(4.0, 0.0, 4.0),),
    )

    assert route.blocked is False
    assert all(
        waypoint.position.distance_to(WorldPosition(4.0, 0.0, 4.0)) > 2.1
        for waypoint in route.waypoints
    )


def test_diagonal_route_cannot_cut_through_an_obstacle_corner() -> None:
    obstacle = ObstacleRectangle(2.0, 0.0, 4.0, 2.0, ObstacleKind.OBJECT)
    planner = TerrainRoutePlanner(
        _map(lambda _x, _z: 0.0, (obstacle,)),
        TerrainRouteConfig(grid_stride=2),
    )

    route = planner.plan(WorldPosition(0.0, 0.0, 0.0), WorldPosition(4.0, 0.0, 4.0))

    assert route.blocked is False
    assert len(route.waypoints) >= 3


def _extracted_archive_map(tmp_path: Path, ridge_height: float) -> WorldVectorMap:
    """Extract a region whose whole height field lives only inside its packed archive."""

    plateau = [
        ridge_height if column >= LAND_BLOCK_VERTICES_PER_SIDE // 2 else 0.0
        for _row in range(LAND_BLOCK_VERTICES_PER_SIDE)
        for column in range(LAND_BLOCK_VERTICES_PER_SIDE)
    ]
    directory = write_world_directory(
        tmp_path,
        "wdtest",
        archived_blocks=[
            (block_x, block_z, plateau) for block_x in range(2) for block_z in range(2)
        ],
    )
    return extract_world(directory)


def test_a_route_over_a_packed_block_follows_its_archived_heights(tmp_path: Path) -> None:
    """Before US-052 only block 0,0 could be loose, so a far block had no elevation at all."""

    planner = TerrainRoutePlanner(_extracted_archive_map(tmp_path, 12.0))

    route = planner.plan(WorldPosition(800.0, 12.0, 600.0), WorldPosition(880.0, 12.0, 680.0))

    assert route.blocked is False
    assert [waypoint.position.y for waypoint in route.waypoints] == [12.0] * len(route.waypoints)


def test_a_cliff_that_exists_only_in_the_packed_archive_blocks_the_route(
    tmp_path: Path,
) -> None:
    planner = TerrainRoutePlanner(
        _extracted_archive_map(tmp_path, 400.0), TerrainRouteConfig(grid_stride=2)
    )

    route = planner.plan(WorldPosition(760.0, 0.0, 600.0), WorldPosition(800.0, 400.0, 600.0))

    assert route.blocked is True
