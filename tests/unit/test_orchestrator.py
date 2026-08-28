"""Tests for the cooperative autonomous farming application service."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from flyff_bot.features.automation.camera_alignment import CameraAligner, CameraAlignmentStatus
from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_F1,
    CombatClassProfile,
    EngagementBreakReason,
)
from flyff_bot.features.automation.models import (
    DesiredState,
    InventoryEntry,
    PlayerVitals,
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
from flyff_bot.features.automation.powerup_controller import PowerUpConfig, PowerUpEntry
from flyff_bot.features.automation.readiness import (
    LiveStateSource,
    ReadinessReason,
)
from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerConfig,
    VitalTriggerRule,
    VitalTriggerType,
)
from flyff_bot.features.diagnostics import SessionEventKind, SessionEventLogger
from flyff_bot.features.input_control import ForegroundWindowInfo, parse_virtual_key
from flyff_bot.features.input_control.keymap import (
    VIRTUAL_KEY_A,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_S,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.navigation.live_position import (
    LivePositionReader,
    PositionReading,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.pathing import (
    PathingController,
)
from flyff_bot.features.navigation.vector_navigation import VectorZoneNavigator
from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldVectorMap,
)
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.features.player_stats.models import (
    ClientPlayerStatsSnapshot,
    PlayerStatField,
    PlayerStatsReadError,
    PlayerStatsReadErrorCode,
    PlayerStatsSource,
)
from flyff_bot.features.vision.models import (
    CapturedFrame,
    ClientSize,
    FrameCaptureError,
    FrameCaptureErrorCode,
)
from flyff_bot.ui.dashboard import (
    BotStatus,
    DashboardFeed,
    DashboardUpdate,
    FarmingGoal,
    WindowStatus,
)

WINDOW_HANDLE = 42
MOB = VisibleMob(1, "Mushpang", 0.9, 20, 20, 20, 20)
POWER_UP_KEY = parse_virtual_key("F4")
FROZEN_FRAME_SIZE = 64
# The stall detector accumulates a stall while consecutive frames stay identical, which is
# exactly what the client shows while the character runs against an obstacle (US-039).
FROZEN_FRAME = CapturedFrame(
    np.zeros((FROZEN_FRAME_SIZE, FROZEN_FRAME_SIZE, 3), dtype=np.uint8),
    ClientSize(width=FROZEN_FRAME_SIZE, height=FROZEN_FRAME_SIZE),
)


class _Pipeline:
    def __init__(
        self,
        states: list[WorldState],
        *,
        capture_error: FrameCaptureErrorCode | None = None,
        frame: CapturedFrame | None = None,
    ) -> None:
        self._states = iter(states)
        self._capture_error = capture_error
        self._frame = frame
        self.calls: list[int] = []

    def tick(self, window_handle: int, _previous: WorldState) -> PerceptionTick:
        self.calls.append(window_handle)
        if self._capture_error is not None:
            raise FrameCaptureError(self._capture_error)
        return PerceptionTick(next(self._states), (), frozenset(), frame=self._frame)


class _LiveStatsPipeline(_Pipeline):
    has_player_stats_provider = True

    def __init__(self, states: list[WorldState]) -> None:
        super().__init__(states)
        self.poll_live_flags: list[bool] = []
        self.close_calls = 0

    def tick(
        self,
        window_handle: int,
        previous: WorldState,
        *,
        poll_live_providers: bool = True,
    ) -> PerceptionTick:
        self.poll_live_flags.append(poll_live_providers)
        return super().tick(window_handle, previous)

    def close(self) -> None:
        self.close_calls += 1


class _InputAdapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.clicks: list[tuple[int, int, int]] = []
        self.keys: list[tuple[int, float]] = []
        self.key_chords: list[tuple[tuple[int, ...], float]] = []
        self.closed_windows: list[int] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def close_window(self, window_handle: int) -> bool:
        self.closed_windows.append(window_handle)
        return True

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.keys.append((virtual_key, duration_seconds))
        self.key_chords.append(((virtual_key,), duration_seconds))

    def send_keys_while_guarded(
        self,
        _window_handle: int,
        virtual_keys: tuple[int, ...] | list[int] | int,
        duration_seconds: float,
    ) -> None:
        keys = (virtual_keys,) if isinstance(virtual_keys, int) else tuple(virtual_keys)
        self.key_chords.append((keys, duration_seconds))
        for k in keys:
            self.keys.append((k, duration_seconds))


def _state(
    time: float,
    *,
    target: SelectedTarget | None = None,
    mobs: tuple[VisibleMob, ...] = (),
    inventory: tuple[InventoryEntry, ...] = (),
) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=inventory,
        progress_marker=0,
        selected_target=target or SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=Viewport(100, 100),
    )


def _player_stats(at_seconds: float) -> ClientPlayerStatsSnapshot:
    return ClientPlayerStatsSnapshot(
        PlayerStatsSource.CLIENT_MEMORY,
        sampled_at_seconds=at_seconds,
        client_sha256="a" * 64,
        fields=(
            PlayerStatField("hp", 100.0, False),
            PlayerStatField("mp", 100.0, False),
            PlayerStatField("fp", 100.0, False),
        ),
    )


def _orchestrator(
    states: list[WorldState],
    adapter: _InputAdapter,
    *,
    config: FarmingConfig | None = None,
    dashboard_feed: DashboardFeed | None = None,
    pipeline: _Pipeline | None = None,
    event_logger: SessionEventLogger | None = None,
    foreground_window_info: Callable[[], ForegroundWindowInfo | None] | None = None,
) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, pipeline or _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
        config=config,
        dashboard_feed=dashboard_feed,
        event_logger=event_logger,
        foreground_window_info=foreground_window_info,
    )


def test_runs_full_target_combat_and_reconciliation_cycle_without_looting() -> None:
    adapter = _InputAdapter()
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    states = [
        _state(1.0, mobs=(MOB,)),
        _state(2.0, target=valid),
        _state(3.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)),
        _state(4.0, target=SelectedTarget(TargetState.NONE, None, 0)),
        _state(5.0),
    ]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    assert orchestrator.tick().mode is FarmingMode.TARGETING
    assert orchestrator.tick().mode is FarmingMode.COMBAT
    assert orchestrator.tick().mode is FarmingMode.COMBAT
    assert orchestrator.tick().mode is FarmingMode.RECONCILING
    assert orchestrator.tick().mode is FarmingMode.SEARCHING
    assert adapter.clicks == [(WINDOW_HANDLE, 30, 30)]
    # Only attack keys: a confirmed fight restarts the search idle timeout (BUG-010),
    # so camera recovery must not fire on the tick right after a kill.
    assert [key for key, _duration in adapter.keys] == [0x20, 0x20]


def test_readiness_blocks_every_action_and_recovers_without_replaying_pending_input() -> None:
    adapter = _InputAdapter()
    unavailable = ClientPlayerStatsSnapshot(
        PlayerStatsSource.UNAVAILABLE,
        error=PlayerStatsReadError(PlayerStatsReadErrorCode.NO_PROFILE),
    )
    blocked_state = replace(
        _state(1.0, mobs=(MOB,), inventory=(InventoryEntry("Quest drop", 3),)),
        player_stats_snapshot=unavailable,
        player_vitals=PlayerVitals(100.0, 100.0, 100.0),
    )
    recovery_state = replace(
        blocked_state, observed_at_seconds=2.0, player_stats_snapshot=_player_stats(2.0)
    )
    ready_state = replace(recovery_state, observed_at_seconds=3.0)
    pipeline = _LiveStatsPipeline([blocked_state, recovery_state, ready_state])
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, pipeline),
        adapter,
        WINDOW_HANDLE,
        config=FarmingConfig(
            vitals=VitalsTriggerConfig(
                rules=(VitalTriggerRule(VitalTriggerType.HP, 50.0, parse_virtual_key("F1")),)
            ),
            powerups=PowerUpConfig(
                entries=(PowerUpEntry(parse_virtual_key("F2"), 1, enabled=True),)
            ),
        ),
    )
    orchestrator.start()

    blocked = orchestrator.tick()

    assert blocked.mode is FarmingMode.PAUSED
    assert blocked.readiness.action_blocked
    assert blocked.readiness.primary_source is LiveStateSource.PLAYER_STATS
    assert adapter.clicks == []
    assert adapter.keys == []
    assert blocked.state.inventory == (InventoryEntry("Quest drop", 3),)

    recovered = orchestrator.tick()
    assert recovered.mode is FarmingMode.SEARCHING
    assert not recovered.readiness.action_blocked
    assert adapter.clicks == []
    assert adapter.keys == []

    dispatched = orchestrator.tick()
    assert dispatched.mode is FarmingMode.TARGETING
    assert adapter.clicks == [(WINDOW_HANDLE, 30, 30)]


def test_end_while_readiness_blocked_closes_live_providers_and_prevents_reopen() -> None:
    adapter = _InputAdapter()
    unavailable = ClientPlayerStatsSnapshot(
        PlayerStatsSource.UNAVAILABLE,
        error=PlayerStatsReadError(PlayerStatsReadErrorCode.HANDLE_LOST),
    )
    state = replace(_state(1.0), player_stats_snapshot=unavailable)
    pipeline = _LiveStatsPipeline([state, state])
    orchestrator = FarmingOrchestrator(cast(PerceptionPipeline, pipeline), adapter, WINDOW_HANDLE)
    orchestrator.start()
    assert orchestrator.tick().mode is FarmingMode.PAUSED

    adapter.aborted = True
    stopped = orchestrator.tick()
    adapter.aborted = False
    preview = orchestrator.tick()

    assert stopped.mode is FarmingMode.EMERGENCY_STOPPED
    assert stopped.readiness.primary_reason is ReadinessReason.EMERGENCY_STOP
    assert pipeline.close_calls == 1
    assert pipeline.poll_live_flags == [True, False]
    assert preview.mode is FarmingMode.EMERGENCY_STOPPED


def test_kill_confirmation_advances_progress_and_avoids_no_progress_pause() -> None:
    """Regression for US-025: progress must move from kill confirmation alone, with
    no loot feed and no monster-stats OCR wired, so Supervisor.NO_PROGRESS never
    false-fires purely because loot-log or kill-count OCR is unattached."""

    adapter = _InputAdapter()
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    states = [
        _state(1.0, mobs=(MOB,)),
        _state(2.0, target=valid),
        _state(3.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)),
        _state(4.0, target=SelectedTarget(TargetState.NONE, None, 0)),
    ]
    assert all(state.monster_kill_count == 0 for state in states)
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    orchestrator.tick()
    orchestrator.tick()
    orchestrator.tick()
    result = orchestrator.tick()

    assert result.mode is FarmingMode.RECONCILING
    assert result.state.progress_marker == 1
    assert result.reconciliation is not None
    assert result.reconciliation.is_healthy
    assert 0x46 not in [key for key, _duration in adapter.keys]


def test_navigation_pathing_continues_uninterrupted_across_a_kill_transition() -> None:
    from flyff_bot.features.navigation.pathing import PathingController

    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    states = [
        _state(1.0, mobs=(MOB,)),
        _state(2.0, target=valid),
        _state(3.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)),
        _state(4.0, target=SelectedTarget(TargetState.NONE, None, 0)),
        _state(5.0),
    ]
    live_reader = cast(
        "LivePositionReader",
        type(
            "_Reader",
            (),
            {
                "poll": lambda self, at: PositionReading(
                    PositionSource.LIVE, WorldPosition(10.0, 10.0, 10.0), sampled_at_seconds=at
                ),
                "close": lambda self: None,
            },
        )(),
    )
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
        pathing=PathingController(position_reader=live_reader),
        dashboard_feed=feed,
    )
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    assert orchestrator.mode is FarmingMode.SEARCHING
    assert len(updates) == len(states)
    assert all(update.navigation is not None for update in updates)


def test_post_kill_reconciliation_selects_next_candidate_in_same_tick() -> None:
    """US-060: reconciliation must not spend an idle tick before the next target."""

    adapter = _InputAdapter()
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    next_mob = VisibleMob(2, "Mushpang", 0.9, 120, 60, 20, 20)
    states = [
        _state(1.0, mobs=(MOB,)),
        _state(2.0, target=valid),
        _state(3.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)),
        _state(4.0, target=SelectedTarget(TargetState.NONE, None, 0)),
        _state(5.0, mobs=(next_mob,)),
    ]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    for _ in range(4):
        orchestrator.tick()

    result = orchestrator.tick()

    assert result.mode is FarmingMode.TARGETING
    assert len(adapter.clicks) == 2
    assert adapter.clicks[-1] == (WINDOW_HANDLE, 130, 70)


def _measured_mob(distance: float) -> VisibleMob:
    return replace(
        MOB,
        world_x=distance,
        world_y=0.0,
        world_z=0.0,
        navmesh_path_distance=distance,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )


def test_ranged_profile_clicks_a_far_straight_route_directly() -> None:
    class StraightNavMesh:
        def find_path(self, start: WorldPosition, goal: WorldPosition) -> tuple[WorldPosition, ...]:
            del goal
            return (start, WorldPosition(20.0, 0.0, 0.0))

    live_reader = cast(
        "LivePositionReader",
        type(
            "_Reader",
            (),
            {
                "live_position": WorldPosition(0.0, 0.0, 0.0),
                "navmesh": StraightNavMesh(),
                "update_engagement_distance": lambda self, distance: None,
            },
        )(),
    )
    orchestrator = _orchestrator([_state(1.0, mobs=(_measured_mob(12.0),))], _InputAdapter())
    orchestrator._pathing = cast("PathingController", live_reader)
    orchestrator.configure_combat_class(CombatClassProfile.RANGED)

    mob = _measured_mob(12.0)

    assert orchestrator._should_dispatch_direct_click(mob) is True
    assert orchestrator.pathing_engagement_distance == pytest.approx(15.0)


def test_multi_waypoint_route_approaches_even_with_ranged_distance() -> None:
    mob = _measured_mob(16.0)

    class DetouredNavMesh:
        def find_path(self, start: WorldPosition, goal: WorldPosition) -> tuple[WorldPosition, ...]:
            return (
                start,
                WorldPosition(5.0, 0.0, 0.0),
                WorldPosition(10.0, 0.0, 0.0),
                WorldPosition(15.0, 0.0, 0.0),
                WorldPosition(15.0, 0.0, 8.0),
                goal,
            )

    live_reader = cast(
        "LivePositionReader",
        type(
            "_Reader",
            (),
            {
                "live_position": WorldPosition(0.0, 0.0, 0.0),
                "navmesh": DetouredNavMesh(),
                "update_engagement_distance": lambda self, distance: None,
            },
        )(),
    )
    orchestrator = _orchestrator([_state(1.0)], _InputAdapter())
    orchestrator._pathing = cast("PathingController", live_reader)
    orchestrator.configure_combat_class(CombatClassProfile.RANGED)

    assert orchestrator._should_dispatch_direct_click(mob) is False


def test_custom_distance_propagates_to_orchestration_and_pathing() -> None:
    pathing = PathingController()
    states = [_state(1.0)]
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        _InputAdapter(),
        WINDOW_HANDLE,
        pathing=pathing,
    )

    orchestrator.configure_engagement_distance(8.0)
    assert orchestrator.pathing_engagement_profile.value == CombatClassProfile.CUSTOM.value
    assert pathing._config.navmesh_engagement_distance_units == pytest.approx(8.0)

    orchestrator.configure_combat_class(CombatClassProfile.RANGED)
    assert orchestrator.pathing_engagement_profile.value == CombatClassProfile.RANGED.value
    assert orchestrator.pathing_engagement_distance == pytest.approx(15.0)
    assert pathing._config.navmesh_engagement_distance_units == pytest.approx(15.0)


def test_target_lost_without_damage_returns_to_search_without_looting() -> None:
    adapter = _InputAdapter()
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    orchestrator = _orchestrator(
        [
            _state(1.0, mobs=(MOB,)),
            _state(2.0, target=valid),
            _state(3.0, target=SelectedTarget(TargetState.NONE, None, 0)),
        ],
        adapter,
    )
    orchestrator.start()

    orchestrator.tick()
    orchestrator.tick()

    assert orchestrator.tick().mode is FarmingMode.SEARCHING
    assert 0x46 not in [key for key, _duration in adapter.keys]


def test_search_waits_for_the_configured_retry_interval_without_input() -> None:
    adapter = _InputAdapter()
    orchestrator = _orchestrator(
        [_state(1.0), _state(1.1), _state(2.0)],
        adapter,
        config=FarmingConfig(search_retry_seconds=1.0),
    )
    orchestrator.start()

    assert orchestrator.tick().mode is FarmingMode.SEARCHING
    assert not orchestrator.tick().dispatched
    assert not orchestrator.tick().dispatched
    assert adapter.keys == []
    assert adapter.clicks == []


def test_search_interrupts_navigation_immediately_when_a_mob_appears() -> None:
    adapter = _InputAdapter()
    orchestrator = _orchestrator(
        [_state(1.0), _state(6.0, mobs=(MOB,))],
        adapter,
    )
    orchestrator.start()

    assert orchestrator.tick().mode is FarmingMode.SEARCHING
    result = orchestrator.tick()

    assert result.mode is FarmingMode.TARGETING
    assert adapter.clicks == [(WINDOW_HANDLE, 30, 30)]


def test_search_interrupts_during_settle_pause_when_mob_appears() -> None:
    adapter = _InputAdapter()
    orchestrator = _orchestrator(
        [
            _state(0.0),  # Idle timeout start
            _state(5.0),  # Dispatches ROTATE pulse (5.0s -> 5.2s key + 0.3s pause)
            _state(5.3, mobs=(MOB,)),  # Settle pause tick: mob spotted!
        ],
        adapter,
    )
    orchestrator.start()

    # Tick 1: starts search timer at t=0
    assert orchestrator.tick().mode is FarmingMode.SEARCHING
    # Tick 2: at t=5.0, dispatches search rotation key
    tick2 = orchestrator.tick()
    assert tick2.mode is FarmingMode.SEARCHING
    assert tick2.dispatched
    assert adapter.keys == [(VIRTUAL_KEY_RIGHT, 0.2)]

    # Tick 3: at t=5.3 (within settle pause), mob enters view -> immediately targets!
    tick3 = orchestrator.tick()
    assert tick3.mode is FarmingMode.TARGETING
    assert adapter.clicks == [(WINDOW_HANDLE, 30, 30)]


def test_configured_attack_key_is_dispatched_for_target_engagement() -> None:
    adapter = _InputAdapter()
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    orchestrator = _orchestrator(
        [_state(1.0, mobs=(MOB,)), _state(2.0, target=valid)],
        adapter,
    )
    orchestrator.configure_attack_key(VIRTUAL_KEY_F1)
    orchestrator.start()

    orchestrator.tick()
    orchestrator.tick()

    assert [key for key, _duration in adapter.keys] == [VIRTUAL_KEY_F1]


def test_configured_target_classes_restrict_candidate_selection_mid_session() -> None:
    adapter = _InputAdapter()
    other_mob = VisibleMob(2, "Rapra", 0.9, 70, 70, 10, 10)
    orchestrator = _orchestrator(
        [_state(1.0, mobs=(MOB, other_mob)), _state(2.0, mobs=(MOB, other_mob))],
        adapter,
    )
    orchestrator.start()
    orchestrator.configure_target_classes(frozenset({"Rapra"}))

    orchestrator.tick()

    # Mushpang sits closer to the viewport centre, so a click on Rapra can only come
    # from the live class filter.
    assert adapter.clicks == [(WINDOW_HANDLE, 75, 75)]


def test_configuring_attack_key_while_active_is_rejected() -> None:
    orchestrator = _orchestrator([_state(1.0)], _InputAdapter())
    orchestrator.start()

    with pytest.raises(RuntimeError):
        orchestrator.configure_attack_key(VIRTUAL_KEY_F1)


def test_end_or_lost_foreground_pauses_without_perception_or_input() -> None:
    stopped = _InputAdapter(aborted=True)
    stopped_orchestrator = _orchestrator([_state(1.0)], stopped)
    stopped_orchestrator.start()
    assert stopped_orchestrator.tick().mode is FarmingMode.EMERGENCY_STOPPED

    unfocused = _InputAdapter(foreground=False)
    unfocused_orchestrator = _orchestrator([_state(1.0)], unfocused)
    unfocused_orchestrator.start()
    assert unfocused_orchestrator.tick().mode is FarmingMode.PAUSED


def test_standby_perception_publishes_live_telemetry_without_dispatching_input() -> None:
    """US-028: a paused session keeps vitals, mob counts, and overlays live, read-only."""

    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    pipeline = _Pipeline([_state(1.0, mobs=(MOB,)), _state(2.0, mobs=(MOB,))])
    orchestrator = _orchestrator([], adapter, dashboard_feed=feed, pipeline=pipeline)

    first = orchestrator.tick()
    second = orchestrator.tick()

    assert pipeline.calls == [WINDOW_HANDLE, WINDOW_HANDLE]
    assert first.mode is FarmingMode.PAUSED
    assert second.state.nearby_mob_count == 1
    assert [update.status for update in updates] == [BotStatus.STANDBY, BotStatus.STANDBY]
    assert all(update.window is WindowStatus.OK for update in updates)
    assert adapter.keys == []
    assert adapter.clicks == []


def test_standby_reports_the_game_window_state_when_no_frame_can_be_captured() -> None:
    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    orchestrator = _orchestrator(
        [],
        adapter,
        dashboard_feed=feed,
        pipeline=_Pipeline([], capture_error=FrameCaptureErrorCode.MINIMIZED),
    )

    orchestrator.tick()

    assert updates[-1].window is WindowStatus.MINIMIZED
    assert updates[-1].status is BotStatus.PAUSED
    assert updates[-1].frame is None


def test_standby_reports_a_background_client_without_blocking_the_preview() -> None:
    adapter = _InputAdapter(foreground=False)
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    orchestrator = _orchestrator([_state(1.0)], adapter, dashboard_feed=feed)

    orchestrator.tick()

    assert updates[-1].window is WindowStatus.NOT_FOREGROUND
    assert updates[-1].status is BotStatus.STANDBY
    assert adapter.keys == []


def test_emergency_stop_keeps_read_only_perception_available() -> None:
    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    pipeline = _Pipeline([_state(1.0, mobs=(MOB,))])
    orchestrator = _orchestrator([], adapter, dashboard_feed=feed, pipeline=pipeline)
    orchestrator.emergency_stop()

    result = orchestrator.tick()

    assert result.mode is FarmingMode.EMERGENCY_STOPPED
    assert pipeline.calls == [WINDOW_HANDLE]
    assert updates[-1].status is BotStatus.EMERGENCY_STOPPED
    assert adapter.keys == []
    assert adapter.clicks == []


def test_a_closed_game_window_pauses_farming_and_reports_the_window_state() -> None:
    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    orchestrator = _orchestrator(
        [],
        adapter,
        dashboard_feed=feed,
        pipeline=_Pipeline([], capture_error=FrameCaptureErrorCode.INVALID_WINDOW),
    )
    orchestrator.start()

    result = orchestrator.tick()

    assert result.mode is FarmingMode.PAUSED
    assert updates[-1].window is WindowStatus.NOT_FOUND
    assert adapter.keys == []


def test_engagement_publishes_a_dedicated_combat_status() -> None:
    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    orchestrator = _orchestrator(
        [_state(1.0, mobs=(MOB,)), _state(2.0, target=valid)],
        adapter,
        dashboard_feed=feed,
    )
    orchestrator.start()

    orchestrator.tick()
    orchestrator.tick()

    assert [update.status for update in updates] == [BotStatus.COMBAT, BotStatus.COMBAT]


def test_item_goal_completes_before_any_input_and_publishes_dashboard_update() -> None:
    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    orchestrator = _orchestrator(
        [_state(1.0, inventory=(InventoryEntry("Sunstones", 3),))],
        adapter,
        config=FarmingConfig(goal=FarmingGoal("Sunstones", 3)),
        dashboard_feed=feed,
    )
    orchestrator.start()
    result = orchestrator.tick()

    assert result.mode is FarmingMode.COMPLETED
    assert adapter.keys == []
    assert updates[-1].goal == FarmingGoal("Sunstones", 3)


def test_orchestrator_publishes_navigation_snapshot_when_pathing_is_configured() -> None:
    from flyff_bot.features.navigation.pathing import PathingController

    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)

    pathing = PathingController()
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline([_state(1.0)])),
        adapter,
        WINDOW_HANDLE,
        pathing=pathing,
        dashboard_feed=feed,
    )
    orchestrator.start()
    orchestrator.tick()

    assert len(updates) == 1
    assert updates[0].navigation is not None
    assert updates[0].navigation.player_x == 0.0
    assert updates[0].navigation.player_y == 0.0


def test_orchestrator_prioritizes_vitals_trigger_ahead_of_combat() -> None:
    adapter = _InputAdapter()
    low_hp_state = _state(
        1.0,
        mobs=(MOB,),
    )
    low_hp_state = replace(low_hp_state, player_vitals=PlayerVitals(hp_percentage=50.0))

    orchestrator = _orchestrator([low_hp_state], adapter)
    orchestrator.start()
    tick = orchestrator.tick()

    assert tick.dispatched is True
    assert (0x70, 0.05) in adapter.keys


def test_failed_acquisition_does_not_thrash_between_search_and_targeting() -> None:
    """US-060: a shortened lockout still prevents immediate thrashing while reselecting."""

    adapter = _InputAdapter()
    states = [_state(index * 0.1, mobs=(MOB,)) for index in range(45)]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    modes = [orchestrator.tick().mode for _ in range(len(states) - 2)]

    assert len(adapter.clicks) == 3
    assert all(click == (WINDOW_HANDLE, 30, 30) for click in adapter.clicks)
    assert modes.count(FarmingMode.TARGETING) == 3
    assert orchestrator.mode in {FarmingMode.SEARCHING, FarmingMode.TARGETING, FarmingMode.COMBAT}


def test_stuck_engagement_breaks_and_repositions_before_searching() -> None:
    """BUG-010: a fight without progress must abort after the engagement timeout.

    US-039 turns that abort into a bounded re-positioning sweep, so the session leaves
    combat through `REPOSITIONING` rather than straight back into target selection.
    """

    adapter = _InputAdapter()
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    states = [_state(1.0, mobs=(MOB,))] + [
        _state(1.0 + index * 0.5, target=valid, mobs=(MOB,)) for index in range(1, 25)
    ]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    modes = [orchestrator.tick().mode for _ in states]

    assert FarmingMode.COMBAT in modes
    assert orchestrator.mode is FarmingMode.REPOSITIONING
    assert adapter.clicks == [(WINDOW_HANDLE, 30, 30)]


def test_engagement_break_reason_is_published_to_the_dashboard() -> None:
    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    states = [_state(0.0, mobs=(MOB,)), _state(1.0, mobs=(MOB,))]
    orchestrator = _orchestrator(states, adapter, dashboard_feed=feed)
    orchestrator.start()

    orchestrator.tick()
    orchestrator.tick()

    assert updates[0].engagement_break is None
    assert updates[1].engagement_break is EngagementBreakReason.ACQUISITION_TIMEOUT


def test_locked_out_mob_lets_camera_search_recovery_take_over() -> None:
    """US-060: the shortened lockout still lets camera search recovery take over."""

    adapter = _InputAdapter()
    states = [_state(index * 0.1, mobs=(MOB,)) for index in range(121)]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    assert len(adapter.clicks) < 8
    assert (VIRTUAL_KEY_RIGHT, 0.2) in adapter.keys


def _power_up_presses(adapter: _InputAdapter) -> int:
    """Count only the timed-hotkey presses, ignoring camera-search recovery keys."""

    return sum(1 for key, _ in adapter.keys if key == POWER_UP_KEY)


def test_power_up_hotkey_is_dispatched_after_its_configured_interval() -> None:
    """US-016: a timed hotkey fires once a full interval of active session time passed."""

    adapter = _InputAdapter()
    states = [_state(index * 0.1) for index in range(26)]
    config = FarmingConfig(
        powerups=PowerUpConfig(
            entries=(PowerUpEntry(virtual_key=POWER_UP_KEY, interval_seconds=2),)
        )
    )
    orchestrator = _orchestrator(states, adapter, config=config)
    orchestrator.start()

    keys_before_interval: list[tuple[int, float]] = []
    for index, _ in enumerate(states):
        if index == 15:
            keys_before_interval = list(adapter.keys)
        orchestrator.tick()

    assert keys_before_interval == []
    assert adapter.keys.count((POWER_UP_KEY, 0.05)) == 1


def test_paused_session_freezes_power_up_countdowns() -> None:
    """US-016: pausing halts interval timers instead of letting wall time expire them."""

    adapter = _InputAdapter()
    states = [_state(time) for time in (0.0, 0.5, 1.0, 100.0, 100.5, 101.0, 101.5, 102.0)]
    config = FarmingConfig(
        powerups=PowerUpConfig(
            entries=(PowerUpEntry(virtual_key=POWER_UP_KEY, interval_seconds=2),)
        )
    )
    orchestrator = _orchestrator(states, adapter, config=config)
    orchestrator.start()
    for _ in range(3):
        orchestrator.tick()

    orchestrator.pause()
    for _ in range(2):
        orchestrator.tick()
    assert _power_up_presses(adapter) == 0

    # The 99 s paused span must not count, so one more second of active time is
    # still owed before the 2 s interval expires.
    orchestrator.start()
    orchestrator.tick()
    orchestrator.tick()
    assert _power_up_presses(adapter) == 0

    orchestrator.tick()
    assert _power_up_presses(adapter) == 1


def test_power_up_hotkey_is_withheld_while_the_client_is_not_foregrounded() -> None:
    """US-016: timed hotkeys stay behind the foreground and emergency-stop guards."""

    adapter = _InputAdapter(foreground=False)
    states = [_state(index * 1.0) for index in range(6)]
    config = FarmingConfig(
        powerups=PowerUpConfig(
            entries=(PowerUpEntry(virtual_key=POWER_UP_KEY, interval_seconds=2),)
        )
    )
    orchestrator = _orchestrator(states, adapter, config=config)
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    assert adapter.keys == []
    assert orchestrator.mode is FarmingMode.PAUSED


class _CameraAligner:
    """Stand in for the guarded camera routine with a scripted outcome."""

    def __init__(self, status: CameraAlignmentStatus = CameraAlignmentStatus.ALIGNED) -> None:
        self._status = status
        self.calls = 0

    def align(self) -> CameraAlignmentStatus:
        self.calls += 1
        return self._status


def _aligning_orchestrator(
    adapter: _InputAdapter,
    aligner: _CameraAligner,
    *,
    auto_align_camera: bool = True,
    feed: DashboardFeed | None = None,
    states: list[WorldState] | None = None,
) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states or [_state(index * 1.0) for index in range(6)])),
        adapter,
        WINDOW_HANDLE,
        config=FarmingConfig(auto_align_camera=auto_align_camera),
        dashboard_feed=feed,
        camera_aligner=cast(CameraAligner, aligner),
    )


def test_farming_start_runs_the_camera_alignment_pre_flight_before_perception() -> None:
    """US-042: the perspective is standardized before the first farming tick."""

    adapter = _InputAdapter()
    aligner = _CameraAligner()
    updates: list[DashboardUpdate] = []
    feed = DashboardFeed()
    feed.update_available.connect(updates.append)
    pipeline = _Pipeline([_state(index * 1.0) for index in range(6)])
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, pipeline),
        adapter,
        WINDOW_HANDLE,
        config=FarmingConfig(),
        dashboard_feed=feed,
        camera_aligner=cast(CameraAligner, aligner),
    )

    orchestrator.start()
    mode_before_tick = orchestrator.mode
    assert mode_before_tick is FarmingMode.ALIGNING
    # The readiness gate has not evaluated until the worker tick begins.
    assert pipeline.calls == []

    orchestrator.tick()

    assert aligner.calls == 1
    assert pipeline.calls == [WINDOW_HANDLE]
    assert orchestrator.mode is FarmingMode.SEARCHING
    # The dashboard shows the alignment state for the whole sequence, not only afterwards.
    assert updates[0].status is BotStatus.ALIGNING
    assert updates[-1].status is not BotStatus.ALIGNING

    orchestrator.tick()
    assert pipeline.calls == [WINDOW_HANDLE, WINDOW_HANDLE]
    assert aligner.calls == 1


def test_farming_start_skips_the_pre_flight_when_auto_alignment_is_disabled() -> None:
    """US-042: the pre-flight is a configured step, not an unconditional one."""

    adapter = _InputAdapter()
    aligner = _CameraAligner()
    orchestrator = _aligning_orchestrator(adapter, aligner, auto_align_camera=False)

    orchestrator.start()

    assert orchestrator.mode is FarmingMode.SEARCHING
    assert aligner.calls == 0


def test_farming_pauses_with_an_explanatory_status_when_alignment_loses_focus() -> None:
    """US-042: an uncalibrated perspective pauses the session instead of farming on."""

    adapter = _InputAdapter()
    aligner = _CameraAligner(CameraAlignmentStatus.FOCUS_LOST)
    updates: list[DashboardUpdate] = []
    feed = DashboardFeed()
    feed.update_available.connect(updates.append)
    orchestrator = _aligning_orchestrator(adapter, aligner, feed=feed)

    orchestrator.start()
    orchestrator.tick()

    assert orchestrator.mode is FarmingMode.PAUSED
    assert updates[-1].status is BotStatus.ALIGNMENT_FAILED


def test_farming_emergency_stops_when_alignment_is_aborted_by_the_killswitch() -> None:
    """US-042: END held during alignment latches the session-local emergency stop."""

    adapter = _InputAdapter()
    aligner = _CameraAligner(CameraAlignmentStatus.ABORTED)
    updates: list[DashboardUpdate] = []
    feed = DashboardFeed()
    feed.update_available.connect(updates.append)
    orchestrator = _aligning_orchestrator(adapter, aligner, feed=feed)

    orchestrator.start()
    orchestrator.tick()

    assert orchestrator.mode is FarmingMode.EMERGENCY_STOPPED
    assert updates[-1].status is BotStatus.EMERGENCY_STOPPED


def test_on_demand_alignment_runs_on_the_worker_tick_and_returns_to_paused() -> None:
    """US-042: the dashboard button queues alignment instead of blocking the GUI thread."""

    adapter = _InputAdapter()
    aligner = _CameraAligner()
    orchestrator = _aligning_orchestrator(adapter, aligner)

    orchestrator.request_camera_alignment()
    mode_before_tick = orchestrator.mode
    assert mode_before_tick is FarmingMode.ALIGNING
    assert aligner.calls == 0

    orchestrator.tick()

    assert aligner.calls == 1
    assert orchestrator.mode is FarmingMode.PAUSED


def test_on_demand_alignment_is_refused_while_a_session_is_running() -> None:
    """US-042: the camera is never moved out from under an active session."""

    adapter = _InputAdapter()
    aligner = _CameraAligner()
    orchestrator = _aligning_orchestrator(adapter, aligner, auto_align_camera=False)
    orchestrator.start()

    with pytest.raises(RuntimeError):
        orchestrator.request_camera_alignment()
    assert aligner.calls == 0


def test_auto_alignment_can_be_toggled_from_the_dashboard() -> None:
    """US-042: the checkbox takes effect on the next session start."""

    adapter = _InputAdapter()
    aligner = _CameraAligner()
    orchestrator = _aligning_orchestrator(adapter, aligner)

    orchestrator.configure_auto_align(False)
    orchestrator.start()
    mode_without_pre_flight = orchestrator.mode
    assert mode_without_pre_flight is FarmingMode.SEARCHING

    orchestrator.pause()
    orchestrator.configure_auto_align(True)
    orchestrator.start()
    assert orchestrator.mode is FarmingMode.ALIGNING


def _blocked_approach_states(count: int) -> list[WorldState]:
    """Return one target acquisition followed by a verified fight that deals no damage."""

    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    return [_state(0.0, mobs=(MOB,))] + [
        _state(index * 0.5, target=valid, mobs=(MOB,)) for index in range(1, count)
    ]


def test_blocked_approach_breaks_the_engagement_and_enters_repositioning() -> None:
    """US-039: a client-driven approach against an obstacle must abort and re-position."""

    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    states = _blocked_approach_states(30)
    orchestrator = _orchestrator(
        states,
        adapter,
        dashboard_feed=feed,
        pipeline=_Pipeline(states, frame=FROZEN_FRAME),
    )
    orchestrator.start()

    modes = [orchestrator.tick().mode for _ in states]

    assert FarmingMode.REPOSITIONING in modes
    assert any(
        update.engagement_break is EngagementBreakReason.OBSTACLE_STALL for update in updates
    )
    assert any(update.status is BotStatus.REPOSITIONING for update in updates)


def test_repositioning_rotates_the_camera_and_roams_before_returning_to_searching() -> None:
    """US-039: the recovery is a bounded rotate-and-roam sweep, not an endless detour."""

    adapter = _InputAdapter()
    states = _blocked_approach_states(30)
    orchestrator = _orchestrator(states, adapter, pipeline=_Pipeline(states, frame=FROZEN_FRAME))
    orchestrator.start()

    modes = [orchestrator.tick().mode for _ in states]
    repositioned = modes.index(FarmingMode.REPOSITIONING)
    dispatched_keys = {virtual_key for virtual_key, _duration in adapter.keys}

    assert VIRTUAL_KEY_RIGHT in dispatched_keys
    assert VIRTUAL_KEY_W in dispatched_keys
    assert FarmingMode.SEARCHING in modes[repositioned:]


def test_lost_foreground_halts_repositioning_without_further_input() -> None:
    """US-039: the re-positioning sweep obeys the same focus guard as every other phase."""

    adapter = _InputAdapter()
    states = _blocked_approach_states(40)
    orchestrator = _orchestrator(states, adapter, pipeline=_Pipeline(states, frame=FROZEN_FRAME))
    orchestrator.start()

    while orchestrator.mode is not FarmingMode.REPOSITIONING:
        orchestrator.tick()

    adapter.foreground = False
    keys_before = len(adapter.keys)
    halted = orchestrator.tick()

    assert halted.mode is FarmingMode.PAUSED
    assert len(adapter.keys) == keys_before


def test_emergency_stop_halts_repositioning_without_further_input() -> None:
    adapter = _InputAdapter()
    states = _blocked_approach_states(40)
    orchestrator = _orchestrator(states, adapter, pipeline=_Pipeline(states, frame=FROZEN_FRAME))
    orchestrator.start()

    while orchestrator.mode is not FarmingMode.REPOSITIONING:
        orchestrator.tick()

    adapter.aborted = True
    keys_before = len(adapter.keys)
    halted = orchestrator.tick()

    assert halted.mode is FarmingMode.EMERGENCY_STOPPED
    assert len(adapter.keys) == keys_before


def test_a_blocked_approach_registers_the_obstacle_in_the_learned_map() -> None:
    """US-039: the blocked path is penalized wherever spatial mapping is active."""

    from flyff_bot.features.navigation.pathing import PathingController

    class _SpyPathing(PathingController):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]
            self.obstacles: list[float] = []

        def register_obstacle(self, at_seconds: float) -> bool:
            self.obstacles.append(at_seconds)
            return super().register_obstacle(at_seconds)

    live_reader = cast(
        "LivePositionReader",
        type(
            "_Reader",
            (),
            {
                "poll": lambda self, at: PositionReading(
                    PositionSource.LIVE, WorldPosition(10.0, 10.0, 10.0), sampled_at_seconds=at
                ),
                "close": lambda self: None,
            },
        )(),
    )
    pathing = _SpyPathing(position_reader=live_reader)
    adapter = _InputAdapter()
    states = _blocked_approach_states(30)
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states, frame=FROZEN_FRAME)),
        adapter,
        WINDOW_HANDLE,
        pathing=pathing,
    )
    orchestrator.start()

    for _tick in states:
        orchestrator.tick()

    assert pathing.obstacles


def test_live_combat_stall_uses_fast_evasion_before_the_blind_reposition_sweep() -> None:
    """BUG-017: live XYZ must drive the two-second stall recovery during auto-approach."""

    class _LiveReader:
        def __init__(self, position: WorldPosition) -> None:
            self._position = position

        def poll(self, at_seconds: float) -> PositionReading:
            return PositionReading(
                PositionSource.LIVE,
                self._position,
                sampled_at_seconds=at_seconds,
            )

        def close(self) -> None:
            pass

    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    states = _blocked_approach_states(20)
    pathing = PathingController(
        position_reader=cast("LivePositionReader", _LiveReader(WorldPosition(100.0, 20.0, 300.0)))
    )
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
        pathing=pathing,
        dashboard_feed=feed,
    )
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    stalled = next(
        update
        for update in updates
        if update.engagement_break is EngagementBreakReason.OBSTACLE_STALL
    )
    assert stalled.state.observed_at_seconds <= 3.0
    evasion_diagonal = adapter.key_chords.index(((VIRTUAL_KEY_W, VIRTUAL_KEY_A), 0.25))
    evasion_backstep = adapter.key_chords.index(((VIRTUAL_KEY_S,), 0.25))
    reposition_rotation = adapter.key_chords.index(((VIRTUAL_KEY_RIGHT,), 0.2))
    assert evasion_diagonal < evasion_backstep < reposition_rotation


def test_mode_transitions_are_recorded_with_previous_and_new_mode(tmp_path: Path) -> None:
    """US-049: every mode change is logged with ISO-8601 timestamp, previous, and new mode."""

    adapter = _InputAdapter()
    logger = SessionEventLogger(tmp_path / "sessions")
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    states = [
        _state(1.0, mobs=(MOB,)),
        _state(2.0, target=valid),
        _state(3.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)),
        _state(4.0, target=SelectedTarget(TargetState.NONE, None, 0)),
        _state(5.0),
    ]
    orchestrator = _orchestrator(states, adapter, event_logger=logger)
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    events = logger.recent_events
    transitions = [(event.previous_mode, event.new_mode) for event in events]
    # Most recent first: reconciling->searching, combat->reconciling, targeting->combat,
    # searching->targeting, paused->searching. A same-mode tick (combat->combat) logs
    # nothing, so five transitions cover the whole run.
    assert transitions == [
        ("reconciling", "searching"),
        ("combat", "reconciling"),
        ("targeting", "combat"),
        ("searching", "targeting"),
        ("paused", "searching"),
    ]
    for event in events:
        datetime.fromisoformat(event.timestamp)


def test_focus_lost_pause_records_foreground_window_diagnostics(tmp_path: Path) -> None:
    """US-049: a focus-loss pause captures the offending foreground window's identity."""

    adapter = _InputAdapter(foreground=False)
    logger = SessionEventLogger(tmp_path / "sessions")
    thief = ForegroundWindowInfo(title="Notepad", process_name="notepad.exe")
    orchestrator = _orchestrator(
        [_state(1.0)],
        adapter,
        event_logger=logger,
        foreground_window_info=lambda: thief,
    )
    orchestrator.start()

    result = orchestrator.tick()

    assert result.mode is FarmingMode.PAUSED
    event = logger.recent_events[0]
    assert event.kind is SessionEventKind.FOCUS_LOST
    assert event.reason == "focus_lost"
    assert event.foreground_window_title == "Notepad"
    assert event.foreground_window_process == "notepad.exe"


