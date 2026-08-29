"""Typed UI-facing updates delivered to the Qt main thread.

The navigation snapshots are produced by the navigation feature and only re-exported here,
so that no feature module has to import the UI layer to describe its own output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from flyff_bot.features.automation.autopilot import AutopilotSnapshot, AutopilotSummary
from flyff_bot.features.automation.controllers import EngagementBreakReason
from flyff_bot.features.automation.kill_goals import MobKillProgress
from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.automation.readiness import LiveReadinessStatus
from flyff_bot.features.diagnostics import SessionEvent
from flyff_bot.features.dungeons.models import DungeonStateSnapshot
from flyff_bot.features.navigation.snapshots import (
    NavigationSnapshot,
    NavMeshMobSnapshot,
    VectorZoneSnapshot,
)
from flyff_bot.features.policy.insights import PolicyInsightSnapshot
from flyff_bot.features.policy.runner import PolicyFault
from flyff_bot.features.quests.models import QuestObjectiveProgress
from flyff_bot.features.quests.objectives import QuestGoalIdentity
from flyff_bot.features.tactical_parameters import TacticalParameterDiagnostic
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
    SEARCH_SCANNING = "search_scanning"
    REPOSITIONING = "repositioning"
    APPROACHING = "approaching"
    ALIGNING = "aligning"
    ALIGNMENT_FAILED = "alignment_failed"
    EMERGENCY_TELEPORT = "emergency_teleport"
    EMERGENCY_TELEPORT_UNAVAILABLE = "emergency_teleport_unavailable"
    DEAD = "dead"
    FAULTED = "faulted"


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
    quest_title: str = ""
    quest_progress: tuple[QuestObjectiveProgress, ...] = ()
    quest_queue_completed: bool = False
    quest_goal: QuestGoalIdentity | None = None
    dungeons: tuple[DungeonStateSnapshot, ...] | None = None
    readiness: LiveReadinessStatus = field(default_factory=LiveReadinessStatus)
    # Set whenever learned automation was halted, so the operator is told instead of being
    # shown heuristic behaviour under a learned label (BUG-031).
    policy_fault: PolicyFault | None = None
    # Live policy, candidate, reward and experience telemetry for the ML and policy view. It
    # is a frozen snapshot, so rendering it can never reach back into the running session
    # (US-087).
    policy_insights: PolicyInsightSnapshot = field(default_factory=PolicyInsightSnapshot)
    tactical_parameter_diagnostics: tuple[TacticalParameterDiagnostic, ...] = ()
    # Unattended-session state, so an operator can tell from the dashboard alone whether the
    # bot is still working and what it is currently pursuing (US-086).
    autopilot: AutopilotSnapshot = field(default_factory=AutopilotSnapshot)
    autopilot_summary: AutopilotSummary | None = None


class DashboardFeed(QObject):
    """Signal bridge for worker-thread UI updates without widget access."""

    update_available = Signal(DashboardUpdate)

    def publish(self, update: DashboardUpdate) -> None:
        """Queue or deliver an immutable dashboard update to connected slots."""

        self.update_available.emit(update)


__all__ = [
    "BotStatus",
    "DashboardFeed",
    "DashboardUpdate",
    "FarmingGoal",
    "NavMeshMobSnapshot",
    "NavigationSnapshot",
    "PolicyInsightSnapshot",
    "VectorZoneSnapshot",
    "WindowStatus",
]
