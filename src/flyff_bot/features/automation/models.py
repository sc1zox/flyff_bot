"""Typed, immutable contracts shared by the automation architecture."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


@dataclass(frozen=True, slots=True)
class Position:
    """A two-dimensional position in the current game view."""

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """An observed inventory count for one item."""

    item: str
    quantity: int


@dataclass(frozen=True, slots=True)
class WorldState:
    """One immutable perception snapshot used by all decision layers."""

    observed_at_seconds: float
    position: Position
    nearby_mob_count: int
    inventory: tuple[InventoryEntry, ...]
    progress_marker: int
    is_stuck: bool = False


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