def test_emergency_stop_via_killswitch_is_recorded(tmp_path: Path) -> None:
    """US-049: the END/Escape killswitch path is distinguished from a button-triggered stop."""

    adapter = _InputAdapter(aborted=True)
    logger = SessionEventLogger(tmp_path / "sessions")
    orchestrator = _orchestrator([_state(1.0)], adapter, event_logger=logger)
    orchestrator.start()

    orchestrator.tick()

    event = logger.recent_events[0]
    assert event.kind is SessionEventKind.EMERGENCY_STOPPED
    assert event.new_mode == FarmingMode.EMERGENCY_STOPPED.value
    assert event.reason == "killswitch"


def test_frame_capture_error_pause_records_the_capture_error_code(tmp_path: Path) -> None:
    """US-049: a frame-capture failure pause names the typed capture error code."""

    adapter = _InputAdapter()
    logger = SessionEventLogger(tmp_path / "sessions")
    orchestrator = _orchestrator(
        [],
        adapter,
        event_logger=logger,
        pipeline=_Pipeline([], capture_error=FrameCaptureErrorCode.MINIMIZED),
    )
    orchestrator.start()

    orchestrator.tick()

    event = logger.recent_events[0]
    assert event.kind is SessionEventKind.FRAME_CAPTURE_ERROR
    assert event.reason == FrameCaptureErrorCode.MINIMIZED.value


