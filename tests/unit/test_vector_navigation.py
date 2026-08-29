"""GPS-only zone navigation over an extracted world vector map (US-053)."""

from __future__ import annotations

import pytest

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshBaker
from flyff_bot.features.navigation.vector_navigation import (
    VectorNavigationRequest,
    VectorZoneNavigator,
    ZoneGoal,
    zone_goals_from_selection,
    zone_locked_goals,
)
from flyff_bot.features.navigation.world_extractor import (
    LAND_BLOCK_VERTICES_PER_SIDE,
    LandBlock,
    VectorSpawnZone,
    WorldDimensions,
    WorldVectorMap,
)
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex

DIMENSIONS = WorldDimensions(blocks_x=2, blocks_z=2, meters_per_unit=4.0)


def _zone(monster_name: str, center: tuple[float, float], monster_id: int) -> VectorSpawnZone:
    x, z = center
    return VectorSpawnZone(
        monster_id=monster_id,
        center_x=x,
        center_y=100.0,
        center_z=z,
        minimum_x=x - 20.0,
        minimum_z=z - 20.0,
        maximum_x=x + 20.0,
        maximum_z=z + 20.0,
        capacity=10,
        respawn_seconds=30,
        monster_name=monster_name,
    )


FLAME_NEAR = _zone("Flame", (100.0, 100.0), 1453)
FLAME_FAR = _zone("Flame", (500.0, 500.0), 1453)
RAPRA_NEAR = _zone("Rapra", (160.0, 100.0), 1458)
WORLD_MAP = WorldVectorMap(
    "wdtest",
    DIMENSIONS,
    (FLAME_NEAR, FLAME_FAR, RAPRA_NEAR),
    terrain_blocks=(
        LandBlock(0, 0, (100.0,) * (LAND_BLOCK_VERTICES_PER_SIDE * LAND_BLOCK_VERTICES_PER_SIDE)),
    ),
)


def _navigator(goals: tuple[ZoneGoal, ...]) -> VectorZoneNavigator:
    return VectorZoneNavigator(WORLD_MAP, goals=goals)


def test_a_navigator_without_goals_is_inactive_and_never_selects_a_zone() -> None:
    navigator = _navigator(())

    assert not navigator.is_active
    assert navigator.select_world_zone(WorldPosition(100.0, 100.0, 100.0)) is None


def test_live_world_position_selects_the_nearest_active_goal_zone_and_stays_sticky() -> None:
    navigator = _navigator((ZoneGoal("Flame"),))

    assert navigator.select_world_zone(WorldPosition(95.0, 100.0, 95.0)) is not None
    assert navigator.active_zone is FLAME_NEAR
    assert navigator.select_world_zone(WorldPosition(500.0, 100.0, 500.0)) is not None
    assert navigator.active_zone is FLAME_NEAR


def test_live_route_waypoints_remain_in_client_world_units() -> None:
    navigator = _navigator((ZoneGoal("Flame"),))

    plan = navigator.plan_live_route(WorldPosition(100.0, 100.0, 100.0))

    assert plan.goal == ZoneGoal("Flame")
    assert plan.zone is FLAME_NEAR
    assert plan.world_waypoints
    assert plan.points
    assert all(80.0 <= point.x <= 120.0 and 80.0 <= point.z <= 120.0 for point in plan.points)


def test_selected_dialog_zone_is_preferred_for_the_initial_patrol() -> None:
    request = VectorNavigationRequest(
        world_map=WORLD_MAP,
        anchor_zone=FLAME_FAR,
        goals=(ZoneGoal("Flame", 5),),
    )

    navigator = request.navigator()
    selection = navigator.select_world_zone(WorldPosition(100.0, 100.0, 100.0))

    assert selection is not None
    assert selection.zone is FLAME_FAR
    assert navigator.goals == (ZoneGoal("Flame", 5),)


def test_completing_a_quota_rebinds_the_next_goal_from_live_gps() -> None:
    navigator = _navigator((ZoneGoal("Flame", 1), ZoneGoal("Rapra", 1)))
    navigator.select_world_zone(WorldPosition(100.0, 100.0, 100.0))

    assert navigator.record_kill("Flame")
    assert navigator.active_goal == ZoneGoal("Rapra", 1)
    assert navigator.active_zone is None
    assert navigator.select_world_zone(WorldPosition(150.0, 100.0, 100.0)) is not None
    assert navigator.active_zone is RAPRA_NEAR


