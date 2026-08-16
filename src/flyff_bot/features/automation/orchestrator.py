"""Cooperative farming-session orchestration over perception and reactive controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from flyff_bot.features.automation.combat_execution import CombatInputAdapter, CombatInputDispatcher
from flyff_bot.features.automation.controllers import (
    CombatConfig,
    CombatController,
    CombatMode,
    KeyBinding,
    SearchConfig,
    SearchController,
    SearchMode,
)
from flyff_bot.features.automation.models import DesiredState, InventoryEntry, Position, WorldState
from flyff_bot.features.automation.search_execution import SearchInputAdapter, SearchInputDispatcher
from flyff_bot.features.automation.supervisor import Reconciliation, Supervisor
from flyff_bot.features.automation.vitals_controller import (
    VitalsInputAdapter,
    VitalsInputDispatcher,
    VitalsTriggerConfig,
    VitalsTriggerController,
)
from flyff_bot.features.navigation.execution import PathingInputAdapter, PathingInputDispatcher
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.vision.minimap_radar import MinimapRadar
from flyff_bot.features.vision.models import (
    CapturedFrame,
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

DEFAULT_TICK_INTERVAL_SECONDS = 0.1
DEFAULT_SEARCH_RETRY_SECONDS = 0.5
NAVIGATION_PERSIST_INTERVAL_SECONDS = 30.0


class FarmingMode(StrEnum):
    """The externally observable phases of one farming session."""

    PAUSED = "paused"
    SEARCHING = "searching"
    TARGETING = "targeting"
    COMBAT = "combat"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    EMERGENCY_STOPPED = "emergency_stopped"


STANDBY_MODES = frozenset(
    {FarmingMode.PAUSED, FarmingMode.COMPLETED, FarmingMode.EMERGENCY_STOPPED}
)

WINDOW_STATUS_BY_CAPTURE_CODE = {
    FrameCaptureErrorCode.INVALID_WINDOW: WindowStatus.NOT_FOUND,
    FrameCaptureErrorCode.MINIMIZED: WindowStatus.MINIMIZED,
    FrameCaptureErrorCode.OCCLUDED: WindowStatus.NOT_FOREGROUND,
    FrameCaptureErrorCode.CAPTURE_FAILED: WindowStatus.CAPTURE_FAILED,
}


class FarmingInputAdapter(
    CombatInputAdapter, SearchInputAdapter, PathingInputAdapter, VitalsInputAdapter, Protocol
):
    """The guarded platform operations needed by a farming session."""


@dataclass(frozen=True, slots=True)
class FarmingConfig:
    """Explicit timing, controller, and item-goal settings for one session."""

    combat: CombatConfig = field(default_factory=CombatConfig)
    desired_state: DesiredState = field(default_factory=DesiredState)
    goal: FarmingGoal | None = None
    tick_interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS
    search_retry_seconds: float = DEFAULT_SEARCH_RETRY_SECONDS
    search: SearchConfig = field(default_factory=SearchConfig)
    vitals: VitalsTriggerConfig = field(default_factory=VitalsTriggerConfig)

    def __post_init__(self) -> None:
        if self.tick_interval_seconds <= 0.0:
            raise ValueError("Farming tick interval must be positive.")
        if self.search_retry_seconds < 0.0:
            raise ValueError("Farming search retry interval must not be negative.")
        if self.goal is not None and self.desired_state.required_inventory:
            raise ValueError("Configure either a dashboard goal or required inventory, not both.")

    @property
    def effective_desired_state(self) -> DesiredState:
        """Return the supervisor target including the optional displayed item goal."""

        if self.goal is None:
            return self.desired_state
        return DesiredState(
            minimum_mob_count=self.desired_state.minimum_mob_count,
            required_inventory=(InventoryEntry(self.goal.item_name, self.goal.required_quantity),),
        )


@dataclass(frozen=True, slots=True)
class FarmingTick:
    """The outcome of one sequential perception and control cycle."""

    state: WorldState
    mode: FarmingMode
    dispatched: bool
    reconciliation: Reconciliation | None = None


class FarmingOrchestrator:
    """Coordinate one foreground-safe farming session without blocking the caller."""

    def __init__(
        self,
        pipeline: PerceptionPipeline,
        input_adapter: FarmingInputAdapter,
        window_handle: int,
        *,
        supervisor: Supervisor | None = None,
        config: FarmingConfig | None = None,
        dashboard_feed: DashboardFeed | None = None,
        pathing: PathingController | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._input_adapter = input_adapter
        self._window_handle = window_handle
        self._supervisor = supervisor or Supervisor()
        self._config = config or FarmingConfig()
        self._combat = CombatController(self._config.combat)
        self._search = SearchController(self._config.search)
        self._radar = MinimapRadar()
        self._vitals = VitalsTriggerController(self._config.vitals)
        self._combat_dispatcher = CombatInputDispatcher(input_adapter, window_handle)
        self._search_dispatcher = SearchInputDispatcher(input_adapter, window_handle)
        self._vitals_dispatcher = VitalsInputDispatcher(input_adapter, window_handle)
        self._pathing = pathing
        self._pathing_dispatcher = PathingInputDispatcher(input_adapter, window_handle)
        self._dashboard_feed = dashboard_feed
        self._mode = FarmingMode.PAUSED
        self._state = _initial_world_state()
        self._last_frame: CapturedFrame | None = None
        self._last_persist_at_seconds = 0.0
        self._window_status = WindowStatus.NOT_FOREGROUND
        self._has_live_frame = False

    @property
    def mode(self) -> FarmingMode:
        """Return the current session phase."""

        return self._mode

    def start(self) -> None:
        """Allow cooperative ticks to resume unless an emergency stop is active."""

        if self._mode is not FarmingMode.EMERGENCY_STOPPED:
            self._mode = FarmingMode.SEARCHING

    def pause(self) -> None:
        """Pause without sending any compensating input to the client."""

        if self._mode is not FarmingMode.EMERGENCY_STOPPED:
            self._mode = FarmingMode.PAUSED
        self._persist_navigation()

    def emergency_stop(self) -> None:
        """Latch a session-local emergency stop until a new session is created."""

        self._mode = FarmingMode.EMERGENCY_STOPPED
        self._persist_navigation()

    def configure_attack_key(self, virtual_key: int) -> None:
        """Apply one dashboard-selected attack key before a paused session starts."""

        if self._mode is not FarmingMode.PAUSED:
            raise RuntimeError("Attack key can only be configured while farming is paused.")
        combat = replace(self._config.combat, rotation=(KeyBinding(virtual_key),))
        self._config = replace(self._config, combat=combat)
        self._combat = CombatController(combat)

    def configure_combat_grace(self, target_acquisition_grace_seconds: float) -> None:
        """Apply a dashboard-selected target-click grace period mid-session."""

        combat = replace(
            self._config.combat,
            target_acquisition_grace_seconds=target_acquisition_grace_seconds,
        )
        self._config = replace(self._config, combat=combat)
        self._combat.update_config(combat)

    def configure_kill_verification(self, enabled: bool) -> None:
        """Toggle HUD monster-stats kill-count confirmation mid-session."""

        combat = replace(self._config.combat, kill_verification_enabled=enabled)
        self._config = replace(self._config, combat=combat)
        self._combat.update_config(combat)

    def configure_vitals(self, config: VitalsTriggerConfig) -> None:
        """Apply vitals trigger configuration before or during a session."""

        self._config = replace(self._config, vitals=config)
        self._vitals.update_config(config)

    def reset_vitals(self) -> None:
        """Reset vitals debounce cooldowns."""

        self._vitals.reset()

    def save_navigation_profile(self, path: Path) -> None:
        """Persist the active spatial map to a specific profile file."""

        if self._mode not in {FarmingMode.PAUSED, FarmingMode.EMERGENCY_STOPPED}:
            raise RuntimeError("Navigation profiles can only be saved while farming is paused.")
        if self._pathing is not None:
            self._pathing.save_map(path)
            self._publish(False)

    def load_navigation_profile(self, path: Path) -> None:
        """Load a persisted map profile from disk and update the live navigation state."""

        if self._mode not in {FarmingMode.PAUSED, FarmingMode.EMERGENCY_STOPPED}:
            raise RuntimeError("Navigation profiles can only be loaded while farming is paused.")
        if self._pathing is not None:
            self._pathing.load_map(path)
            self._publish(False)

    def reset_navigation_map(self) -> None:
        """Reset the active spatial map and tracking origin."""

        if self._mode not in {FarmingMode.PAUSED, FarmingMode.EMERGENCY_STOPPED}:
            raise RuntimeError("Navigation map can only be reset while farming is paused.")
        if self._pathing is not None:
            self._pathing.reset()
            self._publish(False)

    def tick(self) -> FarmingTick:
        """Perform at most one perception, decision, and guarded-dispatch cycle."""

        if self._mode in STANDBY_MODES:
            self._observe()
            return self._publish(False)
        if self._input_adapter.is_aborted():
            self.emergency_stop()
            return self._publish(False)
        if not self._input_adapter.is_foreground(self._window_handle):
            self.pause()
            return self._publish(False)
        if not self._observe():
            self.pause()
            return self._publish(False)

        if self._pathing is not None:
            self._pathing.observe(self._state, self._last_frame)
            self._state = replace(self._state, is_stuck=self._pathing.is_stalled)
            elapsed = self._state.observed_at_seconds - self._last_persist_at_seconds
            if elapsed >= NAVIGATION_PERSIST_INTERVAL_SECONDS:
                self._persist_navigation()
                self._last_persist_at_seconds = self._state.observed_at_seconds
        if self._goal_completed():
            self._mode = FarmingMode.COMPLETED
            self._persist_navigation()
            return self._publish(False)

        vitals_decision = self._vitals.step(self._state)
        if vitals_decision.triggered:
            dispatched = self._vitals_dispatcher.dispatch(vitals_decision)
            if dispatched:
                return self._publish(True)

        dispatched = self._advance()
        return self._publish(dispatched)

    async def run(self, sleep: Callable[[float], Awaitable[object]] = asyncio.sleep) -> None:
        """Run cooperative ticks until paused, completed, or emergency-stopped."""

        while self._mode not in STANDBY_MODES:
            self.tick()
            if self._mode not in STANDBY_MODES:
                await sleep(self._config.tick_interval_seconds)

    def _observe(self) -> bool:
        """Refresh read-only perception state and report whether a frame was captured.

        This dispatches no input, so it is also the standby path that keeps vitals,
        mob counts, target debug metrics, and the debug overlay live while paused.
        """

        try:
            perception = self._pipeline.tick(self._window_handle, self._state)
        except FrameCaptureError as error:
            self._window_status = WINDOW_STATUS_BY_CAPTURE_CODE.get(
                error.code, WindowStatus.CAPTURE_FAILED
            )
            self._last_frame = None
            self._has_live_frame = False
            return False
        self._state = perception.state
        self._last_frame = perception.frame
        self._has_live_frame = True
        self._window_status = (
            WindowStatus.OK
            if self._input_adapter.is_foreground(self._window_handle)
            else WindowStatus.NOT_FOREGROUND
        )
        return True

    def _advance(self) -> bool:
        if self._mode is FarmingMode.SEARCHING:
            combat = self._combat.step(self._state)
            if combat.mode is not CombatMode.IDLE:
                self._search.reset()
                self._mode = FarmingMode.TARGETING
                return self._combat_dispatcher.dispatch(combat)
            if self._advance_pathing():
                return True
            search_decision = self._search.step(self._state.observed_at_seconds)
            dispatched = self._search_dispatcher.dispatch(search_decision)
            if (
                dispatched
                and self._pathing is not None
                and search_decision.virtual_key is not None
                and search_decision.key_press_duration_seconds is not None
            ):
                self._pathing.integrate_movement(
                    search_decision.virtual_key, search_decision.key_press_duration_seconds
                )
            return dispatched

        if self._mode in {FarmingMode.TARGETING, FarmingMode.COMBAT}:
            combat = self._combat.step(self._state)
            if combat.mode in {CombatMode.IDLE, CombatMode.TARGET_LOST}:
                self._search.reset()
                self._mode = FarmingMode.SEARCHING
                return False
            if combat.mode is CombatMode.TARGET_DEAD:
                self._state = replace(self._state, progress_marker=self._state.progress_marker + 1)
                self._mode = FarmingMode.RECONCILING
                return False
            self._mode = FarmingMode.COMBAT
            return self._combat_dispatcher.dispatch(combat)

        if self._mode is FarmingMode.RECONCILING:
            reconciliation = self._supervisor.reconcile(
                self._config.effective_desired_state, self._state
            )
            if reconciliation.is_healthy:
                self._mode = FarmingMode.SEARCHING
            else:
                self.pause()
            return False

        return False

    def _advance_pathing(self) -> bool:
        """Steer one learned-route step, or defer to the staged search stages."""

        if self._pathing is None:
            return False
        decision = self._pathing.step(self._state.observed_at_seconds)
        if not self._pathing_dispatcher.dispatch(decision):
            return False
        self._pathing.confirm(decision)
        self._search.reset()
        return True

    def _persist_navigation(self) -> None:
        if self._pathing is not None:
            self._pathing.persist()

    def _goal_completed(self) -> bool:
        goal = self._config.goal
        if goal is None:
            return False
        quantities = {entry.item: entry.quantity for entry in self._state.inventory}
        return quantities.get(goal.item_name, 0) >= goal.required_quantity

    def _publish(self, dispatched: bool) -> FarmingTick:
        reconciliation = (
            self._supervisor.reconcile(self._config.effective_desired_state, self._state)
            if self._mode is FarmingMode.RECONCILING
            else None
        )
        tick = FarmingTick(self._state, self._mode, dispatched, reconciliation)
        if self._dashboard_feed is not None:
            self._dashboard_feed.publish(
                DashboardUpdate(
                    self._state,
                    _dashboard_status(
                        self._mode,
                        self._search.mode if self._mode is FarmingMode.SEARCHING else None,
                        live_preview=self._has_live_frame,
                    ),
                    self._config.goal,
                    frame=self._last_frame,
                    navigation=(
                        self._pathing.snapshot(self._state.observed_at_seconds)
                        if self._pathing is not None
                        else None
                    ),
                    window=self._window_status,
                )
            )
        return tick


def _dashboard_status(
    mode: FarmingMode,
    search_mode: SearchMode | None = None,
    *,
    live_preview: bool = False,
) -> BotStatus:
    if mode is FarmingMode.RECONCILING:
        return BotStatus.RECONCILING
    if mode is FarmingMode.EMERGENCY_STOPPED:
        return BotStatus.EMERGENCY_STOPPED
    if mode in {FarmingMode.PAUSED, FarmingMode.COMPLETED}:
        return BotStatus.STANDBY if live_preview else BotStatus.PAUSED
    if mode is FarmingMode.SEARCHING:
        return {
            SearchMode.ROTATE: BotStatus.SEARCH_ROTATING,
            SearchMode.TILT: BotStatus.SEARCH_TILTING,
            SearchMode.ROAM_STEP: BotStatus.SEARCH_ROAMING,
            SearchMode.MINIMAP_RADAR: BotStatus.SEARCH_MINIMAP,
        }[search_mode or SearchMode.ROTATE]
    if mode in {FarmingMode.TARGETING, FarmingMode.COMBAT}:
        return BotStatus.COMBAT
    return BotStatus.ACTIVE


def _initial_world_state() -> WorldState:
    return WorldState(0.0, Position(0, 0), 0, (), 0)
