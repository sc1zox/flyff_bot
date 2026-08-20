"""Tests for pure 3D GPS vector navigation and pathing (US-045, US-059)."""

from __future__ import annotations

from typing import cast

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_A,
    VIRTUAL_KEY_S,
    VIRTUAL_KEY_W,
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
    FarmingInputAdapter,
    FarmingMode,
    FarmingOrchestrator,
)
from flyff_bot.features.navigation.live_position import (
    LivePositionReader,
    PositionReadError,
    PositionReadErrorCode,
    PositionReading,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.pathing import (
    PathingConfig,
    PathingController,
    PathingDecision,
    PathingMode,
)
from flyff_bot.features.navigation.teleport import TeleportAnchor, TeleportConfig
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


class _LossReader(_LiveReader):
    def __init__(self) -> None:
        super().__init__([WorldPosition(100.0, 100.0, 100.0)])
        self._polls = 0

    def poll(self, at_seconds: float) -> PositionReading:
        self._polls += 1
        if self._polls == 1:
            return super().poll(at_seconds)
        return PositionReading(
            PositionSource.MINIMAP_FALLBACK,
            error=PositionReadError(PositionReadErrorCode.WINDOW_NOT_FOREGROUND),
        )


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
    return VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        goals=goals,
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


def test_live_stall_triggers_evasion_backstep() -> None:
    stalled_at = WorldPosition(100.0, 100.0, 100.0)
    reader = _LiveReader([stalled_at])
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        goals=(ZoneGoal("Flame"),),
    )
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=navigator,
        position_reader=cast("LivePositionReader", reader),
    )
    controller.observe(_state(0.0))
    for at_seconds in (0.5, 1.0, 1.5, 2.0):
        controller.integrate_movement(VIRTUAL_KEY_W, 0.5)
        controller.observe(_state(at_seconds))

    diagonal = controller.step(2.0)
    backstep = controller.step(2.1)

    assert diagonal.virtual_keys == (VIRTUAL_KEY_W, VIRTUAL_KEY_A)
    assert backstep.virtual_key == VIRTUAL_KEY_S


def test_long_range_teleport_anchor_dispatch() -> None:
    reader = _LiveReader([WorldPosition(0.0, 100.0, 0.0)])
    navigator = VectorZoneNavigator(
        TERRAIN_WORLD_MAP,
        goals=(ZoneGoal("Flame"),),
    )
    controller = PathingController(
        config=PATHING_CONFIG,
        vector_navigator=navigator,
        position_reader=cast("LivePositionReader", reader),
        teleport_config=TeleportConfig(
            enabled=True,
            anchors=(TeleportAnchor("Flame", WorldPosition(190.0, 100.0, 190.0), 0x70),),
        ),
    )
    controller.observe(_state(0.0))
    dispatch = controller.step(0.0)

    assert dispatch.mode is PathingMode.TELEPORTING
    assert dispatch.virtual_key == 0x70


class _Adapter:
    def __init__(self) -> None:
        self.keys: list[tuple[int, float]] = []

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
        pass


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
