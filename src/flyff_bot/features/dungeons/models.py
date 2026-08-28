"""Typed dungeon definitions and immutable live cooldown snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

UNKNOWN_DUNGEON_ID = 0
UNLIMITED_DAILY_ENTRIES = 0
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DISPLAY_DAY = 24


class DungeonStatus(StrEnum):
    """Whether one extracted dungeon is currently available to the character."""

    READY = "ready"
    ON_COOLDOWN = "on_cooldown"
    ENTRY_LIMIT_REACHED = "entry_limit_reached"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DungeonDefinition:
    """One client-declared dungeon the operator can inspect without entering it.

    A client that lists its dungeons without declaring their level range or cooldown leaves
    those fields undeclared (``None``); they are never filled with an invented default.
    """

    dungeon_id: int
    name: str
    minimum_level: int | None = None
    maximum_level: int | None = None
    base_cooldown_seconds: int | None = None
    daily_entry_limit: int = UNLIMITED_DAILY_ENTRIES

    def __post_init__(self) -> None:
        if self.dungeon_id <= UNKNOWN_DUNGEON_ID:
            raise ValueError("A dungeon definition needs a positive client ID.")
        if not self.name.strip():
            raise ValueError("A dungeon definition needs a display name.")
        if self.minimum_level is not None and self.minimum_level < 1:
            raise ValueError("A dungeon level range must start at one.")
        if self.maximum_level is not None and self.maximum_level < (self.minimum_level or 1):
            raise ValueError("A dungeon level range must be ordered.")
        if self.base_cooldown_seconds is not None and self.base_cooldown_seconds < 0:
            raise ValueError("A dungeon cooldown cannot be negative.")
        if self.daily_entry_limit < UNLIMITED_DAILY_ENTRIES:
            raise ValueError("A dungeon daily entry limit cannot be negative.")

    @property
    def has_declared_level_range(self) -> bool:
        """Return whether the client declared both ends of this dungeon's level range."""

        return self.minimum_level is not None and self.maximum_level is not None

    def as_document(self) -> dict[str, object]:
        """Return this definition as its canonical persisted mapping."""

        return {
            "dungeon_id": self.dungeon_id,
            "name": self.name,
            "minimum_level": self.minimum_level,
            "maximum_level": self.maximum_level,
            "base_cooldown_seconds": self.base_cooldown_seconds,
            "daily_entry_limit": self.daily_entry_limit,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> DungeonDefinition:
        """Return the definition described by one validated JSON mapping."""

        name = document.get("name")
        if not isinstance(name, str):
            raise ValueError("A dungeon document has a non-string name.")
        return cls(
            dungeon_id=_required_integer(document, "dungeon_id"),
            name=name,
            minimum_level=_declared_integer(document, "minimum_level"),
            maximum_level=_declared_integer(document, "maximum_level"),
            base_cooldown_seconds=_declared_integer(document, "base_cooldown_seconds"),
            daily_entry_limit=_required_integer(document, "daily_entry_limit"),
        )


def _required_integer(document: Mapping[str, object], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"A dungeon document has a non-integer {key}.")
    return value


def _declared_integer(document: Mapping[str, object], key: str) -> int | None:
    """Return one optionally declared field, where ``None`` means the client is silent."""

    value = document.get(key)
    if value is None:
        return None
    return _required_integer(document, key)


@dataclass(frozen=True, slots=True)
class DungeonRuntimeState:
    """The live fields read from one fingerprinted client build."""

    dungeon_id: int
    cooldown_ends_at_monotonic_seconds: float | None = None
    entries_used: int | None = None
    daily_entry_limit: int | None = None

    def __post_init__(self) -> None:
        if self.dungeon_id <= UNKNOWN_DUNGEON_ID:
            raise ValueError("Live dungeon state needs a positive client ID.")
        timestamp = self.cooldown_ends_at_monotonic_seconds
        if timestamp is not None and timestamp < 0.0:
            raise ValueError("Live dungeon cooldown timestamps must be non-negative.")
        if any(
            (value is not None and (not isinstance(value, int) or isinstance(value, bool)))
            or (value is not None and value < UNLIMITED_DAILY_ENTRIES)
            for value in (self.entries_used, self.daily_entry_limit)
        ):
            raise ValueError("Live dungeon entry counts must be non-negative integers.")


@dataclass(frozen=True, slots=True)
class DungeonStateSnapshot:
    """One operator-facing row combining extracted metadata and live availability."""

    definition: DungeonDefinition
    status: DungeonStatus = DungeonStatus.UNKNOWN
    remaining_cooldown_seconds: float = 0.0
    entries_used: int | None = None
    daily_entry_limit: int | None = None
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        if self.remaining_cooldown_seconds < 0.0:
            raise ValueError("Remaining dungeon cooldown duration cannot be negative.")
        if self.status is not DungeonStatus.ON_COOLDOWN and self.remaining_cooldown_seconds:
            raise ValueError("Only an on-cooldown dungeon can have remaining time.")


def format_cooldown(seconds: float) -> str:
    """Return a non-negative cooldown as zero-padded `HH:MM:SS`."""

    bounded = max(0, round(seconds))
    hours, remainder_seconds = divmod(bounded, SECONDS_PER_MINUTE * MINUTES_PER_HOUR)
    minutes, whole_seconds = divmod(remainder_seconds, SECONDS_PER_MINUTE)
    hours %= HOURS_PER_DISPLAY_DAY
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