def test_obstacle_stall_repositioning_is_recorded(tmp_path: Path) -> None:
    """US-049: a blocked approach records the typed EngagementBreakReason."""

    adapter = _InputAdapter()
    logger = SessionEventLogger(tmp_path / "sessions")
    states = _blocked_approach_states(30)
    orchestrator = _orchestrator(
        states,
        adapter,
        event_logger=logger,
        pipeline=_Pipeline(states, frame=FROZEN_FRAME),
    )
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    obstacle_event = next(
        event for event in logger.recent_events if event.kind is SessionEventKind.OBSTACLE_STALL
    )
    assert obstacle_event.new_mode == FarmingMode.REPOSITIONING.value
    assert obstacle_event.reason == EngagementBreakReason.OBSTACLE_STALL.value


def test_supervisor_failure_pause_records_the_failure_flags(tmp_path: Path) -> None:
    """US-049: a reconciliation pause names the FailureFlag(s) that triggered it."""

    adapter = _InputAdapter()
    logger = SessionEventLogger(tmp_path / "sessions")
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    states = [
        _state(1.0, mobs=(MOB,)),
        _state(2.0, target=valid),
        _state(3.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)),
        _state(4.0, target=SelectedTarget(TargetState.NONE, None, 0)),
        # The kill lands mode in RECONCILING on tick 4; a 5th tick is required to reach
        # the reconciliation check itself and pause on the unmet minimum mob count.
        _state(5.0),
    ]
    config = FarmingConfig(desired_state=DesiredState(minimum_mob_count=1))
    orchestrator = _orchestrator(states, adapter, config=config, event_logger=logger)
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    assert orchestrator.mode is FarmingMode.PAUSED
    failure_event = next(
        event for event in logger.recent_events if event.kind is SessionEventKind.SUPERVISOR_FAILURE
    )
    assert failure_event.reason is not None
    assert "no_mobs" in failure_event.reason.split(",")


