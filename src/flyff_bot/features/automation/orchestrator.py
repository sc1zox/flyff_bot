"""Cooperative farming-session orchestration over perception and reactive controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
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
from flyff_bot.features.automation.kill_goals import KillGoalConfig, KillGoalTracker
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
from flyff_bot.features.navigation.tracking import StallConfig, StallDetector, TrackingQuality
from flyff_bot.features.perception.pipeline import PerceptionPipeline
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
    # Only needed as an annotation; importing it eagerly would close the pre-existing
    # navigation -> automation -> navigation package cycle at module load time.
    from flyff_bot.features.navigation.pathing import PathingController, ProfileLoadResult
    from flyff_bot.features.navigation.vector_navigation import VectorZoneNavigator


DEFAULT_TICK_INTERVAL_SECONDS = 0.1
DEFAULT_SEARCH_RETRY_SECONDS = 0.5
NAVIGATION_PERSIST_INTERVAL_SECONDS = 30.0
# Re-positioning after a blocked approach is a short, bounded look-around rather than the
# open-ended no-mob recovery: it starts immediately and ends after one rotate-then-roam
# sweep, so a target that is merely awkward to reach is retried without a long detour.
DEFAULT_REPOSITION_IDLE_TIMEOUT_SECONDS = 0.0
DEFAULT_REPOSITION_ROTATION_STEPS = 4
DEFAULT_REPOSITION_ROAM_STEPS = 2
REPOSITION_SWEEP_CYCLES = 1


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
    """Classify a broken engagement for the diagnostics event log (US-049)."""

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
        on_target_classes_changed: Callable[[frozenset[str]], None] | None = None,
        event_logger: SessionEventLogger | None = None,
        foreground_window_info: Callable[[], ForegroundWindowInfo | None] | None = None,
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
        self._pathing_dispatcher = PathingInputDispatcher(input_adapter, window_handle)
        self._dashboard_feed = dashboard_feed
        self._mode = FarmingMode.PAUSED
        self._state = _initial_world_state()
        self._last_frame: CapturedFrame | None = None
        self._last_persist_at_seconds = 0.0
        self._window_status = WindowStatus.NOT_FOREGROUND
        self._has_live_frame = False
        self._engagement_break: EngagementBreakReason | None = None
        # The class of the mob currently being fought, remembered while the target header
        # still names it: at the moment a kill confirms, the header is already gone, so the
        # kill could otherwise not be attributed to a monster (US-045).
        self._engaged_monster_name: str | None = None
        self._camera_aligner = camera_aligner
        self._alignment_failure: CameraAlignmentStatus | None = None
        self._mode_after_alignment = FarmingMode.SEARCHING
        self._kill_goals = kill_goals or KillGoalTracker()
        self._on_target_classes_changed = on_target_classes_changed
        self._client_close_requested = False
        self._event_logger = event_logger
        self._foreground_window_info = foreground_window_info
        self._last_capture_error: FrameCaptureErrorCode | None = None
        self._teleport_settled_at_seconds = 0.0
        self._emergency_teleport_unavailable = False

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
        """Apply a mode transition and record it in the diagnostics event log (US-049).

        A no-op when the phase does not actually change, so retrying an already-current
        mode (e.g. an idempotent ``emergency_stop()``) never spams a duplicate event.
        """

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
        self._alignment_failure = None
        self._emergency_teleport_unavailable = False
        self._emergency.reset()
        # Perception and pathing read distances from a perspective that is only calibrated
        # at the standardized camera state, so alignment runs before the first farming tick.
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
    ) -> None:
        """Pause without sending any compensating input to the client."""

        if self._mode is not FarmingMode.EMERGENCY_STOPPED:
            self._set_mode(FarmingMode.PAUSED, kind=kind, reason=reason, foreground=foreground)
        self._persist_navigation()

    def emergency_stop(self, *, reason: str | None = None) -> None:
        """Latch a session-local emergency stop until a new session is created."""

        self._set_mode(
            FarmingMode.EMERGENCY_STOPPED, kind=SessionEventKind.EMERGENCY_STOPPED, reason=reason
        )
        if self._pathing is not None:
            self._pathing.emergency_stop()
        self._persist_navigation()

    def close(self) -> None:
        """Persist navigation and release external resources during application teardown."""

        self._persist_navigation()
        if self._pathing is not None:
            self._pathing.close()

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
        """Restrict candidate selection to the operator-selected monster classes.

        An empty set means every detected monster stays eligible, matching the
        dashboard's "all monsters" selection.
        """

        combat = replace(self._config.combat, allowed_class_names=allowed_class_names)
        self._config = replace(self._config, combat=combat)
        self._combat.update_config(combat)

    def configure_kill_goals(self, config: KillGoalConfig) -> None:
        """Apply the operator's monster selection and per-monster kill quotas (US-035).

        The kills already counted survive an edited quota, so raising a satisfied target
        resumes farming instead of restarting the count.
        """

        self._kill_goals.update_config(config)
        self._client_close_requested = False
        self._apply_active_target_classes()

    @property
    def kill_goals(self) -> KillGoalTracker:
        """Expose the per-monster quota progress of this session."""

        return self._kill_goals

    def _apply_active_target_classes(self) -> None:
        """Push the monsters still worth targeting into combat and perception.

        Both boundaries read an empty set as "no restriction", which is exactly what an
        unconfigured selection means, so completed quotas and the operator's own choice
        travel the same path.
        """

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
        """Apply the unrecoverable-stuck timeout and teleport hotkey (US-040).

        The accumulated stuck span survives the edit: an operator who lowers the timeout
        while the character is already wedged means the recovery to happen sooner, not the
        wait to start again.
        """

        self._config = replace(self._config, emergency=config)
        self._emergency.update_config(config)
        self._emergency_teleport_unavailable = False

    def save_navigation_profile(self, path: Path) -> None:
        """Persist the active spatial map to a specific profile file."""

        if self._mode not in {FarmingMode.PAUSED, FarmingMode.EMERGENCY_STOPPED}:
            raise RuntimeError("Navigation profiles can only be saved while farming is paused.")
        if self._pathing is not None:
            self._pathing.save_map(path)
            self._publish(False)

    def load_navigation_profile(
        self, path: Path, *, accept_unmatched: bool = False
    ) -> ProfileLoadResult | None:
        """Re-anchor a persisted map profile to the live session, or report the refusal.

        The caller owns the operator decision a refused load needs: nothing is loaded unless
        the profile re-anchored or `accept_unmatched` was set from a confirmed prompt.
        Returns ``None`` when this session runs without learned navigation at all.
        """

        if self._mode not in {FarmingMode.PAUSED, FarmingMode.EMERGENCY_STOPPED}:
            raise RuntimeError("Navigation profiles can only be loaded while farming is paused.")
        if self._pathing is None:
            return None
        result = self._pathing.load_map(path, accept_unmatched=accept_unmatched)
        self._publish(False)
        return result

    def configure_vector_navigation(self, navigator: VectorZoneNavigator | None) -> None:
        """Adopt or drop the extracted world map that steers this session (US-045).

        Passing ``None`` returns the session to learned heatmap pathing, which is also what
        an unmapped region gets: the extracted map replaces route generation, never the
        odometry or the stall safety net underneath it.
        """

        if self._pathing is not None:
            self._pathing.attach_vector_navigator(navigator)
            self._publish(False)

    def mark_spawn_point(self) -> tuple[float, float] | None:
        """Store the character's current position as this map's spawn anchor (US-040).

        Returns the stored coordinate, or ``None`` when the session runs without learned
        navigation or the position is currently unmeasured - an unknown position is no
        place, so nothing is marked rather than an arbitrary one.
        """

        if self._pathing is None:
            return None
        marked = self._pathing.mark_spawn_point_here()
        if marked is None:
            return None
        self._publish(False)
        return (marked.x, marked.y)

    def reset_navigation_map(self) -> None:
        """Reset the active spatial map and tracking origin."""

        if self._mode not in {FarmingMode.PAUSED, FarmingMode.EMERGENCY_STOPPED}:
            raise RuntimeError("Navigation map can only be reset while farming is paused.")
        if self._pathing is not None:
            self._pathing.reset()
            self._publish(False)

    def tick(self) -> FarmingTick:
        """Perform at most one perception, decision, and guarded-dispatch cycle."""

        if self._mode is FarmingMode.ALIGNING:
            return self._run_alignment()
        if self._mode in STANDBY_MODES:
            # Every route into standby freezes the power-up countdowns here, so a
            # paused, completed, or stopped span never expires a timer unobserved.
            self._powerups.halt()
            self._emergency.halt()
            self._observe()
            if self._pathing is not None:
                # Standby still follows the character: the minimap measures motion the
                # operator produces by hand, and no input is dispatched on this path.
                self._pathing.track(self._state, self._last_frame)
            return self._publish(False)
        if self._input_adapter.is_aborted():
            self.emergency_stop(reason="killswitch")
            return self._publish(False)
        if not self._input_adapter.is_foreground(self._window_handle):
            lookup_foreground = self._foreground_window_info
            foreground = lookup_foreground() if lookup_foreground is not None else None
            self.pause(kind=SessionEventKind.FOCUS_LOST, reason="focus_lost", foreground=foreground)
            return self._publish(False)
        if not self._observe():
            self.pause(
                kind=SessionEventKind.FRAME_CAPTURE_ERROR,
                reason=self._last_capture_error.value if self._last_capture_error else None,
            )
            return self._publish(False)

        if self._mode is FarmingMode.TELEPORTING:
            # Nothing is observed into the map and no controller steps while the client
            # finishes the teleport: every estimate measured now is about the place the
            # character just left (US-040).
            return self._settle_teleport()

        if self._pathing is not None:
            self._pathing.observe(self._state, self._last_frame)
            self._state = replace(self._state, is_stuck=self._pathing.is_stalled)
            elapsed = self._state.observed_at_seconds - self._last_persist_at_seconds
            if elapsed >= NAVIGATION_PERSIST_INTERVAL_SECONDS:
                self._persist_navigation()
                self._last_persist_at_seconds = self._state.observed_at_seconds
        if self._goal_completed():
            self._complete_session()
            return self._publish(False)

        vitals_decision = self._vitals.step(self._state)
        if vitals_decision.triggered:
            dispatched = self._vitals_dispatcher.dispatch(vitals_decision)
            if dispatched:
                return self._publish(True)

        # Power-ups are evaluated after vitals so an emergency heal always outranks
        # a buff refresh, and one entry at most is dispatched per tick.
        powerup_decision = self._powerups.step(self._state.observed_at_seconds)
        if powerup_decision.triggered and self._powerup_dispatcher.dispatch(powerup_decision):
            self._powerups.confirm(powerup_decision, self._state.observed_at_seconds)
            return self._publish(True)

        if self._advance_emergency_recovery():
            return self._publish(True)
        if self._mode in STANDBY_MODES:
            # The timeout expired with no teleport hotkey configured, so the session paused
            # and the operator has to free the character by hand.
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
        # Publishing first lets the dashboard show the alignment state for the whole
        # sequence instead of only after the camera stopped moving.
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
                self._set_mode(FarmingMode.TARGETING, reason="mob_detected")
                self._engagement_break = None
                self._approach_stalls.reset()
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

        if self._mode is FarmingMode.REPOSITIONING:
            return self._advance_repositioning()

        if self._mode in {FarmingMode.TARGETING, FarmingMode.COMBAT}:
            combat = self._combat.step(self._state, approach_stalled=self._approach_stalled())
            if combat.break_reason is not None:
                self._engagement_break = combat.break_reason
                if combat.break_reason is EngagementBreakReason.OBSTACLE_STALL:
                    self._register_navigation_obstacle()
            if combat.mode in {CombatMode.IDLE, CombatMode.TARGET_LOST}:
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
                self._approach_stalls.reset()
                self._state = replace(self._state, progress_marker=self._state.progress_marker + 1)
                self._record_kill(combat.engaged_class_name)
                self._attribute_kill()
                self._set_mode(FarmingMode.RECONCILING, reason="target_dead")
                return False
            if combat.mode in {CombatMode.ENGAGING, CombatMode.FIGHTING}:
                self._remember_engaged_monster()
                # Only a verified engagement restarts the idle timeout. A click that never
                # confirmed is not progress, so repeated lockout retries cannot keep
                # postponing camera search recovery (BUG-010).
                self._search.reset()
            self._set_mode(FarmingMode.COMBAT, reason="engaging")
            return self._combat_dispatcher.dispatch(combat)

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

    def _approach_stalled(self) -> bool:
        """Return whether the client-driven walk towards the engaged mob is blocked.

        The game client moves the character after a target click, so this session tick is
        the only place that knows movement is under way: the combat state machine dispatches
        no movement key it could report, and `PathingController` samples nothing while it is
        not steering itself (US-039).
        """

        if self._combat.damage_dealt:
            # In attack range the character stands still by design, so frozen scenery stops
            # being evidence of anything.
            self._approach_stalls.reset()
            return False
        measured_speed = (
            self._pathing.measured_speed_pixels_per_second if self._pathing is not None else None
        )
        live_position = self._pathing.live_position if self._pathing is not None else None
        live_sampled_at_seconds = (
            self._pathing.live_sampled_at_seconds if self._pathing is not None else None
        )
        return self._approach_stalls.observe(
            self._last_frame,
            measured_speed_pixels_per_second=measured_speed,
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
            # The collision belongs to live navigation, which already owns a bounded
            # sideways/backward escape before its tangent replan. Drain only those two
            # guarded actions here; ordinary route following remains outside this
            # one-cycle combat repositioning sweep.
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

    def _advance_emergency_recovery(self) -> bool:
        """Escape geometry no unstuck mechanism could free the character from (US-040).

        Only a session with learned navigation runs this: judging spatial progress needs a
        position estimate, and the recovery itself is a reset of exactly that estimate.
        Returns whether the teleport hotkey was dispatched.
        """

        if self._pathing is None:
            return False
        known_position = self._pathing.tracking_quality is not TrackingQuality.DEGRADED
        position = self._pathing.position
        decision = self._emergency.observe(
            self._state.observed_at_seconds,
            position_x=position.x if known_position else None,
            position_y=position.y if known_position else None,
            engaged=self._engagement_progressed(),
        )
        if decision.action is EmergencyRecoveryAction.UNAVAILABLE:
            self._emergency_teleport_unavailable = True
            self.pause()
            return False
        if decision.action is not EmergencyRecoveryAction.TELEPORT:
            return False
        if not self._emergency_dispatcher.dispatch(decision):
            # Focus was lost or the emergency stop engaged; the timer stays expired, so the
            # attempt simply repeats on the next tick the guards allow through.
            return False
        self._begin_teleport_recovery()
        return True

    def _engagement_progressed(self) -> bool:
        """Return whether this tick carries evidence that the character is still fighting.

        A click that started an approach is deliberately not enough: running against a tree
        towards a mob re-targets forever, which is the very situation this recovery exists
        for (US-039). Landing damage, or the tick a kill is reconciled on, is real progress.
        """

        return self._combat.damage_dealt or self._mode is FarmingMode.RECONCILING

    def _begin_teleport_recovery(self) -> None:
        """Blame the place being escaped and hold the session until the client settles."""

        if self._pathing is not None:
            self._pathing.begin_teleport_recovery(self._state.observed_at_seconds)
        self._emergency.halt()
        self._teleport_settled_at_seconds = (
            self._state.observed_at_seconds + self._config.emergency.settle_delay_seconds
        )
        self._set_mode(FarmingMode.TELEPORTING, reason="emergency_teleport")

    def _settle_teleport(self) -> FarmingTick:
        """Wait out the post-teleport transition, then resume from the spawn anchor."""

        if self._state.observed_at_seconds < self._teleport_settled_at_seconds:
            return self._publish(False)
        if self._pathing is not None:
            self._pathing.complete_teleport_recovery()
        # The engagement, the approach evidence, and the search stage all describe a place
        # the character no longer stands in, so the session restarts them from the anchor.
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
        """Penalize the blocked path in the learned map, if the session is learning one."""

        if self._pathing is not None:
            self._pathing.register_obstacle(self._state.observed_at_seconds)

    def _remember_engaged_monster(self) -> None:
        """Keep the verified name of the mob under attack for later kill attribution."""

        name = self._state.selected_target.name
        if name:
            self._engaged_monster_name = name

    def _attribute_kill(self) -> None:
        """Credit one confirmed kill to the vector farming goals, if any are configured."""

        name = self._engaged_monster_name
        self._engaged_monster_name = None
        if name is None or self._pathing is None:
            return
        self._pathing.record_kill(name)

    def _advance_pathing(self) -> bool:
        """Steer one learned-route step, or defer to the staged search stages."""

        if self._pathing is None:
            return False
        decision = self._pathing.step(self._state.observed_at_seconds)
        if not self._pathing_dispatcher.dispatch(decision):
            self._pathing.reject(decision)
            return False
        self._pathing.confirm(decision)
        self._search.reset()
        return True

    def _persist_navigation(self) -> None:
        if self._pathing is not None:
            self._pathing.persist()

    def _record_kill(self, class_name: str | None) -> None:
        """Count a verified kill against its monster class and retire finished quotas.

        The class comes from the candidate this engagement clicked, which is the only
        place the mob's identity is known: the HUD counts kills without naming them.
        """

        if not self._kill_goals.record_kill(class_name):
            return
        if self._kill_goals.has_quotas:
            self._apply_active_target_classes()

    def _goal_completed(self) -> bool:
        if self._kill_goals.is_completed:
            return True
        goal = self._config.goal
        if goal is None:
            return False
        quantities = {entry.item: entry.quantity for entry in self._state.inventory}
        return quantities.get(goal.item_name, 0) >= goal.required_quantity

    def _complete_session(self) -> None:
        """End the session, and optionally ask the game client to close itself."""

        reason = "kill_quota" if self._kill_goals.is_completed else "item_goal"
        self._set_mode(FarmingMode.COMPLETED, kind=SessionEventKind.GOAL_COMPLETED, reason=reason)
        self._persist_navigation()
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
                    events=(
                        self._event_logger.recent_events if self._event_logger is not None else ()
                    ),
                )
            )
        return tick


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
