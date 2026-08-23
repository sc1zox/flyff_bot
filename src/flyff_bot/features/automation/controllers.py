"""Pure reactive controller state machines driven by world snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from flyff_bot.features.automation.models import (
    ActionKind,
    MonsterStatsStatus,
    Position,
    TargetState,
    VisibleMob,
    WorldState,
)

VIRTUAL_KEY_SPACE = 0x20
VIRTUAL_KEY_DIGIT_MINIMUM = 0x30
VIRTUAL_KEY_DIGIT_MAXIMUM = 0x39
VIRTUAL_KEY_ALPHA_MINIMUM = 0x41
VIRTUAL_KEY_ALPHA_MAXIMUM = 0x5A
VIRTUAL_KEY_C = ord("C")
VIRTUAL_KEY_1 = ord("1")
VIRTUAL_KEY_9 = ord("9")
VIRTUAL_KEY_F1 = 0x70
VIRTUAL_KEY_F4 = 0x73
VIRTUAL_KEY_F12 = 0x7B
DEFAULT_KEY_PRESS_DURATION_SECONDS = 0.05
DEFAULT_ATTACK_COOLDOWN_SECONDS = 0.5
VIRTUAL_KEY_A = 0x41
VIRTUAL_KEY_D = 0x44
VIRTUAL_KEY_S = 0x53
VIRTUAL_KEY_W = 0x57
VIRTUAL_KEY_LEFT = 0x25
VIRTUAL_KEY_UP = 0x26
VIRTUAL_KEY_RIGHT = 0x27
VIRTUAL_KEY_DOWN = 0x28
DEFAULT_TARGET_ACQUISITION_GRACE_SECONDS = 0.8
DEFAULT_ENGAGEMENT_GRACE_SECONDS = 0.5
DEFAULT_TARGET_LOCKOUT_SECONDS = 1.0
DEFAULT_TARGET_LOCKOUT_RADIUS_PIXELS = 15
DEFAULT_ENGAGEMENT_TIMEOUT_SECONDS = 10.0
# A location that blocked two approaches in a row is treated as unreachable rather than
# merely contested, so it is ignored long enough for the session to farm somewhere else
# (US-039).
DEFAULT_UNREACHABLE_LOCKOUT_SECONDS = 30.0
# How long one recorded approach failure still counts as the predecessor of the next one.
# It has to outlive the short lockout plus the re-positioning sweep, otherwise the second
# attempt against the same obstacle would always look like a first one.
DEFAULT_APPROACH_FAILURE_MEMORY_SECONDS = 30.0
# The first failure buys a re-positioning attempt; the second one ends the pursuit.
UNREACHABLE_APPROACH_STRIKES = 2
DEFAULT_SEARCH_IDLE_TIMEOUT_SECONDS = 5.0
DEFAULT_SEARCH_ROTATION_DURATION_SECONDS = 0.2
DEFAULT_SEARCH_ROTATION_SETTLE_PAUSE_SECONDS = 0.3
DEFAULT_SEARCH_MOVEMENT_DURATION_SECONDS = 1.0
DEFAULT_SEARCH_ROTATION_STEPS = 8
DEFAULT_SEARCH_ROAM_STEPS = 4
DEFAULT_SEARCH_ROTATION_VIRTUAL_KEY = VIRTUAL_KEY_RIGHT


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


class CombatMode(StrEnum):
    """The visual-verification stages of one target engagement."""

    IDLE = "idle"
    TARGETING = "targeting"
    ENGAGING = "engaging"
    FIGHTING = "fighting"
    TARGET_DEAD = "target_dead"
    TARGET_LOST = "target_lost"


class CombatInputKind(StrEnum):
    """Foreground-safe input requests emitted by the combat state machine."""

    CLICK = "click"
    KEY = "key"


class EngagementBreakReason(StrEnum):
    """Why the combat state machine abandoned an engagement without a kill."""

    ACQUISITION_TIMEOUT = "acquisition_timeout"
    TARGET_UNVERIFIED = "target_unverified"
    ENGAGEMENT_TIMEOUT = "engagement_timeout"
    OBSTACLE_STALL = "obstacle_stall"


# The client walks the character to a clicked mob on its own, so both of these mean the same
# thing: the approach never arrived. They share the strike counter and the extended lockout.
UNREACHABLE_BREAK_REASONS = frozenset(
    {EngagementBreakReason.OBSTACLE_STALL, EngagementBreakReason.ENGAGEMENT_TIMEOUT}
)


class SearchMode(StrEnum):
    """The ordered recovery stages used while no eligible mob is visible."""

    ROTATE = "rotate"
    ROAM_STEP = "roam_step"


class SearchInputKind(StrEnum):
    """Safe search requests supported by the platform dispatcher."""

    KEY = "key"
    CLICK = "click"


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """Explicit timing and bounded stage sizes for spawn searching."""

    idle_timeout_seconds: float = DEFAULT_SEARCH_IDLE_TIMEOUT_SECONDS
    rotation_step_duration_seconds: float = DEFAULT_SEARCH_ROTATION_DURATION_SECONDS
    rotation_settle_pause_seconds: float = DEFAULT_SEARCH_ROTATION_SETTLE_PAUSE_SECONDS
    movement_step_duration_seconds: float = DEFAULT_SEARCH_MOVEMENT_DURATION_SECONDS
    rotation_steps: int = DEFAULT_SEARCH_ROTATION_STEPS
    roam_steps: int = DEFAULT_SEARCH_ROAM_STEPS
    rotation_virtual_key: int = DEFAULT_SEARCH_ROTATION_VIRTUAL_KEY

    def __post_init__(self) -> None:
        if self.idle_timeout_seconds < 0.0:
            raise ValueError("Search idle timeout must not be negative.")
        if self.rotation_step_duration_seconds <= 0.0:
            raise ValueError("Search rotation step duration must be positive.")
        if self.rotation_settle_pause_seconds < 0.0:
            raise ValueError("Search rotation settle pause must not be negative.")
        if self.movement_step_duration_seconds <= 0.0:
            raise ValueError("Search movement step duration must be positive.")
        if self.rotation_steps <= 0 or self.roam_steps <= 0:
            raise ValueError("Search stage step counts must be positive.")
        if self.rotation_virtual_key not in {VIRTUAL_KEY_LEFT, VIRTUAL_KEY_RIGHT}:
            raise ValueError("Search rotation key must be a valid left or right arrow key.")


@dataclass(frozen=True, slots=True)
class SearchDecision:
    """One interruptible staged-search action, if a stage is ready to act."""

    mode: SearchMode
    input_kind: SearchInputKind | None = None
    virtual_key: int | None = None
    key_press_duration_seconds: float | None = None
    position: Position | None = None


def _is_supported_combat_virtual_key(virtual_key: int) -> bool:
    return virtual_key == VIRTUAL_KEY_SPACE or any(
        minimum <= virtual_key <= maximum
        for minimum, maximum in (
            (VIRTUAL_KEY_DIGIT_MINIMUM, VIRTUAL_KEY_DIGIT_MAXIMUM),
            (VIRTUAL_KEY_ALPHA_MINIMUM, VIRTUAL_KEY_ALPHA_MAXIMUM),
            (VIRTUAL_KEY_F1, VIRTUAL_KEY_F12),
        )
    )


@dataclass(frozen=True, slots=True)
class KeyBinding:
    """One attack or skill key and the minimum interval before it may repeat."""

    virtual_key: int
    cooldown_seconds: float = DEFAULT_ATTACK_COOLDOWN_SECONDS

    def __post_init__(self) -> None:
        if not _is_supported_combat_virtual_key(self.virtual_key):
            raise ValueError("Combat bindings must use A-Z, 0-9, F1-F12, or Space.")
        if self.cooldown_seconds < 0.0:
            raise ValueError("Combat binding cooldown must not be negative.")


@dataclass(frozen=True, slots=True)
class CombatConfig:
    """Target filtering and input timing used by :class:`CombatController`."""

    allowed_class_names: frozenset[str] = field(default_factory=frozenset)
    rotation: tuple[KeyBinding, ...] = (KeyBinding(VIRTUAL_KEY_SPACE),)
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS
    target_acquisition_grace_seconds: float = DEFAULT_TARGET_ACQUISITION_GRACE_SECONDS
    engagement_grace_seconds: float = DEFAULT_ENGAGEMENT_GRACE_SECONDS
    kill_verification_enabled: bool = True
    target_lockout_seconds: float = DEFAULT_TARGET_LOCKOUT_SECONDS
    target_lockout_radius_pixels: int = DEFAULT_TARGET_LOCKOUT_RADIUS_PIXELS
    engagement_timeout_seconds: float = DEFAULT_ENGAGEMENT_TIMEOUT_SECONDS
    unreachable_lockout_seconds: float = DEFAULT_UNREACHABLE_LOCKOUT_SECONDS
    approach_failure_memory_seconds: float = DEFAULT_APPROACH_FAILURE_MEMORY_SECONDS

    def __post_init__(self) -> None:
        if not self.rotation:
            raise ValueError("Combat rotation must contain at least one binding.")
        if self.key_press_duration_seconds <= 0.0:
            raise ValueError("Combat key press duration must be positive.")
        if self.target_acquisition_grace_seconds < 0.0:
            raise ValueError("Target acquisition grace period must not be negative.")
        if self.engagement_grace_seconds < 0.0:
            raise ValueError("Engagement grace period must not be negative.")
        if self.target_lockout_seconds < 0.0:
            raise ValueError("Target lockout duration must not be negative.")
        if self.target_lockout_radius_pixels < 0:
            raise ValueError("Target lockout radius must not be negative.")
        if self.engagement_timeout_seconds <= 0.0:
            raise ValueError("Engagement timeout must be positive.")
        if self.unreachable_lockout_seconds < self.target_lockout_seconds:
            raise ValueError("Unreachable lockout must not be shorter than the target lockout.")
        if self.approach_failure_memory_seconds < 0.0:
            raise ValueError("Approach failure memory must not be negative.")


@dataclass(frozen=True, slots=True)
class CombatDecision:
    """One state transition, optional input request, and visual progress evidence."""

    mode: CombatMode
    input_kind: CombatInputKind | None = None
    position: Position | None = None
    virtual_key: int | None = None
    key_press_duration_seconds: float | None = None
    progress_observed: bool = False
    damage_dealt: bool = False
    break_reason: EngagementBreakReason | None = None
    # Whether the session should clear the blocked path before selecting the next target.
    reposition_requested: bool = False
    # The class of the mob this engagement selected, so a confirmed kill can be counted
    # against that monster's quota (US-035).
    engaged_class_name: str | None = None
    # The exact detection selected by the scoring pass.  Navigation and telemetry consume
    # this instead of matching a later candidate by rounded screen coordinates.
    selected_mob: VisibleMob | None = None


class CombatClassProfile(StrEnum):
    """Operator-selected engagement profile used by orchestration and pathing."""

    MELEE = "melee"
    RANGED = "ranged"
    CUSTOM = "custom"


MELEE_COMBAT_CLASS_PROFILE = CombatClassProfile.MELEE
RANGED_COMBAT_CLASS_PROFILE = CombatClassProfile.RANGED
CUSTOM_COMBAT_CLASS_PROFILE = CombatClassProfile.CUSTOM
DEFAULT_COMBAT_CLASS_PROFILE = MELEE_COMBAT_CLASS_PROFILE
MELEE_ENGAGEMENT_DISTANCE_UNITS = 3.0
RANGED_ENGAGEMENT_DISTANCE_UNITS = 15.0


@dataclass(frozen=True, slots=True)
class TargetLockout:
    """One client-space location candidate selection ignores until it expires."""

    position: Position
    expires_at_seconds: float


@dataclass(frozen=True, slots=True)
class ApproachFailure:
    """How often one client-space location blocked an approach, and until when that counts.

    The engagement has no detection identity, so "the same mob candidate" is judged exactly
    as :class:`TargetLockout` judges it: by proximity in client space (BUG-010).
    """

    position: Position
    strikes: int
    expires_at_seconds: float


class CombatController:
    """Select and fight whitelisted mobs using later visual snapshots as verification."""

    def __init__(self, config: CombatConfig | None = None) -> None:
        self._config = config or CombatConfig()
        self._mode = CombatMode.IDLE
        self._rotation_index = 0
        self._next_attack_at_seconds = 0.0
        self._previous_hp_pixel_count: int | None = None
        self._previous_kill_count: int | None = None
        self._targeting_started_at_seconds: float | None = None
        self._engagement_grace_expires_at: float | None = None
        self._damage_dealt = False
        self._engaged_position: Position | None = None
        self._engaged_class_name: str | None = None
        self._last_progress_at_seconds: float | None = None
        self._lockouts: list[TargetLockout] = []
        self._approach_failure: ApproachFailure | None = None

    @property
    def engaged_class_name(self) -> str | None:
        """Return the monster class of the candidate this engagement selected."""

        return self._engaged_class_name

    @property
    def damage_dealt(self) -> bool:
        """Return whether the current engagement has already reduced the target's HP.

        The session reads this to stop sampling approach stalls once the character stands
        in attack range, where motionless scenery is the expected picture rather than
        evidence of a blocked path (US-039).
        """

        return self._damage_dealt

    def is_position_locked_out(self, x: int, y: int, observed_at_seconds: float) -> bool:
        """Return the current selection lockout for one client-space candidate centre."""

        self._purge_lockouts(observed_at_seconds)
        return self._is_locked_out(Position(x, y))

    def update_config(self, config: CombatConfig) -> None:
        """Apply a new configuration without resetting the in-progress engagement."""

        self._config = config

    def begin_target_acquisition(self, observed_at_seconds: float) -> None:
        """Start the visual target-header grace period when a deferred click is sent."""

        if self._mode is CombatMode.TARGETING:
            self._targeting_started_at_seconds = observed_at_seconds

    def step(self, state: WorldState, *, approach_stalled: bool = False) -> CombatDecision:
        """Advance one state-machine tick without dispatching platform input.

        ``approach_stalled`` carries the session's verdict that the client-driven walk
        towards the engaged mob is running against an obstacle (US-039). The state machine
        cannot observe it itself: the movement is commanded by the game client after the
        target click, not by any input this controller emits.
        """

        if self._mode is CombatMode.IDLE:
            candidate = self._best_candidate(state)
            if candidate is None:
                return CombatDecision(CombatMode.IDLE)
            self._mode = CombatMode.TARGETING
            self._targeting_started_at_seconds = state.observed_at_seconds
            self._previous_kill_count = (
                state.monster_kill_count
                if state.monster_stats.status is MonsterStatsStatus.OK
                else None
            )
            self._engaged_position = _mob_center(candidate)
            self._engaged_class_name = candidate.class_name
            return CombatDecision(
                CombatMode.TARGETING,
                CombatInputKind.CLICK,
                self._engaged_position,
                engaged_class_name=self._engaged_class_name,
                selected_mob=candidate,
            )

        if self._mode is CombatMode.TARGETING:
            if approach_stalled:
                return self._break_engagement(state, EngagementBreakReason.OBSTACLE_STALL)
            if state.selected_target.state is TargetState.VALID:
                self._previous_hp_pixel_count = state.selected_target.hp_pixel_count
                self._mode = CombatMode.ENGAGING
                self._targeting_started_at_seconds = None
                self._last_progress_at_seconds = state.observed_at_seconds
                return self._attack_if_ready(state)
            grace_deadline = (
                self._targeting_started_at_seconds or 0.0
            ) + self._config.target_acquisition_grace_seconds
            if state.observed_at_seconds < grace_deadline:
                return CombatDecision(CombatMode.TARGETING)
            return self._break_engagement(state, EngagementBreakReason.ACQUISITION_TIMEOUT)

        if self._mode is CombatMode.ENGAGING:
            if self._kill_count_incremented(state):
                return self._confirm_kill(state)
            if approach_stalled:
                return self._break_engagement(state, EngagementBreakReason.OBSTACLE_STALL)
            if self._engagement_timed_out(state):
                return self._break_engagement(state, EngagementBreakReason.ENGAGEMENT_TIMEOUT)
            self._track_engaged_position(state)
            return self._attack_if_ready(state)

        if self._mode is CombatMode.FIGHTING:
            if self._kill_count_incremented(state):
                return self._confirm_kill(state)
            if state.selected_target.hp_pixel_count == 0 and self._damage_dealt:
                return self._confirm_kill(state)
            if state.selected_target.state is TargetState.NONE:
                if self._damage_dealt:
                    return self._confirm_kill(state)
                self._register_lockout(state.observed_at_seconds)
                self._mode = CombatMode.TARGET_LOST
                return CombatDecision(CombatMode.TARGET_LOST, damage_dealt=False)
            if state.selected_target.state is not TargetState.VALID:
                if self._engagement_grace_expires_at is None:
                    self._engagement_grace_expires_at = (
                        state.observed_at_seconds + self._config.engagement_grace_seconds
                    )
                if state.observed_at_seconds < self._engagement_grace_expires_at:
                    return CombatDecision(CombatMode.FIGHTING, damage_dealt=self._damage_dealt)
                return self._break_engagement(state, EngagementBreakReason.TARGET_UNVERIFIED)
            self._engagement_grace_expires_at = None
            progress = self._target_hp_decreased(state)
            if approach_stalled and not self._damage_dealt:
                return self._break_engagement(state, EngagementBreakReason.OBSTACLE_STALL)
            if self._engagement_timed_out(state):
                return self._break_engagement(state, EngagementBreakReason.ENGAGEMENT_TIMEOUT)
            self._track_engaged_position(state)
            return self._attack_if_ready(state, progress)

        self._reset()
        return CombatDecision(CombatMode.IDLE)

    def _best_candidate(self, state: WorldState) -> VisibleMob | None:
        self._purge_lockouts(state.observed_at_seconds)
        candidates = [
            mob
            for mob in self._allowed_mobs(state)
            if not self._is_locked_out(_mob_center(mob))
            and mob.navmesh_reachable is not False
            and mob.navmesh_within_leash is not False
        ]
        if not candidates:
            return None
        if not state.viewport.has_size:
            if not any(mob.navmesh_path_distance is not None for mob in candidates):
                return max(
                    candidates, key=lambda mob: (mob.confidence, -mob.class_id, mob.class_name)
                )
            return min(candidates, key=_navmesh_candidate_key)
        center = Position(state.viewport.width // 2, state.viewport.height // 2)
        return min(
            candidates,
            key=lambda mob: (
                *_navmesh_candidate_key(mob),
                _distance_squared(_mob_center(mob), center),
                mob.class_id,
                mob.class_name,
            ),
        )

    def _attack_if_ready(self, state: WorldState, progress: bool = False) -> CombatDecision:
        binding = self._config.rotation[self._rotation_index]
        if state.observed_at_seconds < self._next_attack_at_seconds:
            return CombatDecision(
                self._mode,
                progress_observed=progress,
                damage_dealt=self._damage_dealt,
            )
        self._rotation_index = (self._rotation_index + 1) % len(self._config.rotation)
        self._next_attack_at_seconds = state.observed_at_seconds + binding.cooldown_seconds
        self._mode = CombatMode.FIGHTING
        return CombatDecision(
            CombatMode.FIGHTING,
            CombatInputKind.KEY,
            virtual_key=binding.virtual_key,
            key_press_duration_seconds=self._config.key_press_duration_seconds,
            progress_observed=progress,
            damage_dealt=self._damage_dealt,
        )

    def _allowed_mobs(self, state: WorldState) -> list[VisibleMob]:
        return [
            mob
            for mob in state.visible_mobs
            if not self._config.allowed_class_names
            or mob.class_name in self._config.allowed_class_names
        ]

    def _purge_lockouts(self, observed_at_seconds: float) -> None:
        self._lockouts = [
            lockout
            for lockout in self._lockouts
            if lockout.expires_at_seconds > observed_at_seconds
        ]

    def _is_locked_out(self, position: Position) -> bool:
        radius = self._config.target_lockout_radius_pixels
        return any(
            _distance_squared(position, lockout.position) <= radius * radius
            for lockout in self._lockouts
        )

    def _register_lockout(
        self, observed_at_seconds: float, duration_seconds: float | None = None
    ) -> None:
        """Blacklist the engaged screen location so the next tick cannot re-click it."""

        duration = (
            self._config.target_lockout_seconds if duration_seconds is None else duration_seconds
        )
        if self._engaged_position is None or duration <= 0.0:
            return
        self._lockouts.append(TargetLockout(self._engaged_position, observed_at_seconds + duration))

    def _record_approach_failure(self, observed_at_seconds: float) -> int:
        """Count how often the engaged location blocked an approach in a row (US-039)."""

        position = self._engaged_position
        if position is None:
            return 1
        previous = self._approach_failure
        consecutive = (
            previous is not None
            and previous.expires_at_seconds > observed_at_seconds
            and _distance_squared(position, previous.position)
            <= self._config.target_lockout_radius_pixels**2
        )
        strikes = previous.strikes + 1 if consecutive and previous is not None else 1
        self._approach_failure = ApproachFailure(
            position,
            strikes,
            observed_at_seconds + self._config.approach_failure_memory_seconds,
        )
        return strikes

    def _track_engaged_position(self, state: WorldState) -> None:
        """Follow the engaged mob's detection so its lockout lands on the corpse.

        The engagement has no detection identity, so the nearest allowed mob still
        inside the lockout radius is assumed to be the one being fought.
        """

        anchor = self._engaged_position
        if anchor is None:
            return
        radius = self._config.target_lockout_radius_pixels
        nearby = [
            _mob_center(mob)
            for mob in self._allowed_mobs(state)
            if _distance_squared(_mob_center(mob), anchor) <= radius * radius
        ]
        if nearby:
            self._engaged_position = min(
                nearby, key=lambda center: _distance_squared(center, anchor)
            )

    def _engagement_timed_out(self, state: WorldState) -> bool:
        last_progress = self._last_progress_at_seconds
        return (
            last_progress is not None
            and state.observed_at_seconds - last_progress >= self._config.engagement_timeout_seconds
        )

    def _confirm_kill(self, state: WorldState) -> CombatDecision:
        self._register_lockout(state.observed_at_seconds)
        self._mode = CombatMode.TARGET_DEAD
        return CombatDecision(
            CombatMode.TARGET_DEAD,
            damage_dealt=True,
            engaged_class_name=self._engaged_class_name,
        )

    def _break_engagement(self, state: WorldState, reason: EngagementBreakReason) -> CombatDecision:
        """Abandon the engagement, and escalate the lockout for an unreachable target.

        The first blocked approach only earns the short lockout plus a re-positioning
        request, because the obstacle is often cleared by walking around it. A second
        consecutive block against the same location ends the pursuit for
        `unreachable_lockout_seconds` so the session farms elsewhere instead (US-039).
        """

        reposition_requested = False
        if reason in UNREACHABLE_BREAK_REASONS:
            if self._record_approach_failure(state.observed_at_seconds) >= (
                UNREACHABLE_APPROACH_STRIKES
            ):
                self._register_lockout(
                    state.observed_at_seconds, self._config.unreachable_lockout_seconds
                )
                self._approach_failure = None
            else:
                self._register_lockout(state.observed_at_seconds)
                reposition_requested = True
        else:
            self._register_lockout(state.observed_at_seconds)
        self._reset()
        return CombatDecision(
            CombatMode.IDLE, break_reason=reason, reposition_requested=reposition_requested
        )

    def _target_hp_decreased(self, state: WorldState) -> bool:
        hp_pixel_count = state.selected_target.hp_pixel_count
        progress = (
            self._previous_hp_pixel_count is not None
            and hp_pixel_count < self._previous_hp_pixel_count
        )
        if progress:
            self._damage_dealt = True
            self._last_progress_at_seconds = state.observed_at_seconds
        self._previous_hp_pixel_count = hp_pixel_count
        return progress

    def _kill_count_incremented(self, state: WorldState) -> bool:
        """Report a rise of the HUD kill counter above this engagement's baseline.

        Only a successful reading may set or move the baseline. That is what rejects the
        large jump produced when OCR first succeeds mid-engagement and reports the session's
        running total: until then there is no baseline to compare against. Because the
        baseline is trustworthy, any increase counts, so two kills landing between two
        successful readings still confirm instead of being discarded as an unclean delta.
        """

        if state.monster_stats.status is not MonsterStatsStatus.OK:
            return False
        previous = self._previous_kill_count
        self._previous_kill_count = state.monster_kill_count
        return (
            self._config.kill_verification_enabled
            and previous is not None
            and state.monster_kill_count > previous
        )

    def _reset(self) -> None:
        """Clear one engagement.

        Lockouts and the recorded approach failure deliberately survive: both describe
        places rather than engagements, and the strike counter only means anything across
        the engagements it counts.
        """

        self._mode = CombatMode.IDLE
        self._previous_hp_pixel_count = None
        self._previous_kill_count = None
        self._targeting_started_at_seconds = None
        self._engagement_grace_expires_at = None
        self._damage_dealt = False
        self._next_attack_at_seconds = 0.0
        self._engaged_position = None
        self._engaged_class_name = None
        self._last_progress_at_seconds = None


def _navmesh_candidate_key(mob: VisibleMob) -> tuple[int, float]:
    """Sort measured reachable routes ahead of unprojected viewport-only candidates."""

    if mob.navmesh_path_distance is not None:
        return (0, mob.navmesh_path_distance)
    return (1, float("inf"))


def _mob_center(mob: VisibleMob) -> Position:
    return Position(mob.x + mob.width // 2, mob.y + mob.height // 2)


def _distance_squared(left: Position, right: Position) -> int:
    return (left.x - right.x) ** 2 + (left.y - right.y) ** 2


class NavigationController:
    """Request recovery for a stuck state and movement otherwise."""

    def step(self, state: WorldState) -> ControllerDecision:
        if state.is_stuck:
            return ControllerDecision(ControllerMode.RECOVERING, ActionKind.RECOVER)
        return ControllerDecision(ControllerMode.ACTIVE, ActionKind.MOVE)


class SearchController:
    """Emit timed rotation and roaming actions until a target is found."""

    def __init__(self, config: SearchConfig | None = None) -> None:
        self._config = config or SearchConfig()
        self._mode = SearchMode.ROTATE
        self._started_at_seconds: float | None = None
        self._next_action_at_seconds = 0.0
        self._rotation_index = 0
        self._roam_index = 0
        self._completed_cycles = 0

    @property
    def mode(self) -> SearchMode:
        """Return the currently active recovery stage."""

        return self._mode

    @property
    def completed_cycles(self) -> int:
        """Return how many full rotate-then-roam sweeps finished since the last reset.

        A session that only wants to look around once - re-positioning after a blocked
        approach (US-039) - reads this to bound an otherwise endless recovery.
        """

        return self._completed_cycles

    def reset(self) -> None:
        """Start the next no-mob interval with a fresh idle timeout."""

        self._mode = SearchMode.ROTATE
        self._started_at_seconds = None
        self._next_action_at_seconds = 0.0
        self._rotation_index = 0
        self._roam_index = 0
        self._completed_cycles = 0

    def step(self, observed_at_seconds: float) -> SearchDecision:
        """Advance one non-blocking search tick using the latest perception timestamp."""

        if self._started_at_seconds is None:
            self._started_at_seconds = observed_at_seconds
            self._next_action_at_seconds = observed_at_seconds + self._config.idle_timeout_seconds
        if observed_at_seconds < self._next_action_at_seconds:
            return SearchDecision(self._mode)

        if self._mode is SearchMode.ROTATE:
            if self._rotation_index >= self._config.rotation_steps:
                self._mode = SearchMode.ROAM_STEP
                return self.step(observed_at_seconds)
            virtual_key = self._config.rotation_virtual_key
            self._rotation_index += 1
            self._next_action_at_seconds = (
                observed_at_seconds
                + self._config.rotation_step_duration_seconds
                + self._config.rotation_settle_pause_seconds
            )
            return SearchDecision(
                SearchMode.ROTATE,
                SearchInputKind.KEY,
                virtual_key,
                self._config.rotation_step_duration_seconds,
            )

        if self._mode is SearchMode.ROAM_STEP:
            if self._roam_index >= self._config.roam_steps:
                self._mode = SearchMode.ROTATE
                self._rotation_index = 0
                self._roam_index = 0
                self._completed_cycles += 1
                return self.step(observed_at_seconds)
            virtual_key = (VIRTUAL_KEY_W, VIRTUAL_KEY_D, VIRTUAL_KEY_W, VIRTUAL_KEY_A)[
                self._roam_index % 4
            ]
            self._roam_index += 1
            self._next_action_at_seconds = (
                observed_at_seconds + self._config.movement_step_duration_seconds
            )
            return SearchDecision(
                SearchMode.ROAM_STEP,
                SearchInputKind.KEY,
                virtual_key,
                self._config.movement_step_duration_seconds,
            )

        return SearchDecision(self._mode)
