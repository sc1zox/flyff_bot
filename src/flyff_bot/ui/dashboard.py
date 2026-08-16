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
    STANDBY = "standby"
    PAUSED = "paused"
    EMERGENCY_STOPPED = "emergency_stopped"
    COMBAT = "combat"
    RECONCILING = "reconciling"
    SEARCH_ROTATING = "search_rotating"
    SEARCH_TILTING = "search_tilting"
    SEARCH_ROAMING = "search_roaming"
    SEARCH_MINIMAP = "search_minimap"


class WindowStatus(StrEnum):
    """Observed condition of the game client window behind read-only perception."""

    OK = "ok"
    NOT_FOREGROUND = "not_foreground"
    MINIMIZED = "minimized"
    NOT_FOUND = "not_found"
    CAPTURE_FAILED = "capture_failed"


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
class CellSnapshot:
    """Immutable view of one spatial grid cell."""

    x: int
    y: int
    center_x: float
    center_y: float
    visits: int
    stalls: int
    spawn_weight: float


@dataclass(frozen=True, slots=True)
class EdgeSnapshot:
    """Immutable view of one navigation graph edge between two cell centers."""

    origin_x: float
    origin_y: float
    destination_x: float
    destination_y: float
    stalls: int


@dataclass(frozen=True, slots=True)
class NavigationSnapshot:
    """Immutable view of the learned spatial map, dead reckoning, and active route."""

    player_x: float
    player_y: float
    heading_degrees: float
    cells: tuple[CellSnapshot, ...]
    edges: tuple[EdgeSnapshot, ...]
    waypoints: tuple[tuple[float, float], ...] = ()
    safe_waypoint: tuple[float, float] | None = None
    cell_size_units: float = 15.0
    leash_radius_units: float = 50.0


@dataclass(frozen=True, slots=True)
class DashboardUpdate:
    """One optional frame plus the matching immutable perception state."""

    state: WorldState
    status: BotStatus
    goal: FarmingGoal | None = None
    frame: CapturedFrame | None = None
    navigation: NavigationSnapshot | None = None
    window: WindowStatus = WindowStatus.OK


class DashboardFeed(QObject):
    """Signal bridge for worker-thread UI updates without widget access."""

    update_available = Signal(DashboardUpdate)

    def publish(self, update: DashboardUpdate) -> None:
        """Queue or deliver an immutable dashboard update to connected slots."""

        self.update_available.emit(update)
