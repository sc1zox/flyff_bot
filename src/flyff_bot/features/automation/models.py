"""Typed, immutable contracts shared by the automation architecture."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from flyff_bot.features.vision.models import MonsterStatsMetrics as MonsterStatsMetrics
from flyff_bot.features.vision.models import MonsterStatsStatus as MonsterStatsStatus
from flyff_bot.features.vision.models import PlayerVitals as PlayerVitals
from flyff_bot.features.vision.models import TargetVerificationMetrics as TargetVerificationMetrics


class FailureFlag(StrEnum):
    """Failures detected while reconciling the world state."""

    NO_PROGRESS = "no_progress"
    NO_MOBS = "no_mobs"
    STUCK = "stuck"
    INVENTORY_MISMATCH = "inventory_mismatch"


class ActionKind(StrEnum):
    """The currently supported abstract action categories."""

    ATTACK = "attack"
    MOVE = "move"
    LOOT = "loot"
    RECOVER = "recover"


class ObservationKind(StrEnum):
    """Facts that may verify an action after it is dispatched."""

    TARGET_ENGAGED = "target_engaged"
    POSITION_CHANGED = "position_changed"
    LOOT_COLLECTED = "loot_collected"
    RECOVERY_COMPLETE = "recovery_complete"


class TargetState(StrEnum):
    """The observed state of the client target header."""

    VALID = "valid"
    WRONG = "wrong"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Position:
    """A two-dimensional position in the current game view."""

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Viewport:
    """Dimensions of the client area that produced a world-state snapshot."""

    width: int = 0
    height: int = 0

    @property
    def has_size(self) -> bool:
        """Return whether the client dimensions are available."""

        return self.width > 0 and self.height > 0


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """An observed inventory count for one item."""

    item: str
    quantity: int


@dataclass(frozen=True, slots=True)
class VisibleMob:
    """A mob located in client-space by the perception pipeline."""

    class_id: int
    class_name: str
    confidence: float
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class SelectedTarget:
    """The latest target-header observation."""

    state: TargetState
    name: str | None
    hp_pixel_count: int
    hp_percentage: float = 0.0
    metrics: TargetVerificationMetrics = field(
        default_factory=TargetVerificationMetrics, compare=False
    )


@dataclass(frozen=True, slots=True)
class RecentLoot:
    """One pickup carried into a world-state snapshot."""

    item_name: str
    count: int
    raw_text: str


@dataclass(frozen=True, slots=True)
class WorldState:
    """One immutable perception snapshot used by all decision layers."""

    observed_at_seconds: float
    position: Position
    nearby_mob_count: int
    inventory: tuple[InventoryEntry, ...]
    progress_marker: int
    is_stuck: bool = False
    selected_target: SelectedTarget = SelectedTarget(TargetState.NONE, None, 0)
    visible_mobs: tuple[VisibleMob, ...] = ()
    recent_loot: tuple[RecentLoot, ...] = ()
    viewport: Viewport = Viewport()
    player_vitals: PlayerVitals = field(default_factory=PlayerVitals)
    monster_kill_count: int = 0
    monster_stats: MonsterStatsMetrics = field(default_factory=MonsterStatsMetrics)


@dataclass(frozen=True, slots=True)
class DesiredState:
    """The observable conditions the supervisor tries to maintain."""

    minimum_mob_count: int = 0
    required_inventory: tuple[InventoryEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class Action:
    """An input-independent action that requires a named observation to succeed."""

    identifier: str
    kind: ActionKind
    required_observation: ObservationKind


@dataclass(frozen=True, slots=True)
class Observation:
    """A post-action fact emitted by the perception layer."""

    kind: ObservationKind
    observed_at_seconds: float
    is_confirmed: bool
