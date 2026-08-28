"""Cooperative farming-session orchestration over perception and reactive controllers."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Protocol

from flyff_bot.features.automation.autopilot import (
    DEAD_HP_PERCENTAGE,
    AutopilotCompletionReason,
    AutopilotConfig,
    AutopilotGoalKind,
    AutopilotSessionController,
    AutopilotSnapshot,
    DeathDetector,
    arbitrate_goal,
)
from flyff_bot.features.automation.camera_alignment import (
    DEFAULT_AUTO_ALIGN_CAMERA,
    CameraAligner,
    CameraAlignmentStatus,
)
from flyff_bot.features.automation.combat_execution import CombatInputAdapter, CombatInputDispatcher
from flyff_bot.features.automation.controllers import (
    CUSTOM_COMBAT_CLASS_PROFILE,
    MELEE_COMBAT_CLASS_PROFILE,
    MELEE_ENGAGEMENT_DISTANCE_UNITS,
    RANGED_COMBAT_CLASS_PROFILE,
    RANGED_ENGAGEMENT_DISTANCE_UNITS,
    CombatClassProfile,
    CombatConfig,
    CombatController,
    CombatDecision,
    CombatMode,
    EngagementBreakReason,
    KeyBinding,
    SearchConfig,
    SearchController,
    SearchMode,
)
from flyff_bot.features.automation.emergency_recovery import (
    EmergencyRecoveryAction,
    EmergencyRecoveryConfig,
    EmergencyRecoveryMonitor,
)
from flyff_bot.features.automation.kill_goals import (
    KillGoalConfig,
    KillGoalTracker,
    MobKillQuota,
)
from flyff_bot.features.automation.models import (
    DesiredState,
    InventoryEntry,
    Position,
    TargetState,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.powerup_controller import (
    PowerUpConfig,
    PowerUpInputAdapter,
    PowerUpInputDispatcher,
    PowerUpScheduler,
)
from flyff_bot.features.automation.quest_execution import QuestInputDispatcher
from flyff_bot.features.automation.quest_execution_models import (
    DialoguePerceiver,
    QuestInteractionController,
    QuestInteractionMode,
)
from flyff_bot.features.automation.quest_goals import (
    hierarchical_objective_for,
    kill_goal_config_for,
    leash_for,
    patrol_zones_for,
    zone_goals_for,
)
from flyff_bot.features.automation.readiness import (
    CapabilityRequirement,
    LiveProviderSample,
    LiveReadinessGate,
    LiveReadinessStatus,
    LiveStateSource,
    ProviderHealth,
    ProviderRegistration,
    SessionCapability,
)
from flyff_bot.features.automation.respawn import (
    RespawnInputDispatcher,
    RespawnMenuPerceiver,
)
from flyff_bot.features.automation.search_execution import SearchInputAdapter, SearchInputDispatcher
from flyff_bot.features.automation.supervisor import Reconciliation, Supervisor
from flyff_bot.features.automation.target_reconciliation import (
    TargetAgreement,
    TargetReconciliation,
    reconcile_selected_target,
)
from flyff_bot.features.automation.vitals_controller import (
    VitalsInputAdapter,
    VitalsInputDispatcher,
    VitalsTriggerConfig,
    VitalsTriggerController,
    VitalTriggerType,
)
from flyff_bot.features.diagnostics import SessionEventKind, SessionEventLogger
from flyff_bot.features.dungeons.live_reader import DungeonReadStatus
from flyff_bot.features.dungeons.models import DungeonStateSnapshot
from flyff_bot.features.input_control import ForegroundWindowInfo
from flyff_bot.features.ml.features import (
    NEARBY_CANDIDATE_DISTANCE_UNITS,
    bearing,
    candidate_feature_row,
    feature_matrix,
    route_slope,
)
from flyff_bot.features.navigation.execution import PathingInputAdapter, PathingInputDispatcher
from flyff_bot.features.navigation.goal_travel import (
    GoalTravelConfig,
    GoalTravelMode,
    plan_goal_travel,
)
from flyff_bot.features.navigation.live_camera import (
    CameraReadErrorCode,
    WorldProjectionStatus,
    project_world_to_screen,
)
from flyff_bot.features.navigation.live_position import (
    PositionReadErrorCode,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.teleporter_dispatch import (
    CombatObservation,
    TeleporterDispatchStatus,
)
from flyff_bot.features.navigation.teleporter_models import TeleporterCatalog
from flyff_bot.features.navigation.tracking import StallConfig, StallDetector
from flyff_bot.features.navigation.world_extractor import WorldCoordinate
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.player_stats.models import (
    PlayerStatsReadErrorCode,
    PlayerStatsSource,
)
from flyff_bot.features.policy.action_payloads import STRATEGIC_GOAL_ORDER, StrategicGoalKind
from flyff_bot.features.policy.contract import ContractVersionError, current_contract_stamp
from flyff_bot.features.policy.goal_preconditions import (
    SessionGrounding,
    can_engage_targets,
    can_interact,
    can_navigate,
)
from flyff_bot.features.policy.hierarchical import (
    HierarchicalObjective,
    HierarchicalObjectiveKind,
)
from flyff_bot.features.policy.models import (
    AttackPointAction,
    LiveObservationState,
    PolicyCandidate,
    PolicyContext,
    TargetAction,
)
from flyff_bot.features.policy.runner import (
    LearnedPolicyProtocol,
    PolicyFault,
    PolicyFaultCode,
    PolicyRunner,
)
from flyff_bot.features.quests.objectives import (
    NO_OBJECTIVE_ORDINAL,
    OBJECTIVE_GOAL_KINDS,
    TURN_IN_GOAL_KINDS,
    QuestGoal,
    QuestGoalFailure,
    QuestGoalKind,
    QuestGoalSequence,
    QuestGoalTimeouts,
)
from flyff_bot.features.rl.actions import TacticalActionCatalog
from flyff_bot.features.rl.models import NavMeshContext, PlayerKinematics
from flyff_bot.features.tactical_parameters import (
    DEFAULT_TACTICAL_PARAMETERS,
    TACTICAL_PARAMETER_DEFINITIONS,
    TACTICAL_PARAMETER_SCHEMA_VERSION,
    TacticalParameterDiagnostic,
    TacticalParameterName,
    TacticalParameterSpace,
)
from flyff_bot.features.telemetry.models import (
    ActiveGoal,
    CombatOutcome,
    CombatVerificationSource,
    NavigationOutcome,
)
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

if TYPE_CHECKING:
    from flyff_bot.features.navigation.pathing import PathingController
    from flyff_bot.features.navigation.vector_navigation import VectorZoneNavigator, ZoneGoal
    from flyff_bot.features.navigation.world_extractor import VectorSpawnZone
    from flyff_bot.features.quests.goals import QuestFarmingQueue, QuestResolution
    from flyff_bot.features.telemetry.recorder import TelemetryRecorder


DEFAULT_TICK_INTERVAL_SECONDS = 0.1
DEFAULT_SEARCH_RETRY_SECONDS = 0.5
DEFAULT_REPOSITION_IDLE_TIMEOUT_SECONDS = 0.0
DEFAULT_REPOSITION_ROTATION_STEPS = 4
DEFAULT_REPOSITION_ROAM_STEPS = 2
REPOSITION_SWEEP_CYCLES = 1
# One full patrol lap of a camp without a confirmed kill is what exhausts it: the next
# selected spawn zone is worth walking to rather than sweeping the empty one again.
PATROL_SWEEPS_BEFORE_ZONE_CHANGE = 1
FOREGROUND_FRESHNESS_SECONDS = 0.5
PERCEPTION_FRAME_FRESHNESS_SECONDS = 0.5
GPS_FRESHNESS_SECONDS = 0.5
CAMERA_FRESHNESS_SECONDS = 0.5
PLAYER_STATS_FRESHNESS_SECONDS = 1.0
DUNGEON_STATE_FRESHNESS_SECONDS = 2.0
# The stable diagnostic reason recorded once when an unfingerprinted client build forces the
# session off exact client-memory statistics and back onto the visual HUD (US-085).
PLAYER_STATS_HUD_FALLBACK_REASON = "player_stats_hud_fallback"
# How long an unsupported client-memory profile is tolerated before the session gives up on it
# and reads vitals from the visible HUD instead. A profile is only ever declared unsupported by
# the client build itself, so this grace only absorbs the reader's pre-first-poll state.
PLAYER_STATS_FALLBACK_GRACE_SECONDS = 5.0
TACTICAL_APPROACH_DISTANCE_MULTIPLIERS = (0.75, 1.0, 1.25)


def _default_reposition_config() -> SearchConfig:
    """Return the bounded rotate-and-roam sweep used to clear a blocked approach."""

    return SearchConfig(
        idle_timeout_seconds=DEFAULT_REPOSITION_IDLE_TIMEOUT_SECONDS,
        rotation_steps=DEFAULT_REPOSITION_ROTATION_STEPS,
        roam_steps=DEFAULT_REPOSITION_ROAM_STEPS,
    )


class FarmingMode(StrEnum):
    """The externally observable phases of one farming session."""

    PAUSED = "paused"
    ALIGNING = "aligning"
    SEARCHING = "searching"
    REPOSITIONING = "repositioning"
    TARGETING = "targeting"
    APPROACHING = "approaching"
    COMBAT = "combat"
    TELEPORTING = "teleporting"
    RECONCILING = "reconciling"
    DEAD = "dead"
    FAULTED = "faulted"
    EMERGENCY_STOPPED = "emergency_stopped"
    COMPLETED = "completed"


class PolicyRuntimeMode(StrEnum):
    """Selectable policy execution modes (US-067)."""

    HEURISTIC = "HEURISTIC"
    ML_SHADOW = "ML_SHADOW"
    ML_ACTIVE = "ML_ACTIVE"


DEFAULT_POLICY_RUNTIME_MODE = PolicyRuntimeMode.HEURISTIC
HIERARCHICAL_METADATA_NAME = "hierarchical-metadata.json"
POLICY_MODEL_NOT_CONFIGURED = "not_configured"
LEARNED_POLICY_HALTED_REASON = "learned_policy_halted"
# Machine-readable reasons for the unattended-session events the dashboard localizes.
TICK_FAULT_REASON = "tick_fault"
AUTOPILOT_ARMED_REASON = "autopilot_armed"
NO_EXECUTABLE_GOAL_REASON = "no_executable_goal"
RECOVERY_BLOCKING_CONDITION_CLEARED = "blocking_condition_cleared"
DEATH_CONFIRMED_REASON = "zero_hp_dwell_confirmed"
DEATH_BUDGET_EXHAUSTED_REASON = "death_budget_exhausted"
RESPAWN_CONFIRMED_REASON = "respawn_confirmed"
RESPAWN_WAITING_FOR_OPERATOR_REASON = "respawn_waiting_for_operator"
NPC_PROJECTION_UNAVAILABLE_REASON = "npc_projection_unavailable"
OPERATOR_PAUSE_REASON = "operator_pause"


class QuestGoalFailurePolicy(StrEnum):
    """What a session does when one quest goal stops being executable (US-080)."""

    ADVANCE_QUEST = "advance_quest"
    PAUSE_SESSION = "pause_session"


DEFAULT_QUEST_GOAL_FAILURE_POLICY = QuestGoalFailurePolicy.ADVANCE_QUEST


NPC_GOAL_KIND_BY_INTERACTION_MODE = {
    QuestInteractionMode.NAVIGATING_TO_ACCEPT: QuestGoalKind.TRAVEL_TO_ACCEPT,
    QuestInteractionMode.INTERACTING: QuestGoalKind.ACCEPT,
    QuestInteractionMode.AWAITING_ACCEPT_CONFIRMATION: QuestGoalKind.ACCEPT,
    QuestInteractionMode.NAVIGATING_TO_TURN_IN: QuestGoalKind.TRAVEL_TO_TURN_IN,
    QuestInteractionMode.INTERACTING_FOR_TURN_IN: QuestGoalKind.TURN_IN,
    QuestInteractionMode.AWAITING_REWARD_CLAIM: QuestGoalKind.TURN_IN,
}

#: Declared session outcomes a contained fault must not overwrite.
TERMINAL_MODES = frozenset({FarmingMode.EMERGENCY_STOPPED, FarmingMode.COMPLETED})

#: The modes an orderly stop waits out, so a budget never abandons a live engagement.
ENGAGEMENT_MODES = frozenset({FarmingMode.APPROACHING, FarmingMode.TARGETING, FarmingMode.COMBAT})

STANDBY_MODES = frozenset(
    {
        FarmingMode.PAUSED,
        FarmingMode.DEAD,
        FarmingMode.FAULTED,
        FarmingMode.COMPLETED,
        FarmingMode.EMERGENCY_STOPPED,
    }
)

WINDOW_STATUS_BY_CAPTURE_CODE = {
    FrameCaptureErrorCode.INVALID_WINDOW: WindowStatus.NOT_FOUND,
    FrameCaptureErrorCode.MINIMIZED: WindowStatus.MINIMIZED,
    FrameCaptureErrorCode.OCCLUDED: WindowStatus.NOT_FOREGROUND,
    FrameCaptureErrorCode.CAPTURE_FAILED: WindowStatus.CAPTURE_FAILED,
}


def _break_kind(reason: EngagementBreakReason | None) -> SessionEventKind:
    """Classify a broken engagement for the diagnostics event log."""

    if reason is EngagementBreakReason.OBSTACLE_STALL:
        return SessionEventKind.OBSTACLE_STALL
    return SessionEventKind.MODE_TRANSITION


class SessionShutdownAdapter(Protocol):
    """The cooperative window shutdown a finished session may request."""

    def close_window(self, window_handle: int) -> bool:
        """Ask the client window to close itself and report whether that was posted."""


class DungeonStateProvider(Protocol):
    """Optional bounded live dungeon feed owned by the session lifecycle."""

    @property
    def last_diagnostic(self) -> object | None: ...

    def poll(self, at_seconds: float | None = None) -> tuple[DungeonStateSnapshot, ...]: ...

    def close(self) -> None: ...


class FarmingInputAdapter(
    CombatInputAdapter,
    SearchInputAdapter,
    PathingInputAdapter,
    VitalsInputAdapter,
    PowerUpInputAdapter,
    SessionShutdownAdapter,
    Protocol,
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
    reposition: SearchConfig = field(default_factory=_default_reposition_config)
    approach_stall: StallConfig = field(default_factory=StallConfig)
    vitals: VitalsTriggerConfig = field(default_factory=VitalsTriggerConfig)
    powerups: PowerUpConfig = field(default_factory=PowerUpConfig)
    emergency: EmergencyRecoveryConfig = field(default_factory=EmergencyRecoveryConfig)
    tactical_parameters: TacticalParameterSpace = DEFAULT_TACTICAL_PARAMETERS
    auto_align_camera: bool = DEFAULT_AUTO_ALIGN_CAMERA
    policy_mode: PolicyRuntimeMode = DEFAULT_POLICY_RUNTIME_MODE
    policy_model_directory: str | None = None
    quest_travel: GoalTravelConfig = field(default_factory=GoalTravelConfig)
    quest_goal_timeouts: QuestGoalTimeouts = field(default_factory=QuestGoalTimeouts)
    quest_goal_failure_policy: QuestGoalFailurePolicy = DEFAULT_QUEST_GOAL_FAILURE_POLICY
    autopilot: AutopilotConfig = field(default_factory=AutopilotConfig)

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
    readiness: LiveReadinessStatus = field(default_factory=LiveReadinessStatus)


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
        camera_aligner: CameraAligner | None = None,
        kill_goals: KillGoalTracker | None = None,
        quest_queue: QuestFarmingQueue | None = None,
        on_target_classes_changed: Callable[[frozenset[str]], None] | None = None,
        quest_menu_perceiver: DialoguePerceiver | None = None,
        respawn_menu_perceiver: RespawnMenuPerceiver | None = None,
        event_logger: SessionEventLogger | None = None,
        foreground_window_info: Callable[[], ForegroundWindowInfo | None] | None = None,
        telemetry: TelemetryRecorder | None = None,
        dungeon_provider: DungeonStateProvider | None = None,
        teleporter_catalog: TeleporterCatalog | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._pipeline = pipeline
        self._input_adapter = input_adapter
        self._window_handle = window_handle
        self._supervisor = supervisor or Supervisor()
        self._config = config or FarmingConfig()
        self._tactical_parameters = self._config.tactical_parameters
        self._combat = CombatController(
            self._config.combat, tactical_parameters=self._tactical_parameters
        )
        self._search = SearchController(
            self._config.search, tactical_parameters=self._tactical_parameters
        )
        self._reposition = SearchController(
            self._config.reposition, tactical_parameters=self._tactical_parameters
        )
        self._approach_stalls = StallDetector(self._config.approach_stall)
        self._vitals = VitalsTriggerController(
            self._config.vitals, tactical_parameters=self._tactical_parameters
        )
        self._powerups = PowerUpScheduler(self._config.powerups)
        self._emergency = EmergencyRecoveryMonitor(self._config.emergency)
        self._combat_dispatcher = CombatInputDispatcher(input_adapter, window_handle)
        self._search_dispatcher = SearchInputDispatcher(input_adapter, window_handle)
        self._vitals_dispatcher = VitalsInputDispatcher(input_adapter, window_handle)
        self._powerup_dispatcher = PowerUpInputDispatcher(input_adapter, window_handle)
        self._quest_interaction: QuestInteractionController | None = None
        self._quest_goals: QuestGoalSequence | None = None
        self._quest_travel_index: int | None = None
        self._teleporter_catalog = teleporter_catalog
        self._quest_teleport_active = False
        self._quest_menu_perceiver = quest_menu_perceiver
        self._quest_input_dispatcher = QuestInputDispatcher(input_adapter, window_handle)
        self._respawn_menu_perceiver = respawn_menu_perceiver
        self._respawn_dispatcher = RespawnInputDispatcher(input_adapter, window_handle)
        self._respawn_dispatched = False
        self._pathing = pathing
        if self._pathing is not None:
            update_tactical_parameters = getattr(self._pathing, "update_tactical_parameters", None)
            if callable(update_tactical_parameters):
                update_tactical_parameters(self._tactical_parameters)
        attach_geometry = getattr(self._pipeline, "attach_world_geometry", None)
        if callable(attach_geometry):
            attach_geometry(pathing)
        self._pathing_dispatcher = PathingInputDispatcher(input_adapter, window_handle)
        self._dashboard_feed = dashboard_feed
        self._mode = FarmingMode.PAUSED
        self._state = _initial_world_state()
        self._last_frame: CapturedFrame | None = None
        self._window_status = WindowStatus.NOT_FOREGROUND
        self._has_live_frame = False
        self._engagement_break: EngagementBreakReason | None = None
        self._engaged_monster_name: str | None = None
        self._target_reconciliation = TargetReconciliation(TargetAgreement.NO_AUTHORITATIVE_PROFILE)
        self._camera_aligner = camera_aligner
        if self._camera_aligner is not None:
            update_tactical_parameters = getattr(
                self._camera_aligner, "update_tactical_parameters", None
            )
            if callable(update_tactical_parameters):
                update_tactical_parameters(self._tactical_parameters)
        self._alignment_failure: CameraAlignmentStatus | None = None
        self._mode_after_alignment = FarmingMode.SEARCHING
        self._kill_goals = kill_goals or KillGoalTracker()
        self._quest_queue = quest_queue
        self._on_target_classes_changed = on_target_classes_changed
        self._client_close_requested = False
        self._event_logger = event_logger
        self._foreground_window_info = foreground_window_info
        self._last_capture_error: FrameCaptureErrorCode | None = None
        self._emergency_recovery_started_at_seconds: float | None = None
        self._emergency_teleport_unavailable = False
        self._telemetry = telemetry
        self._dungeon_provider = dungeon_provider
        self._dungeon_snapshots: tuple[DungeonStateSnapshot, ...] | None = None
        self._telemetry_observed_at_seconds: float | None = None
        self._pending_target_click: CombatDecision | None = None
        self._session_active = False
        self._pathing_engagement_distance = self._tactical_parameters.engagement_distance_units
        self._pathing_engagement_profile: CombatClassProfile = MELEE_COMBAT_CLASS_PROFILE
        self._policy_mode = self._config.policy_mode
        self._learned_policy: LearnedPolicyProtocol | None = None
        self._policy_load_fault: PolicyFault | None = None
        self._policy_runner = PolicyRunner(None)
        self._policy_fault: PolicyFault | None = None
        self._policy_attack_point_override: AttackPointAction | None = None
        self._tactical_parameter_diagnostics: tuple[TacticalParameterDiagnostic, ...] = (
            self._tactical_parameters.diagnostics
        )
        self._last_policy_action: TargetAction | AttackPointAction | None = None
        self._load_learned_policy(self._config.policy_model_directory)
        self._readiness_gate = LiveReadinessGate()
        self._player_stats_unsupported_since_seconds: float | None = None
        self._readiness = LiveReadinessStatus()
        self._readiness_was_blocked = False
        self._clock = clock
        self._autopilot = AutopilotSessionController(self._config.autopilot)
        self._death_detector = DeathDetector()
        self._orderly_stop_requested = False
        self._session_kills = 0
        self._completed_quests = 0
        self._configure_readiness_gate()

    @property
    def mode(self) -> FarmingMode:
        """Return the current session phase."""

        return self._mode

    @property
    def readiness(self) -> LiveReadinessStatus:
        """Return the immutable status produced for the most recently published tick."""

        return self._readiness

    def _configure_readiness_gate(self) -> None:
        registrations = (
            ProviderRegistration(LiveStateSource.WINDOW_FOREGROUND, FOREGROUND_FRESHNESS_SECONDS),
            ProviderRegistration(
                LiveStateSource.PERCEPTION_FRAME, PERCEPTION_FRAME_FRESHNESS_SECONDS
            ),
            ProviderRegistration(LiveStateSource.GPS, GPS_FRESHNESS_SECONDS),
            ProviderRegistration(LiveStateSource.CAMERA, CAMERA_FRESHNESS_SECONDS),
            ProviderRegistration(LiveStateSource.PLAYER_STATS, PLAYER_STATS_FRESHNESS_SECONDS),
            ProviderRegistration(LiveStateSource.DUNGEON_STATE, DUNGEON_STATE_FRESHNESS_SECONDS),
        )
        for registration in registrations:
            self._readiness_gate.register_provider(registration)
        self._readiness_gate.register_capability(
            CapabilityRequirement(
                SessionCapability.READ_ONLY_PREVIEW,
                frozenset({LiveStateSource.PERCEPTION_FRAME}),
                blocks_session_actions=False,
            )
        )
        self._readiness_gate.register_capability(
            CapabilityRequirement(
                SessionCapability.CAMERA_ALIGNMENT,
                frozenset({LiveStateSource.WINDOW_FOREGROUND, LiveStateSource.PERCEPTION_FRAME}),
                blocks_session_actions=False,
            )
        )
        player_stats_enabled = bool(getattr(self._pipeline, "has_player_stats_provider", False))
        combat_sources = {
            LiveStateSource.WINDOW_FOREGROUND,
            LiveStateSource.PERCEPTION_FRAME,
        }
        if player_stats_enabled:
            combat_sources.add(LiveStateSource.PLAYER_STATS)
        self._readiness_gate.register_capability(
            CapabilityRequirement(SessionCapability.COMBAT, frozenset(combat_sources))
        )
        if player_stats_enabled:
            self._readiness_gate.register_capability(
                CapabilityRequirement(
                    SessionCapability.VITALS,
                    frozenset({LiveStateSource.WINDOW_FOREGROUND, LiveStateSource.PLAYER_STATS}),
                )
            )
        if self._pathing is not None:
            navigation_sources = {
                LiveStateSource.WINDOW_FOREGROUND,
                LiveStateSource.PERCEPTION_FRAME,
                LiveStateSource.GPS,
            }
            if bool(getattr(self._pathing, "has_camera_provider", False)):
                navigation_sources.add(LiveStateSource.CAMERA)
            self._readiness_gate.register_capability(
                CapabilityRequirement(SessionCapability.NAVIGATION, frozenset(navigation_sources))
            )
        if self._dungeon_provider is not None:
            self._readiness_gate.register_capability(
                CapabilityRequirement(
                    SessionCapability.DUNGEON_AUTOMATION,
                    frozenset({LiveStateSource.WINDOW_FOREGROUND, LiveStateSource.DUNGEON_STATE}),
                )
            )

    def _evaluate_readiness(self, at_seconds: float) -> LiveReadinessStatus:
        self._refresh_readiness_samples(at_seconds)
        self._readiness = self._readiness_gate.evaluate(at_seconds)
        return self._readiness

    def _refresh_readiness_samples(self, at_seconds: float) -> None:
        foreground = self._input_adapter.is_foreground(self._window_handle)
        self._readiness_gate.update(
            LiveProviderSample(
                LiveStateSource.WINDOW_FOREGROUND,
                ProviderHealth.HEALTHY if foreground else ProviderHealth.UNAVAILABLE,
                at_seconds,
                "ok" if foreground else "window_not_foreground",
            )
        )
        self._readiness_gate.update(
            LiveProviderSample(
                LiveStateSource.PERCEPTION_FRAME,
                ProviderHealth.HEALTHY if self._has_live_frame else ProviderHealth.UNAVAILABLE,
                self._state.observed_at_seconds if self._has_live_frame else at_seconds,
                "ok"
                if self._has_live_frame
                else (
                    self._last_capture_error.value
                    if self._last_capture_error is not None
                    else "no_frame"
                ),
            )
        )
        self._update_navigation_readiness(at_seconds)
        self._update_player_stats_readiness(at_seconds)
        self._update_dungeon_readiness(at_seconds)

    def _update_navigation_readiness(self, at_seconds: float) -> None:
        pathing = self._pathing
        if pathing is None or not bool(getattr(pathing, "has_position_provider", False)):
            gps_sample = LiveProviderSample(
                LiveStateSource.GPS,
                ProviderHealth.UNAVAILABLE,
                at_seconds,
                "not_configured",
            )
        elif pathing.is_gps_available:
            gps_sample = LiveProviderSample(
                LiveStateSource.GPS,
                ProviderHealth.HEALTHY,
                pathing.live_sampled_at_seconds,
                "ok",
            )
        else:
            error_code = pathing.position_error_code
            gps_sample = LiveProviderSample(
                LiveStateSource.GPS,
                _position_provider_health(error_code),
                at_seconds,
                error_code.value if error_code is not None else "unavailable",
            )
        self._readiness_gate.update(gps_sample)
        if pathing is None or not bool(getattr(pathing, "has_camera_provider", False)):
            camera_sample = LiveProviderSample(
                LiveStateSource.CAMERA,
                ProviderHealth.UNAVAILABLE,
                at_seconds,
                "not_configured",
            )
        elif pathing.camera_state is not None:
            camera_sample = LiveProviderSample(
                LiveStateSource.CAMERA,
                ProviderHealth.HEALTHY,
                pathing.camera_sampled_at_seconds,
                "ok",
            )
        else:
            camera_error_code = pathing.camera_error_code
            camera_sample = LiveProviderSample(
                LiveStateSource.CAMERA,
                _camera_provider_health(camera_error_code),
                at_seconds,
                camera_error_code.value if camera_error_code is not None else "unavailable",
            )
        self._readiness_gate.update(camera_sample)

    def _update_player_stats_readiness(self, at_seconds: float) -> None:
        if not bool(getattr(self._pipeline, "has_player_stats_provider", False)):
            sample = LiveProviderSample(
                LiveStateSource.PLAYER_STATS,
                ProviderHealth.UNAVAILABLE,
                at_seconds,
                "not_configured",
            )
        else:
            snapshot = self._state.player_stats_snapshot
            if snapshot is None:
                sample = LiveProviderSample(
                    LiveStateSource.PLAYER_STATS,
                    ProviderHealth.UNAVAILABLE,
                    at_seconds,
                    "no_sample",
                )
            elif snapshot.source is PlayerStatsSource.CLIENT_MEMORY:
                required_fields = {"hp", "mp", "fp"}
                if required_fields.issubset(snapshot.field_values):
                    health = ProviderHealth.HEALTHY
                    diagnostic = "ok"
                else:
                    health = ProviderHealth.MALFORMED
                    diagnostic = "required_fields_missing"
                sample = LiveProviderSample(
                    LiveStateSource.PLAYER_STATS,
                    health,
                    snapshot.sampled_at_seconds,
                    diagnostic,
                )
            else:
                error_code = snapshot.error.code if snapshot.error is not None else None
                sample = LiveProviderSample(
                    LiveStateSource.PLAYER_STATS,
                    _player_stats_provider_health(error_code),
                    at_seconds,
                    error_code.value if error_code is not None else "unavailable",
                )
        self._readiness_gate.update(sample)
        self._track_player_stats_fallback(sample.health, at_seconds)

    def _track_player_stats_fallback(self, health: ProviderHealth, at_seconds: float) -> None:
        """Give up on client-memory statistics this client build has never supported.

        Only an ``UNSUPPORTED`` result describes the build itself; a window that lost focus or
        a handle that dropped reports ``UNAVAILABLE`` and keeps its chance to recover.
        """

        if health is not ProviderHealth.UNSUPPORTED:
            self._player_stats_unsupported_since_seconds = None
            return
        since = self._player_stats_unsupported_since_seconds
        if since is None:
            self._player_stats_unsupported_since_seconds = at_seconds
            return
        if at_seconds - since >= PLAYER_STATS_FALLBACK_GRACE_SECONDS:
            self._demote_player_stats_to_hud()

    def _demote_player_stats_to_hud(self) -> None:
        """Fall back to the visual HUD when this client build has no verified stats profile.

        An unsupported profile can never start working during the session, so keeping combat
        and vitals blocked on it would stall autonomous farming for good (US-085).
        """

        if not self._readiness_gate.demote_source(LiveStateSource.PLAYER_STATS):
            return
        demote = getattr(self._pipeline, "demote_player_stats_provider", None)
        if callable(demote):
            demote()
        if self._event_logger is not None:
            self._event_logger.record(
                SessionEventKind.CAPABILITY_DEGRADED,
                self._mode.value,
                previous_mode=self._mode.value,
                reason=PLAYER_STATS_HUD_FALLBACK_REASON,
            )

    def _update_dungeon_readiness(self, at_seconds: float) -> None:
        provider = self._dungeon_provider
        if provider is None:
            sample = LiveProviderSample(
                LiveStateSource.DUNGEON_STATE,
                ProviderHealth.UNAVAILABLE,
                at_seconds,
                "not_configured",
            )
        else:
            self._dungeon_snapshots = provider.poll(at_seconds)
            diagnostic = provider.last_diagnostic
            if diagnostic is None:
                sample = LiveProviderSample(
                    LiveStateSource.DUNGEON_STATE,
                    ProviderHealth.HEALTHY,
                    at_seconds,
                    "ok",
                )
            else:
                status = getattr(diagnostic, "status", None)
                sample = LiveProviderSample(
                    LiveStateSource.DUNGEON_STATE,
                    _dungeon_provider_health(status),
                    at_seconds,
                    status.value if isinstance(status, DungeonReadStatus) else "unavailable",
                )
        self._readiness_gate.update(sample)

    def _set_mode(
        self,
        new_mode: FarmingMode,
        *,
        kind: SessionEventKind = SessionEventKind.MODE_TRANSITION,
        reason: str | None = None,
        foreground: ForegroundWindowInfo | None = None,
    ) -> None:
        if new_mode is self._mode:
            return
        previous = self._mode
        self._mode = new_mode
        if self._event_logger is not None:
            self._event_logger.record(
                kind,
                new_mode.value,
                previous_mode=previous.value,
                reason=reason,
                foreground_window_title=foreground.title if foreground is not None else None,
                foreground_window_process=(
                    foreground.process_name if foreground is not None else None
                ),
            )

    def start(self) -> None:
        """Allow cooperative ticks to resume unless an emergency stop is active."""

        if self._mode is FarmingMode.EMERGENCY_STOPPED:
            return
        self._session_active = True
        self._alignment_failure = None
        self._emergency_teleport_unavailable = False
        self._emergency.reset()
        if self._telemetry is not None:
            self._telemetry.start(
                active_spawn_zone=(
                    self._pathing.active_spawn_zone_metadata if self._pathing is not None else None
                ),
                tactical_parameter_schema_version=TACTICAL_PARAMETER_SCHEMA_VERSION,
                tactical_parameter_digest=self._tactical_parameters.content_digest,
            )
        if self._config.auto_align_camera and self._camera_aligner is not None:
            self._mode_after_alignment = FarmingMode.SEARCHING
            self._set_mode(FarmingMode.ALIGNING, reason="session_start")
            return
        self._set_mode(FarmingMode.SEARCHING, reason="session_start")

    def arm_autopilot(self) -> None:
        """Arm one self-directed session and immediately arbitrate its first goal."""

        if self._mode is FarmingMode.EMERGENCY_STOPPED:
            return
        now = self._clock()
        self._autopilot.arm(now)
        self._orderly_stop_requested = False
        self._session_kills = 0
        self._completed_quests = 0
        self._record_event(SessionEventKind.AUTOPILOT_ARMED, AUTOPILOT_ARMED_REASON)
        self._arbitrate_autopilot_goal()
        self.start()

    @property
    def autopilot_snapshot(self) -> AutopilotSnapshot:
        """Return immutable unattended-session state for the dashboard."""

        return self._autopilot.snapshot(self._clock())

    def request_camera_alignment(self) -> None:
        """Queue one on-demand alignment that the next tick performs on its worker thread."""

        if self._mode not in {FarmingMode.PAUSED, FarmingMode.COMPLETED}:
            raise RuntimeError("Camera alignment can only be requested while farming is paused.")
        if self._camera_aligner is None:
            return
        self._alignment_failure = None
        self._mode_after_alignment = self._mode
        self._set_mode(FarmingMode.ALIGNING, reason="operator_request")

    def configure_auto_align(self, enabled: bool) -> None:
        """Toggle the pre-flight camera alignment performed when a session starts."""

        self._config = replace(self._config, auto_align_camera=enabled)

    def pause(
        self,
        *,
        kind: SessionEventKind = SessionEventKind.MODE_TRANSITION,
        reason: str | None = None,
        foreground: ForegroundWindowInfo | None = None,
        manual: bool = True,
    ) -> None:
        """Pause without sending any compensating input to the client."""

        if manual:
            self._session_active = False
            if self._autopilot.armed:
                self._autopilot.disarm()
                self._record_event(
                    SessionEventKind.AUTOPILOT_DISARMED, reason or OPERATOR_PAUSE_REASON
                )
        if self._mode is not FarmingMode.EMERGENCY_STOPPED:
            self._set_mode(FarmingMode.PAUSED, kind=kind, reason=reason, foreground=foreground)

    def emergency_stop(self, *, reason: str | None = None) -> None:
        """Latch a session-local emergency stop until a new session is created."""

        self._session_active = False
        self._readiness_gate.emergency_stop()
        self._clear_armed_actions()
        self._set_mode(
            FarmingMode.EMERGENCY_STOPPED, kind=SessionEventKind.EMERGENCY_STOPPED, reason=reason
        )
        if self._pathing is not None:
            self._pathing.emergency_stop()
        close_pipeline = getattr(self._pipeline, "close", None)
        if callable(close_pipeline):
            close_pipeline()
        if self._dungeon_provider is not None:
            self._dungeon_provider.close()

    def handle_tick_fault(self, error: Exception) -> None:
        """Contain a worker tick fault in a visible, non-dispatching session state.

        The worker thread stays alive; what ends is the faulted tick. Held keys are released
        first, so a fault can never leave the character running into a wall (US-086).
        """

        previous = self._mode
        self._clear_armed_actions()
        if self._pathing is not None:
            self._pathing.emergency_stop()
        now = self._clock()
        budget_exhausted = self._autopilot.record_tick_fault(error, now)
        exhausted = self._autopilot.armed and budget_exhausted
        # An emergency stop and a completed budget are declared outcomes: a later fault is
        # still recorded, but it must not overwrite what ended the session.
        if self._mode not in TERMINAL_MODES:
            self._mode = FarmingMode.FAULTED
        if self._event_logger is not None:
            self._event_logger.record(
                SessionEventKind.TICK_FAULT,
                self._mode.value,
                previous_mode=previous.value,
                reason=TICK_FAULT_REASON,
                exception_type=type(error).__name__,
                exception_message=str(error),
            )
        if exhausted:
            self._complete_autopilot(AutopilotCompletionReason.TICK_FAULT_BUDGET, now)
        elif self._autopilot.armed:
            self._autopilot.begin_recovery(now)
        self._publish(False)

    def close(self) -> None:
        """Release external resources during application teardown."""

        self._readiness_gate.close()
        self._clear_armed_actions()
        if self._pathing is not None:
            self._pathing.close()
        close_pipeline = getattr(self._pipeline, "close", None)
        if callable(close_pipeline):
            close_pipeline()
        if self._dungeon_provider is not None:
            self._dungeon_provider.close()
        if self._telemetry is not None:
            self._telemetry.close()

    def _clear_armed_actions(self) -> None:
        """Discard ephemeral input intent while preserving durable session progress."""

        self._pending_target_click = None
        self._combat.reset()
        self._search.reset()
        self._reposition.reset()
        self._vitals.reset()
        self._powerups.halt()
        self._emergency.halt()
        self._approach_stalls.reset()
        self._engagement_break = None
        self._engaged_monster_name = None
        self._quest_teleport_active = False
        if self._quest_interaction is not None:
            self._quest_interaction.reset()
        if self._pathing is not None:
            block_pathing = getattr(self._pathing, "block_for_readiness", None)
            if callable(block_pathing):
                block_pathing()

    def configure_attack_key(self, virtual_key: int) -> None:
        """Apply one dashboard-selected attack key before a paused session starts."""

        if self._mode is not FarmingMode.PAUSED:
            raise RuntimeError("Attack key can only be configured while farming is paused.")
        combat = replace(self._config.combat, rotation=(KeyBinding(virtual_key),))
        self._config = replace(self._config, combat=combat)
        self._combat = CombatController(combat, tactical_parameters=self._tactical_parameters)

    def configure_combat_grace(self, target_acquisition_grace_seconds: float) -> None:
        """Apply a dashboard-selected target-click grace period mid-session."""

        combat = replace(
            self._config.combat,
            target_acquisition_grace_seconds=target_acquisition_grace_seconds,
        )
        self._config = replace(self._config, combat=combat)
        self._combat.update_config(combat)

    def configure_target_classes(self, allowed_class_names: frozenset[str]) -> None:
        """Restrict candidate selection to the operator-selected monster classes."""

        combat = replace(self._config.combat, allowed_class_names=allowed_class_names)
        self._config = replace(self._config, combat=combat)
        self._combat.update_config(combat)

    def configure_kill_goals(self, config: KillGoalConfig) -> None:
        """Apply the operator's monster selection and per-monster kill quotas."""

        self._kill_goals.update_config(config)
        self._client_close_requested = False
        self._apply_active_target_classes()

    @property
    def kill_goals(self) -> KillGoalTracker:
        """Expose the per-monster quota progress of this session."""

        return self._kill_goals

    @property
    def quest_queue(self) -> QuestFarmingQueue | None:
        """Expose the quest queue this session is working through, when one is attached."""

        return self._quest_queue

    def configure_quest_queue(self, queue: QuestFarmingQueue | None) -> None:
        """Adopt a quest queue and bind the session to its first quest."""

        self._quest_queue = queue
        self._client_close_requested = False
        if queue is None:
            self._quest_interaction = None
            return
        active = queue.active
        if active is not None:
            self._bind_quest(active)

    @property
    def policy_objective(self) -> HierarchicalObjective | None:
        """Return the goal the tactical policy is currently conditioned on."""

        return self._policy_runner.objective

    @property
    def quest_goals(self) -> QuestGoalSequence | None:
        """Expose the ordered goal sequence of the quest this session is executing."""

        return self._quest_goals

    def _bind_quest(self, resolution: QuestResolution) -> None:
        """Resolve one quest into its ordered goal sequence and pursue its first goal."""

        self._quest_goals = QuestGoalSequence(resolution, timeouts=self._config.quest_goal_timeouts)
        self._quest_goals.begin(self._state.observed_at_seconds)
        self._quest_interaction = QuestInteractionController(
            resolution,
            dialogue_perceiver=self._quest_menu_perceiver,
        )
        self._quest_teleport_active = False
        self._quest_travel_index = None
        self._apply_active_goal()

    def _apply_active_goal(self) -> None:
        """Derive the whitelist, the patrol zones, the leash and the policy objective.

        Everything a tactical decision is allowed to see about the current step of a quest
        comes from here, so a change of active goal changes all of it in one place.
        """

        sequence = self._quest_goals
        if sequence is None:
            return
        resolution = sequence.resolution
        goal = sequence.active
        if goal is None:
            self._kill_goals.update_config(
                KillGoalConfig(
                    quotas=tuple(
                        MobKillQuota(monster, required)
                        for monster, required in resolution.required_kills
                    )
                )
            )
            self._apply_active_target_classes()
            self._apply_patrol_zones(resolution.zones, resolution.zone_goals)
            return
        self._kill_goals.update_config(kill_goal_config_for(goal, resolution))
        self._apply_active_target_classes()
        self._apply_patrol_zones(
            patrol_zones_for(goal, resolution), zone_goals_for(goal, resolution)
        )
        self._apply_goal_leash(goal)
        self._apply_policy_objective()

    def _apply_patrol_zones(
        self,
        zones: tuple[VectorSpawnZone, ...],
        goals: tuple[ZoneGoal, ...],
    ) -> None:
        """Replace the navigator's camp selection with the active goal's spawn zones."""

        pathing = self._pathing
        if pathing is None or not zones:
            return
        navigator = pathing.vector_navigator
        if navigator is None:
            return
        navigator.set_preferred_zones(zones)
        navigator.set_goals(goals)
        # Re-attaching the same navigator is how the pathing controller is told to drop the
        # route it is following and plan a fresh one towards the new camp.
        pathing.attach_vector_navigator(navigator)

    def _apply_goal_leash(self, goal: QuestGoal) -> None:
        """Anchor the targeting leash on the active objective's resolved spawn zone."""

        pathing = self._pathing
        if pathing is None:
            return
        leash = leash_for(goal)
        if leash is None:
            pathing.set_objective_leash(None)
            return
        pathing.set_objective_leash(leash[0], leash[1])

    def _apply_policy_objective(self) -> None:
        """Condition the tactical policy on the goal the session is actually pursuing."""

        sequence = self._quest_goals
        if sequence is None:
            return
        goal = sequence.active
        identity = sequence.identity()
        if goal is None or identity is None:
            return
        self._policy_runner.set_objective(
            hierarchical_objective_for(
                goal,
                identity,
                destination_reached=self._reached_goal_destination(goal),
            )
        )

    def _reached_goal_destination(self, goal: QuestGoal) -> bool:
        """Return whether live GPS proves the character stands at the goal's destination."""

        pathing = self._pathing
        position = None if pathing is None else pathing.live_position
        destination = goal.destination
        if position is None or destination is None:
            return False
        zone = goal.spawn_zone
        if zone is not None:
            return zone.contains(WorldCoordinate(position.x, position.z))
        npc = goal.npc
        if npc is not None:
            return npc.is_interactable_from(position)
        return False

    def _apply_active_target_classes(self) -> None:
        allowed = self._kill_goals.active_class_names
        self.configure_target_classes(allowed)
        # The classes that still owe a quota are worth more than the ones that do not, and
        # ranking is where that difference has to be visible (US-083 AC8).
        self._combat.configure_quota_classes(allowed)
        if self._on_target_classes_changed is not None:
            self._on_target_classes_changed(allowed)

    def configure_kill_verification(self, enabled: bool) -> None:
        """Toggle HUD monster-stats kill-count confirmation mid-session."""

        combat = replace(self._config.combat, kill_verification_enabled=enabled)
        self._config = replace(self._config, combat=combat)
        self._combat.update_config(combat)

    def configure_policy_mode(self, mode: PolicyRuntimeMode | str) -> None:
        """Select the runtime tactical-policy mode and reset fallback telemetry."""

        selected_mode = (
            mode if isinstance(mode, PolicyRuntimeMode) else PolicyRuntimeMode(str(mode).upper())
        )
        self._policy_mode = selected_mode
        self._policy_fault = None
        self._policy_runner.reset_fault()

    def configure_policy_model_directory(self, directory: str | None) -> None:
        """Point the session at a trained artifact directory while it is paused."""

        if self._mode not in {FarmingMode.PAUSED, FarmingMode.COMPLETED}:
            raise RuntimeError("A policy model can only be selected while farming is paused.")
        self._config = replace(self._config, policy_model_directory=directory)
        self._policy_fault = None
        self._load_learned_policy(directory)

    @property
    def policy_fault(self) -> PolicyFault | None:
        """Return the fault that halted learned automation, if any."""

        return self._policy_fault

    @property
    def learned_policy_available(self) -> bool:
        """Return whether a learned artifact is loaded and servable."""

        return self._learned_policy is not None

    def _load_learned_policy(self, directory: str | None) -> None:
        """Load the configured artifact, or record why learned automation cannot run."""

        self._learned_policy = None
        if not directory:
            self._policy_load_fault = PolicyFault(
                PolicyFaultCode.MODEL_UNAVAILABLE, POLICY_MODEL_NOT_CONFIGURED
            )
        else:
            try:
                model_directory = Path(directory)
                learned: LearnedPolicyProtocol
                if (model_directory / HIERARCHICAL_METADATA_NAME).is_file():
                    from flyff_bot.features.policy.hierarchical_onnx import HierarchicalOnnxPolicy

                    learned = HierarchicalOnnxPolicy(model_directory)
                else:
                    from flyff_bot.features.policy.learned import LearnedPolicy

                    learned = LearnedPolicy(model_directory)
                learned.warm_up()
            except ContractVersionError as error:
                self._policy_load_fault = PolicyFault.from_contract_error(error)
            except (OSError, ValueError) as error:
                self._policy_load_fault = PolicyFault(
                    PolicyFaultCode.MODEL_UNAVAILABLE, str(error) or type(error).__name__
                )
            else:
                self._learned_policy = learned
                self._policy_load_fault = None
        self._policy_runner = PolicyRunner(self._learned_policy, load_fault=self._policy_load_fault)

    @property
    def target_reconciliation(self) -> TargetReconciliation:
        """Return whether the client and the engaged detection agree on the target."""

        return self._target_reconciliation

    def _policy_candidates(self) -> tuple[PolicyCandidate, ...]:
        candidates = self._combat._eligible_candidates(self._state)
        allowed = self._config.combat.allowed_class_names
        eligible_positions = [
            index
            for index, mob in enumerate(candidates)
            if not allowed or mob.class_name in allowed
        ]
        return tuple(
            PolicyCandidate(
                mob=mob,
                is_alive_and_recognized=bool(mob.confidence) and bool(mob.class_name),
                is_unlocked=True,
                is_within_leash=mob.navmesh_within_leash is not False,
                is_navmesh_reachable=mob.navmesh_reachable is not False,
                has_valid_world_position=(
                    mob.world_x is not None and mob.world_y is not None and mob.world_z is not None
                ),
                original_position=index,
                candidate_identity=mob.candidate_index,
            )
            for index in eligible_positions
            for mob in (candidates[index],)
        )

    def _policy_context(self, candidates: tuple[PolicyCandidate, ...]) -> PolicyContext:
        """Build the decision-time options, features, and live world facts for a policy."""

        return PolicyContext(
            candidates,
            self._config.combat.allowed_class_names,
            tuple(not candidate.is_unlocked for candidate in candidates),
            feature_matrix(self._policy_feature_rows(candidates)),
            valid_attack_points=self._policy_attack_points(candidates),
            live_state=self._live_observation_state(),
            grounding=self._session_grounding(),
        )

    def _decision_artifact_version(self) -> str:
        """Return the artifact that produced this decision, or empty for the heuristic path.

        Empty rather than a placeholder name: the deterministic path is not a model, and
        giving it a version would let it be compared against one in a promotion report.
        """

        if self._policy_mode is PolicyRuntimeMode.HEURISTIC or self._learned_policy is None:
            return ""
        return current_contract_stamp().contract_version

    def _strategic_action_mask(self) -> tuple[bool, ...]:
        """Return which strategic goals were legal when this decision was taken.

        A recorded choice cannot be evaluated without knowing what else was on offer: the
        same action is a good decision among three options and a forced one among one.
        """

        grounding = self._session_grounding()
        legality = {
            StrategicGoalKind.TARGET: can_engage_targets(grounding),
            StrategicGoalKind.NAVIGATE: can_navigate(grounding),
            StrategicGoalKind.INTERACT: can_interact(grounding),
            StrategicGoalKind.WAIT: True,
        }
        return tuple(legality.get(goal, False) for goal in STRATEGIC_GOAL_ORDER)

    def _session_grounding(self) -> SessionGrounding:
        """Describe the facts that decide which goals can be grounded this tick (US-083).

        Read from the live session rather than assumed: an unmeasured fact keeps its
        least-capable default, which narrows the offered options instead of claiming a
        capability the session cannot actually ground.
        """

        pathing = self._pathing
        sequence = self._quest_goals
        goal = None if sequence is None else sequence.active
        identity = None if sequence is None else sequence.identity()
        return SessionGrounding(
            world_id=None if pathing is None else pathing.observed_world_id,
            objective_id=None if goal is None or identity is None else str(identity),
            has_route=pathing is not None and bool(pathing.world_waypoints),
            teleport_in_progress=self._quest_teleport_active,
            # The dungeon registry is intentionally empty until one is extracted, so the goal
            # stays unoffered rather than being ranked against nothing.
            dungeon_available=bool(self._dungeon_snapshots),
            is_engaged=self._engaged_monster_name is not None,
            # An engagement that cannot cast is an engagement that stalls, so a configured
            # resource floor is part of whether attacking is grounded at all.
            has_skill_resources=(
                self._state.player_vitals.mp_percentage
                >= self._tactical_parameters.mp_threshold_percent
            ),
            blocked_capabilities=frozenset(
                item.capability for item in self._readiness.capabilities if item.blocked
            ),
        )

    def _policy_attack_points(
        self, candidates: tuple[PolicyCandidate, ...]
    ) -> tuple[AttackPointAction, ...]:
        """Offer only bounded, NavMesh-contained distance choices to a learned policy."""

        pathing = self._pathing
        if pathing is None:
            return ()
        definition = TACTICAL_PARAMETER_DEFINITIONS[TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS]
        options: list[AttackPointAction] = []
        for candidate in candidates:
            base = self._tactical_parameters.engagement_distance_for(candidate.mob.class_name)
            distances = {
                definition.normalize(base * multiplier)[0]
                for multiplier in TACTICAL_APPROACH_DISTANCE_MULTIPLIERS
            }
            for distance in sorted(distances):
                planned = pathing.plan_tactical_attack_point(candidate.mob, distance)
                if planned is None:
                    continue
                point, angle = planned
                options.append(
                    AttackPointAction(
                        candidate.mob.class_id,
                        (point.x, point.y, point.z),
                        angle,
                        candidate.original_position,
                        distance,
                    )
                )
        return tuple(options)

    def _policy_feature_rows(
        self, candidates: tuple[PolicyCandidate, ...]
    ) -> tuple[dict[str, float | None], ...]:
        """Build one decision-time feature row per candidate in the trained column order.

        A quantity that only exists after the bot has travelled -- the observed heading and the
        planned corridor geometry -- is genuinely unobserved while the target is still being
        chosen, so it stays missing rather than being replaced by a fabricated number.
        """

        player = self._pathing.live_position if self._pathing is not None else None
        origin = None if player is None else (player.x, player.y, player.z)
        reachable = sum(1 for item in candidates if item.mob.navmesh_path_distance is not None)
        nearby = self._nearby_candidate_count(candidates, origin)
        return tuple(
            candidate_feature_row(
                path_distance=item.mob.navmesh_path_distance,
                relative_distance=_world_distance(origin, item.mob),
                relative_elevation=_world_elevation(origin, item.mob),
                player_heading=None,
                target_bearing=_world_bearing(origin, item.mob),
                terrain_slope=route_slope(origin, _mob_point(item.mob)),
                corridor=None,
                target_class_id=float(item.mob.class_id),
                detection_confidence=item.mob.confidence,
                visible_mob_count=float(len(candidates)),
                reachable_mob_count=float(reachable),
                nearby_targetable_mob_count=nearby,
                recent_kill_rate=None,
                recent_stuck_rate=None,
                decision_latency_ms=None,
            )
            for item in candidates
        )

    @staticmethod
    def _nearby_candidate_count(
        candidates: tuple[PolicyCandidate, ...], origin: tuple[float, float, float] | None
    ) -> float | None:
        measured = [
            distance
            for item in candidates
            if (distance := _world_distance(origin, item.mob)) is not None
        ]
        if not measured:
            return None
        return float(sum(1 for value in measured if value <= NEARBY_CANDIDATE_DISTANCE_UNITS))

    def _live_observation_state(self) -> LiveObservationState | None:
        """Return the measured kinematics and NavMesh context, or ``None`` without live GPS."""

        pathing = self._pathing
        position = None if pathing is None else pathing.live_position
        if pathing is None or position is None:
            return None
        heading_radians = math.radians(pathing.heading_degrees)
        navmesh = pathing.navmesh
        polygon_id = None if navmesh is None else navmesh.polygon_or_region_id(position)
        return LiveObservationState(
            PlayerKinematics(position.x, position.y, position.z, heading_radians),
            NavMeshContext(
                None if polygon_id is None else str(polygon_id),
                pathing.terrain_slope,
                _route_distance(position, pathing.world_waypoints),
            ),
            recent_stuck_count=int(self._state.is_stuck),
        )

    def _evaluate_policy_target(self) -> VisibleMob | None:
        """Return a policy-selected candidate only when every deterministic mask passes."""

        self._policy_attack_point_override = None
        if self._policy_mode is PolicyRuntimeMode.HEURISTIC:
            return None
        candidates = self._policy_candidates()
        if not any(candidate.is_eligible for candidate in candidates):
            # Nothing legal to choose between is an empty option set, not a serving failure:
            # the deterministic search path keeps running and no fault is raised.
            self._last_policy_action = None
            return None
        context = self._policy_context(candidates)
        self._bind_policy_objective()
        action = self._policy_runner.evaluate(self._state, context)
        fault = self._policy_runner.last_fault
        if fault is not None:
            self._record_policy_fault(fault)
            return None
        self._autopilot.clear_policy_faults()
        self._last_policy_action = (
            action if isinstance(action, TargetAction | AttackPointAction) else None
        )
        if self._policy_mode is PolicyRuntimeMode.ML_SHADOW or not isinstance(
            action, TargetAction | AttackPointAction
        ):
            return None
        if isinstance(action, TargetAction) and action.attack_point is not None:
            self._policy_attack_point_override = action.attack_point
        if isinstance(action, AttackPointAction):
            self._policy_attack_point_override = action
        return next(
            (
                candidate.mob
                for candidate in candidates
                if candidate.original_position == action.candidate_index
            ),
            None,
        )

    def _bind_policy_objective(self) -> None:
        """Hand the active quest or farming objective to a hierarchical learned policy."""

        configure = getattr(self._learned_policy, "configure_objective", None)
        if not callable(configure):
            return
        queue = self._quest_queue
        quest = None if queue is None else queue.active
        if quest is None:
            configure(HierarchicalObjective())
            return
        configure(
            HierarchicalObjective(
                HierarchicalObjectiveKind.QUEST,
                quest_id=quest.quest.quest_id,
                target_class_names=frozenset(name for name, _count in quest.required_kills),
            )
        )

    def _record_policy_fault(self, fault: PolicyFault) -> None:
        """Let one serving failure cost its decision rather than the session (US-086).

        An unloadable model can never start working, so it still halts the session the way
        BUG-031 requires. Every other fault discards the decision it produced, is counted, and
        lets the tick fall through to the deterministic path. Only a run of consecutive faults
        beyond the configured budget demotes learned automation, and farming then continues
        heuristically instead of stopping.
        """

        self._policy_fault = fault
        self._last_policy_action = None
        if fault.code is PolicyFaultCode.MODEL_UNAVAILABLE:
            self._halt_learned_automation(fault)
            return
        if self._autopilot.record_policy_fault():
            self._demote_learned_automation(fault)

    def _demote_learned_automation(self, fault: PolicyFault) -> None:
        """Keep farming deterministically instead of presenting heuristics as learned."""

        self._autopilot.clear_policy_faults()
        if self._policy_mode is PolicyRuntimeMode.HEURISTIC:
            return
        self._policy_mode = PolicyRuntimeMode.HEURISTIC
        if self._event_logger is not None:
            self._event_logger.record(
                SessionEventKind.CAPABILITY_DEGRADED,
                self._mode.value,
                previous_mode=self._mode.value,
                reason=f"{LEARNED_POLICY_HALTED_REASON}:{fault.reason}",
            )

    def _halt_learned_automation(self, fault: PolicyFault) -> None:
        """Stop learned automation instead of presenting heuristic behaviour as learned.

        A shadow session was never steered by the model, so dropping back to the declared
        heuristic mode is enough. An active session was, and is paused. Either way the fault is
        published for the operator rather than absorbed silently (BUG-031).
        """

        was_active = self._policy_mode is PolicyRuntimeMode.ML_ACTIVE
        self._policy_fault = fault
        self._last_policy_action = None
        self._policy_mode = PolicyRuntimeMode.HEURISTIC
        if was_active:
            self.pause(
                kind=SessionEventKind.MODE_TRANSITION,
                reason=f"{LEARNED_POLICY_HALTED_REASON}:{fault.reason}",
                manual=False,
            )

    def configure_vitals(self, config: VitalsTriggerConfig) -> None:
        """Apply vitals trigger configuration before or during a session."""

        self._config = replace(self._config, vitals=config)
        self._vitals.update_config(config)
        parameters = self._tactical_parameters
        hp = config.rule_for(VitalTriggerType.HP)
        mp = config.rule_for(VitalTriggerType.MP)
        if hp is not None:
            parameters = parameters.with_value(
                TacticalParameterName.HP_POTION_THRESHOLD_PERCENT,
                hp.threshold_percentage,
            ).with_value(
                TacticalParameterName.RECOVERY_DEBOUNCE_SECONDS,
                hp.debounce_seconds,
            )
        if mp is not None:
            parameters = parameters.with_value(
                TacticalParameterName.MP_THRESHOLD_PERCENT,
                mp.threshold_percentage,
            )
        self.configure_tactical_parameters(parameters)

    def reset_vitals(self) -> None:
        """Reset vitals debounce cooldowns."""

        self._vitals.reset()

    def configure_powerups(self, config: PowerUpConfig) -> None:
        """Apply timed power-up hotkeys before or during a session."""

        self._config = replace(self._config, powerups=config)
        self._powerups.update_config(config)

    def reset_powerups(self) -> None:
        """Restart every power-up countdown from zero."""

        self._powerups.reset()

    def configure_emergency_recovery(self, config: EmergencyRecoveryConfig) -> None:
        """Apply the unrecoverable-stuck timeout and teleport hotkey."""

        self._config = replace(self._config, emergency=config)
        self._emergency.update_config(config)
        self._emergency_teleport_unavailable = False

    def configure_vector_navigation(self, navigator: VectorZoneNavigator | None) -> None:
        """Adopt or drop the extracted world map that steers this session."""

        # The adopted map is also what declares how densely each mover spawns, so the
        # catalog join is re-read against the world actually being farmed (US-083).
        attach_spawn_zones = getattr(self._pipeline, "attach_spawn_zones", None)
        if callable(attach_spawn_zones):
            attach_spawn_zones(() if navigator is None else navigator.world_map.zones)
        # Adoption is the one moment the session knows which world its offline geometry
        # belongs to, so the world is sampled here rather than polled every tick (US-083).
        adopt_world_id = getattr(self._pipeline, "adopt_world_id", None)
        if callable(adopt_world_id):
            adopt_world_id(
                None
                if navigator is None or self._pathing is None
                else self._pathing.observe_world_id()
            )
        if self._pathing is not None:
            self._pathing.attach_vector_navigator(navigator)
            self._publish(False)

    def tick(self) -> FarmingTick:
        """Perform at most one perception, decision, and guarded-dispatch cycle."""

        if self._input_adapter.is_aborted():
            self.emergency_stop(reason="killswitch")
            self._readiness = self._readiness_gate.evaluate(self._state.observed_at_seconds)
            return self._publish(False)
        if self._mode is FarmingMode.ALIGNING:
            return self._run_alignment()
        if self._mode in STANDBY_MODES:
            self._powerups.halt()
            self._emergency.halt()
            emergency_stopped = self._mode is FarmingMode.EMERGENCY_STOPPED
            self._observe(poll_live_providers=not emergency_stopped)
            if self._pathing is not None and not emergency_stopped:
                self._pathing.track(self._state, self._last_frame)
            if emergency_stopped:
                self._readiness = self._readiness_gate.evaluate(self._state.observed_at_seconds)
                return self._publish(False)
            now = self._clock()
            if self._autopilot.armed and self._autopilot.time_exhausted(now):
                self._complete_autopilot(AutopilotCompletionReason.TIME_BUDGET, now)
                return self._publish(False)
            if self._mode is FarmingMode.DEAD:
                return self._publish(self._advance_dead_state())
            readiness = self._evaluate_readiness(self._state.observed_at_seconds)
            if self._autopilot.armed and self._autopilot.absence_exhausted(now):
                self._complete_autopilot(AutopilotCompletionReason.CLIENT_ABSENCE, now)
                return self._publish(False)
            if (
                self._session_active
                and self._mode in {FarmingMode.PAUSED, FarmingMode.FAULTED}
                and self._has_live_frame
                and not readiness.action_blocked
                and (not self._autopilot.armed or self._autopilot.recovery_due(now))
            ):
                self._readiness_was_blocked = False
                if self._autopilot.armed:
                    if self._autopilot.record_recovery(now):
                        self._complete_autopilot(AutopilotCompletionReason.RECOVERY_BUDGET, now)
                        return self._publish(False)
                    self._record_event(
                        SessionEventKind.RECOVERY_RESUMED, RECOVERY_BLOCKING_CONDITION_CLEARED
                    )
                    self._arbitrate_autopilot_goal()
                self._set_mode(FarmingMode.SEARCHING, reason="resumed_auto")
            return self._publish(False)
        if not self._input_adapter.is_foreground(self._window_handle):
            lookup_foreground = self._foreground_window_info
            foreground = lookup_foreground() if lookup_foreground is not None else None
            if self._pathing is not None:
                self._pathing.mark_gps_offline(PositionReadErrorCode.WINDOW_NOT_FOREGROUND)
            self._evaluate_readiness(self._state.observed_at_seconds)
            self._pause_for_readiness(
                kind=SessionEventKind.FOCUS_LOST,
                foreground=foreground,
                reason_override="focus_lost",
            )
            return self._publish(False)
        if not self._observe():
            self._evaluate_readiness(self._state.observed_at_seconds)
            self._pause_for_readiness(
                kind=SessionEventKind.FRAME_CAPTURE_ERROR,
                reason_override=(
                    self._last_capture_error.value if self._last_capture_error is not None else None
                ),
            )
            return self._publish(False)

        if self._mode is FarmingMode.TELEPORTING:
            if self._quest_teleport_active:
                return self._settle_quest_teleport()
            return self._settle_teleport()

        if self._pathing is not None:
            self._pathing.observe(self._state, self._last_frame)
            self._state = replace(
                self._state,
                is_stuck=self._pathing.is_stalled,
                visible_mobs=self._pathing.enrich_visible_mobs(self._state),
            )
            if self._telemetry is not None:
                self._telemetry.record_navigation_stall(stalled=self._pathing.is_stalled)
        readiness = self._evaluate_readiness(self._state.observed_at_seconds)
        if readiness.action_blocked:
            self._pause_for_readiness()
            return self._publish(False)
        self._readiness_was_blocked = False
        if self._observe_player_death():
            return self._publish(False)
        now = self._clock()
        if self._autopilot.armed and self._autopilot.time_exhausted(now):
            self._orderly_stop_requested = True
        if self._orderly_stop_requested and self._mode not in ENGAGEMENT_MODES:
            self._complete_autopilot(AutopilotCompletionReason.TIME_BUDGET, now)
            return self._publish(False)
        if self._goal_completed() and not self._autopilot.armed:
            self._complete_session()
            return self._publish(False)

        vitals_decision = self._vitals.step(self._state)
        if vitals_decision.triggered:
            dispatched = self._vitals_dispatcher.dispatch(vitals_decision)
            if dispatched:
                return self._publish(True)

        powerup_decision = self._powerups.step(self._state.observed_at_seconds)
        if powerup_decision.triggered and self._powerup_dispatcher.dispatch(powerup_decision):
            self._powerups.confirm(powerup_decision, self._state.observed_at_seconds)
            return self._publish(True)

        if self._advance_emergency_recovery():
            return self._publish(True)
        if self._mode in STANDBY_MODES:
            return self._publish(False)

        dispatched = self._advance()
        return self._publish(dispatched)

    def _record_event(self, kind: SessionEventKind, reason: str) -> None:
        """Record one diagnostic that reports a decision rather than a mode change."""

        if self._event_logger is not None:
            self._event_logger.record(
                kind,
                self._mode.value,
                previous_mode=self._mode.value,
                reason=reason,
            )

    def _arbitrate_autopilot_goal(self) -> None:
        """Choose and adopt the next self-directed goal without operator input.

        A turn-in goal is reported as a completed quest rather than as a continuation,
        because that is the decision the operator needs to see on the dashboard.
        """

        if not self._autopilot.armed:
            return
        sequence = self._quest_goals
        active_goal = None if sequence is None else sequence.active
        kind = None if active_goal is None else active_goal.kind
        completed_quest = kind in TURN_IN_GOAL_KINDS
        queue = self._quest_queue
        decision = arbitrate_goal(
            active_quest=kind is not None and not completed_quest,
            active_kill_objective=kind in OBJECTIVE_GOAL_KINDS,
            completed_quest=completed_quest,
            next_quest_available=(kind is None and queue is not None and queue.active is not None),
            fallback_zone_configured=self._config.autopilot.has_fallback_zone,
        )
        if decision is not None and decision.goal is AutopilotGoalKind.FALLBACK_FARM:
            self._apply_fallback_zone()
        if self._autopilot.choose_goal(decision):
            self._record_event(
                SessionEventKind.AUTOPILOT_GOAL,
                NO_EXECUTABLE_GOAL_REASON
                if decision is None
                else f"{decision.goal.value}:{decision.reason.value}",
            )

    def _apply_fallback_zone(self) -> None:
        """Farm the configured fallback monsters without an upper bound."""

        names = self._config.autopilot.fallback_monster_names
        if not names or self._kill_goals.active_class_names == frozenset(names):
            return
        self.configure_kill_goals(KillGoalConfig(quotas=tuple(MobKillQuota(n) for n in names)))

    def _complete_autopilot(self, reason: AutopilotCompletionReason, at_seconds: float) -> None:
        """End the session in an orderly way once a declared budget is exhausted."""

        self._session_active = False
        self._orderly_stop_requested = False
        self._clear_armed_actions()
        if self._pathing is not None:
            self._pathing.emergency_stop()
        self._autopilot.complete(
            reason,
            at_seconds,
            kills=self._session_kills,
            completed_quests=self._completed_quests,
        )
        self._set_mode(
            FarmingMode.COMPLETED,
            kind=SessionEventKind.BUDGET_EXHAUSTED,
            reason=reason.value,
        )

    def _observe_player_death(self) -> bool:
        """Enter the death state once a zero-HP dwell confirms the character died."""

        observed_at = self._state.observed_at_seconds
        if not self._death_detector.observe(self._state.player_vitals.hp_percentage, observed_at):
            return False
        self._clear_armed_actions()
        if self._pathing is not None:
            self._pathing.emergency_stop()
        self._respawn_dispatched = False
        budget_exhausted = self._autopilot.armed and self._autopilot.record_death(observed_at)
        self._set_mode(
            FarmingMode.DEAD,
            kind=SessionEventKind.PLAYER_DEATH,
            reason=DEATH_CONFIRMED_REASON,
        )
        if budget_exhausted:
            deaths = self._autopilot.deaths
            self._autopilot.disarm()
            self.pause(reason=f"{DEATH_BUDGET_EXHAUSTED_REASON}:{deaths}", manual=False)
        elif not self._autopilot.armed:
            # Without autopilot the operator owns the respawn, so the session waits.
            self._session_active = False
        return True

    def _advance_dead_state(self) -> bool:
        """Dispatch the observed revive option, or hand a confirmed respawn back to farming."""

        observed_at = self._state.observed_at_seconds
        if self._state.player_vitals.hp_percentage > DEAD_HP_PERCENTAGE:
            self._death_detector.reset()
            self._respawn_dispatched = False
            if not self._autopilot.armed:
                self._set_mode(FarmingMode.PAUSED, reason=RESPAWN_WAITING_FOR_OPERATOR_REASON)
                return False
            if self._autopilot.record_recovery(observed_at):
                self._complete_autopilot(AutopilotCompletionReason.RECOVERY_BUDGET, observed_at)
                return False
            self._record_event(SessionEventKind.RECOVERY_RESUMED, RESPAWN_CONFIRMED_REASON)
            self._arbitrate_autopilot_goal()
            self._set_mode(FarmingMode.SEARCHING, reason=RESPAWN_CONFIRMED_REASON)
            return False
        if (
            not self._autopilot.armed
            or self._respawn_dispatched
            or self._respawn_menu_perceiver is None
        ):
            return False
        observation = self._respawn_menu_perceiver.observe(self._last_frame)
        self._respawn_dispatched = self._respawn_dispatcher.dispatch(observation)
        return self._respawn_dispatched

    async def run(self, sleep: Callable[[float], Awaitable[object]] = asyncio.sleep) -> None:
        """Run cooperative ticks until paused, completed, or emergency-stopped."""

        while self._mode not in STANDBY_MODES:
            self.tick()
            if self._mode not in STANDBY_MODES:
                await sleep(self._config.tick_interval_seconds)

    def _run_alignment(self) -> FarmingTick:
        """Perform the blocking pre-flight alignment on the calling worker thread."""

        if self._camera_aligner is None:
            self._set_mode(self._mode_after_alignment, reason="alignment_skipped")
            return self._publish(False)
        if not self._observe():
            self._evaluate_readiness(self._state.observed_at_seconds)
            self._pause_for_readiness(
                kind=SessionEventKind.FRAME_CAPTURE_ERROR,
                reason_override=(
                    self._last_capture_error.value if self._last_capture_error is not None else None
                ),
            )
            return self._publish(False)
        self._evaluate_readiness(self._state.observed_at_seconds)
        alignment = next(
            item
            for item in self._readiness.capabilities
            if item.capability is SessionCapability.CAMERA_ALIGNMENT
        )
        if alignment.blocked:
            self._pause_for_readiness()
            return self._publish(False)
        self._publish(False)
        status = self._camera_aligner.align()
        if status is CameraAlignmentStatus.ALIGNED:
            self._set_mode(self._mode_after_alignment, reason="alignment_complete")
        elif status is CameraAlignmentStatus.ABORTED:
            self._alignment_failure = status
            self.emergency_stop(reason="alignment_aborted")
        else:
            self._alignment_failure = status
            self.pause(reason=f"alignment_failed:{status.value}")
        return self._publish(False)

    def _observe(self, *, poll_live_providers: bool = True) -> bool:
        """Refresh read-only perception state and report whether a frame was captured."""

        try:
            if poll_live_providers or not bool(
                getattr(self._pipeline, "has_player_stats_provider", False)
            ):
                perception = self._pipeline.tick(self._window_handle, self._state)
            else:
                perception = self._pipeline.tick(
                    self._window_handle,
                    self._state,
                    poll_live_providers=False,
                )
        except FrameCaptureError as error:
            self._window_status = WINDOW_STATUS_BY_CAPTURE_CODE.get(
                error.code, WindowStatus.CAPTURE_FAILED
            )
            self._last_capture_error = error.code
            self._last_frame = None
            self._has_live_frame = False
            return False
        self._last_capture_error = None
        self._state = perception.state
        self._last_frame = perception.frame
        self._has_live_frame = True
        self._window_status = (
            WindowStatus.OK
            if self._input_adapter.is_foreground(self._window_handle)
            else WindowStatus.NOT_FOREGROUND
        )
        return True

    def _pause_for_readiness(
        self,
        *,
        kind: SessionEventKind = SessionEventKind.MODE_TRANSITION,
        foreground: ForegroundWindowInfo | None = None,
        reason_override: str | None = None,
    ) -> None:
        if not self._readiness_was_blocked:
            self._clear_armed_actions()
            if self._autopilot.armed:
                self._autopilot.begin_recovery(self._clock())
        self._readiness_was_blocked = True
        reason = self._readiness.primary_reason
        source = self._readiness.primary_source
        detail = ":".join(
            item
            for item in (
                "readiness",
                source.value if source is not None else None,
                reason.value if reason is not None else None,
            )
            if item is not None
        )
        self.pause(
            kind=kind,
            reason=reason_override or detail,
            foreground=foreground,
            manual=False,
        )

    def _synchronize_quest_goal(self) -> None:
        """Restate which goal is active and act on a change, a refusal, or a timeout."""

        sequence = self._quest_goals
        if sequence is None or not sequence.has_goals:
            return
        at_seconds = self._state.observed_at_seconds
        queue = self._quest_queue
        if queue is not None:
            sequence.apply_progress(queue.progress, at_seconds)
        interaction = self._quest_interaction
        goal = sequence.active
        # An exhausted NPC cycle only fails the goal that needed that NPC. A quest whose
        # NPCs the client never resolved has no such goal and keeps farming.
        if (
            interaction is not None
            and interaction.is_failed
            and not sequence.is_failed
            and goal is not None
            and goal.npc is not None
        ):
            self._fail_active_goal(QuestGoalFailure.INTERACTION_FAILED)
            return
        step = self._observed_goal_step(sequence)
        if step is not None and sequence.synchronize(
            step[0], at_seconds, objective_ordinal=step[1]
        ):
            self._apply_active_goal()
        goal = sequence.active
        # Travel is decided once per goal, and again only when the active goal changes.
        if goal is not None and goal.is_travel and self._quest_travel_index != goal.index:
            self._quest_travel_index = goal.index
            if self._begin_goal_travel(goal):
                return
        self._apply_policy_objective()
        if sequence.is_failed:
            return
        if sequence.observe(at_seconds) is not None:
            self._handle_goal_failure()

    def _observed_goal_step(self, sequence: QuestGoalSequence) -> tuple[QuestGoalKind, int] | None:
        """Return the goal family and objective the executor is currently working on."""

        mode = None if self._quest_interaction is None else self._quest_interaction.mode
        if mode in {QuestInteractionMode.RETREATING, QuestInteractionMode.FAILED}:
            # A bounded retreat or an exhausted interaction is not a new goal.
            return None
        npc_kind = NPC_GOAL_KIND_BY_INTERACTION_MODE.get(mode) if mode is not None else None
        # A quest whose NPCs the client never resolved has no NPC goal to work on, so the
        # unexecutable accept phase falls through to the objectives it can actually farm.
        if npc_kind is not None and sequence.includes(npc_kind):
            return npc_kind, NO_OBJECTIVE_ORDINAL
        ordinal = sequence.pending_objective_ordinal
        kind = (
            QuestGoalKind.SATISFY_OBJECTIVE
            if self._within_objective_zone(sequence, ordinal)
            else QuestGoalKind.TRAVEL_TO_OBJECTIVE
        )
        return kind, ordinal

    def _within_objective_zone(self, sequence: QuestGoalSequence, ordinal: int) -> bool:
        """Return whether live GPS places the character inside one objective's spawn zone."""

        targets = sequence.resolution.targets
        if not 0 <= ordinal < len(targets):
            return False
        zone = targets[ordinal].zone
        pathing = self._pathing
        position = None if pathing is None else pathing.live_position
        if zone is None or position is None:
            return False
        return zone.contains(WorldCoordinate(position.x, position.z))

    def _begin_goal_travel(self, goal: QuestGoal) -> bool:
        """Dispatch guarded long-range travel for a goal, or refuse it explicitly.

        Returns whether this tick was consumed by the travel decision: a teleport was armed
        or the goal was refused. A destination worth walking to is left to the navigator.
        """

        sequence = self._quest_goals
        pathing = self._pathing
        catalog = self._teleporter_catalog
        if sequence is None or pathing is None or catalog is None:
            return False
        player_world_id = pathing.observe_world_id()
        plan = plan_goal_travel(
            catalog,
            goal_destination=goal.destination,
            player_position=pathing.live_position,
            player_world_id=player_world_id,
            config=self._config.quest_travel,
        )
        sequence.bind_world(plan.world_id if plan.world_id is not None else player_world_id)
        if plan.mode is GoalTravelMode.WALK:
            return False
        dispatcher = pathing.teleporter_dispatcher
        if (
            plan.mode is GoalTravelMode.UNREACHABLE
            or dispatcher is None
            or plan.destination is None
        ):
            self._fail_active_goal(QuestGoalFailure.UNREACHABLE_DESTINATION)
            return True
        dispatcher.request(plan.destination, self._state.observed_at_seconds)
        self._quest_teleport_active = True
        self._set_mode(FarmingMode.TELEPORTING, reason="quest_goal_teleport")
        return True

    def _settle_quest_teleport(self) -> FarmingTick:
        """Gate a quest goal on live arrival confirmation before it continues."""

        sequence = self._quest_goals
        pathing = self._pathing
        dispatcher = None if pathing is None else pathing.teleporter_dispatcher
        at_seconds = self._state.observed_at_seconds
        if sequence is None or dispatcher is None:
            self._quest_teleport_active = False
            self._set_mode(FarmingMode.SEARCHING, reason="quest_goal_teleport_unavailable")
            return self._publish(False)
        result = dispatcher.tick(
            CombatObservation(
                self._state.selected_target.state is TargetState.VALID,
                self._state.player_vitals.hp_percentage,
                at_seconds,
            ),
            at_seconds=at_seconds,
        )
        if result.status is TeleporterDispatchStatus.CONFIRMED:
            self._quest_teleport_active = False
            self._set_mode(FarmingMode.SEARCHING, reason="quest_goal_arrived")
            return self._publish(True)
        if result.status is TeleporterDispatchStatus.FAILED_STANDBY:
            self._quest_teleport_active = False
            self._fail_active_goal(QuestGoalFailure.TELEPORT_FAILED)
            return self._publish(False)
        return self._publish(result.status is TeleporterDispatchStatus.DISPATCHED)

    def _fail_active_goal(self, reason: QuestGoalFailure) -> None:
        """Record why the active goal stopped being executable and apply the policy."""

        sequence = self._quest_goals
        if sequence is None:
            return
        sequence.fail(reason)
        self._handle_goal_failure()

    def _handle_goal_failure(self) -> None:
        """Advance to the next quest or pause, according to the configured policy."""

        sequence = self._quest_goals
        if sequence is None or sequence.failure is None:
            return
        reason = f"quest_goal_{sequence.failure.value}"
        queue = self._quest_queue
        if self._config.quest_goal_failure_policy is QuestGoalFailurePolicy.ADVANCE_QUEST:
            following = None if queue is None else queue.advance()
            if following is not None:
                self._bind_quest(following)
                self._set_mode(FarmingMode.SEARCHING, reason=reason)
                return
        # A refused or timed-out goal is not a transient block: the session stays paused
        # until the operator changes the selection rather than resuming into the same wall.
        self.pause(kind=SessionEventKind.MODE_TRANSITION, reason=reason)

    def _record_executed_target_selection(
        self, combat: CombatDecision, requested_target: VisibleMob | None
    ) -> None:
        """Record a target action only after its direct dispatch or exact route was accepted."""

        telemetry = self._telemetry
        if telemetry is None or combat.position is None:
            return
        telemetry.record_target_selection(
            self._state,
            combat.position.x,
            combat.position.y,
            reason=(
                f"policy_{self._policy_mode.value.lower()}"
                if requested_target is not None
                else (
                    "policy_fallback"
                    if self._last_policy_action is not None
                    and self._policy_runner.last_fallback_reason
                    else "shortest_navmesh_path"
                )
                if combat.selected_mob is not None
                and combat.selected_mob.navmesh_path_distance is not None
                else "nearest_to_viewport_center"
            ),
            player_position=(self._pathing.live_position if self._pathing is not None else None),
            camera_state=(self._pathing.camera_state if self._pathing is not None else None),
            is_locked_out=lambda x, y: self._combat.is_position_locked_out(
                x, y, self._state.observed_at_seconds
            ),
            active_goal=self._active_goal_record(),
            executed_action=(
                TacticalActionCatalog.encode(self._last_policy_action)
                if requested_target is not None and self._last_policy_action is not None
                else None
            ),
            tactical_parameter_digest=self._tactical_parameters.content_digest,
            # Attributing an outcome to the artifact that did not take the decision is how a
            # promotion gate credits the wrong model, so the decision names its own producer
            # and the mask it was taken under (US-083 AC10).
            model_artifact_version=self._decision_artifact_version(),
            action_mask=self._strategic_action_mask(),
        )

    def _advance(self) -> bool:
        if self._quest_interaction is not None:
            self._advance_quest_interaction()
        self._synchronize_quest_goal()
        if self._mode in STANDBY_MODES or self._mode is FarmingMode.TELEPORTING:
            return False
        if self._mode is FarmingMode.SEARCHING:
            requested_target = self._evaluate_policy_target()
            if self._mode is not FarmingMode.SEARCHING:
                return False
            combat = self._combat.step(self._state, requested_target=requested_target)
            if combat.mode is not CombatMode.IDLE:
                pathing = self._pathing
                should_approach = (
                    pathing is not None
                    and combat.selected_mob is not None
                    and not self._should_dispatch_direct_click(combat.selected_mob)
                )
                approach_started = False
                if should_approach and pathing is not None and combat.selected_mob is not None:
                    attack_point = self._policy_attack_point_override
                    approach_started = (
                        pathing.begin_tactical_attack_point_approach(
                            combat.selected_mob,
                            attack_point.attack_point,
                            self._state.observed_at_seconds,
                        )
                        if attack_point is not None
                        else pathing.begin_target_approach(
                            combat.selected_mob, self._state.observed_at_seconds
                        )
                    )
                if approach_started:
                    self._pending_target_click = combat
                    self._record_executed_target_selection(combat, requested_target)
                    self._policy_attack_point_override = None
                    if self._telemetry is not None and pathing is not None:
                        route = pathing.world_waypoints
                        start = pathing.live_position
                        if start is not None and route:
                            self._telemetry.begin_navigation(start, route)
                    self._set_mode(FarmingMode.APPROACHING, reason="navmesh_target_selected")
                    return False
                if should_approach and self._policy_attack_point_override is not None:
                    # The candidate is skipped for this decision; the next tick re-selects
                    # rather than the session being paused for an unroutable attack point.
                    self._policy_attack_point_override = None
                    self._record_policy_fault(
                        PolicyFault(
                            PolicyFaultCode.INVALID_OR_MASKED_ACTION,
                            "attack_point_route_unavailable",
                        )
                    )
                    return False
                self._policy_attack_point_override = None
                self._set_mode(FarmingMode.TARGETING, reason="mob_detected")
                self._engagement_break = None
                self._approach_stalls.reset()
                dispatched = self._combat_dispatcher.dispatch(combat)
                if dispatched:
                    self._record_executed_target_selection(combat, requested_target)
                return dispatched
            if self._exhausted_zone_handed_over():
                return False
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

        if self._mode is FarmingMode.APPROACHING:
            return self._advance_navmesh_approach()

        if self._mode is FarmingMode.REPOSITIONING:
            return self._advance_repositioning()

        if self._mode in {FarmingMode.TARGETING, FarmingMode.COMBAT}:
            combat = self._combat.step(self._state, approach_stalled=self._approach_stalled())
            if combat.break_reason is not None:
                self._engagement_break = combat.break_reason
                if combat.break_reason is EngagementBreakReason.OBSTACLE_STALL:
                    self._register_navigation_obstacle()
            if combat.mode in {CombatMode.IDLE, CombatMode.TARGET_LOST}:
                if self._telemetry is not None:
                    self._telemetry.finish_combat(
                        self._state,
                        outcome=(
                            combat.break_reason.value
                            if combat.break_reason is not None
                            else CombatOutcome.TARGET_LOST.value
                        ),
                    )
                self._approach_stalls.reset()
                self._engaged_monster_name = None
                if combat.reposition_requested:
                    self._begin_repositioning()
                    return False
                self._set_mode(
                    FarmingMode.SEARCHING,
                    kind=_break_kind(combat.break_reason),
                    reason=combat.break_reason.value if combat.break_reason is not None else None,
                )
                return False
            if combat.mode is CombatMode.TARGET_DEAD:
                if self._telemetry is not None:
                    self._telemetry.finish_combat(
                        self._state,
                        outcome=CombatOutcome.KILL_VERIFIED.value,
                        verification_source=CombatVerificationSource.HP_ZERO,
                    )
                self._approach_stalls.reset()
                self._state = replace(self._state, progress_marker=self._state.progress_marker + 1)
                self._record_kill(combat.engaged_class_name)
                self._attribute_kill()
                self._set_mode(FarmingMode.RECONCILING, reason="target_dead")
                return False
            # The client states exactly which actor is selected; perception infers it from a
            # box. Attacking is the action that needs a proven identity, so a stated
            # disagreement between the two stops the swing rather than resolving itself in
            # favour of whichever source happened to be read last (US-083).
            engaged = combat.selected_mob
            engaged_join = (
                None if engaged is None else self._state.catalog_join(engaged.candidate_index)
            )
            self._target_reconciliation = reconcile_selected_target(
                self._state.player_stats_snapshot,
                candidate_index=None if engaged is None else engaged.candidate_index,
                visual_mover_id=None if engaged_join is None else engaged_join.mover_id,
                has_visual_target=engaged is not None,
            )
            self._state = replace(self._state, target_reconciliation=self._target_reconciliation)
            if self._target_reconciliation.blocks_identity_dependent_action:
                self._approach_stalls.reset()
                self._engaged_monster_name = None
                self._set_mode(
                    FarmingMode.SEARCHING, reason=TargetAgreement.IDENTITY_MISMATCH.value
                )
                return False
            if combat.mode in {CombatMode.ENGAGING, CombatMode.FIGHTING}:
                if self._telemetry is not None:
                    self._telemetry.begin_combat(self._state)
                self._remember_engaged_monster()
                self._search.reset()
            self._set_mode(FarmingMode.COMBAT, reason="engaging")
            dispatched = self._combat_dispatcher.dispatch(combat)
            if (
                dispatched
                and self._telemetry is not None
                and combat.virtual_key is not None
                and combat.key_press_duration_seconds is not None
            ):
                self._telemetry.record_attack(combat.virtual_key, combat.key_press_duration_seconds)
            return dispatched

        if self._mode is FarmingMode.RECONCILING:
            reconciliation = self._supervisor.reconcile(
                self._config.effective_desired_state, self._state
            )
            if reconciliation.is_healthy:
                self._combat.reset()
                self._set_mode(FarmingMode.SEARCHING, reason="reconciled")
                return self._advance()
            else:
                self.pause(
                    kind=SessionEventKind.SUPERVISOR_FAILURE,
                    reason=",".join(sorted(flag.value for flag in reconciliation.failures)),
                )
            return False

        return False

    def _advance_navmesh_approach(self) -> bool:
        """Follow an active Funnel corridor before the existing guarded target click."""

        pathing = self._pathing
        pending = self._pending_target_click
        interaction = self._quest_interaction
        from flyff_bot.features.navigation.pathing import PathingMode

        if interaction is not None and pending is None:
            npc = interaction.active_npc
            live_position = pathing.live_position if pathing is not None else None
            if (
                pathing is not None
                and npc is not None
                and npc.position is not None
                and live_position is not None
            ):
                if npc.is_interactable_from(live_position):
                    pathing.cancel_target_approach()
                    self._set_mode(FarmingMode.SEARCHING, reason="quest_npc_reached")
                    return self._advance()
                if not pathing.world_waypoints:
                    self._set_mode(FarmingMode.SEARCHING, reason="quest_route_unavailable")
                    return False
            decision = pathing.step(self._state.observed_at_seconds) if pathing else None
            if decision is None or decision.mode is PathingMode.IDLE:
                self._set_mode(FarmingMode.SEARCHING, reason="quest_route_unavailable")
                return False
            if not self._pathing_dispatcher.dispatch(decision):
                if pathing is not None:
                    pathing.reject(decision)
                return False
            if pathing is not None:
                pathing.confirm(decision)
            return True

        if pathing is None or pending is None:
            self._set_mode(FarmingMode.SEARCHING, reason="approach_unavailable")
            return False
        if pathing.target_in_engagement_range():
            pathing.cancel_target_approach()
            self._pending_target_click = None
            if self._telemetry is not None:
                self._telemetry.finish_navigation(NavigationOutcome.REACHED_TARGET.value)
            self._set_mode(FarmingMode.TARGETING, reason="engagement_range")
            self._combat.begin_target_acquisition(self._state.observed_at_seconds)
            return self._combat_dispatcher.dispatch(pending)
        decision = pathing.step(self._state.observed_at_seconds)
        from flyff_bot.features.navigation.pathing import PathingMode

        if decision.mode is PathingMode.IDLE and pathing.navmesh_target is None:
            self._pending_target_click = None
            if self._telemetry is not None:
                self._telemetry.finish_navigation(NavigationOutcome.ROUTE_UNAVAILABLE.value)
            self._set_mode(FarmingMode.SEARCHING, reason="route_unavailable")
            return False
        if self._telemetry is not None and decision.mode is PathingMode.EVADING:
            self._telemetry.record_navigation_evasion(decision.key_press_duration_seconds or 0.0)
        if not self._pathing_dispatcher.dispatch(decision):
            pathing.reject(decision)
            return False
        pathing.confirm(decision)
        return True

    def _should_dispatch_direct_click(self, mob: VisibleMob) -> bool:
        """Return whether a selected mob may be clicked without a Funnel approach."""

        distance_limit = (
            self._policy_attack_point_override.approach_distance_units
            if self._policy_attack_point_override is not None
            and self._policy_attack_point_override.approach_distance_units is not None
            else self._tactical_parameters.engagement_distance_for(mob.class_name)
        )
        self._pathing_engagement_distance = distance_limit
        if self._pathing is not None:
            self._pathing.update_engagement_distance(distance_limit)
        if self._policy_attack_point_override is not None:
            pathing = self._pathing
            player = None if pathing is None else pathing.live_position
            if player is None:
                return False
            point = self._policy_attack_point_override.attack_point
            return math.dist((player.x, player.y, player.z), point) <= (
                self._tactical_parameters.navmesh_waypoint_arrival_units
            )
        if self._pathing is None or mob.world_x is None or mob.world_z is None:
            return True
        player = self._pathing.live_position
        if player is None or mob.navmesh_reachable is False or mob.navmesh_within_leash is False:
            return True
        distance = math.dist(
            (player.x, player.z),
            (mob.world_x, mob.world_z),
        )
        if distance <= distance_limit:
            return True
        navmesh = self._pathing.navmesh
        if navmesh is None:
            return False
        route = navmesh.find_path(
            player,
            WorldPosition(
                mob.world_x, mob.world_y if mob.world_y is not None else player.y, mob.world_z
            ),
        )
        return len(route) <= 2

    def configure_combat_class(self, profile: CombatClassProfile) -> None:
        """Apply a combat-class engagement profile to orchestration and pathing."""

        if profile is MELEE_COMBAT_CLASS_PROFILE:
            distance = MELEE_ENGAGEMENT_DISTANCE_UNITS
        elif profile is RANGED_COMBAT_CLASS_PROFILE:
            distance = RANGED_ENGAGEMENT_DISTANCE_UNITS
        elif profile is CUSTOM_COMBAT_CLASS_PROFILE:
            distance = self.pathing_engagement_distance
        else:
            raise ValueError("Unsupported combat class profile.")
        self.configure_engagement_distance(distance)
        self._pathing_engagement_profile = profile

    def configure_engagement_distance(self, distance_units: float) -> None:
        """Apply the operator-selected target engagement distance dynamically."""

        parameters = self._tactical_parameters.with_value(
            TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS,
            distance_units,
        )
        self.configure_tactical_parameters(parameters)
        self._pathing_engagement_profile = CUSTOM_COMBAT_CLASS_PROFILE

    def configure_tactical_parameters(self, parameters: TacticalParameterSpace) -> None:
        """Atomically apply one validated profile to every deterministic controller."""

        self._tactical_parameters = parameters
        self._tactical_parameter_diagnostics = parameters.diagnostics
        self._config = replace(self._config, tactical_parameters=parameters)
        self._combat.update_tactical_parameters(parameters)
        self._search.update_tactical_parameters(parameters)
        self._reposition.update_tactical_parameters(parameters)
        self._vitals.update_tactical_parameters(parameters)
        self._pathing_engagement_distance = parameters.engagement_distance_units
        if self._pathing is not None:
            update_tactical_parameters = getattr(self._pathing, "update_tactical_parameters", None)
            if callable(update_tactical_parameters):
                update_tactical_parameters(parameters)
        if self._camera_aligner is not None:
            update_tactical_parameters = getattr(
                self._camera_aligner, "update_tactical_parameters", None
            )
            if callable(update_tactical_parameters):
                update_tactical_parameters(parameters)

    @property
    def tactical_parameters(self) -> TacticalParameterSpace:
        """Return the active immutable base profile without a transient policy override."""

        return self._tactical_parameters

    @property
    def pathing_engagement_profile(self) -> CombatClassProfile:
        """Return the combat class profile that owns the current distance."""

        return self._pathing_engagement_profile

    @property
    def pathing_engagement_distance(self) -> float:
        """Return the current direct-targeting and approach hand-off distance."""

        return self._pathing_engagement_distance

    def _approach_stalled(self) -> bool:
        """Return whether the client-driven walk towards the engaged mob is blocked."""

        if self._combat.damage_dealt:
            self._approach_stalls.reset()
            return False
        live_position = self._pathing.live_position if self._pathing is not None else None
        live_sampled_at_seconds = (
            self._pathing.live_sampled_at_seconds if self._pathing is not None else None
        )
        return self._approach_stalls.observe(
            self._last_frame,
            movement_commanded=True,
            at_seconds=self._state.observed_at_seconds,
            live_position=live_position,
            live_sampled_at_seconds=live_sampled_at_seconds,
        )

    def _begin_repositioning(self) -> None:
        """Start one bounded rotate-and-roam sweep to clear the blocked approach."""

        self._reposition.reset()
        self._set_mode(
            FarmingMode.REPOSITIONING,
            kind=_break_kind(self._engagement_break),
            reason=self._engagement_break.value if self._engagement_break is not None else None,
        )

    def _advance_repositioning(self) -> bool:
        """Steer one re-positioning step, or hand back to searching once the sweep is done."""

        if self._pathing is not None and self._pathing.has_pending_evasion:
            return self._advance_pathing()
        decision = self._reposition.step(self._state.observed_at_seconds)
        if self._reposition.completed_cycles >= REPOSITION_SWEEP_CYCLES:
            self._set_mode(FarmingMode.SEARCHING, reason="reposition_complete")
            self._search.reset()
            return False
        dispatched = self._search_dispatcher.dispatch(decision)
        if (
            dispatched
            and self._pathing is not None
            and decision.virtual_key is not None
            and decision.key_press_duration_seconds is not None
        ):
            self._pathing.integrate_movement(
                decision.virtual_key, decision.key_press_duration_seconds
            )
        return dispatched

    def _advance_quest_interaction(self) -> bool:
        """Drive the configured accept/turn-in cycle before ordinary mob searching."""

        interaction = self._quest_interaction
        if interaction is None:
            return False
        if interaction.is_failed:
            return False
        pathing = self._pathing
        if pathing is None:
            return False
        npc = interaction.active_npc
        if npc is None:
            return False
        live_position = pathing.live_position
        in_range = bool(live_position and npc.is_interactable_from(live_position))
        if in_range and interaction.mode.startswith("navigating_"):
            pathing.cancel_target_approach()
            self._set_mode(FarmingMode.SEARCHING, reason="quest_npc_reached")
            return False
        if npc.position is None:
            interaction.observe_navigation(
                None, False, route_available=False, at_seconds=self._state.observed_at_seconds
            )
            return False
        npc_screen_position = None
        if in_range:
            # The NPC's click target is projected through the live view-projection matrix.
            # Anything the projection cannot prove drops the stale target instead of clicking
            # where the NPC used to be; the bounded interaction timeout then fails the goal
            # with a typed reason (US-086).
            camera = pathing.camera_state
            viewport = self._state.viewport
            projection = (
                None
                if camera is None or not viewport.has_size
                else project_world_to_screen(npc.position, viewport.width, viewport.height, camera)
            )
            if projection is None:
                interaction.observe_npc_projection_failure(NPC_PROJECTION_UNAVAILABLE_REASON)
            elif (
                projection.status is not WorldProjectionStatus.VISIBLE
                or projection.x is None
                or projection.y is None
            ):
                interaction.observe_npc_projection_failure(projection.status.value)
            else:
                npc_screen_position = Position(projection.x, projection.y)
        if not in_range and interaction.mode.startswith("navigating_"):
            if not pathing.begin_position_approach(
                npc.position,
                self._state.observed_at_seconds,
            ):
                interaction.observe_navigation(
                    npc.position,
                    False,
                    route_available=False,
                    at_seconds=self._state.observed_at_seconds,
                )
                return False
            self._set_mode(FarmingMode.APPROACHING, reason="quest_npc_selected")
            return False
        decision = interaction.step(
            self._state,
            self._last_frame,
            npc_screen_position=npc_screen_position,
        )
        return self._quest_input_dispatcher.dispatch(decision)

    def _exhausted_zone_handed_over(self) -> bool:
        """Route to the next selected spawn zone once this camp searched out empty.

        Returns whether the session switched camps, in which case this tick dispatches no
        search input and the next one plans the route to the new zone (US-059).
        """

        if (
            self._pathing is None
            or self._pathing.completed_zone_sweeps < PATROL_SWEEPS_BEFORE_ZONE_CHANGE
        ):
            return False
        if self._pathing.advance_to_next_zone() is None:
            return False
        self._search.reset()
        return True

    def _advance_emergency_recovery(self) -> bool:
        """Escape geometry when wedged."""

        if self._pathing is None:
            return False
        live = self._pathing.live_position
        decision = self._emergency.observe(
            self._state.observed_at_seconds,
            position_x=live.x if live is not None else None,
            position_z=live.z if live is not None else None,
            engaged=self._engagement_progressed(),
        )
        if decision.action is EmergencyRecoveryAction.UNAVAILABLE:
            self._emergency_teleport_unavailable = True
            self.pause()
            return False
        if decision.action is not EmergencyRecoveryAction.TELEPORT:
            return False

        pathing = self._pathing
        dispatcher = pathing._teleporter_dispatcher if pathing is not None else None
        destination = decision.destination
        if dispatcher is None or destination is None:
            return False
        dispatcher.request(destination, self._state.observed_at_seconds)
        self._begin_emergency_recovery()
        return True

    def _engagement_progressed(self) -> bool:
        return self._combat.damage_dealt or self._mode is FarmingMode.RECONCILING

    def _begin_emergency_recovery(self) -> None:
        self._emergency.halt()
        self._emergency_recovery_started_at_seconds = self._state.observed_at_seconds
        self._set_mode(FarmingMode.TELEPORTING, reason="emergency_teleport")

    def _settle_teleport(self) -> FarmingTick:
        started_at = self._emergency_recovery_started_at_seconds
        if (
            started_at is None
            or self._state.observed_at_seconds - started_at
            < self._config.emergency.confirmation_timeout_seconds
        ):
            return self._publish(False)
        self.emergency_stop(reason="emergency_reset_unconfirmed")
        return self._publish(False)

    def _register_navigation_obstacle(self) -> None:
        if self._pathing is not None:
            self._pathing.register_obstacle(self._state.observed_at_seconds)

    def _remember_engaged_monster(self) -> None:
        name = self._state.selected_target.name
        if name:
            self._engaged_monster_name = name

    def _attribute_kill(self) -> None:
        name = self._engaged_monster_name
        self._engaged_monster_name = None
        if name is None or self._pathing is None:
            return
        self._pathing.record_kill(name)

    def _advance_pathing(self) -> bool:
        """Steer one authoritative 3D NavMesh/Vector route step."""

        if self._pathing is None:
            return False
        from flyff_bot.features.navigation.pathing import PathingMode

        decision = self._pathing.step(self._state.observed_at_seconds)
        if decision.mode is PathingMode.BLOCKED:
            self.pause(reason="gps_unavailable", manual=False)
            return False
        if self._telemetry is not None:
            live_position = self._pathing.live_position
            waypoints = self._pathing.world_waypoints
            if decision.mode is PathingMode.TRAVELING and live_position is not None and waypoints:
                self._telemetry.begin_navigation(live_position, waypoints)
            if decision.mode is PathingMode.EVADING:
                self._telemetry.record_navigation_evasion(
                    decision.key_press_duration_seconds or 0.0
                )
            if decision.mode is PathingMode.IDLE:
                self._telemetry.finish_navigation(NavigationOutcome.REACHED_TARGET.value)
        if not self._pathing_dispatcher.dispatch(decision):
            self._pathing.reject(decision)
            return False
        self._pathing.confirm(decision)
        self._search.reset()
        return True

    def _record_kill(self, class_name: str | None) -> None:
        if not self._kill_goals.record_kill(class_name):
            return
        self._session_kills += 1
        if self._kill_goals.has_quotas:
            self._apply_active_target_classes()
        self._advance_quest_queue(class_name)
        if self._telemetry is not None:
            self._telemetry.record_objective_progress(
                1.0,
                quest_id=_active_quest_identifier(self._quest_queue),
                completed=self._goal_completed(),
            )

    def _advance_quest_queue(self, class_name: str | None) -> None:
        """Hand the session on to the next selected quest once the active one is met."""

        queue = self._quest_queue
        if queue is None or not queue.record_kill(class_name):
            return
        self._completed_quests += 1
        following = queue.advance()
        if following is not None:
            self._bind_quest(following)
        self._arbitrate_autopilot_goal()

    def _goal_completed(self) -> bool:
        queue = self._quest_queue
        if queue is not None and queue.has_quests:
            # A quest session ends when its queue does, not when one quest's quotas are met.
            return queue.is_completed
        if self._kill_goals.is_completed:
            return True
        goal = self._config.goal
        if goal is None:
            return False
        quantities = {entry.item: entry.quantity for entry in self._state.inventory}
        return quantities.get(goal.item_name, 0) >= goal.required_quantity

    def _complete_session(self) -> None:
        self._session_active = False
        reason = _completion_reason(self._quest_queue, self._kill_goals)
        self._set_mode(FarmingMode.COMPLETED, kind=SessionEventKind.GOAL_COMPLETED, reason=reason)
        if self._kill_goals.close_client_on_completion and not self._client_close_requested:
            self._client_close_requested = True
            self._input_adapter.close_window(self._window_handle)

    def _publish(self, dispatched: bool) -> FarmingTick:
        reconciliation = (
            self._supervisor.reconcile(self._config.effective_desired_state, self._state)
            if self._mode is FarmingMode.RECONCILING
            else None
        )
        tick = FarmingTick(
            self._state,
            self._mode,
            dispatched,
            reconciliation,
            self._readiness,
        )
        self._record_telemetry_snapshot()
        if self._dashboard_feed is not None:
            self._dashboard_feed.publish(
                DashboardUpdate(
                    self._state,
                    _dashboard_status(
                        self._mode,
                        self._search.mode if self._mode is FarmingMode.SEARCHING else None,
                        live_preview=self._has_live_frame,
                        alignment_failed=self._alignment_failure is not None,
                        teleport_unavailable=self._emergency_teleport_unavailable,
                    ),
                    self._config.goal,
                    frame=self._last_frame,
                    navigation=(
                        self._pathing.snapshot(self._state.observed_at_seconds)
                        if self._pathing is not None
                        else None
                    ),
                    window=self._window_status,
                    engagement_break=self._engagement_break,
                    kill_progress=self._kill_goals.progress,
                    quest_title=_active_quest_title(self._quest_queue),
                    quest_progress=(
                        () if self._quest_queue is None else self._quest_queue.progress
                    ),
                    quest_queue_completed=(
                        self._quest_queue is not None and self._quest_queue.is_completed
                    ),
                    quest_goal=(
                        None if self._quest_goals is None else self._quest_goals.identity()
                    ),
                    events=(
                        self._event_logger.recent_events if self._event_logger is not None else ()
                    ),
                    dungeons=self._dungeon_snapshots,
                    readiness=self._readiness,
                    policy_fault=self._policy_fault,
                    tactical_parameter_diagnostics=self._tactical_parameter_diagnostics,
                    autopilot=self._autopilot.snapshot(self._clock()),
                    autopilot_summary=self._autopilot.summary,
                )
            )
        return tick

    def _record_telemetry_snapshot(self) -> None:
        if self._telemetry is None or not self._has_live_frame:
            return
        observed_at_seconds = self._state.observed_at_seconds
        if observed_at_seconds == self._telemetry_observed_at_seconds:
            return
        self._telemetry_observed_at_seconds = observed_at_seconds
        self._telemetry.record_snapshot(
            self._state,
            self._mode.value,
            live_position=self._pathing.live_position if self._pathing is not None else None,
            position_source=(
                self._pathing.position_source
                if self._pathing is not None
                else PositionSource.UNAVAILABLE
            ),
            player_terrain_slope=(
                self._pathing.terrain_slope if self._pathing is not None else None
            ),
            readiness=self._readiness,
            active_goal=self._active_goal_record(),
        )

    def _active_goal_record(self) -> ActiveGoal | None:
        """Return the active goal as the telemetry sidecar persists it."""

        sequence = self._quest_goals
        identity = None if sequence is None else sequence.identity()
        if identity is None:
            return None
        return ActiveGoal(
            identity.quest_id,
            identity.kind.value,
            identity.index,
            identity.goal_count,
            identity.progress,
            identity.required_progress,
            identity.state.value,
            identity.monster_name,
            identity.spawn_zone_monster_id,
            identity.world_id,
            None if identity.failure is None else identity.failure.value,
        )


