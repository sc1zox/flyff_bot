"""Visibility-graph A* routing over extracted world obstacles (US-045)."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from flyff_bot.features.navigation.vector_routing import (
    ObstacleField,
    VectorRouteConfig,
    VectorRoutePlanner,
    segment_enters_rectangle,
)
from flyff_bot.features.navigation.world_extractor import (
    ObstacleKind,
    ObstacleRectangle,
    WorldCoordinate,
)

NO_CLEARANCE = VectorRouteConfig(clearance_units=0.0)


def _wall(
    minimum_x: float, minimum_z: float, maximum_x: float, maximum_z: float
) -> ObstacleRectangle:
    return ObstacleRectangle(minimum_x, minimum_z, maximum_x, maximum_z, ObstacleKind.SLOPE)


def _length(points: tuple[WorldCoordinate, ...]) -> float:
    return sum(
        math.hypot(second.x - first.x, second.z - first.z) for first, second in pairwise(points)
    )


def test_an_unobstructed_query_returns_the_straight_line() -> None:
    planner = VectorRoutePlanner((), NO_CLEARANCE)

    route = planner.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(30.0, 40.0))

    assert route.points == (WorldCoordinate(0.0, 0.0), WorldCoordinate(30.0, 40.0))
    assert route.length_units == pytest.approx(50.0)
    assert not route.blocked


def test_a_query_that_needs_no_movement_returns_its_own_position() -> None:
    planner = VectorRoutePlanner((_wall(-10.0, -10.0, 10.0, 10.0),), NO_CLEARANCE)

    route = planner.plan(WorldCoordinate(50.0, 50.0), WorldCoordinate(50.0, 50.0))

    assert route.is_empty
    assert not route.blocked


def test_a_wall_across_the_corridor_is_routed_around_its_nearest_corner() -> None:
    # The wall reaches 60 units west of the straight line and only 10 units east of it.
    planner = VectorRoutePlanner((_wall(-60.0, 40.0, 10.0, 60.0),), NO_CLEARANCE)

    route = planner.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(0.0, 100.0))

    assert not route.blocked
    assert len(route.points) > 2
    # Every bend sits on a corner of the wall, and none of the legs re-enters it.
    for point in route.points[1:-1]:
        assert point.x == pytest.approx(10.0)
        assert point.z in (pytest.approx(40.0), pytest.approx(60.0))
    assert route.length_units > 100.0
    assert route.length_units == pytest.approx(_length(route.points))


def test_the_planner_takes_the_shorter_of_two_available_detours() -> None:
    """A* over the visibility graph is exact, so the cheaper side must always win."""

    eastward = VectorRoutePlanner((_wall(-60.0, 40.0, 10.0, 60.0),), NO_CLEARANCE)
    westward = VectorRoutePlanner((_wall(-10.0, 40.0, 60.0, 60.0),), NO_CLEARANCE)

    start, goal = WorldCoordinate(0.0, 0.0), WorldCoordinate(0.0, 100.0)

    assert all(point.x >= 0.0 for point in eastward.plan(start, goal).points)
    assert all(point.x <= 0.0 for point in westward.plan(start, goal).points)


def test_clearance_pushes_the_route_away_from_the_obstacle_edge() -> None:
    wall = _wall(-60.0, 40.0, 10.0, 60.0)
    tight = VectorRoutePlanner((wall,), NO_CLEARANCE)
    padded = VectorRoutePlanner((wall,), VectorRouteConfig(clearance_units=8.0))

    tight_route = tight.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(0.0, 100.0))
    padded_route = padded.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(0.0, 100.0))

    assert max(point.x for point in tight_route.points) == pytest.approx(10.0)
    assert max(point.x for point in padded_route.points) == pytest.approx(18.0)
    assert padded_route.length_units > tight_route.length_units


def test_an_obstacle_the_character_already_stands_in_never_makes_a_query_unsolvable() -> None:
    """Standing on a steep quad is a place to walk out of, not a reason to refuse to plan."""

    planner = VectorRoutePlanner((_wall(-10.0, -10.0, 10.0, 10.0),), NO_CLEARANCE)

    route = planner.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(0.0, 100.0))

    assert not route.blocked
    assert route.points[-1] == WorldCoordinate(0.0, 100.0)


def test_a_fully_enclosed_goal_is_reported_blocked_rather_than_walked_into() -> None:
    walls = (
        _wall(20.0, 20.0, 80.0, 30.0),
        _wall(20.0, 70.0, 80.0, 80.0),
        _wall(20.0, 20.0, 30.0, 80.0),
        _wall(70.0, 20.0, 80.0, 80.0),
    )
    planner = VectorRoutePlanner(walls, NO_CLEARANCE)

    route = planner.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(50.0, 50.0))

    assert route.blocked
    assert route.points == ()
    assert not planner.is_reachable(WorldCoordinate(0.0, 0.0), WorldCoordinate(50.0, 50.0))


def test_a_corridor_denser_than_the_search_bound_falls_back_instead_of_stalling() -> None:
    walls = tuple(
        _wall(float(index) * 4.0, 40.0, float(index) * 4.0 + 2.0, 60.0) for index in range(40)
    )
    planner = VectorRoutePlanner(walls, VectorRouteConfig(clearance_units=0.0, maximum_obstacles=4))

    route = planner.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(80.0, 100.0))

    assert route.blocked


def test_planning_is_deterministic_for_the_same_query() -> None:
    walls = (_wall(-5.0, 40.0, 30.0, 60.0), _wall(40.0, 10.0, 60.0, 90.0))
    planner = VectorRoutePlanner(walls, NO_CLEARANCE)

    first = planner.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(80.0, 100.0))
    second = planner.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(80.0, 100.0))

    assert first == second


def test_a_segment_along_an_edge_or_across_a_corner_still_counts_as_visible() -> None:
    """Otherwise two corners of the same rectangle could never see each other."""

    rectangle = _wall(0.0, 0.0, 10.0, 10.0)

    assert not segment_enters_rectangle(
        WorldCoordinate(0.0, 0.0), WorldCoordinate(10.0, 0.0), rectangle
    )
    assert not segment_enters_rectangle(
        WorldCoordinate(-5.0, 5.0), WorldCoordinate(5.0, -5.0), rectangle
    )
    assert segment_enters_rectangle(
        WorldCoordinate(-5.0, 5.0), WorldCoordinate(15.0, 5.0), rectangle
    )


def test_a_field_without_obstacles_blocks_nothing() -> None:
    field = ObstacleField(())

    assert len(field) == 0
    assert not field.blocks(WorldCoordinate(0.0, 0.0), WorldCoordinate(100.0, 100.0))


def test_an_obstacle_outside_the_corridor_does_not_affect_the_route() -> None:
    far = _wall(900.0, 900.0, 1000.0, 1000.0)
    planner = VectorRoutePlanner((far,), VectorRouteConfig(clearance_units=0.0))

    route = planner.plan(WorldCoordinate(0.0, 0.0), WorldCoordinate(0.0, 100.0))

    assert planner.obstacle_count == 1
    assert len(route.points) == 2
