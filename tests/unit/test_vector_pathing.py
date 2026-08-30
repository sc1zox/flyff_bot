"""Tests for pure 3D GPS vector navigation and pathing (US-045, US-059)."""

from __future__ import annotations

import math
from typing import cast

import pytest

from flyff_bot.features.automation.controllers import (
    SearchConfig,
)
from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import (
    FarmingConfig,
    FarmingInputAdapter,
    FarmingMode,
    FarmingOrchestrator,
)
from flyff_bot.features.diagnostics import SessionEventKind, SessionEventLogger
from flyff_bot.features.input_control.keymap import VIRTUAL_KEY_W
from flyff_bot.features.navigation.live_camera import (
    CameraReading,
    CameraState,
    LiveCameraReader,
)
from flyff_bot.features.navigation.live_position import (
    LivePositionReader,
    PositionReadError,
    PositionReadErrorCode,
    PositionReading,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshBaker
from flyff_bot.features.navigation.pathing import (
    PathingConfig,
    PathingController,
    PathingDecision,
    PathingMode,
)
from flyff_bot.features.navigation.stall_recovery import RecoveryEventKind
from flyff_bot.features.navigation.tracking import StallConfig
from flyff_bot.features.navigation.vector_navigation import (
    VectorZoneNavigator,
    ZoneGoal,
)
from flyff_bot.features.navigation.world_extractor import (
    LAND_BLOCK_VERTICES_PER_SIDE,
    LandBlock,
    VectorSpawnZone,
    WorldDimensions,
    WorldVectorMap,
)
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick

PATHING_CONFIG = PathingConfig(
    step_duration_seconds=0.5,
    turn_duration_seconds=0.25,
    stall=StallConfig(live_motion_threshold_units_per_second=1.0, live_stall_timeout_seconds=2.0),
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

    def poll(self, at_seconds: float) -> PositionReading:
        self._last = next(self._positions, self._last)
        return PositionReading(PositionSource.LIVE, self._last, sampled_at_seconds=at_seconds)

    def close(self) -> None:
        self.closed += 1


class _CameraReader:
    """Yield one distinct yaw per poll so a suppressed poll is observable."""

    def __init__(self, yaw_radians: list[float]) -> None:
        self._yaw_radians = iter(yaw_radians)
        self._last = 0.0
        self.polls = 0

    def poll(self, at_seconds: float) -> CameraReading:
        self.polls += 1
        self._last = next(self._yaw_radians, self._last)
        return CameraReading(CameraState(yaw_radians=self._last), sampled_at_seconds=at_seconds)

    def close(self) -> None:
        return None


class _WaypointWalker:
    """Report the character as standing on the route's next station on every poll.

    A camp patrol is only exhausted once its stations are actually reached, so the walk has
    to be modelled: a fixed position would keep the first leg pending forever.
    """

    def __init__(self, start: WorldPosition) -> None:
        self.controller: PathingController | None = None
        self._position = start

    def poll(self, at_seconds: float) -> PositionReading:
        controller = self.controller
        if controller is not None and controller.waypoints:
            station = controller.waypoints[0]
            self._position = WorldPosition(station.x, self._position.y, station.z)
        return PositionReading(PositionSource.LIVE, self._position, sampled_at_seconds=at_seconds)

    def close(self) -> None:
        return None


class _LossReader(_LiveReader):
    def __init__(self) -> None:
        super().__init__([WorldPosition(100.0, 100.0, 100.0)])
        self._polls = 0

    def poll(self, at_seconds: float) -> PositionReading:
        self._polls += 1
        if self._polls == 1:
            return super().poll(at_seconds)
        return PositionReading(
            PositionSource.UNAVAILABLE,
            error=PositionReadError(PositionReadErrorCode.WINDOW_NOT_FOREGROUND),
        )


def _state(seconds: float, mobs: tuple[VisibleMob, ...] = ()) -> WorldState:
    return WorldState(
        observed_at_seconds=seconds,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        progress_marker=0,
        is_stuck=False,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=VIEWPORT,
    )


def _wide_mesh() -> BakedNavMesh:
    """Bake one flat walkable slab spanning every fixture camp and its approaches.

    US-093 removed the 2D heightfield fallback, so a navigator only routes when it has a
    baked mesh; this slab keeps the pure routing tests exercising the real Funnel pipeline.
    """

    def corner(x: float, z: float) -> WorldVertex:
        return WorldVertex(x, 100.0, z)

    return NavMeshBaker().bake(
        (
            WorldTriangle(corner(-50.0, -50.0), corner(420.0, -50.0), corner(420.0, 300.0), "fx"),
            WorldTriangle(corner(-50.0, -50.0), corner(420.0, 300.0), corner(-50.0, 300.0), "fx"),
        )
    )


WIDE_MESH = _wide_mesh()


def _navigator(goals: tuple[ZoneGoal, ...]) -> VectorZoneNavigator:
    return VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        goals=goals,
        navmesh=WIDE_MESH,
    )


def _controller(
    navigator: VectorZoneNavigator | None,
    positions: list[WorldPosition] | None = None,
) -> PathingController:
    pos_list = positions or [WorldPosition(100.0, 100.0, 100.0)]
    return PathingController(
        config=PATHING_CONFIG,
        vector_navigator=navigator,
        position_reader=cast("LivePositionReader", _LiveReader(pos_list)),
    )


def test_vector_navigation_routes_via_gps_to_goal_zone() -> None:
    controller = _controller(_navigator((ZoneGoal("Flame"),)))
    controller.observe(_state(0.0))

    decision = controller.step(0.0)

    assert controller.vector_navigation_active
    assert decision.mode is PathingMode.TRAVELING
    assert controller.waypoints
    assert any(point.x >= 180.0 and point.z >= 180.0 for point in controller.waypoints)


def test_vector_navigation_without_gps_is_blocked() -> None:
    # "Kein GPS, kein Bot"
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        position_reader=None,
    )
    decision = controller.step(0.0)

    assert decision == PathingDecision(PathingMode.BLOCKED)
    assert not controller.is_gps_available
    assert controller.waypoints == ()