def _dashboard_status(
    mode: FarmingMode,
    search_mode: SearchMode | None = None,
    *,
    live_preview: bool = False,
    alignment_failed: bool = False,
    teleport_unavailable: bool = False,
) -> BotStatus:
    if mode is FarmingMode.ALIGNING:
        return BotStatus.ALIGNING
    if mode is FarmingMode.TELEPORTING:
        return BotStatus.EMERGENCY_TELEPORT
    if mode is FarmingMode.EMERGENCY_STOPPED:
        return BotStatus.EMERGENCY_STOPPED
    if mode is FarmingMode.DEAD:
        return BotStatus.DEAD
    if mode is FarmingMode.FAULTED:
        return BotStatus.FAULTED
    if teleport_unavailable:
        return BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE
    if alignment_failed:
        return BotStatus.ALIGNMENT_FAILED
    if mode is FarmingMode.RECONCILING:
        return BotStatus.RECONCILING
    if mode is FarmingMode.COMPLETED:
        return BotStatus.COMPLETED
    if mode is FarmingMode.PAUSED:
        return BotStatus.STANDBY if live_preview else BotStatus.PAUSED
    if mode is FarmingMode.REPOSITIONING:
        return BotStatus.REPOSITIONING
    if mode is FarmingMode.APPROACHING:
        return BotStatus.APPROACHING
    if mode is FarmingMode.SEARCHING:
        return {
            SearchMode.ROTATE: BotStatus.SEARCH_ROTATING,
            SearchMode.ROAM_STEP: BotStatus.SEARCH_ROAMING,
        }[search_mode or SearchMode.ROTATE]
    if mode in {FarmingMode.TARGETING, FarmingMode.COMBAT}:
        return BotStatus.COMBAT
    return BotStatus.ACTIVE


