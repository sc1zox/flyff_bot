"""Goal-driven zone navigation over an extracted world vector map (US-045)."""

from __future__ import annotations

import pytest

from flyff_bot.features.navigation.spatial import WorldPoint
from flyff_bot.features.navigation.vector_navigation import (
    PROVISIONAL_MINIMAP_PIXELS_PER_WORLD_UNIT,
    VectorNavigationRequest,
    VectorZoneNavigator,
    WorldRegistration,
    ZoneGoal,
    zone_goals_from_selection,
)
from flyff_bot.features.navigation.vector_routing import VectorRouteConfig
from flyff_bot.features.navigation.world_extractor import (
    ObstacleKind,
    ObstacleRectangle,
    VectorSpawnZone,
    WorldCoordinate,
    WorldDimensions,
    WorldVectorMap,
)

DIMENSIONS = WorldDimensions(blocks_x=2, blocks_z=2, meters_per_unit=4.0)
NO_CLEARANCE = VectorRouteConfig(clearance_units=0.0)


def _zone(
    monster_name: str,
    center: tuple[float, float],
    half_extent: float = 20.0,
    capacity: int = 10,
    monster_id: int = 1453,
) -> VectorSpawnZone:
    x, z = center
    return VectorSpawnZone(
        monster_id=monster_id,
        center_x=x,
        center_y=100.0,
        center_z=z,
        minimum_x=x - half_extent,
        minimum_z=z - half_extent,
        maximum_x=x + half_extent,
        maximum_z=z + half_extent,
        capacity=capacity,
        respawn_seconds=30,
        monster_name=monster_name,
    )


FLAME_NEAR = _zone("Flame", (100.0, 100.0))
FLAME_FAR = _zone("Flame", (500.0, 500.0), capacity=30)
RAPRA_NEAR = _zone("Rapra", (160.0, 100.0), monster_id=1458)
RAPRA_FAR = _zone("Rapra", (700.0, 700.0), monster_id=1458, capacity=30)

WORLD_MAP = WorldVectorMap("wdtest", DIMENSIONS, (FLAME_NEAR, FLAME_FAR, RAPRA_NEAR, RAPRA_FAR))


# Registering the session origin onto the near Flame zone's centre keeps the arithmetic in
# every assertion plain: a world coordinate and its session pixel differ only by that offset.
REGISTRATION_ORIGIN = WorldCoordinate(100.0, 100.0)


def _navigator(
    world_map: WorldVectorMap = WORLD_MAP,
    goals: tuple[ZoneGoal, ...] = (),
    origin: WorldCoordinate | None = None,
) -> VectorZoneNavigator:
    return VectorZoneNavigator(
        world_map,
        WorldRegistration(origin or REGISTRATION_ORIGIN),
        goals=goals,
        route_config=NO_CLEARANCE,
    )


def test_the_registration_round_trips_between_world_units_and_session_pixels() -> None:
    registration = WorldRegistration(WorldCoordinate(1000.0, 2000.0), 2.0)

    session = registration.to_session(WorldCoordinate(1050.0, 2100.0))

    assert session == WorldPoint(100.0, 200.0)
    assert registration.to_world(session) == WorldCoordinate(1050.0, 2100.0)
    assert registration.to_session_distance(10.0) == pytest.approx(20.0)


def test_anchoring_puts_the_measured_position_at_the_stated_world_position() -> None:
    """The operator names the zone they stand in; the live estimate becomes its anchor."""

    measured = WorldPoint(-40.0, 75.0)

    registration = WorldRegistration.anchored(measured, WorldCoordinate(1234.0, 5678.0))

    assert registration.to_world(measured) == WorldCoordinate(1234.0, 5678.0)
    assert registration.pixels_per_world_unit == pytest.approx(
        PROVISIONAL_MINIMAP_PIXELS_PER_WORLD_UNIT
    )


def test_a_navigator_without_goals_is_inactive_and_plans_nothing() -> None:
    navigator = _navigator()

    assert not navigator.is_active
    assert navigator.active_goal is None
    assert navigator.plan_route(WorldPoint(0.0, 0.0)).is_empty


def test_a_goal_whose_monster_has_no_extracted_zone_leaves_the_navigator_inactive() -> None:
    navigator = _navigator(goals=(ZoneGoal("Oldrut"),))

    assert navigator.active_goal == ZoneGoal("Oldrut")
    assert not navigator.is_active


def test_the_nearest_zone_of_the_active_goal_becomes_the_patrol_boundary() -> None:
    navigator = _navigator(goals=(ZoneGoal("Flame"),))

    selection = navigator.select_zone(WorldPoint(0.0, 0.0))

    assert selection is not None
    assert selection.zone is FLAME_NEAR
    assert navigator.active_zone is FLAME_NEAR


def test_the_zone_selection_is_sticky_so_drifting_never_abandons_a_route() -> None:
    navigator = _navigator(goals=(ZoneGoal("Flame"),))
    navigator.select_zone(WorldPoint(0.0, 0.0))

    # Standing right on top of the far zone must not re-bind mid-route.
    assert navigator.select_zone(WorldPoint(400.0, 400.0)) is not None
    assert navigator.active_zone is FLAME_NEAR


def test_a_completed_quota_hands_the_session_to_the_next_unfinished_monster() -> None:
    navigator = _navigator(goals=(ZoneGoal("Flame", 2), ZoneGoal("Rapra", 3)))
    navigator.select_zone(WorldPoint(0.0, 0.0))

    assert navigator.active_zone is FLAME_NEAR
    assert not navigator.record_kill("Flame")
    assert navigator.record_kill("Flame")

    assert navigator.kills("Flame") == 2
    assert navigator.active_goal == ZoneGoal("Rapra", 3)
    assert navigator.active_zone is None

    navigator.select_zone(WorldPoint(0.0, 0.0))

    assert navigator.active_zone is RAPRA_NEAR
    assert navigator.is_active