def test_losing_live_gps_immediately_blocks_controller() -> None:
    reader = _LossReader()
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        position_reader=cast("LivePositionReader", reader),
    )

    controller.observe(_state(0.0))
    assert controller.step(0.0).mode is PathingMode.TRAVELING

    assert controller.step(1.0) == PathingDecision(PathingMode.BLOCKED)
    assert controller.waypoints == ()
    assert not controller.is_gps_available


def test_completed_quota_advances_to_next_monster_zone() -> None:
    navigator = _navigator((ZoneGoal("Flame", 2), ZoneGoal("Rapra", 1)))
    controller = _controller(navigator)
    controller.observe(_state(0.0))
    controller.step(0.0)

    assert navigator.active_zone is FLAME_ZONE
    assert not controller.record_kill("Flame")
    assert controller.record_kill("Flame")

    decision = controller.step(1.0)
    assert decision.mode is PathingMode.TRAVELING
    assert navigator.active_zone is RAPRA_ZONE


def test_multi_zone_cycling_when_multiple_zones_present() -> None:
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        preferred_zones=(FLAME_ZONE, RAPRA_ZONE),
        goals=(ZoneGoal("Flame"), ZoneGoal("Rapra")),
    )
    controller = _controller(navigator)
    controller.observe(_state(0.0))
    controller.step(0.0)

    assert navigator.active_zone is FLAME_ZONE
    # Cycle zone
    next_zone = controller.advance_to_next_zone()
    assert next_zone is RAPRA_ZONE
    assert navigator.active_zone is RAPRA_ZONE


def test_a_single_selected_zone_has_nowhere_to_advance_to() -> None:
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        preferred_zones=(FLAME_ZONE,),
        goals=(ZoneGoal("Flame"),),
    )
    controller = _controller(navigator)
    controller.observe(_state(0.0))
    controller.step(0.0)

    assert controller.advance_to_next_zone() is None
    assert navigator.active_zone is FLAME_ZONE


