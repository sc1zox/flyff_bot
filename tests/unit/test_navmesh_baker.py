"""Multi-layer surface bake and query tests."""

from __future__ import annotations

from itertools import pairwise

import pytest

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import AgentNavigationConfig, NavMeshBaker
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex


def _triangle(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
    source: str = "fixture",
) -> WorldTriangle:
    return WorldTriangle(WorldVertex(*first), WorldVertex(*second), WorldVertex(*third), source)


def _deck(y: float, source: str) -> tuple[WorldTriangle, WorldTriangle]:
    return (
        _triangle((0.0, y, 0.0), (4.0, y, 0.0), (0.0, y, 4.0), source),
        _triangle((4.0, y, 0.0), (4.0, y, 4.0), (0.0, y, 4.0), source),
    )


def test_multiple_vertical_surfaces_share_one_xz_cell_without_connecting() -> None:
    mesh = NavMeshBaker().bake(_deck(0.0, "ground") + _deck(8.0, "bridge"))

    assert len(mesh.surface_spans) == 1
    assert len(mesh.surface_spans[0].polygon_ids) == 4
    assert not mesh.is_reachable(WorldPosition(2.0, 0.1, 2.0), WorldPosition(2.0, 8.1, 2.0))
    assert mesh.polygon_or_region_id(WorldPosition(2.0, 8.2, 2.0)) is not None


def test_connected_surface_path_is_3d_and_distance_matches_returned_waypoints() -> None:
    triangles = (
        *_deck(0.0, "left"),
        _triangle((4.0, 0.0, 0.0), (8.0, 1.0, 0.0), (4.0, 0.0, 4.0), "ramp"),
        _triangle((8.0, 1.0, 0.0), (8.0, 1.0, 4.0), (4.0, 0.0, 4.0), "ramp"),
    )
    mesh = NavMeshBaker(AgentNavigationConfig(maximum_step_height_units=2.0)).bake(triangles)
    start = WorldPosition(1.0, 0.0, 1.0)
    goal = WorldPosition(7.0, 1.0, 2.0)

    path = mesh.find_path(start, goal)

    assert len(path) >= 2
    assert mesh.is_reachable(start, goal)
    assert mesh.path_distance(start, goal) == pytest.approx(
        sum(
            ((second.x - first.x) ** 2 + (second.y - first.y) ** 2 + (second.z - first.z) ** 2)
            ** 0.5
            for first, second in pairwise(path)
        )
    )


def test_funnel_string_pulling_uses_polygon_portals_instead_of_centroids() -> None:
    triangles = (
        *_deck(0.0, "west"),
        _triangle((4.0, 0.0, 0.0), (8.0, 0.0, 0.0), (4.0, 0.0, 4.0), "east"),
        _triangle((8.0, 0.0, 0.0), (8.0, 0.0, 4.0), (4.0, 0.0, 4.0), "east"),
        _triangle((4.0, 0.0, 4.0), (8.0, 0.0, 4.0), (4.0, 0.0, 8.0), "north"),
        _triangle((8.0, 0.0, 4.0), (8.0, 0.0, 8.0), (4.0, 0.0, 8.0), "north"),
    )
    mesh = NavMeshBaker().bake(triangles)

    path = mesh.find_path(WorldPosition(1.0, 0.0, 1.0), WorldPosition(6.0, 0.0, 6.0))

    assert path[0] == WorldPosition(1.0, 0.0, 1.0)
    assert path[-1] == WorldPosition(6.0, 0.0, 6.0)
    assert len(path) < 5
    assert all(point not in {polygon.centroid for polygon in mesh.polygons} for point in path[1:-1])


def test_agent_radius_and_slope_limits_reject_unsuitable_surfaces() -> None:
    narrow = _triangle((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), "narrow")
    steep = _triangle((0.0, 0.0, 0.0), (4.0, 5.0, 0.0), (0.0, 0.0, 4.0), "steep")
    mesh = NavMeshBaker(AgentNavigationConfig(agent_radius_units=1.0)).bake((narrow, steep))

    assert mesh.polygons == ()
    assert mesh.nearest_walkable_position(WorldPosition(0.0, 0.0, 0.0)) is None


def test_agent_height_removes_a_floor_with_insufficient_vertical_clearance() -> None:
    mesh = NavMeshBaker(AgentNavigationConfig(agent_height_units=2.0)).bake(
        _deck(0.0, "floor") + _deck(1.0, "low-ceiling")
    )

    assert len(mesh.polygons) == 2
    assert all(polygon.triangle.source == "low-ceiling" for polygon in mesh.polygons)