def _position_provider_health(error: PositionReadErrorCode | None) -> ProviderHealth:
    if error in {
        PositionReadErrorCode.UNSUPPORTED_PLATFORM,
        PositionReadErrorCode.UNSUPPORTED_BUILD,
    }:
        return ProviderHealth.UNSUPPORTED
    if error in {
        PositionReadErrorCode.MALFORMED_READ,
        PositionReadErrorCode.INVALID_PROFILE_CONFIGURATION,
    }:
        return ProviderHealth.MALFORMED
    return ProviderHealth.UNAVAILABLE


def _camera_provider_health(error: CameraReadErrorCode | None) -> ProviderHealth:
    if error in {
        CameraReadErrorCode.UNSUPPORTED_PLATFORM,
        CameraReadErrorCode.UNSUPPORTED_BUILD,
    }:
        return ProviderHealth.UNSUPPORTED
    if error in {
        CameraReadErrorCode.MALFORMED_READ,
        CameraReadErrorCode.INVALID_PROFILE_CONFIGURATION,
    }:
        return ProviderHealth.MALFORMED
    return ProviderHealth.UNAVAILABLE


def _player_stats_provider_health(
    error: PlayerStatsReadErrorCode | None,
) -> ProviderHealth:
    if error in {
        PlayerStatsReadErrorCode.UNSUPPORTED_PLATFORM,
        PlayerStatsReadErrorCode.UNSUPPORTED_BUILD,
        PlayerStatsReadErrorCode.NO_PROFILE,
    }:
        return ProviderHealth.UNSUPPORTED
    if error in {
        PlayerStatsReadErrorCode.MALFORMED_READ,
        PlayerStatsReadErrorCode.INVALID_POINTER,
        PlayerStatsReadErrorCode.INVALID_PROFILE_CONFIGURATION,
    }:
        return ProviderHealth.MALFORMED
    return ProviderHealth.UNAVAILABLE


