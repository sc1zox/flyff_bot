"""Cooperative farming-session orchestration over perception and reactive controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from flyff_bot.features.automation.combat_execution import CombatInputAdapter, CombatInputDispatcher
from flyff_bot.features.automation.controllers import (
    CombatConfig,
    CombatController,
    CombatDecision,
    CombatMode,
    KeyBinding,
    LootConfig,
    LootController,
    LootDecision,
    LootMode,
)
from flyff_bot.features.automation.loot_execution import LootInputDispatcher
from flyff_bot.features.automation.models import DesiredState, InventoryEntry, Position, WorldState
from flyff_bot.features.automation.supervisor import Reconciliation, Supervisor
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.ui.dashboard import BotStatus, DashboardFeed, DashboardUpdate, FarmingGoal

DEFAULT_TICK_INTERVAL_SECONDS = 0.1
DEFAULT_SEARCH_RETRY_SECONDS = 0.5


class FarmingMode(StrEnum):
    """The externally observable phases of one farming session."""

    PAUSED = "paused"
    SEARCHING = "searching"
    TARGETING = "targeting"
    COMBAT = "combat"
    LOOTING = "looting"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    EMERGENCY_STOPPED = "emergency_stopped"


class FarmingInputAdapter(CombatInputAdapter, Protocol):
    """The guarded platform operations needed by a farming session."""


@dataclass(frozen=True, slots=True)
class FarmingConfig:
    """Explicit timing, controller, and item-goal settings for one session."""

    combat: CombatConfig = field(default_factory=CombatConfig)
    loot: LootConfig = field(default_factory=LootConfig)
    desired_state: DesiredState = field(default_factory=DesiredState)
    goal: FarmingGoal | None = None
    tick_interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS
    search_retry_seconds: float = DEFAULT_SEARCH_RETRY_SECONDS

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
    ) -> None:
        self._pipeline = pipeline
        self._input_adapter = input_adapter
        self._window_handle = window_handle
        self._supervisor = supervisor or Supervisor()
        self._config = config or FarmingConfig()
        self._combat = CombatController(self._config.combat)
        self._loot = LootController(self._config.loot)
        self._combat_dispatcher = CombatInputDispatcher(input_adapter, window_handle)
        self._loot_dispatcher = LootInputDispatcher(input_adapter, window_handle)
        self._dashboard_feed = dashboard_feed
        self._mode = FarmingMode.PAUSED
        self._state = _initial_world_state()
        self._last_frame: CapturedFrame | None = None
        self._search_retry_at_seconds = 0.0
        self._loot_combat = CombatDecision(CombatMode.FIGHTING)

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

    def emergency_stop(self) -> None:
        """Latch a session-local emergency stop until a new session is created."""

        self._mode = FarmingMode.EMERGENCY_STOPPED

    def configure_attack_key(self, virtual_key: int) -> None:
        """Apply one dashboard-selected attack key before a paused session starts."""

        if self._mode is not FarmingMode.PAUSED:
            raise RuntimeError("Attack key can only be configured while farming is paused.")
        combat = replace(self._config.combat, rotation=(KeyBinding(virtual_key),))
        self._config = replace(self._config, combat=combat)
        self._combat = CombatController(combat)

    def tick(self) -> FarmingTick:
        """Perform at most one perception, decision, and guarded-dispatch cycle."""

        if self._mode in {FarmingMode.PAUSED, FarmingMode.COMPLETED, FarmingMode.EMERGENCY_STOPPED}:
            return self._publish(False)
        if self._input_adapter.is_aborted():
            self.emergency_stop()
            return self._publish(False)
        if not self._input_adapter.is_foreground(self._window_handle):
            self.pause()
            return self._publish(False)

        perception = self._pipeline.tick(self._window_handle, self._state)
        self._state = perception.state
        self._last_frame = perception.frame
        if self._goal_completed():
            self._mode = FarmingMode.COMPLETED
            return self._publish(False)

        dispatched = self._advance(perception)
        return self._publish(dispatched)

    async def run(self, sleep: Callable[[float], Awaitable[object]] = asyncio.sleep) -> None:
        """Run cooperative ticks until paused, completed, or emergency-stopped."""

        while self._mode not in {
            FarmingMode.PAUSED,
            FarmingMode.COMPLETED,
            FarmingMode.EMERGENCY_STOPPED,
        }:
            self.tick()
            if self._mode not in {
                FarmingMode.PAUSED,
                FarmingMode.COMPLETED,
                FarmingMode.EMERGENCY_STOPPED,
            }:
                await sleep(self._config.tick_interval_seconds)

    def _advance(self, perception: PerceptionTick) -> bool:
        if self._mode is FarmingMode.SEARCHING:
            if self._state.observed_at_seconds < self._search_retry_at_seconds:
                return False
            combat = self._combat.step(self._state)
            if combat.mode is CombatMode.IDLE:
                self._search_retry_at_seconds = (
                    self._state.observed_at_seconds + self._config.search_retry_seconds
                )
                return False
            self._mode = FarmingMode.TARGETING
            return self._combat_dispatcher.dispatch(combat)

        if self._mode in {FarmingMode.TARGETING, FarmingMode.COMBAT}:
            combat = self._combat.step(self._state)
            if combat.mode is CombatMode.IDLE:
                self._mode = FarmingMode.SEARCHING
                return False
            if combat.mode is CombatMode.TARGET_DEAD:
                self._loot_combat = combat
                self._mode = FarmingMode.LOOTING
                return self._advance_loot()
            self._mode = FarmingMode.COMBAT
            return self._combat_dispatcher.dispatch(combat)

        if self._mode is FarmingMode.LOOTING:
            return self._advance_loot()

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

    def _advance_loot(self) -> bool:
        decision: LootDecision = self._loot.step(self._state, self._loot_combat)
        self._loot_combat = CombatDecision(CombatMode.FIGHTING)
        if decision.mode is LootMode.IDLE or decision.mode is LootMode.TIMED_OUT:
            self._mode = FarmingMode.RECONCILING
            return False
        return self._loot_dispatcher.dispatch(decision)

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
                    _dashboard_status(self._mode),
                    self._config.goal,
                    frame=self._last_frame,
                )
            )
        return tick


def _dashboard_status(mode: FarmingMode) -> BotStatus:
    if mode is FarmingMode.RECONCILING:
        return BotStatus.RECONCILING
    if mode is FarmingMode.EMERGENCY_STOPPED:
        return BotStatus.EMERGENCY_STOPPED
    if mode in {FarmingMode.PAUSED, FarmingMode.COMPLETED}:
        return BotStatus.PAUSED
    return BotStatus.ACTIVE


def _initial_world_state() -> WorldState:
    return WorldState(0.0, Position(0, 0), 0, (), 0)
