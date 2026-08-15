"""Pure reactive controller state machines driven by world snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.automation.models import ActionKind, WorldState


class ControllerMode(StrEnum):
    """State modes shared by the small reactive controllers."""

    IDLE = "idle"
    ACTIVE = "active"
    RECOVERING = "recovering"


@dataclass(frozen=True, slots=True)
class ControllerDecision:
    """One state transition and the abstract action category it requests."""

    mode: ControllerMode
    action_kind: ActionKind | None


class CombatController:
    """Engage a visible mob and otherwise remain idle."""

    def step(self, state: WorldState) -> ControllerDecision:
        if state.nearby_mob_count > 0:
            return ControllerDecision(ControllerMode.ACTIVE, ActionKind.ATTACK)
        return ControllerDecision(ControllerMode.IDLE, None)


class NavigationController:
    """Request recovery for a stuck state and movement otherwise."""

    def step(self, state: WorldState) -> ControllerDecision:
        if state.is_stuck:
            return ControllerDecision(ControllerMode.RECOVERING, ActionKind.RECOVER)
        return ControllerDecision(ControllerMode.ACTIVE, ActionKind.MOVE)


class LootController:
    """Request loot collection when inventory evidence has changed."""

    def __init__(self) -> None:
        self._last_inventory: tuple[object, ...] | None = None

    def step(self, state: WorldState) -> ControllerDecision:
        if self._last_inventory != state.inventory:
            self._last_inventory = state.inventory
            return ControllerDecision(ControllerMode.ACTIVE, ActionKind.LOOT)
        return ControllerDecision(ControllerMode.IDLE, None)