def test_goal_completion_is_recorded(tmp_path: Path) -> None:
    """US-049: reaching an item goal records a typed GOAL_COMPLETED event."""

    adapter = _InputAdapter()
    logger = SessionEventLogger(tmp_path / "sessions")
    orchestrator = _orchestrator(
        [_state(1.0, inventory=(InventoryEntry("Sunstones", 3),))],
        adapter,
        config=FarmingConfig(goal=FarmingGoal("Sunstones", 3)),
        event_logger=logger,
    )
    orchestrator.start()

    result = orchestrator.tick()

    assert result.mode is FarmingMode.COMPLETED
    event = logger.recent_events[0]
    assert event.kind is SessionEventKind.GOAL_COMPLETED
    assert event.reason == "item_goal"


def test_dashboard_update_carries_recent_session_events(tmp_path: Path) -> None:
    """US-049: the diagnostics event log reaches the dashboard, not only the log file."""

    adapter = _InputAdapter()
    logger = SessionEventLogger(tmp_path / "sessions")
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    orchestrator = _orchestrator([_state(1.0)], adapter, dashboard_feed=feed, event_logger=logger)

    orchestrator.start()
    orchestrator.tick()

    assert updates[-1].events
    assert updates[-1].events[0].new_mode == FarmingMode.SEARCHING.value


