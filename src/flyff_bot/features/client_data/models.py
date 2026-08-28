"""Typed normalized records for the client's static gameplay tables (US-083).

Every record here is either fully parsed from a client table or is absent and accompanied by
a typed :class:`CatalogRejection`. A row that cannot be read is never completed from a
neighbouring row, a similarly named symbol, or a default: the acceptance criteria of US-083
require missing client data to stay explicitly missing so a policy cannot learn from a value
the client never stated.

The client ships its property tables as tab-separated symbol tables. It does *not* ship the
``MI_*``-to-numeric-mover-id table, which is compiled into the executable, so a mover is keyed
by its symbol here and its numeric identity is supplied separately by the versioned mapping in
:mod:`flyff_bot.features.client_data.label_mapping`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, unique

# Schema of the persisted catalog artifact. Bumped whenever a record field changes; a
# document written under any other version is rejected rather than adapted (ADR-003).
CLIENT_CATALOG_SCHEMA_VERSION = "us083-v1"


@unique
class CatalogTable(StrEnum):
    """One static client table this feature normalizes."""

    MOVERS = "movers"
    DROPS = "drops"
    ITEMS = "items"
    SKILLS = "skills"
    NPCS = "npcs"


@unique
class CatalogRejectionReason(StrEnum):
    """Why one client record is unavailable, stated instead of being filled in."""

    # The table itself was not found in any opened archive or on disk.
    TABLE_MISSING = "table_missing"
    # The table was found but its bytes could not be decoded as client text.
    TABLE_UNREADABLE = "table_unreadable"
    # The row carries no symbol of the prefix its table is declared to use.
    SYMBOL_MISSING = "symbol_missing"
    # Two rows declare the same symbol, so neither can be resolved unambiguously.
    SYMBOL_DUPLICATED = "symbol_duplicated"
    # The row's localized-name reference is absent from the language catalog.
    NAME_UNRESOLVED = "name_unresolved"
    # The row has fewer columns than the header it is read against declares.
    ROW_TRUNCATED = "row_truncated"
    # A declared numeric column did not hold a number.
    FIELD_NOT_NUMERIC = "field_not_numeric"
    # The table shipped no column header, so no numeric column can be located by name.
    LAYOUT_UNVERIFIED = "layout_unverified"
    # A drop declaration referenced a mover symbol no mover row declares.
    DROP_MOVER_UNKNOWN = "drop_mover_unknown"


@dataclass(frozen=True, slots=True)
class CatalogRejection:
    """One record that could not be normalized, and exactly why."""

    table: CatalogTable
    reason: CatalogRejectionReason
    #: The symbol, file name or row ordinal that locates the rejected record.
    locator: str

    def __post_init__(self) -> None:
        if not self.locator:
            raise ValueError("A catalog rejection must name what it rejected.")


@dataclass(frozen=True, slots=True)
class MoverCombatProperties:
    """The combat and movement columns of one mover row.

    Present only when the table shipped a column header naming these fields, so a consumer
    can tell a real measurement from a column this build could not locate.
    """

    level: int | None = None
    attack_minimum: int | None = None
    attack_maximum: int | None = None
    hit_points: int | None = None
    attack_speed: int | None = None
    movement_speed: float | None = None
    sight_range: int | None = None
    belligerence: int | None = None
    experience_value: int | None = None

    @property
    def is_aggressive(self) -> bool | None:
        """Return whether the mover attacks on sight, or ``None`` when unstated.

        The client encodes passive behaviour as belligerence zero; any other declared value
        means the mover initiates combat.
        """

        if self.belligerence is None:
            return None
        return self.belligerence != 0


@dataclass(frozen=True, slots=True)
class MoverRecord:
    """One normalized ``propMover.txt`` row."""

    symbol: str
    display_name: str | None
    combat: MoverCombatProperties = field(default_factory=MoverCombatProperties)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("A mover record is identified by its client symbol.")


@dataclass(frozen=True, slots=True)
class DropRecord:
    """One item a mover is declared to drop, with the client's own odds."""

    mover_symbol: str
    item_symbol: str
    #: The client's raw drop weight. Its scale is table-defined, so it is not rescaled here.
    probability_weight: int
    minimum_quantity: int
    maximum_quantity: int

    def __post_init__(self) -> None:
        if not self.mover_symbol or not self.item_symbol:
            raise ValueError("A drop record names both a mover and an item symbol.")
        if self.minimum_quantity < 0 or self.maximum_quantity < self.minimum_quantity:
            raise ValueError("A drop quantity range is non-negative and not inverted.")


@dataclass(frozen=True, slots=True)
class ItemRecord:
    """One normalized ``Spec_Item.txt`` row."""

    symbol: str
    display_name: str | None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("An item record is identified by its client symbol.")


@dataclass(frozen=True, slots=True)
class SkillRecord:
    """One normalized ``propSkill.txt`` row."""

    symbol: str
    display_name: str | None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("A skill record is identified by its client symbol.")


@dataclass(frozen=True, slots=True)
class NpcRecord:
    """One normalized NPC declaration."""

    symbol: str
    display_name: str | None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("An NPC record is identified by its client symbol.")


@dataclass(frozen=True, slots=True)
class ClientCatalog:
    """Every static gameplay record this build could normalize, plus what it could not."""

    movers: tuple[MoverRecord, ...] = ()
    drops: tuple[DropRecord, ...] = ()
    items: tuple[ItemRecord, ...] = ()
    skills: tuple[SkillRecord, ...] = ()
    npcs: tuple[NpcRecord, ...] = ()
    rejections: tuple[CatalogRejection, ...] = ()
    schema_version: str = CLIENT_CATALOG_SCHEMA_VERSION

    def record_count(self, table: CatalogTable) -> int:
        """Return how many records of one table were actually parsed."""

        return len(self._records_by_table()[table])

    def rejections_for(self, table: CatalogTable) -> tuple[CatalogRejection, ...]:
        """Return every typed rejection raised while reading one table."""

        return tuple(rejection for rejection in self.rejections if rejection.table is table)

    def mover(self, symbol: str) -> MoverRecord | None:
        """Return one mover by its exact client symbol, never by a near match."""

        for mover in self.movers:
            if mover.symbol == symbol:
                return mover
        return None

    def drops_for(self, mover_symbol: str) -> tuple[DropRecord, ...]:
        """Return the declared drops of one mover, empty when it declares none."""

        return tuple(drop for drop in self.drops if drop.mover_symbol == mover_symbol)

    def _records_by_table(
        self,
    ) -> dict[CatalogTable, tuple[object, ...]]:
        return {
            CatalogTable.MOVERS: self.movers,
            CatalogTable.DROPS: self.drops,
            CatalogTable.ITEMS: self.items,
            CatalogTable.SKILLS: self.skills,
            CatalogTable.NPCS: self.npcs,
        }