def _dungeon_provider_health(status: object | None) -> ProviderHealth:
    if status is DungeonReadStatus.UNCONFIGURED_PROFILE:
        return ProviderHealth.UNSUPPORTED
    return ProviderHealth.UNAVAILABLE


def _initial_world_state() -> WorldState:
    return WorldState(0.0, Position(0, 0), 0, (), 0)


def _completion_reason(queue: QuestFarmingQueue | None, kill_goals: KillGoalTracker) -> str:
    """Return the diagnostic reason recorded when a session reaches its goal."""

    if queue is not None and queue.is_completed:
        return "quest_queue"
    if kill_goals.is_completed:
        return "kill_quota"
    return "item_goal"


def _active_quest_title(queue: QuestFarmingQueue | None) -> str:
    """Return the title of the quest a session is currently working on."""

    if queue is None:
        return ""
    active = queue.active
    return "" if active is None else active.quest.display_title


def _mob_point(mob: VisibleMob) -> tuple[float, float, float] | None:
    """Return a candidate's measured world position, or ``None`` when it was never measured."""

    if mob.world_x is None or mob.world_y is None or mob.world_z is None:
        return None
    return mob.world_x, mob.world_y, mob.world_z


def _world_distance(origin: tuple[float, float, float] | None, mob: VisibleMob) -> float | None:
    point = _mob_point(mob)
    if origin is None or point is None:
        return None
    return math.dist(origin, point)


def _world_elevation(origin: tuple[float, float, float] | None, mob: VisibleMob) -> float | None:
    point = _mob_point(mob)
    if origin is None or point is None:
        return None
    return point[1] - origin[1]


def _world_bearing(origin: tuple[float, float, float] | None, mob: VisibleMob) -> float | None:
    point = _mob_point(mob)
    if origin is None or point is None:
        return None
    return bearing(point[0] - origin[0], point[2] - origin[2])


def _route_distance(position: WorldPosition, waypoints: tuple[WorldPosition, ...]) -> float | None:
    """Return the remaining planned route length, or ``None`` without an active route."""

    if not waypoints:
        return None
    points = [(position.x, position.y, position.z)] + [
        (point.x, point.y, point.z) for point in waypoints
    ]
    return sum(math.dist(points[index], points[index + 1]) for index in range(len(points) - 1))


def _active_quest_identifier(queue: QuestFarmingQueue | None) -> str | None:
    """Return the identifier of the quest a session is currently pursuing."""

    active = None if queue is None else queue.active
    return None if active is None else active.quest.quest_id
