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
VIRTUAL_KEY_C = 0x43
VIRTUAL_KEY_1 = 0x31
VIRTUAL_KEY_9 = 0x39
DEFAULT_KEY_PRESS_DURATION_SECONDS = 0.05
DEFAULT_ATTACK_COOLDOWN_SECONDS = 0.5


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


@dataclass(frozen=True, slots=True)
class KeyBinding:
    """One attack or skill key and the minimum interval before it may repeat."""

    virtual_key: int
    cooldown_seconds: float = DEFAULT_ATTACK_COOLDOWN_SECONDS

    def __post_init__(self) -> None:
        if not VIRTUAL_KEY_1 <= self.virtual_key <= VIRTUAL_KEY_9 and self.virtual_key not in {
            VIRTUAL_KEY_C,
            VIRTUAL_KEY_SPACE,
        }:
            raise ValueError("Combat bindings must use 1-9, C, or Space.")
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


class LootController:
    """Request loot collection when inventory evidence has changed."""

    def __init__(self) -> None:
        self._last_inventory: tuple[object, ...] | None = None

    def step(self, state: WorldState) -> ControllerDecision:
        if self._last_inventory != state.inventory:
            self._last_inventory = state.inventory
            return ControllerDecision(ControllerMode.ACTIVE, ActionKind.LOOT)
        return ControllerDecision(ControllerMode.IDLE, None)
