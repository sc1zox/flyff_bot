"""Cooperative farming-session orchestration over perception and reactive controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from flyff_bot.features.automation.camera_alignment import (
    DEFAULT_AUTO_ALIGN_CAMERA,
    CameraAligner,
    CameraAlignmentStatus,
)
from flyff_bot.features.automation.combat_execution import CombatInputAdapter, CombatInputDispatcher
from flyff_bot.features.automation.controllers import (
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
    EmergencyTeleportDispatcher,
    EmergencyTeleportInputAdapter,
)
from flyff_bot.features.automation.kill_goals import (
    KillGoalConfig,
    KillGoalTracker,
    MobKillQuota,
)
from flyff_bot.features.automation.models import DesiredState, InventoryEntry, Position, WorldState
from flyff_bot.features.automation.powerup_controller import (
    PowerUpConfig,
    PowerUpInputAdapter,
    PowerUpInputDispatcher,
    PowerUpScheduler,
)
from flyff_bot.features.automation.search_execution import SearchInputAdapter, SearchInputDispatcher
from flyff_bot.features.automation.supervisor import Reconciliation, Supervisor
from flyff_bot.features.automation.vitals_controller import (
    VitalsInputAdapter,
    VitalsInputDispatcher,
    VitalsTriggerConfig,
    VitalsTriggerController,
)
from flyff_bot.features.diagnostics import SessionEventKind, SessionEventLogger
from flyff_bot.features.input_control import ForegroundWindowInfo
from flyff_bot.features.navigation.execution import PathingInputAdapter, PathingInputDispatcher
from flyff_bot.features.navigation.live_position import PositionReadErrorCode, PositionSource
from flyff_bot.features.navigation.tracking import StallConfig, StallDetector
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.telemetry.models import CombatVerificationSource
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
    # The quests feature routes through the navigation package, which routes back here.
    # The orchestrator only needs these names to describe its own surface, so importing
    # them for type checking alone keeps the runtime dependency one-directional.
    from flyff_bot.features.navigation.pathing import PathingController
    from flyff_bot.features.navigation.vector_navigation import VectorZoneNavigator
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


def _break_kind(reason: EngagementBreakReason | None) -> SessionEventKind:
    """Classify a broken engagement for the diagnostics event log."""

    if reason is EngagementBreakReason.OBSTACLE_STALL:
        return SessionEventKind.OBSTACLE_STALL
    return SessionEventKind.MODE_TRANSITION


class SessionShutdownAdapter(Protocol):
    """The cooperative window shutdown a finished session may request."""

    def close_window(self, window_handle: int) -> bool:
        """Ask the client window to close itself and report whether that was posted."""


class FarmingInputAdapter(
    CombatInputAdapter,
    SearchInputAdapter,
    PathingInputAdapter,
    VitalsInputAdapter,
    PowerUpInputAdapter,
    EmergencyTeleportInputAdapter,
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
    auto_align_camera: bool = DEFAULT_AUTO_ALIGN_CAMERA

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
        camera_aligner: CameraAligner | None = None,
        kill_goals: KillGoalTracker | None = None,
        quest_queue: QuestFarmingQueue | None = None,
        on_target_classes_changed: Callable[[frozenset[str]], None] | None = None,
        event_logger: SessionEventLogger | None = None,
        foreground_window_info: Callable[[], ForegroundWindowInfo | None] | None = None,
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._input_adapter = input_adapter
        self._window_handle = window_handle
        self._supervisor = supervisor or Supervisor()
        self._config = config or FarmingConfig()
        self._combat = CombatController(self._config.combat)
        self._search = SearchController(self._config.search)
        self._reposition = SearchController(self._config.reposition)
        self._approach_stalls = StallDetector(self._config.approach_stall)
        self._vitals = VitalsTriggerController(self._config.vitals)
        self._powerups = PowerUpScheduler(self._config.powerups)
        self._emergency = EmergencyRecoveryMonitor(self._config.emergency)
        self._combat_dispatcher = CombatInputDispatcher(input_adapter, window_handle)
        self._search_dispatcher = SearchInputDispatcher(input_adapter, window_handle)
        self._vitals_dispatcher = VitalsInputDispatcher(input_adapter, window_handle)
        self._powerup_dispatcher = PowerUpInputDispatcher(input_adapter, window_handle)
        self._emergency_dispatcher = EmergencyTeleportDispatcher(input_adapter, window_handle)
        self._pathing = pathing
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
        self._camera_aligner = camera_aligner
        self._alignment_failure: CameraAlignmentStatus | None = None
        self._mode_after_alignment = FarmingMode.SEARCHING
        self._kill_goals = kill_goals or KillGoalTracker()
        self._quest_queue = quest_queue
        self._on_target_classes_changed = on_target_classes_changed
        self._client_close_requested = False
        self._event_logger = event_logger
        self._foreground_window_info = foreground_window_info
        self._last_capture_error: FrameCaptureErrorCode | None = None
        self._teleport_settled_at_seconds = 0.0
        self._emergency_teleport_unavailable = False
        self._telemetry = telemetry
        self._telemetry_observed_at_seconds: float | None = None
        self._pending_target_click: CombatDecision | None = None
        self._session_active = False

    @property
    def mode(self) -> FarmingMode:
        """Return the current session phase."""

        return self._mode

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
                )
            )
        if self._config.auto_align_camera and self._camera_aligner is not None:
            self._mode_after_alignment = FarmingMode.SEARCHING
            self._set_mode(FarmingMode.ALIGNING, reason="session_start")
            return
        self._set_mode(FarmingMode.SEARCHING, reason="session_start")

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
        if self._mode is not FarmingMode.EMERGENCY_STOPPED:
            self._set_mode(FarmingMode.PAUSED, kind=kind, reason=reason, foreground=foreground)

    def emergency_stop(self, *, reason: str | None = None) -> None:
        """Latch a session-local emergency stop until a new session is created."""

        self._session_active = False
        self._set_mode(
            FarmingMode.EMERGENCY_STOPPED, kind=SessionEventKind.EMERGENCY_STOPPED, reason=reason
        )
        if self._pathing is not None:
            self._pathing.emergency_stop()

    def close(self) -> None:
        """Release external resources during application teardown."""

        if self._pathing is not None:
            self._pathing.close()
        if self._telemetry is not None:
            self._telemetry.close()

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
            return
        active = queue.active
        if active is not None:
            self._bind_quest(active)

    def _bind_quest(self, resolution: QuestResolution) -> None:
        """Point the session's quotas and navigation at one quest's targets.

        The quotas restrict combat to that quest's monsters, and the resolved spawn zones
        replace the navigator's camp selection so the next replan routes to the new area.
        """

        self._kill_goals.update_config(
            KillGoalConfig(
                quotas=tuple(
                    MobKillQuota(monster, required)
                    for monster, required in resolution.required_kills
                )
            )
        )
        self._apply_active_target_classes()
        pathing = self._pathing
        zones = resolution.zones
        if pathing is None or not zones:
            return
        navigator = pathing.vector_navigator
        if navigator is None:
            return
        navigator.set_preferred_zones(zones)
        navigator.set_goals(resolution.zone_goals)
        # Re-attaching the same navigator is how the pathing controller is told to drop the
        # route it is following and plan a fresh one towards the new camp.
        pathing.attach_vector_navigator(navigator)

    def _apply_active_target_classes(self) -> None:
        allowed = self._kill_goals.active_class_names
        self.configure_target_classes(allowed)
        if self._on_target_classes_changed is not None:
            self._on_target_classes_changed(allowed)

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

        if self._pathing is not None:
            self._pathing.attach_vector_navigator(navigator)
            self._publish(False)

    def tick(self) -> FarmingTick:
        """Perform at most one perception, decision, and guarded-dispatch cycle."""

        if self._mode is FarmingMode.ALIGNING:
            return self._run_alignment()
        if self._mode in STANDBY_MODES:
            self._powerups.halt()
            self._emergency.halt()
            self._observe()
            if self._pathing is not None:
                self._pathing.track(self._state, self._last_frame)
            if (
                self._session_active
                and self._mode is FarmingMode.PAUSED
                and self._has_live_frame
                and self._input_adapter.is_foreground(self._window_handle)
                and (self._pathing is None or self._pathing.is_gps_available)
            ):
                self._set_mode(FarmingMode.SEARCHING, reason="resumed_auto")
            return self._publish(False)
        if self._input_adapter.is_aborted():
            self.emergency_stop(reason="killswitch")
            return self._publish(False)
        if not self._input_adapter.is_foreground(self._window_handle):
            lookup_foreground = self._foreground_window_info
            foreground = lookup_foreground() if lookup_foreground is not None else None
            if self._pathing is not None:
                self._pathing.mark_gps_offline(PositionReadErrorCode.WINDOW_NOT_FOREGROUND)
            self.pause(
                kind=SessionEventKind.FOCUS_LOST,
                reason="focus_lost",
                foreground=foreground,
                manual=False,
            )
            return self._publish(False)
        if not self._observe():
            self.pause(
                kind=SessionEventKind.FRAME_CAPTURE_ERROR,
                reason=self._last_capture_error.value if self._last_capture_error else None,
                manual=False,
            )
            return self._publish(False)

        if self._mode is FarmingMode.TELEPORTING:
            return self._settle_teleport()

        if self._pathing is not None:
            self._pathing.observe(self._state, self._last_frame)
            self._state = replace(
                self._state,
                is_stuck=self._pathing.is_stalled,
                visible_mobs=self._pathing.enrich_visible_mobs(self._state),
            )
            if not self._pathing.is_gps_available:
                self.pause(reason="gps_unavailable", manual=False)
                return self._publish(False)
            if self._telemetry is not None:
                self._telemetry.record_navigation_stall(stalled=self._pathing.is_stalled)
        if self._goal_completed():
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

    def _observe(self) -> bool:
        """Refresh read-only perception state and report whether a frame was captured."""

        try:
            perception = self._pipeline.tick(self._window_handle, self._state)
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

    def _advance(self) -> bool:
        if self._mode is FarmingMode.SEARCHING:
            combat = self._combat.step(self._state)
            if combat.mode is not CombatMode.IDLE:
                if self._telemetry is not None and combat.position is not None:
                    self._telemetry.record_target_selection(
                        self._state,
                        combat.position.x,
                        combat.position.y,
                        reason=(
                            "shortest_navmesh_path"
                            if combat.selected_mob is not None
                            and combat.selected_mob.navmesh_path_distance is not None
                            else "nearest_to_viewport_center"
                        ),
                        player_position=(
                            self._pathing.live_position if self._pathing is not None else None
                        ),
                        camera_state=(
                            self._pathing.camera_state if self._pathing is not None else None
                        ),
                        is_locked_out=lambda x, y: self._combat.is_position_locked_out(
                            x, y, self._state.observed_at_seconds
                        ),
                    )
                if (
                    self._pathing is not None
                    and combat.selected_mob is not None
                    and self._pathing.begin_target_approach(
                        combat.selected_mob, self._state.observed_at_seconds
                    )
                ):
                    self._pending_target_click = combat
                    if self._telemetry is not None:
                        route = self._pathing.world_waypoints
                        start = self._pathing.live_position
                        if start is not None and route:
                            self._telemetry.begin_navigation(start, route)
                    self._set_mode(FarmingMode.APPROACHING, reason="navmesh_target_selected")
                    return False
                self._set_mode(FarmingMode.TARGETING, reason="mob_detected")
                self._engagement_break = None
                self._approach_stalls.reset()
                return self._combat_dispatcher.dispatch(combat)
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
                            else "target_lost"
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
                        outcome="kill_verified",
                        verification_source=CombatVerificationSource.HP_ZERO,
                    )
                self._approach_stalls.reset()
                self._state = replace(self._state, progress_marker=self._state.progress_marker + 1)
                self._record_kill(combat.engaged_class_name)
                self._attribute_kill()
                self._set_mode(FarmingMode.RECONCILING, reason="target_dead")
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
                self._set_mode(FarmingMode.SEARCHING, reason="reconciled")
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
        from flyff_bot.features.navigation.pathing import PathingMode

        if pathing is None or pending is None:
            self._set_mode(FarmingMode.SEARCHING, reason="approach_unavailable")
            return False
        if pathing.target_in_engagement_range():
            pathing.cancel_target_approach()
            self._pending_target_click = None
            if self._telemetry is not None:
                self._telemetry.finish_navigation("reached_target")
            self._set_mode(FarmingMode.TARGETING, reason="engagement_range")
            self._combat.begin_target_acquisition(self._state.observed_at_seconds)
            return self._combat_dispatcher.dispatch(pending)
        decision = pathing.step(self._state.observed_at_seconds)
        if decision.mode is PathingMode.IDLE and pathing.navmesh_target is None:
            self._pending_target_click = None
            if self._telemetry is not None:
                self._telemetry.finish_navigation("route_unavailable")
            self._set_mode(FarmingMode.SEARCHING, reason="route_unavailable")
            return False
        if self._telemetry is not None and decision.mode is PathingMode.EVADING:
            self._telemetry.record_navigation_evasion()
        if not self._pathing_dispatcher.dispatch(decision):
            pathing.reject(decision)
            return False
        pathing.confirm(decision)
        return True

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
        if not self._emergency_dispatcher.dispatch(decision):
            return False
        self._begin_teleport_recovery()
        return True

    def _engagement_progressed(self) -> bool:
        return self._combat.damage_dealt or self._mode is FarmingMode.RECONCILING

    def _begin_teleport_recovery(self) -> None:
        self._emergency.halt()
        self._teleport_settled_at_seconds = (
            self._state.observed_at_seconds + self._config.emergency.settle_delay_seconds
        )
        self._set_mode(FarmingMode.TELEPORTING, reason="emergency_teleport")

    def _settle_teleport(self) -> FarmingTick:
        if self._state.observed_at_seconds < self._teleport_settled_at_seconds:
            return self._publish(False)
        self._combat = CombatController(self._config.combat)
        self._engagement_break = None
        self._engaged_monster_name = None
        self._approach_stalls.reset()
        self._search.reset()
        self._reposition.reset()
        self._emergency.reset()
        self._set_mode(FarmingMode.SEARCHING)
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
                self._telemetry.record_navigation_evasion()
            if decision.mode is PathingMode.IDLE:
                self._telemetry.finish_navigation("reached_target")
        if not self._pathing_dispatcher.dispatch(decision):
            self._pathing.reject(decision)
            return False
        self._pathing.confirm(decision)
        self._search.reset()
        return True

    def _record_kill(self, class_name: str | None) -> None:
        if not self._kill_goals.record_kill(class_name):
            return
        if self._kill_goals.has_quotas:
            self._apply_active_target_classes()
        self._advance_quest_queue(class_name)

    def _advance_quest_queue(self, class_name: str | None) -> None:
        """Hand the session on to the next selected quest once the active one is met."""

        queue = self._quest_queue
        if queue is None or not queue.record_kill(class_name):
            return
        following = queue.advance()
        if following is None:
            return
        self._bind_quest(following)

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
        tick = FarmingTick(self._state, self._mode, dispatched, reconciliation)
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
                    events=(
                        self._event_logger.recent_events if self._event_logger is not None else ()
                    ),
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
