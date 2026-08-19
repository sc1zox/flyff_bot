"""Tests for unrecoverable-stuck detection, emergency teleport, and spawn reset (US-040)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from minimap_doubles import MirrorOdometer

from flyff_bot.features.automation.emergency_persistence import (
    load_emergency_config,
    save_emergency_config,
)
from flyff_bot.features.automation.emergency_recovery import (
    DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY,
    DEFAULT_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    EmergencyRecoveryAction,
    EmergencyRecoveryConfig,
    EmergencyRecoveryMonitor,
    EmergencyTeleportDispatcher,
    EmergencyTeleportInputAdapter,
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
    FarmingMode,
    FarmingOrchestrator,
)
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.persistence import (
    NavigationProfile,
    load_profile,
    save_profile,
)
from flyff_bot.features.navigation.spatial import SpatialMap, SpatialMapConfig, WorldPoint
from flyff_bot.features.navigation.tracking import MovementModel
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.ui.dashboard import BotStatus, DashboardFeed, DashboardUpdate

WINDOW_HANDLE = 42
TIMEOUT_SECONDS = 60.0
TICK_SECONDS = 1.0
MAP_CONFIG = SpatialMapConfig(cell_size_pixels=10.0)
MOVEMENT_MODEL = MovementModel(forward_speed_pixels_per_second=10.0, turn_degrees_per_second=90.0)
SPAWN_POINT = WorldPoint(120.0, -45.0)
CONFIG = EmergencyRecoveryConfig(stuck_timeout_seconds=TIMEOUT_SECONDS, settle_delay_seconds=2.0)
# Comfortably above the default 10.0-pixel progress distance, so one tick of travel counts.
PROGRESS_STEP_PIXELS = 25.0


class _Adapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.keys: list[tuple[int, float]] = []
        self.clicks: list[tuple[int, int, int]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def close_window(self, window_handle: int) -> bool:
        return True

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))

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
        for k in keys:
            self.keys.append((k, duration_seconds))


class _Pipeline:
    """Repeat one snapshot per tick with an advancing observation clock."""

    def __init__(self, *, mobs: tuple[VisibleMob, ...] = ()) -> None:
        self._at_seconds = 0.0
        self._mobs = mobs

    def tick(self, _window_handle: int, _previous: WorldState) -> PerceptionTick:
        self._at_seconds += TICK_SECONDS
        return PerceptionTick(_state(self._at_seconds, mobs=self._mobs), (), frozenset())


def _state(at_seconds: float, *, mobs: tuple[VisibleMob, ...] = ()) -> WorldState:
    return WorldState(
        observed_at_seconds=at_seconds,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=Viewport(100, 100),
    )


def _pathing(*, spawn_point: WorldPoint | None = None) -> PathingController:
    return PathingController(
        SpatialMap(MAP_CONFIG),
        odometer=MirrorOdometer(MOVEMENT_MODEL),
        spawn_point=spawn_point,
    )


def _orchestrator(
    adapter: _Adapter,
    pathing: PathingController,
    *,
    config: EmergencyRecoveryConfig = CONFIG,
    dashboard_feed: DashboardFeed | None = None,
) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline()),
        adapter,
        WINDOW_HANDLE,
        config=FarmingConfig(emergency=config),
        pathing=pathing,
        dashboard_feed=dashboard_feed,
    )


def _tick_until(orchestrator: FarmingOrchestrator, mode: FarmingMode, limit: int = 200) -> int:
    """Tick until the session reaches one mode and return how many ticks that took."""

    for count in range(1, limit + 1):
        orchestrator.tick()
        if orchestrator.mode is mode:
            return count
    raise AssertionError(f"session never reached {mode}")


def test_the_stuck_timer_accumulates_only_across_the_ticks_it_is_stepped() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)

    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    monitor.observe(10.0, position_x=0.0, position_y=0.0)
    monitor.observe(25.0, position_x=0.0, position_y=0.0)

    assert monitor.stuck_seconds == pytest.approx(25.0)


def test_a_halted_span_never_counts_towards_the_timeout() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    monitor.observe(5.0, position_x=0.0, position_y=0.0)

    monitor.halt()
    decision = monitor.observe(3600.0, position_x=0.0, position_y=0.0)

    assert monitor.stuck_seconds == pytest.approx(5.0)
    assert decision.action is EmergencyRecoveryAction.NONE


def test_verified_displacement_cancels_the_accumulated_stuck_span() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    monitor.observe(30.0, position_x=0.0, position_y=0.0)
    assert monitor.stuck_seconds == pytest.approx(30.0)

    monitor.observe(31.0, position_x=40.0, position_y=0.0)

    assert monitor.stuck_seconds == pytest.approx(0.0)


def test_jitter_below_the_progress_distance_is_not_treated_as_progress() -> None:
    monitor = EmergencyRecoveryMonitor(replace(CONFIG, progress_distance_pixels=10.0))
    monitor.observe(0.0, position_x=0.0, position_y=0.0)

    monitor.observe(20.0, position_x=3.0, position_y=2.0)

    assert monitor.stuck_seconds == pytest.approx(20.0)


def test_an_engaged_target_cancels_the_accumulated_stuck_span() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    monitor.observe(45.0, position_x=0.0, position_y=0.0)

    monitor.observe(46.0, position_x=0.0, position_y=0.0, engaged=True)

    assert monitor.stuck_seconds == pytest.approx(0.0)


def test_an_unknown_position_neither_advances_nor_cancels_the_reference() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)

    monitor.observe(10.0)
    monitor.observe(20.0, position_x=0.0, position_y=0.0)

    assert monitor.stuck_seconds == pytest.approx(20.0)


def test_the_expired_timer_asks_for_the_configured_teleport_hotkey() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)

    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_y=0.0)

    assert decision.action is EmergencyRecoveryAction.TELEPORT
    assert decision.virtual_key == DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY


def test_an_unassigned_hotkey_reports_the_recovery_as_unavailable() -> None:
    monitor = EmergencyRecoveryMonitor(
        EmergencyRecoveryConfig(teleport_virtual_key=None, stuck_timeout_seconds=TIMEOUT_SECONDS)
    )
    monitor.observe(0.0, position_x=0.0, position_y=0.0)

    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_y=0.0)

    assert decision.action is EmergencyRecoveryAction.UNAVAILABLE
    assert decision.virtual_key is None


@pytest.mark.parametrize(
    "timeout_seconds",
    [9.9, 300.1],
)
def test_a_timeout_outside_the_supported_range_is_refused(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="Unrecoverable stuck timeout"):
        EmergencyRecoveryConfig(stuck_timeout_seconds=timeout_seconds)


@pytest.mark.parametrize(
    "adapter",
    [_Adapter(aborted=True), _Adapter(foreground=False)],
)
def test_a_lost_foreground_or_engaged_emergency_stop_aborts_the_teleport(
    adapter: _Adapter,
) -> None:
    dispatcher = EmergencyTeleportDispatcher(
        cast(EmergencyTeleportInputAdapter, adapter), WINDOW_HANDLE
    )
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_y=0.0)

    assert not dispatcher.dispatch(decision)
    assert adapter.keys == []


def test_the_guarded_dispatcher_sends_the_hotkey_while_the_client_is_safe() -> None:
    adapter = _Adapter()
    dispatcher = EmergencyTeleportDispatcher(
        cast(EmergencyTeleportInputAdapter, adapter), WINDOW_HANDLE
    )
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_y=0.0)

    assert dispatcher.dispatch(decision)
    assert adapter.keys == [
        (DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY, CONFIG.key_press_duration_seconds)
    ]


def test_the_emergency_settings_survive_a_restart_including_an_unassigned_hotkey(
    tmp_path: Path,
) -> None:
    path = tmp_path / "emergency.json"
    stored = EmergencyRecoveryConfig(teleport_virtual_key=None, stuck_timeout_seconds=125.0)

    save_emergency_config(stored, path)

    assert load_emergency_config(path) == stored
    assert load_emergency_config(tmp_path / "absent.json").stuck_timeout_seconds == pytest.approx(
        DEFAULT_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS
    )


def test_an_unreadable_emergency_config_falls_back_to_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "emergency.json"
    path.write_text("{not json}", encoding="utf-8")

    assert load_emergency_config(path) == EmergencyRecoveryConfig()


def test_the_mapped_spawn_point_travels_with_the_navigation_profile(tmp_path: Path) -> None:
    path = tmp_path / "camp.json"
    controller = _pathing()
    controller.observe(_state(1.0))
    controller.set_spawn_point(SPAWN_POINT)

    controller.save_map(path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["spawn_point"] == {"x": SPAWN_POINT.x, "y": SPAWN_POINT.y}
    restored = load_profile(path)
    assert restored.spawn_point == SPAWN_POINT


def test_a_profile_without_a_spawn_point_loads_without_one(tmp_path: Path) -> None:
    path = tmp_path / "camp.json"
    save_profile(NavigationProfile(SpatialMap(MAP_CONFIG)), path)

    assert load_profile(path).spawn_point is None


def test_an_unmeasured_position_is_never_stored_as_a_spawn_point() -> None:
    controller = _pathing(spawn_point=SPAWN_POINT)

    assert controller.mark_spawn_point_here() is None
    assert controller.spawn_point == SPAWN_POINT


def test_marking_the_spawn_point_stores_the_measured_position() -> None:
    controller = _pathing()
    controller.observe(_state(1.0))

    marked = controller.mark_spawn_point_here()

    assert marked == controller.position
    assert controller.spawn_point == marked


def test_marking_the_spawn_point_uses_live_position_when_available() -> None:
    from flyff_bot.features.navigation.live_position import WorldPosition

    controller = _pathing()
    live_pos = WorldPosition(1312.23, 139.01, 1109.04)
    controller._live_position = live_pos

    marked = controller.mark_spawn_point_here()

    assert marked == WorldPoint(1312.23, 1109.04)
    assert controller.spawn_point == marked
    assert controller.navmesh_anchor == live_pos


def test_the_teleport_blames_the_escaped_place_and_resets_onto_the_spawn_anchor() -> None:
    controller = _pathing(spawn_point=SPAWN_POINT)
    controller.observe(_state(1.0))
    stuck_cell = controller.spatial_map.cell_of(controller.position)

    assert controller.begin_teleport_recovery(2.0)
    assert controller.spatial_map.stall_count(stuck_cell) == 1
    assert controller.waypoints == ()

    assert controller.complete_teleport_recovery() == SPAWN_POINT
    assert controller.position == SPAWN_POINT
    assert controller.safe_waypoint is None


def test_without_a_mapped_spawn_point_the_reset_falls_back_to_the_session_origin() -> None:
    controller = _pathing()
    controller.observe(_state(1.0))

    assert controller.complete_teleport_recovery() == WorldPoint(0.0, 0.0)
    assert controller.position == WorldPoint(0.0, 0.0)


def test_a_stalled_session_teleports_and_resumes_from_the_mapped_spawn_anchor() -> None:
    adapter = _Adapter()
    pathing = _pathing(spawn_point=SPAWN_POINT)
    orchestrator = _orchestrator(adapter, pathing)
    orchestrator.start()

    _tick_until(orchestrator, FarmingMode.TELEPORTING)

    assert (DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY, CONFIG.key_press_duration_seconds) in (
        adapter.keys
    )

    _tick_until(orchestrator, FarmingMode.SEARCHING)

    assert pathing.position == SPAWN_POINT


def test_the_settle_delay_holds_every_controller_until_the_client_transition_ends() -> None:
    adapter = _Adapter()
    orchestrator = _orchestrator(adapter, _pathing(spawn_point=SPAWN_POINT))
    orchestrator.start()
    _tick_until(orchestrator, FarmingMode.TELEPORTING)
    dispatched_before_settle = len(adapter.keys)

    # One tick short of the 2.0 s settle window at the 1.0 s pipeline clock.
    orchestrator.tick()

    assert orchestrator.mode is FarmingMode.TELEPORTING
    assert len(adapter.keys) == dispatched_before_settle


def test_an_unconfigured_hotkey_pauses_the_session_and_alerts_the_operator() -> None:
    adapter = _Adapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    orchestrator = _orchestrator(
        adapter,
        _pathing(),
        config=EmergencyRecoveryConfig(
            teleport_virtual_key=None, stuck_timeout_seconds=TIMEOUT_SECONDS
        ),
        dashboard_feed=feed,
    )
    orchestrator.start()

    _tick_until(orchestrator, FarmingMode.PAUSED)

    assert DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY not in [key for key, _ in adapter.keys]
    assert updates[-1].status is BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE


def test_a_session_that_keeps_moving_never_reaches_the_emergency_teleport() -> None:
    adapter = _Adapter()
    odometer = MirrorOdometer(MOVEMENT_MODEL)
    pathing = PathingController(SpatialMap(MAP_CONFIG), odometer=odometer, spawn_point=SPAWN_POINT)
    orchestrator = _orchestrator(adapter, pathing)
    orchestrator.start()

    for _ in range(int(TIMEOUT_SECONDS / TICK_SECONDS) + 5):
        # The measured minimap keeps reporting real travel, which is exactly the evidence
        # a wedged character cannot produce.
        odometer.displace(PROGRESS_STEP_PIXELS, 0.0)
        orchestrator.tick()

    assert orchestrator.mode is not FarmingMode.TELEPORTING
    assert DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY not in [key for key, _ in adapter.keys]