def test_a_goal_without_a_quota_never_completes() -> None:
    navigator = _navigator(goals=(ZoneGoal("Flame"), ZoneGoal("Rapra")))

    for _kill in range(50):
        assert not navigator.record_kill("Flame")

    assert navigator.active_goal == ZoneGoal("Flame")


def test_all_quotas_finished_leaves_no_active_goal() -> None:
    navigator = _navigator(goals=(ZoneGoal("Flame", 1), ZoneGoal("Rapra", 1)))

    navigator.record_kill("Flame")
    navigator.record_kill("Rapra")

    assert navigator.active_goal is None
    assert not navigator.is_active


def test_replacing_the_goals_drops_the_zone_bound_to_the_previous_one() -> None:
    navigator = _navigator(goals=(ZoneGoal("Flame"),))
    navigator.select_zone(WorldPoint(0.0, 0.0))

    navigator.set_goals((ZoneGoal("Rapra"),))

    assert navigator.active_zone is None
    assert navigator.select_zone(WorldPoint(0.0, 0.0)) is not None
    assert navigator.active_zone is RAPRA_NEAR


def test_a_planned_route_sweeps_the_zone_and_is_returned_in_session_pixels() -> None:
    # The registration origin is the near Flame zone's centre, so its anchor is the session
    # origin and every returned waypoint is a small offset around it.
    navigator = _navigator(goals=(ZoneGoal("Flame"),))

    plan = navigator.plan_route(WorldPoint(-60.0, 0.0))

    assert plan.goal == ZoneGoal("Flame")
    assert plan.zone is FLAME_NEAR
    assert not plan.blocked
    assert len(plan.points) >= 4
    # The inset ring is 60 % of the zone's 20-unit half extent, so nothing leaves +-12 px.
    assert all(abs(point.x) <= 12.0 and abs(point.y) <= 12.0 for point in plan.points)


def test_the_sweep_starts_at_the_station_nearest_the_character() -> None:
    navigator = _navigator(goals=(ZoneGoal("Flame"),))

    plan = navigator.plan_route(WorldPoint(-100.0, -100.0))

    assert plan.points[0] == WorldPoint(-12.0, -12.0)


def test_a_zone_too_small_to_ring_is_swept_from_its_anchor_alone() -> None:
    tiny = _zone("Flame", (100.0, 100.0), half_extent=2.0)
    navigator = _navigator(WorldVectorMap("wdtest", DIMENSIONS, (tiny,)), (ZoneGoal("Flame"),))

    plan = navigator.plan_route(WorldPoint(-50.0, 0.0))

    assert plan.points == (WorldPoint(0.0, 0.0),)


def test_a_zone_walled_off_from_the_character_is_reported_blocked() -> None:
    walls = tuple(
        ObstacleRectangle(*bounds, ObstacleKind.SLOPE)
        for bounds in (
            (60.0, 60.0, 140.0, 70.0),
            (60.0, 130.0, 140.0, 140.0),
            (60.0, 60.0, 70.0, 140.0),
            (130.0, 60.0, 140.0, 140.0),
        )
    )
    world_map = WorldVectorMap("wdtest", DIMENSIONS, (FLAME_NEAR,), walls)
    navigator = _navigator(world_map, (ZoneGoal("Flame"),))

    plan = navigator.plan_route(WorldPoint(-100.0, -100.0))

    assert plan.blocked
    assert plan.is_empty


def test_the_navigator_reports_whether_the_character_stands_inside_its_zone() -> None:
    navigator = _navigator(goals=(ZoneGoal("Flame"),))
    navigator.select_zone(WorldPoint(0.0, 0.0))

    assert navigator.zone_contains(WorldPoint(10.0, -10.0))
    assert not navigator.zone_contains(WorldPoint(60.0, 0.0))


def test_a_request_builds_its_navigator_against_the_position_it_is_applied_at() -> None:
    request = VectorNavigationRequest(
        world_map=WORLD_MAP,
        anchor_zone=FLAME_NEAR,
        goals=(ZoneGoal("Flame", 5),),
        pixels_per_world_unit=2.0,
        route_config=NO_CLEARANCE,
    )

    navigator = request.navigator(WorldPoint(30.0, -10.0))

    assert navigator.registration.to_world(WorldPoint(30.0, -10.0)) == FLAME_NEAR.anchor
    assert navigator.registration.pixels_per_world_unit == pytest.approx(2.0)
    assert navigator.goals == (ZoneGoal("Flame", 5),)


def test_goals_are_built_from_a_monster_selection_and_its_quotas() -> None:
    assert zone_goals_from_selection(("Flame", "Rapra")) == (
        ZoneGoal("Flame"),
        ZoneGoal("Rapra"),
    )
    assert zone_goals_from_selection(("Flame",), (5,)) == (ZoneGoal("Flame", 5),)

    with pytest.raises(ValueError):
        zone_goals_from_selection(("Flame", "Rapra"), (5,))


def test_a_zone_goal_rejects_an_empty_monster_or_a_non_positive_quota() -> None:
    with pytest.raises(ValueError):
        ZoneGoal("   ")
    with pytest.raises(ValueError):
        ZoneGoal("Flame", 0)


def test_a_registration_rejects_a_non_positive_scale() -> None:
    with pytest.raises(ValueError):
        WorldRegistration(WorldCoordinate(0.0, 0.0), 0.0)
    with pytest.raises(ValueError):
        WorldRegistration.anchored(WorldPoint(0.0, 0.0), WorldCoordinate(0.0, 0.0), -1.0)
