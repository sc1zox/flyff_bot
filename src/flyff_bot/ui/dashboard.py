"""Typed UI-facing updates delivered to the Qt main thread."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from flyff_bot.features.automation.controllers import EngagementBreakReason
from flyff_bot.features.automation.kill_goals import MobKillProgress
from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.diagnostics import SessionEvent
from flyff_bot.features.navigation.live_camera import CameraReadErrorCode, CameraState
from flyff_bot.features.navigation.live_position import (
    PositionReadErrorCode,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.vision.models import CapturedFrame


class BotStatus(StrEnum):
    """Operator-visible runtime states."""

    ACTIVE = "active"
    STANDBY = "standby"
    COMPLETED = "completed"
    PAUSED = "paused"
    EMERGENCY_STOPPED = "emergency_stopped"
    COMBAT = "combat"
    RECONCILING = "reconciling"
    SEARCH_ROTATING = "search_rotating"
    SEARCH_ROAMING = "search_roaming"
    REPOSITIONING = "repositioning"
    APPROACHING = "approaching"
    ALIGNING = "aligning"
    ALIGNMENT_FAILED = "alignment_failed"
    EMERGENCY_TELEPORT = "emergency_teleport"
    EMERGENCY_TELEPORT_UNAVAILABLE = "emergency_teleport_unavailable"


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
class VectorZoneSnapshot:
    """Immutable view of the extracted spawn zone the session is currently bound to."""

    monster_name: str
    center_x: float
    center_y: float
    half_width_pixels: float
    half_depth_pixels: float
    capacity: int


@dataclass(frozen=True, slots=True)
class NavMeshMobSnapshot:
    """Read-only 3D candidate diagnostic projected onto the inspector's X/Z plane."""

    world_x: float
    world_z: float
    reachable: bool | None
    locked_out: bool = False
    selected: bool = False


@dataclass(frozen=True, slots=True)
class NavigationSnapshot:
    """Immutable view of authoritative 3D GPS, NavMesh, and active vector route."""

    player_x: float
    player_y: float
    heading_degrees: float
    waypoints: tuple[tuple[float, float], ...] = ()
    vector_zone: VectorZoneSnapshot | None = None
    vector_zones: tuple[VectorZoneSnapshot, ...] = ()
    position_source: PositionSource = PositionSource.UNAVAILABLE
    position_error_code: PositionReadErrorCode | None = None
    world_position: WorldPosition | None = None
    camera_state: CameraState | None = None
    camera_error_code: CameraReadErrorCode | None = None
    world_waypoints: tuple[WorldPosition, ...] = ()
    terrain_samples: tuple[tuple[float, float, float], ...] = ()
    navmesh_mobs: tuple[NavMeshMobSnapshot, ...] = ()
    navigation_trajectory: tuple[WorldPosition, ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardUpdate:
    """One optional frame plus the matching immutable perception state."""

    state: WorldState
    status: BotStatus
    goal: FarmingGoal | None = None
    frame: CapturedFrame | None = None
    navigation: NavigationSnapshot | None = None
    window: WindowStatus = WindowStatus.OK
    engagement_break: EngagementBreakReason | None = None
    kill_progress: tuple[MobKillProgress, ...] = ()
    events: tuple[SessionEvent, ...] = ()


class DashboardFeed(QObject):
    """Signal bridge for worker-thread UI updates without widget access."""

    update_available = Signal(DashboardUpdate)

    def publish(self, update: DashboardUpdate) -> None:
        """Queue or deliver an immutable dashboard update to connected slots."""

        self.update_available.emit(update)