def test_live_stall_projects_an_obstacle_ahead_and_replans_via_steering() -> None:
    """US-093 AC1/AC2/AC3/AC5: no blind macro; a projected obstacle and an immediate replan."""

    stalled_at = WorldPosition(100.0, 100.0, 100.0)
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        navmesh=WIDE_MESH,
        position_reader=cast("LivePositionReader", _LiveReader([stalled_at])),
    )
    controller.observe(_state(0.0))
    for at_seconds in (0.5, 1.0, 1.5, 2.0):
        controller.integrate_movement(VIRTUAL_KEY_W, 0.5)
        controller.observe(_state(at_seconds))

    assert controller.is_recovering
    decision = controller.step(2.0)

    # Recovery steers a replanned NavMesh route; it never queues a backstep, jump, or turn
    # macro, and the controller stays logically in TRAVELING.
    assert decision.mode is PathingMode.TRAVELING
    assert VIRTUAL_KEY_W in (decision.virtual_key, *decision.virtual_keys)
    # The obstacle is projected ahead of the character, never onto its own coordinate.
    blocks = controller.temporary_world_blocks
    assert len(blocks) == 1
    assert blocks[0] != stalled_at
    assert blocks[0].z > stalled_at.z
    kinds = [event.kind for event in controller.drain_recovery_events()]
    assert RecoveryEventKind.STALL_DETECTED in kinds
    assert RecoveryEventKind.TEMPORARY_OBSTACLE_CREATED in kinds
    assert RecoveryEventKind.LOCAL_REPLAN_REQUESTED in kinds
    assert RecoveryEventKind.LOCAL_REPLAN_SUCCEEDED in kinds


class _Adapter:
    def __init__(self) -> None:
        self.keys: list[tuple[int, float]] = []
        self.chords: list[tuple[int, ...]] = []

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, _window_handle: int) -> bool:
        return True

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_keys_while_guarded(
        self,
        _window_handle: int,
        virtual_keys: tuple[int, ...] | list[int] | int,
        duration_seconds: float,
    ) -> None:
        keys = (virtual_keys,) if isinstance(virtual_keys, int) else tuple(virtual_keys)
        self.chords.append(keys)


class _Pipeline:
    def __init__(self, states: list[WorldState]) -> None:
        self._states = iter(states)

    def tick(self, _window_handle: int, _previous: WorldState) -> PerceptionTick:
        return PerceptionTick(next(self._states), (), frozenset())


def test_orchestrator_pauses_when_gps_is_offline() -> None:
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        position_reader=None,
    )
    adapter = _Adapter()
    orchestrator = FarmingOrchestrator(
        cast("PerceptionPipeline", _Pipeline([_state(1.0)])),
        cast("FarmingInputAdapter", adapter),
        WINDOW_HANDLE,
        pathing=controller,
    )
    orchestrator.start()

    tick = orchestrator.tick()

    assert tick.mode is FarmingMode.PAUSED
    assert adapter.keys == []


def test_out_of_zone_start_uses_navmesh_travel_instead_of_camera_search() -> None:
    """BUG-043: an activated camp owns the first no-target tick from any live position."""

    controller = _controller(_navigator((ZoneGoal("Flame"),)))
    adapter = _Adapter()
    orchestrator = FarmingOrchestrator(
        cast("PerceptionPipeline", _Pipeline([_state(1.0)])),
        cast("FarmingInputAdapter", adapter),
        WINDOW_HANDLE,
        pathing=controller,
    )
    orchestrator.start()

    tick = orchestrator.tick()

    assert tick.mode is FarmingMode.SEARCHING
    assert any(VIRTUAL_KEY_W in keys for keys in adapter.chords)
    assert controller.waypoints