def test_zone_goals_validate_names_quotas_and_lengths() -> None:
    assert zone_goals_from_selection(("Flame", "Rapra")) == (ZoneGoal("Flame"), ZoneGoal("Rapra"))
    with pytest.raises(ValueError):
        ZoneGoal("", 1)
    with pytest.raises(ValueError):
        ZoneGoal("Flame", 0)
    with pytest.raises(ValueError):
        zone_goals_from_selection(("Flame", "Rapra"), (1,))


def _triangle(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> WorldTriangle:
    return WorldTriangle(WorldVertex(*first), WorldVertex(*second), WorldVertex(*third), "fixture")


def _camp_mesh() -> BakedNavMesh:
    """Bake one flat walkable slab covering the Flame camp and its approach."""

    return NavMeshBaker().bake(
        (
            _triangle((60.0, 100.0, 60.0), (140.0, 100.0, 60.0), (140.0, 100.0, 140.0)),
            _triangle((60.0, 100.0, 60.0), (140.0, 100.0, 140.0), (60.0, 100.0, 140.0)),
        )
    )


def test_patrol_legs_are_routed_over_the_baked_collision_mesh() -> None:
    """US-091 AC8: camp patrol and combat approaches read the same walkable polygons."""

    mesh = _camp_mesh()
    navigator = VectorZoneNavigator(WORLD_MAP, goals=(ZoneGoal("Flame"),), navmesh=mesh)

    plan = navigator.plan_live_route(WorldPosition(100.0, 100.0, 100.0))

    assert navigator.navmesh is mesh
    assert plan.world_waypoints
    assert all(mesh.contained_surface(waypoint) is not None for waypoint in plan.world_waypoints)


def test_a_patrol_leg_through_a_recorded_obstacle_is_refused() -> None:
    """US-091 AC9: a node that already stalled the character is routed around, not through."""

    navigator = VectorZoneNavigator(WORLD_MAP, goals=(ZoneGoal("Flame"),), navmesh=_camp_mesh())
    origin = WorldPosition(100.0, 100.0, 100.0)

    open_plan = navigator.plan_live_route(origin)
    blocked_plan = navigator.plan_live_route(
        origin, temporary_blocks=tuple(open_plan.world_waypoints)
    )

    assert open_plan.world_waypoints
    assert blocked_plan.is_empty
    assert blocked_plan.blocked


def test_an_attached_mesh_replaces_the_heightfield_fallback() -> None:
    """US-091: activation hands the navigator the mesh the pathing controller already owns."""

    navigator = VectorZoneNavigator(WORLD_MAP, goals=(ZoneGoal("Flame"),))
    assert navigator.navmesh is None

    mesh = _camp_mesh()
    navigator.attach_navmesh(mesh)

    assert navigator.navmesh is mesh
    assert navigator.plan_live_route(WorldPosition(100.0, 100.0, 100.0)).world_waypoints


def test_activation_locks_the_goals_to_the_selected_camps() -> None:
    """US-091 AC1/AC3: the camp selection is the whole statement of what to farm."""

    request = VectorNavigationRequest(
        world_map=WORLD_MAP,
        anchor_zone=RAPRA_NEAR,
        active_zones=(RAPRA_NEAR,),
        goals=(ZoneGoal("Flame", 5), ZoneGoal("Rapra", 3)),
    )

    navigator = request.navigator()

    assert navigator.goals == (ZoneGoal("Rapra", 3),)
    assert navigator.active_goal == ZoneGoal("Rapra", 3)


def test_zone_locked_goals_follow_the_selection_order_and_keep_matching_quotas() -> None:
    """US-091 AC3: multiple camps are worked through in the order the operator listed them."""

    locked = zone_locked_goals(
        (ZoneGoal("Rapra", 3), ZoneGoal("Mushpang", 9)), (FLAME_NEAR, RAPRA_NEAR)
    )

    assert locked == (ZoneGoal("Flame"), ZoneGoal("Rapra", 3))


def test_an_empty_camp_selection_leaves_the_configured_goals_untouched() -> None:
    """A session without any selected camp still farms whatever the preset stated."""

    goals = (ZoneGoal("Flame", 2),)

    assert zone_locked_goals(goals, ()) == goals
