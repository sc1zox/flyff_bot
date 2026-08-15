"""Pure reactive controller state machines driven by world snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from flyff_bot.features.automation.models import (
    ActionKind,
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
VIRTUAL_KEY_F12 = 0x7B
DEFAULT_KEY_PRESS_DURATION_SECONDS = 0.05
DEFAULT_ATTACK_COOLDOWN_SECONDS = 0.5
VIRTUAL_KEY_F = 0x46
VIRTUAL_KEY_A = 0x41
VIRTUAL_KEY_D = 0x44
VIRTUAL_KEY_W = 0x57
VIRTUAL_KEY_LEFT = 0x25
VIRTUAL_KEY_RIGHT = 0x27
DEFAULT_LOOT_PICKUP_WAIT_SECONDS = 2.0
DEFAULT_SEARCH_IDLE_TIMEOUT_SECONDS = 5.0
DEFAULT_SEARCH_ROTATION_DURATION_SECONDS = 0.4
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


class CombatInputKind(StrEnum):
    """Foreground-safe input requests emitted by the combat state machine."""

    CLICK = "click"
    KEY = "key"


class LootMode(StrEnum):
    """The pickup and confirmation stages after one combat death."""

    IDLE = "idle"
    PICKING_UP = "picking_up"
    WAITING = "waiting"
    TIMED_OUT = "timed_out"


class SearchMode(StrEnum):
    """The ordered recovery stages used while no eligible mob is visible."""

    ROTATE = "rotate"
    ROAM_STEP = "roam_step"
    MINIMAP_RADAR = "minimap_radar"


class SearchInputKind(StrEnum):
    """Safe search requests supported by the platform dispatcher."""

    KEY = "key"
    CLICK = "click"


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """Explicit timing and bounded stage sizes for spawn searching."""

    idle_timeout_seconds: float = DEFAULT_SEARCH_IDLE_TIMEOUT_SECONDS
    rotation_step_duration_seconds: float = DEFAULT_SEARCH_ROTATION_DURATION_SECONDS
    movement_step_duration_seconds: float = DEFAULT_SEARCH_MOVEMENT_DURATION_SECONDS
    rotation_steps: int = DEFAULT_SEARCH_ROTATION_STEPS
    roam_steps: int = DEFAULT_SEARCH_ROAM_STEPS
    rotation_virtual_key: int = DEFAULT_SEARCH_ROTATION_VIRTUAL_KEY

    def __post_init__(self) -> None:
        if self.idle_timeout_seconds < 0.0:
            raise ValueError("Search idle timeout must not be negative.")
        if self.rotation_step_duration_seconds <= 0.0:
            raise ValueError("Search rotation step duration must be positive.")
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

    def __post_init__(self) -> None:
        if not self.rotation:
            raise ValueError("Combat rotation must contain at least one binding.")
        if self.key_press_duration_seconds <= 0.0:
            raise ValueError("Combat key press duration must be positive.")


@dataclass(frozen=True, slots=True)
class CombatDecision:
    """One state transition, optional input request, and visual progress evidence."""

    mode: CombatMode
    input_kind: CombatInputKind | None = None
    position: Position | None = None
    virtual_key: int | None = None
    key_press_duration_seconds: float | None = None
    progress_observed: bool = False


@dataclass(frozen=True, slots=True)
class LootConfig:
    """The pickup key and confirmation window for one loot attempt."""

    pickup_virtual_key: int = VIRTUAL_KEY_F
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS
    pickup_wait_seconds: float = DEFAULT_LOOT_PICKUP_WAIT_SECONDS

    def __post_init__(self) -> None:
        if self.pickup_virtual_key != VIRTUAL_KEY_F:
            raise ValueError("Loot pickup must use the configured F key.")
        if self.key_press_duration_seconds <= 0.0:
            raise ValueError("Loot key press duration must be positive.")
        if self.pickup_wait_seconds <= 0.0:
            raise ValueError("Loot pickup wait duration must be positive.")


@dataclass(frozen=True, slots=True)
class LootDecision:
    """One loot-controller transition and optional guarded pickup key request."""

    mode: LootMode
    action_kind: ActionKind | None = None
    virtual_key: int | None = None
    key_press_duration_seconds: float | None = None


class CombatController:
    """Select and fight whitelisted mobs using later visual snapshots as verification."""

    def __init__(self, config: CombatConfig | None = None) -> None:
        self._config = config or CombatConfig()
        self._mode = CombatMode.IDLE
        self._rotation_index = 0
        self._next_attack_at_seconds = 0.0
        self._previous_hp_pixel_count: int | None = None

    def step(self, state: WorldState) -> CombatDecision:
        """Advance one state-machine tick without dispatching platform input."""

        if self._mode is CombatMode.IDLE:
            candidate = self._best_candidate(state)
            if candidate is None:
                return CombatDecision(CombatMode.IDLE)
            self._mode = CombatMode.TARGETING
            return CombatDecision(
                CombatMode.TARGETING,
                CombatInputKind.CLICK,
                _mob_center(candidate),
            )

        if self._mode is CombatMode.TARGETING:
            if state.selected_target.state is not TargetState.VALID:
                self._reset()
                return CombatDecision(CombatMode.IDLE)
            self._previous_hp_pixel_count = state.selected_target.hp_pixel_count
            self._mode = CombatMode.ENGAGING
            return CombatDecision(CombatMode.ENGAGING)

        if self._mode is CombatMode.ENGAGING:
            return self._attack_if_ready(state)

        if self._mode is CombatMode.FIGHTING:
            if (
                state.selected_target.state is TargetState.NONE
                or state.selected_target.hp_pixel_count == 0
            ):
                self._mode = CombatMode.TARGET_DEAD
                return CombatDecision(CombatMode.TARGET_DEAD)
            if state.selected_target.state is not TargetState.VALID:
                self._reset()
                return CombatDecision(CombatMode.IDLE)
            progress = self._target_hp_decreased(state)
            return self._attack_if_ready(state, progress)

        self._reset()
        return CombatDecision(CombatMode.IDLE)

    def _best_candidate(self, state: WorldState) -> VisibleMob | None:
        candidates = [
            mob
            for mob in state.visible_mobs
            if not self._config.allowed_class_names
            or mob.class_name in self._config.allowed_class_names
        ]
        if not candidates:
            return None
        if not state.viewport.has_size:
            return max(candidates, key=lambda mob: (mob.confidence, -mob.class_id, mob.class_name))
        center = Position(state.viewport.width // 2, state.viewport.height // 2)
        return min(
            candidates,
            key=lambda mob: (
                _distance_squared(_mob_center(mob), center),
                mob.class_id,
                mob.class_name,
            ),
        )

    def _attack_if_ready(self, state: WorldState, progress: bool = False) -> CombatDecision:
        binding = self._config.rotation[self._rotation_index]
        if state.observed_at_seconds < self._next_attack_at_seconds:
            return CombatDecision(self._mode, progress_observed=progress)
        self._rotation_index = (self._rotation_index + 1) % len(self._config.rotation)
        self._next_attack_at_seconds = state.observed_at_seconds + binding.cooldown_seconds
        self._mode = CombatMode.FIGHTING
        return CombatDecision(
            CombatMode.FIGHTING,
            CombatInputKind.KEY,
            virtual_key=binding.virtual_key,
            key_press_duration_seconds=self._config.key_press_duration_seconds,
            progress_observed=progress,
        )

    def _target_hp_decreased(self, state: WorldState) -> bool:
        hp_pixel_count = state.selected_target.hp_pixel_count
        progress = (
            self._previous_hp_pixel_count is not None
            and hp_pixel_count < self._previous_hp_pixel_count
        )
        self._previous_hp_pixel_count = hp_pixel_count
        return progress

    def _reset(self) -> None:
        self._mode = CombatMode.IDLE
        self._previous_hp_pixel_count = None


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
    """Emit timed rotation, roaming, then minimap actions until a target is found."""

    def __init__(self, config: SearchConfig | None = None) -> None:
        self._config = config or SearchConfig()
        self._mode = SearchMode.ROTATE
        self._started_at_seconds: float | None = None
        self._next_action_at_seconds = 0.0
        self._rotation_index = 0
        self._roam_index = 0

    @property
    def mode(self) -> SearchMode:
        """Return the currently active recovery stage."""

        return self._mode

    def reset(self) -> None:
        """Start the next no-mob interval with a fresh idle timeout."""

        self._mode = SearchMode.ROTATE
        self._started_at_seconds = None
        self._next_action_at_seconds = 0.0
        self._rotation_index = 0
        self._roam_index = 0

    def step(
        self, observed_at_seconds: float, radar_position: Position | None = None
    ) -> SearchDecision:
        """Advance one non-blocking search tick using the latest perception timestamp."""

        if self._started_at_seconds is None:
            self._started_at_seconds = observed_at_seconds
            self._next_action_at_seconds = observed_at_seconds + self._config.idle_timeout_seconds
        if observed_at_seconds < self._next_action_at_seconds:
            return SearchDecision(self._mode)

        if self._mode is SearchMode.ROTATE:
            if self._rotation_index >= self._config.rotation_steps:
                self._mode = SearchMode.ROAM_STEP
                return self.step(observed_at_seconds, radar_position)
            virtual_key = self._config.rotation_virtual_key
            self._rotation_index += 1
            self._next_action_at_seconds = (
                observed_at_seconds + self._config.rotation_step_duration_seconds
            )
            return SearchDecision(
                SearchMode.ROTATE,
                SearchInputKind.KEY,
                virtual_key,
                self._config.rotation_step_duration_seconds,
            )

        if self._mode is SearchMode.ROAM_STEP:
            if self._roam_index >= self._config.roam_steps:
                self._mode = SearchMode.MINIMAP_RADAR
                return self.step(observed_at_seconds, radar_position)
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

        if radar_position is None:
            return SearchDecision(SearchMode.MINIMAP_RADAR)
        self._next_action_at_seconds = (
            observed_at_seconds + self._config.movement_step_duration_seconds
        )
        return SearchDecision(
            SearchMode.MINIMAP_RADAR, SearchInputKind.CLICK, position=radar_position
        )


class LootController:
    """Collect drops after explicit combat death evidence and await OCR confirmation."""

    def __init__(self, config: LootConfig | None = None) -> None:
        self._config = config or LootConfig()
        self._mode = LootMode.IDLE
        self._pickup_deadline_seconds = 0.0
        self._awaiting_new_death = False

    def step(self, state: WorldState, combat: CombatDecision) -> LootDecision:
        """Advance pickup state using explicit death and newly emitted loot evidence."""

        if combat.mode is not CombatMode.TARGET_DEAD:
            self._awaiting_new_death = False

        if self._mode is LootMode.IDLE:
            if combat.mode is not CombatMode.TARGET_DEAD or self._awaiting_new_death:
                return LootDecision(LootMode.IDLE)
            self._awaiting_new_death = True
            self._mode = LootMode.PICKING_UP
            self._pickup_deadline_seconds = (
                state.observed_at_seconds + self._config.pickup_wait_seconds
            )
            return LootDecision(
                LootMode.PICKING_UP,
                ActionKind.LOOT,
                self._config.pickup_virtual_key,
                self._config.key_press_duration_seconds,
            )

        if self._mode is LootMode.PICKING_UP:
            self._mode = LootMode.WAITING
            return LootDecision(LootMode.WAITING)

        if self._mode is LootMode.WAITING:
            if state.recent_loot:
                self._mode = LootMode.IDLE
                return LootDecision(LootMode.IDLE)
            if state.observed_at_seconds >= self._pickup_deadline_seconds:
                self._mode = LootMode.TIMED_OUT
                return LootDecision(LootMode.TIMED_OUT, ActionKind.MOVE)
            return LootDecision(LootMode.WAITING)

        self._mode = LootMode.IDLE
        return LootDecision(LootMode.IDLE)
