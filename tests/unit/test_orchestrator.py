"""Tests for the cooperative autonomous farming application service."""

from __future__ import annotations

from typing import cast

from flyff_bot.features.automation.models import (
    InventoryEntry,
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
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.ui.dashboard import DashboardFeed, DashboardUpdate, FarmingGoal

WINDOW_HANDLE = 42
MOB = VisibleMob(1, "Mushpang", 0.9, 20, 20, 20, 20)


class _Pipeline:
    def __init__(self, states: list[WorldState]) -> None:
        self._states = iter(states)
        self.calls: list[int] = []

    def tick(self, window_handle: int, _previous: WorldState) -> PerceptionTick:
        self.calls.append(window_handle)
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
) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
        config=config,
        dashboard_feed=dashboard_feed,
    )


def test_runs_full_target_combat_loot_and_reconciliation_cycle() -> None:
    adapter = _InputAdapter()
    valid = SelectedTarget(TargetState.VALID, "Mushpang", 100)
    states = [
        _state(1.0, mobs=(MOB,)),
        _state(2.0, target=valid),
        _state(3.0, target=valid),
        _state(4.0, target=SelectedTarget(TargetState.NONE, None, 0)),
        _state(5.0),
        _state(6.0),
        _state(7.0),
    ]
    orchestrator = _orchestrator(states, adapter)
    orchestrator.start()

    assert orchestrator.tick().mode is FarmingMode.TARGETING
    assert orchestrator.tick().mode is FarmingMode.COMBAT
    assert orchestrator.tick().mode is FarmingMode.COMBAT
    assert orchestrator.tick().mode is FarmingMode.LOOTING
    assert orchestrator.tick().mode is FarmingMode.LOOTING
    assert orchestrator.tick().mode is FarmingMode.RECONCILING
    assert orchestrator.tick().mode is FarmingMode.SEARCHING
    assert adapter.clicks == [(WINDOW_HANDLE, 30, 30)]
    assert [key for key, _duration in adapter.keys] == [0x20, 0x46]


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


def test_end_or_lost_foreground_pauses_without_perception_or_input() -> None:
    stopped = _InputAdapter(aborted=True)
    stopped_orchestrator = _orchestrator([_state(1.0)], stopped)
    stopped_orchestrator.start()
    assert stopped_orchestrator.tick().mode is FarmingMode.EMERGENCY_STOPPED

    unfocused = _InputAdapter(foreground=False)
    unfocused_orchestrator = _orchestrator([_state(1.0)], unfocused)
    unfocused_orchestrator.start()
    assert unfocused_orchestrator.tick().mode is FarmingMode.PAUSED


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
