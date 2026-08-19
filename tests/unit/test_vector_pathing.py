"""Pathing over an extracted world map, and the fallback that survives beside it (US-045)."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest
from minimap_doubles import MirrorOdometer

from flyff_bot.features.automation.controllers import VIRTUAL_KEY_W
from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import FarmingMode, FarmingOrchestrator
from flyff_bot.features.navigation.live_position import (
    LivePositionReader,
    PositionReading,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.pathing import (
    VIRTUAL_KEY_Q,
    VIRTUAL_KEY_S,
    PathingConfig,
    PathingController,
    PathingDecision,
    PathingMode,
)
from flyff_bot.features.navigation.planning import RouteConfig
from flyff_bot.features.navigation.spatial import (
    GridCell,
    SpatialMap,
    SpatialMapConfig,
    WorldPoint,
)
from flyff_bot.features.navigation.teleport import TeleportAnchor, TeleportConfig
from flyff_bot.features.navigation.tracking import MovementModel, StallConfig
from flyff_bot.features.navigation.vector_navigation import (
    VectorZoneNavigator,
    WorldRegistration,
    ZoneGoal,
)
from flyff_bot.features.navigation.vector_routing import VectorRouteConfig
from flyff_bot.features.navigation.world_extractor import (
    LAND_BLOCK_VERTICES_PER_SIDE,
    LandBlock,
    VectorSpawnZone,
    WorldCoordinate,
    WorldDimensions,
    WorldVectorMap,
)
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick

CELL_SIZE_PIXELS = 10.0
MAP_CONFIG = SpatialMapConfig(cell_size_pixels=CELL_SIZE_PIXELS, maximum_link_span_cells=1)
PATHING_CONFIG = PathingConfig(
    step_duration_seconds=0.5,
    turn_duration_seconds=0.25,
    movement=MovementModel(forward_speed_pixels_per_second=10.0, turn_degrees_per_second=90.0),
    stall=StallConfig(motion_threshold=1.0, stall_timeout_seconds=0.1),
    route=RouteConfig(minimum_hotspot_weight=1.0),
)
DIMENSIONS = WorldDimensions(blocks_x=2, blocks_z=2, meters_per_unit=4.0)
VIEWPORT = Viewport(100, 100)
WINDOW_HANDLE = 42


def _zone(monster_name: str, center: tuple[float, float], monster_id: int) -> VectorSpawnZone:
    x, z = center
    return VectorSpawnZone(
        monster_id=monster_id,
        center_x=x,
        center_y=100.0,
        center_z=z,
        minimum_x=x - 30.0,
        minimum_z=z - 30.0,
        maximum_x=x + 30.0,
        maximum_z=z + 30.0,
        capacity=10,
        respawn_seconds=30,
        monster_name=monster_name,
    )


FLAME_ZONE = _zone("Flame", (200.0, 200.0), 1453)
RAPRA_ZONE = _zone("Rapra", (320.0, 200.0), 1458)
WORLD_MAP = WorldVectorMap("wdtest", DIMENSIONS, (FLAME_ZONE, RAPRA_ZONE))
FLAT_BLOCK = LandBlock(
    0,
    0,
    (100.0,) * (LAND_BLOCK_VERTICES_PER_SIDE * LAND_BLOCK_VERTICES_PER_SIDE),
)
TERRAIN_WORLD_MAP = WorldVectorMap(
    "wdtest", DIMENSIONS, (FLAME_ZONE, RAPRA_ZONE), terrain_blocks=(FLAT_BLOCK,)
)


class _LiveReader:
    def __init__(self, positions: list[WorldPosition]) -> None:
        self._positions = iter(positions)
        self._last: WorldPosition | None = None
        self.closed = 0

    def poll(self, _at_seconds: float) -> PositionReading:
        self._last = next(self._positions, self._last)
        return PositionReading(PositionSource.LIVE, self._last)

    def close(self) -> None:
        self.closed += 1


def _state(seconds: float, mobs: tuple[VisibleMob, ...] = ()) -> WorldState:
    return WorldState(
        observed_at_seconds=seconds,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        is_stuck=False,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=VIEWPORT,
    )


def _navigator(goals: tuple[ZoneGoal, ...]) -> VectorZoneNavigator:
    # The session origin is registered onto the Flame zone anchor, so the extracted map and
    # the measured position share an origin and the arithmetic in the assertions stays plain.
    return VectorZoneNavigator(
        WORLD_MAP,
        WorldRegistration.anchored(WorldPoint(0.0, 0.0), FLAME_ZONE.anchor),
        goals=goals,
        route_config=VectorRouteConfig(clearance_units=0.0),
    )


def _controller(
    navigator: VectorZoneNavigator | None, spatial_map: SpatialMap | None = None
) -> PathingController:
    return PathingController(
        spatial_map or SpatialMap(MAP_CONFIG),
        config=PATHING_CONFIG,
        odometer=MirrorOdometer(PATHING_CONFIG.movement),
        vector_navigator=navigator,
    )


def _learned_map() -> SpatialMap:
    """Return a map whose only hotspot lies to the north of the session origin."""

    spatial_map = SpatialMap(MAP_CONFIG)
    for index, cell in enumerate((GridCell(0, 0), GridCell(0, 1), GridCell(0, 2))):
        spatial_map.record_visit(
            WorldPoint((cell.x + 0.5) * CELL_SIZE_PIXELS, (cell.y + 0.5) * CELL_SIZE_PIXELS),
            float(index),
        )
    spatial_map.record_spawn(WorldPoint(5.0, 25.0), 0.0, weight=5.0)
    return spatial_map


def test_an_extracted_map_supplies_the_route_instead_of_the_learned_heatmap() -> None:
    controller = _controller(_navigator((ZoneGoal("Flame"),)), _learned_map())

    decision = controller.step(0.0)

    assert controller.vector_navigation_active
    assert decision.mode is PathingMode.TRAVELING
    # The zone's inset ring is 60 % of its 30-unit half extent, so the sweep stays inside
    # +-18 px of the registered origin - nowhere near the learned hotspot at y = 25.
    assert controller.waypoints
    assert all(abs(point.x) <= 18.0 and abs(point.y) <= 18.0 for point in controller.waypoints)


def test_a_session_without_an_extracted_map_still_plans_over_what_it_learned() -> None:
    controller = _controller(None, _learned_map())

    decision = controller.step(0.0)

    assert not controller.vector_navigation_active
    assert decision.mode is PathingMode.TRAVELING
    # The learned planner walks a circuit out to its hotspot and back to the start cell.
    assert WorldPoint(5.0, 25.0) in controller.waypoints


def test_goals_whose_monsters_have_no_zone_fall_back_to_the_learned_map() -> None:
    """An unmapped region has to keep working, so an inactive navigator changes nothing."""

    controller = _controller(_navigator((ZoneGoal("Oldrut"),)), _learned_map())

    decision = controller.step(0.0)

    assert not controller.vector_navigation_active
    assert decision.mode is PathingMode.TRAVELING
    assert WorldPoint(5.0, 25.0) in controller.waypoints


def test_detaching_the_extracted_map_returns_the_session_to_learned_pathing() -> None:
    controller = _controller(_navigator((ZoneGoal("Flame"),)), _learned_map())
    controller.step(0.0)

    controller.attach_vector_navigator(None)
    decision = controller.step(1.0)

    assert not controller.vector_navigation_active
    assert decision.mode is PathingMode.TRAVELING
    assert WorldPoint(5.0, 25.0) in controller.waypoints


def test_heuristic_spawn_learning_is_bypassed_while_an_extracted_map_is_active() -> None:
    spatial_map = SpatialMap(MAP_CONFIG)
    controller = _controller(_navigator((ZoneGoal("Flame"),)), spatial_map)
    controller.step(0.0)
    mobs = (
        VisibleMob(x=40, y=40, width=20, height=20, confidence=0.9, class_id=0, class_name="Flame"),
    )

    controller.observe(_state(0.0, mobs))

    # The visit is still recorded - it is what the retreat and the stall history read - but
    # no estimated sighting competes with the authoritative zone geometry.
    assert spatial_map.known_cells()
    assert all(
        spatial_map.spawn_weight(cell, 0.0) == pytest.approx(0.0)
        for cell in spatial_map.known_cells()
    )


def test_spawn_learning_continues_when_no_extracted_map_is_active() -> None:
    spatial_map = SpatialMap(MAP_CONFIG)
    controller = _controller(None, spatial_map)
    mobs = (
        VisibleMob(x=40, y=40, width=20, height=20, confidence=0.9, class_id=0, class_name="Flame"),
    )

    controller.observe(_state(0.0, mobs))

    assert any(spatial_map.spawn_weight(cell, 0.0) > 0.0 for cell in spatial_map.known_cells())


def test_a_completed_quota_replans_into_the_next_monsters_zone_without_a_restart() -> None:
    navigator = _navigator((ZoneGoal("Flame", 2), ZoneGoal("Rapra", 1)))
    controller = _controller(navigator)
    controller.step(0.0)

    assert navigator.active_zone is FLAME_ZONE
    assert not controller.record_kill("Flame")
    assert controller.record_kill("Flame")

    # The completed goal dropped the route, so the next step is planned for Rapra.
    abandoned_route = controller.waypoints
    assert abandoned_route == ()
    decision = controller.step(1.0)

    assert decision.mode is PathingMode.TRAVELING
    assert navigator.active_zone is RAPRA_ZONE
    # Rapra's zone sits 120 world units east of the registered origin.
    assert all(point.x >= 100.0 for point in controller.waypoints)


def test_a_kill_without_an_extracted_map_is_simply_not_attributed() -> None:
    controller = _controller(None)

    assert not controller.record_kill("Flame")
    assert not controller.record_kill("")


def test_the_bound_zone_is_published_for_the_dashboard() -> None:
    controller = _controller(_navigator((ZoneGoal("Flame"),)))
    controller.step(0.0)

    zone = controller.snapshot(0.0).vector_zone

    assert zone is not None
    assert zone.monster_name == "Flame"
    assert zone.capacity == 10
    assert (zone.center_x, zone.center_y) == (0.0, 0.0)
    assert zone.half_width_pixels == pytest.approx(30.0)
    assert zone.half_depth_pixels == pytest.approx(30.0)


def test_a_session_without_an_extracted_map_publishes_no_zone() -> None:
    controller = _controller(None, _learned_map())
    controller.step(0.0)

    assert controller.snapshot(0.0).vector_zone is None


def test_the_route_is_planned_in_world_units_and_delivered_in_minimap_pixels() -> None:
    """The registration scale is the only thing between the two frames."""

    navigator = VectorZoneNavigator(
        WORLD_MAP,
        WorldRegistration.anchored(WorldPoint(0.0, 0.0), FLAME_ZONE.anchor, 2.0),
        goals=(ZoneGoal("Flame"),),
        route_config=VectorRouteConfig(clearance_units=0.0),
    )
    controller = _controller(navigator)

    controller.step(0.0)

    # At two pixels per world unit the same +-18 unit ring is drawn at +-36 px.
    assert max(abs(point.x) for point in controller.waypoints) == pytest.approx(36.0)


def test_live_xyz_drives_terrain_route_snapshot_and_emergency_handle_release() -> None:
    reader = _LiveReader([WorldPosition(100.0, 100.0, 100.0)])
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        WorldRegistration(WorldCoordinate(0.0, 0.0)),
        goals=(ZoneGoal("Flame"),),
    )
    controller = PathingController(
        SpatialMap(MAP_CONFIG),
        config=PATHING_CONFIG,
        odometer=MirrorOdometer(PATHING_CONFIG.movement),
        vector_navigator=navigator,
        position_reader=cast("LivePositionReader", reader),
    )

    controller.observe(_state(0.0))
    decision = controller.step(0.0)
    snapshot = controller.snapshot(0.0)

    assert decision.mode is PathingMode.TRAVELING
    assert snapshot.position_source is PositionSource.LIVE
    assert snapshot.world_position == WorldPosition(100.0, 100.0, 100.0)
    assert snapshot.world_waypoints
    assert snapshot.terrain_samples

    controller.emergency_stop()
    assert controller.mode is PathingMode.IDLE
    assert reader.closed == 1


def test_long_range_live_goal_requests_its_configured_teleport_hotkey_once() -> None:
    reader = _LiveReader([WorldPosition(0.0, 100.0, 0.0)])
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        WorldRegistration(WorldCoordinate(0.0, 0.0)),
        goals=(ZoneGoal("Flame"),),
    )
    controller = PathingController(
        SpatialMap(MAP_CONFIG),
        config=PATHING_CONFIG,
        odometer=MirrorOdometer(PATHING_CONFIG.movement),
        vector_navigator=navigator,
        position_reader=cast("LivePositionReader", reader),
        teleport_config=TeleportConfig(
            enabled=True,
            anchors=(TeleportAnchor("Flame", WorldPosition(190.0, 100.0, 190.0), 0x70),),
        ),
    )
    controller.observe(_state(0.0))

    dispatch = controller.step(0.0)
    waiting = controller.step(0.1)

    assert dispatch.mode is PathingMode.TELEPORTING
    assert dispatch.virtual_key == 0x70
    assert waiting == PathingDecision(PathingMode.TELEPORTING)


def test_live_stall_runs_strafe_backstep_tangent_replan_and_repeated_block() -> None:
    stalled_at = WorldPosition(100.0, 100.0, 100.0)
    reader = _LiveReader([stalled_at])
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        WorldRegistration(WorldCoordinate(0.0, 0.0)),
        goals=(ZoneGoal("Flame"),),
    )
    controller = PathingController(
        SpatialMap(MAP_CONFIG),
        config=PATHING_CONFIG,
        odometer=MirrorOdometer(PATHING_CONFIG.movement),
        vector_navigator=navigator,
        position_reader=cast("LivePositionReader", reader),
    )
    controller.observe(_state(0.0))
    for at_seconds in (0.5, 1.0, 1.5, 2.0):
        controller.integrate_movement(VIRTUAL_KEY_W, 0.1)
        controller.observe(_state(at_seconds))

    strafe = controller.step(2.0)
    backstep = controller.step(2.1)
    reroute = controller.step(2.2)

    assert strafe.virtual_key == VIRTUAL_KEY_Q
    assert backstep.virtual_key == VIRTUAL_KEY_S
    assert reroute.mode is PathingMode.TRAVELING
    initial_blocks = controller.temporary_world_blocks
    assert not initial_blocks

    for at_seconds in (2.5, 3.0, 3.5, 4.0, 4.5):
        controller.integrate_movement(VIRTUAL_KEY_W, 0.1)
        controller.observe(_state(at_seconds))

    blocks = controller.temporary_world_blocks
    assert len(blocks) == 1
    assert blocks[0] == stalled_at


def test_an_external_live_combat_obstacle_uses_the_same_evasion_and_blocking() -> None:
    """BUG-017: combat-reported stalls must not bypass live terrain recovery."""

    stalled_at = WorldPosition(100.0, 100.0, 100.0)
    controller = PathingController(
        SpatialMap(MAP_CONFIG),
        config=PATHING_CONFIG,
        position_reader=cast("LivePositionReader", _LiveReader([stalled_at])),
    )
    controller.observe(_state(0.0))

    assert controller.register_obstacle(0.5)
    assert controller.step(0.5).virtual_key == VIRTUAL_KEY_Q
    assert controller.step(0.6).virtual_key == VIRTUAL_KEY_S

    assert controller.register_obstacle(1.0)
    assert controller.temporary_world_blocks == (stalled_at,)


def test_the_registered_frame_maps_the_zone_anchor_onto_the_live_position() -> None:
    navigator = VectorZoneNavigator(
        WORLD_MAP,
        WorldRegistration.anchored(WorldPoint(15.0, -25.0), FLAME_ZONE.anchor),
        goals=(ZoneGoal("Flame"),),
        route_config=VectorRouteConfig(clearance_units=0.0),
    )

    assert navigator.registration.to_session(FLAME_ZONE.anchor) == WorldPoint(15.0, -25.0)
    assert navigator.registration.to_world(WorldPoint(15.0, -25.0)) == WorldCoordinate(
        FLAME_ZONE.anchor.x, FLAME_ZONE.anchor.z
    )


class _Adapter:
    """A guarded-input adapter that records every dispatch instead of sending it."""

    def __init__(self) -> None:
        self.keys: list[tuple[int, float]] = []
        self.clicks: list[tuple[int, int, int]] = []

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, _window_handle: int) -> bool:
        return True

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def close_window(self, _window_handle: int) -> bool:
        return True


class _Pipeline:
    """A perception pipeline that replays a scripted sequence of world states."""

    def __init__(self, states: list[WorldState]) -> None:
        self._states = iter(states)

    def tick(self, _window_handle: int, _previous: WorldState) -> PerceptionTick:
        return PerceptionTick(next(self._states), (), frozenset())


def _engagement_states() -> list[WorldState]:
    """Return one full engagement: sighting, attack, damage, and the empty target bar."""

    mob = VisibleMob(1, "Flame", 0.9, 20, 20, 20, 20)
    return [
        _state(1.0, (mob,)),
        replace(_state(2.0), selected_target=SelectedTarget(TargetState.VALID, "Flame", 100)),
        replace(_state(2.5), selected_target=SelectedTarget(TargetState.VALID, "Flame", 50)),
        replace(_state(3.0), selected_target=SelectedTarget(TargetState.NONE, None, 0)),
    ]


def test_a_confirmed_kill_is_credited_to_the_monster_the_target_bar_named() -> None:
    navigator = _navigator((ZoneGoal("Flame", 1), ZoneGoal("Rapra", 1)))
    controller = _controller(navigator)
    orchestrator = FarmingOrchestrator(
        cast("PerceptionPipeline", _Pipeline(_engagement_states())),
        _Adapter(),
        WINDOW_HANDLE,
        pathing=controller,
    )
    orchestrator.start()

    modes = [orchestrator.tick().mode for _tick in range(4)]

    assert modes[-1] is FarmingMode.RECONCILING
    assert navigator.kills("Flame") == 1
    # The Flame quota is satisfied, so the session is already bound to the next monster.
    assert navigator.active_goal == ZoneGoal("Rapra", 1)


def test_a_session_adopts_and_drops_an_extracted_map_without_restarting() -> None:
    controller = _controller(None)
    orchestrator = FarmingOrchestrator(
        cast("PerceptionPipeline", _Pipeline([])),
        _Adapter(),
        WINDOW_HANDLE,
        pathing=controller,
    )
    navigator = _navigator((ZoneGoal("Flame"),))

    orchestrator.configure_vector_navigation(navigator)
    assert controller.vector_navigation_active

    orchestrator.configure_vector_navigation(None)
    assert not controller.vector_navigation_active
