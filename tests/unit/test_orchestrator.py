"""Tests for the cooperative autonomous farming application service."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_F1,
    VIRTUAL_KEY_RIGHT,
    EngagementBreakReason,
)
from flyff_bot.features.automation.models import (
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
from flyff_bot.features.input_control import parse_virtual_key
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.features.vision.models import FrameCaptureError, FrameCaptureErrorCode
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


class _Pipeline:
    def __init__(
        self, states: list[WorldState], *, capture_error: FrameCaptureErrorCode | None = None
    ) -> None:
        self._states = iter(states)
        self._capture_error = capture_error
        self.calls: list[int] = []

    def tick(self, window_handle: int, _previous: WorldState) -> PerceptionTick:
        self.calls.append(window_handle)
        if self._capture_error is not None:
            raise FrameCaptureError(self._capture_error)
        return PerceptionTick(next(self._states), (), frozenset())


class _InputAdapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.clicks: list[tuple[int, int, int]] = []
        self.keys: list[tuple[int, float]] = []

    def is_aborted(self) -> bool:
        return self.aborted

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


def _state(
    time: float,
    *,
    target: SelectedTarget | None = None,
    mobs: tuple[VisibleMob, ...] = (),
    inventory: tuple[InventoryEntry, ...] = (),
    loot: bool = False,
) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=inventory,
        progress_marker=0,
        selected_target=target or SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        recent_loot=(),
        viewport=Viewport(100, 100),
    )


def _orchestrator(
    states: list[WorldState],
    adapter: _InputAdapter,
    *,
    config: FarmingConfig | None = None,
    dashboard_feed: DashboardFeed | None = None,
    pipeline: _Pipeline | None = None,
) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, pipeline or _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
        config=config,
        dashboard_feed=dashboard_feed,
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
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
        pathing=PathingController(),
        dashboard_feed=feed,
    )
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    assert orchestrator.mode is FarmingMode.SEARCHING
    assert len(updates) == len(states)
    assert all(update.navigation is not None for update in updates)


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
    """BUG-010: an unverified click must not be re-issued on every grace expiry."""

    adapter = _InputAdapter()
    states = [_state(index * 0.1, mobs=(MOB,)) for index in range(41)]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    modes = [orchestrator.tick().mode for _ in states]

    assert adapter.clicks == [(WINDOW_HANDLE, 30, 30)]
    assert modes.count(FarmingMode.TARGETING) == 1
    assert orchestrator.mode is FarmingMode.SEARCHING


def test_stuck_engagement_breaks_and_returns_to_searching() -> None:
    """BUG-010: a fight without progress must abort after the engagement timeout."""

    adapter = _InputAdapter()
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    states = [_state(1.0, mobs=(MOB,))] + [
        _state(1.0 + index * 0.5, target=valid, mobs=(MOB,)) for index in range(1, 25)
    ]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    modes = [orchestrator.tick().mode for _ in states]

    assert FarmingMode.COMBAT in modes
    assert orchestrator.mode is FarmingMode.SEARCHING
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
    """BUG-010: repeated unverified clicks must not keep postponing search recovery."""

    adapter = _InputAdapter()
    states = [_state(index * 0.1, mobs=(MOB,)) for index in range(121)]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    for _ in states:
        orchestrator.tick()

    assert len(adapter.clicks) < 4
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