def test_in_zone_search_uses_navmesh_patrol_instead_of_camera_rotation() -> None:
    """BUG-044: an empty camera sweep cannot starve an active camp patrol."""

    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        position_reader=cast(
            "LivePositionReader", _LiveReader([WorldPosition(200.0, 100.0, 200.0)])
        ),
        camera_reader=cast("LiveCameraReader", _CameraReader([math.radians(225.0)])),
    )
    adapter = _Adapter()
    orchestrator = FarmingOrchestrator(
        cast("PerceptionPipeline", _Pipeline([_state(1.0)])),
        cast("FarmingInputAdapter", adapter),
        WINDOW_HANDLE,
        pathing=controller,
        config=FarmingConfig(search=SearchConfig(idle_timeout_seconds=0.0)),
    )
    orchestrator.start()

    tick = orchestrator.tick()

    assert tick.mode is FarmingMode.SEARCHING
    assert any(VIRTUAL_KEY_W in keys for keys in adapter.chords)
    assert controller.waypoints


def test_unreachable_selected_zone_pauses_without_camera_search() -> None:
    """BUG-043: an active camp without a route is a latched, diagnosable safe pause."""

    navigator = VectorZoneNavigator(TERRAIN_WORLD_MAP, goals=(ZoneGoal("Flame"),))
    controller = _controller(navigator)
    adapter = _Adapter()
    events: list[tuple[SessionEventKind, str | None]] = []

    class _EventLogger:
        def record(
            self,
            kind: SessionEventKind,
            _new_mode: str,
            *,
            reason: str | None = None,
            **_kwargs: object,
        ) -> None:
            events.append((kind, reason))

    orchestrator = FarmingOrchestrator(
        cast("PerceptionPipeline", _Pipeline([_state(1.0), _state(2.0)])),
        cast("FarmingInputAdapter", adapter),
        WINDOW_HANDLE,
        pathing=controller,
        event_logger=cast("SessionEventLogger", _EventLogger()),
    )
    orchestrator.start()

    first = orchestrator.tick()
    second = orchestrator.tick()

    assert first.mode is FarmingMode.PAUSED
    assert second.mode is FarmingMode.PAUSED
    assert adapter.keys == []
    assert events[-1] == (SessionEventKind.ZONE_ROUTE_UNAVAILABLE, "zone_route_unavailable")


def test_orchestrator_auto_resumes_when_gps_recovers() -> None:
    from dataclasses import replace

    valid_reading = PositionReading(PositionSource.LIVE, WorldPosition(100.0, 100.0, 100.0))
    error_reading = PositionReading(
        PositionSource.UNAVAILABLE,
        error=PositionReadError(PositionReadErrorCode.HANDLE_LOST),
    )

    class _IntermittentGPSReader:
        def __init__(self, sequence: list[PositionReading]) -> None:
            self._sequence = iter(sequence)
            self._last = sequence[-1]

        def poll(self, at_seconds: float) -> PositionReading:
            reading = next(self._sequence, self._last)
            return replace(reading, sampled_at_seconds=at_seconds)

        def close(self) -> None:
            pass

    reader = _IntermittentGPSReader([valid_reading, error_reading, valid_reading, valid_reading])
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        position_reader=cast("LivePositionReader", reader),
    )
    adapter = _Adapter()
    orchestrator = FarmingOrchestrator(
        cast(
            "PerceptionPipeline",
            _Pipeline([_state(0.0), _state(1.0), _state(2.0), _state(3.0)]),
        ),
        cast("FarmingInputAdapter", adapter),
        WINDOW_HANDLE,
        pathing=controller,
    )
    orchestrator.start()

    # Tick 1: GPS online -> actively searching
    tick1 = orchestrator.tick()
    assert tick1.mode is FarmingMode.SEARCHING

    # Tick 2: GPS dropped -> automatically paused
    tick2 = orchestrator.tick()
    assert tick2.mode is FarmingMode.PAUSED
    assert adapter.keys == []

    # Tick 3: GPS back online -> automatically resumed to SEARCHING
    tick3 = orchestrator.tick()
    assert tick3.mode is FarmingMode.SEARCHING

    # Tick 4: continues active execution
    tick4 = orchestrator.tick()
    assert tick4.mode is FarmingMode.SEARCHING


