"""Typed UI-facing updates delivered to the Qt main thread."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.vision.models import CapturedFrame


class BotStatus(StrEnum):
    """Operator-visible runtime states."""

    ACTIVE = "active"
    PAUSED = "paused"
    EMERGENCY_STOPPED = "emergency_stopped"
    RECONCILING = "reconciling"
    SEARCH_ROTATING = "search_rotating"
    SEARCH_ROAMING = "search_roaming"
    SEARCH_MINIMAP = "search_minimap"


@dataclass(frozen=True, slots=True)
class FarmingGoal:
    """One inventory target displayed by the dashboard."""

    item_name: str
    required_quantity: int

    def __post_init__(self) -> None:
        if not self.item_name.strip():
            raise ValueError("Farming goal item name must not be empty.")
        if self.required_quantity <= 0:
            raise ValueError("Farming goal quantity must be positive.")


@dataclass(frozen=True, slots=True)
class DashboardUpdate:
    """One optional frame plus the matching immutable perception state."""

    state: WorldState
    status: BotStatus
    goal: FarmingGoal | None = None
    frame: CapturedFrame | None = None


class DashboardFeed(QObject):
    """Signal bridge for worker-thread UI updates without widget access."""

    update_available = Signal(DashboardUpdate)

    def publish(self, update: DashboardUpdate) -> None:
        """Queue or deliver an immutable dashboard update to connected slots."""

        self.update_available.emit(update)