def test_repeated_pause_from_the_same_mode_does_not_duplicate_events(tmp_path: Path) -> None:
    """US-049: a no-op transition never spams a duplicate diagnostic event."""

    adapter = _InputAdapter()
    logger = SessionEventLogger(tmp_path / "sessions")
    orchestrator = _orchestrator([_state(1.0)], adapter, event_logger=logger)
    orchestrator.start()
    orchestrator.pause()

    orchestrator.pause()

    assert len(logger.recent_events) == 2


class _SpawnZoneRecordingPipeline(_Pipeline):
    """A pipeline that records the spawn declarations a session hands it."""

    def __init__(self, states: list[WorldState]) -> None:
        super().__init__(states)
        self.spawn_zones: list[tuple[VectorSpawnZone, ...]] = []

    def attach_spawn_zones(self, zones: Iterable[VectorSpawnZone]) -> None:
        self.spawn_zones.append(tuple(zones))


def test_adopting_a_world_map_hands_perception_its_spawn_declarations(
    world_map: WorldVectorMap,
) -> None:
    """US-083: the adopted map is what declares how densely each mover spawns."""

    pipeline = _SpawnZoneRecordingPipeline([_state(1.0)])
    orchestrator = _orchestrator([_state(1.0)], _InputAdapter(), pipeline=pipeline)

    orchestrator.configure_vector_navigation(VectorZoneNavigator(world_map))
    orchestrator.configure_vector_navigation(None)

    assert pipeline.spawn_zones == [world_map.zones, ()]