def test_orchestrator_manual_pause_does_not_auto_resume_even_with_gps() -> None:
    reader = _LiveReader([WorldPosition(100.0, 100.0, 100.0)])
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        position_reader=cast("LivePositionReader", reader),
    )
    adapter = _Adapter()
    orchestrator = FarmingOrchestrator(
        cast("PerceptionPipeline", _Pipeline([_state(0.0), _state(1.0), _state(2.0)])),
        cast("FarmingInputAdapter", adapter),
        WINDOW_HANDLE,
        pathing=controller,
    )
    orchestrator.start()
    started = orchestrator.tick()
    assert started.mode is FarmingMode.SEARCHING

    orchestrator.pause()

    # Even with valid GPS the operator's own pause stays latched.
    resumed = orchestrator.tick()
    assert resumed.mode is FarmingMode.PAUSED


def test_live_camera_is_polled_on_every_tick_while_gps_is_live() -> None:
    # Regression for BUG-019: the camera guard compared against the GPS sample time, so
    # every poll after the first was suppressed and the heading froze.
    camera = _CameraReader([0.0, math.radians(90.0)])
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        position_reader=cast(
            "LivePositionReader", _LiveReader([WorldPosition(100.0, 100.0, 100.0)])
        ),
        camera_reader=cast("LiveCameraReader", camera),
    )

    controller.step(0.0)
    first_heading = controller.heading_degrees
    controller.step(1.0)

    assert camera.polls == 2
    assert first_heading == pytest.approx(0.0)
    assert controller.heading_degrees == pytest.approx(90.0)


def test_live_camera_is_polled_once_per_tick() -> None:
    camera = _CameraReader([0.0])
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        position_reader=cast(
            "LivePositionReader", _LiveReader([WorldPosition(100.0, 100.0, 100.0)])
        ),
        camera_reader=cast("LiveCameraReader", camera),
    )

    controller.observe(_state(0.0))
    controller.step(0.0)

    assert camera.polls == 1


def test_an_exhausted_camp_hands_the_session_to_the_next_selected_zone() -> None:
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        preferred_zones=(FLAME_ZONE, RAPRA_ZONE),
        goals=(ZoneGoal("Flame"), ZoneGoal("Rapra")),
        navmesh=WIDE_MESH,
    )
    inside_flame_camp = WorldPosition(FLAME_ZONE.center_x, 100.0, FLAME_ZONE.center_z)
    walker = _WaypointWalker(inside_flame_camp)
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=navigator,
        position_reader=cast("LivePositionReader", walker),
    )
    walker.controller = controller
    search = SearchConfig(idle_timeout_seconds=0.0, rotation_steps=1)
    states = [_state(float(tick)) for tick in range(12)]
    orchestrator = FarmingOrchestrator(
        cast("PerceptionPipeline", _Pipeline(states)),
        cast("FarmingInputAdapter", _Adapter()),
        WINDOW_HANDLE,
        config=FarmingConfig(search=search, auto_align_camera=False),
        pathing=controller,
    )
    orchestrator.start()

    for _ in range(len(states)):
        orchestrator.tick()
        if navigator.active_zone is RAPRA_ZONE:
            break

    assert navigator.active_zone is RAPRA_ZONE


def _mesh_triangle(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> WorldTriangle:
    return WorldTriangle(WorldVertex(*first), WorldVertex(*second), WorldVertex(*third), "fixture")


def _canyon_mesh() -> BakedNavMesh:
    """Bake one walkable slab that stops well short of the camp the session is bound to."""

    return NavMeshBaker().bake(
        (
            _mesh_triangle((0.0, 100.0, 0.0), (60.0, 100.0, 0.0), (60.0, 100.0, 60.0)),
            _mesh_triangle((0.0, 100.0, 0.0), (60.0, 100.0, 60.0), (0.0, 100.0, 60.0)),
        )
    )


def test_a_trapped_character_routes_to_a_verified_mesh_node_making_progress() -> None:
    """US-093 AC7/AC8: an unroutable camp goal falls back to a verified walkable route."""

    mesh = _canyon_mesh()
    trapped_at = WorldPosition(-40.0, 100.0, 30.0)
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP, goals=(ZoneGoal("Flame"),), preferred_zones=(FLAME_ZONE,)
    )
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=navigator,
        navmesh=mesh,
        position_reader=cast("LivePositionReader", _LiveReader([trapped_at])),
    )

    decision = controller.step(0.0)

    assert decision.mode is PathingMode.TRAVELING
    node = controller.world_waypoints[-1]
    assert mesh.contained_surface(node) is not None
    # The route has to make progress towards the camp, not merely leave the pocket.
    assert math.hypot(FLAME_ZONE.center_x - node.x, FLAME_ZONE.center_z - node.z) < math.hypot(
        FLAME_ZONE.center_x - trapped_at.x, FLAME_ZONE.center_z - trapped_at.z
    )


def test_repeated_local_stalls_escalate_to_the_geometric_escape_planner() -> None:
    """US-093 AC6/AC7: a second stall in the same spot hands the trap to the escape planner."""

    stalled_at = WorldPosition(100.0, 100.0, 100.0)
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        navmesh=WIDE_MESH,
        position_reader=cast("LivePositionReader", _LiveReader([stalled_at])),
    )
    controller.observe(_state(0.0))
    for at_seconds in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5):
        controller.integrate_movement(VIRTUAL_KEY_W, 0.5)
        controller.observe(_state(at_seconds))

    decision = controller.step(4.5)

    assert decision.mode is PathingMode.TRAVELING
    kinds = [event.kind for event in controller.drain_recovery_events()]
    assert RecoveryEventKind.REPEATED_LOCAL_STALL in kinds
    assert RecoveryEventKind.ESCAPE_PLAN_SUCCEEDED in kinds
    assert WIDE_MESH.contained_surface(controller.world_waypoints[-1], tolerance=1.0) is not None


def test_a_projected_obstacle_never_hard_blocks_the_start_polygon() -> None:
    """US-093 AC4: A* still routes out of a polygon an obstacle circle covers."""

    mesh = _wide_mesh()
    start = WorldPosition(0.0, 100.0, 0.0)
    goal = WorldPosition(200.0, 100.0, 150.0)
    covering_start = ((start, 5.0),)

    assert mesh.find_path(start, goal, obstacles=covering_start)


def test_an_adopted_navigator_shares_the_controller_mesh() -> None:
    """US-091: patrol routing and combat approaches never disagree about what is walkable."""

    mesh = _canyon_mesh()
    navigator = VectorZoneNavigator(TERRAIN_WORLD_MAP, goals=(ZoneGoal("Flame"),))
    controller = PathingController(config=PATHING_CONFIG, navmesh=mesh)

    controller.attach_vector_navigator(navigator)

    assert navigator.navmesh is mesh


def test_a_controller_without_a_mesh_adopts_the_one_loaded_with_the_world_map() -> None:
    """US-091: the mesh the operator loaded next to the map becomes the session's mesh."""

    mesh = _canyon_mesh()
    navigator = VectorZoneNavigator(TERRAIN_WORLD_MAP, goals=(ZoneGoal("Flame"),), navmesh=mesh)
    controller = PathingController(config=PATHING_CONFIG)

    controller.attach_vector_navigator(navigator)

    assert controller.navmesh is mesh


def test_the_emergency_stop_aborts_recovery_and_clears_the_obstacle_memory() -> None:
    """US-093 AC11: the killswitch halts recovery and drops the projected obstacle memory."""

    stalled_at = WorldPosition(100.0, 100.0, 100.0)
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=_navigator((ZoneGoal("Flame"),)),
        navmesh=WIDE_MESH,
        position_reader=cast("LivePositionReader", _LiveReader([stalled_at])),
    )
    controller.observe(_state(0.0))
    for at_seconds in (0.5, 1.0, 1.5, 2.0):
        controller.integrate_movement(VIRTUAL_KEY_W, 0.5)
        controller.observe(_state(at_seconds))

    assert controller.is_recovering
    assert controller.temporary_world_blocks

    controller.emergency_stop()

    assert not controller.is_recovering
    assert controller.temporary_world_blocks == ()
    assert controller.world_waypoints == ()
    assert controller.drain_recovery_events() == ()
