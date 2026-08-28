"""Pure parsers for the client's static property tables (US-083).

These are offline transformations over already-decoded text. Nothing here opens a game
process, and nothing writes a client file (ADR-005).

The numeric columns of ``propMover.txt`` are located by the *client's own* column header
rather than by a hard-coded index. A private-server table can carry extra columns, so a fixed
index would silently read the wrong field and hand a policy a fabricated attack value. When no
header is present the numeric fields stay ``None`` and the table is reported as
:attr:`~flyff_bot.features.client_data.models.CatalogRejectionReason.LAYOUT_UNVERIFIED`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from flyff_bot.features.client_data.models import (
    CatalogRejection,
    CatalogRejectionReason,
    CatalogTable,
    DropRecord,
    ItemRecord,
    MoverCombatProperties,
    MoverRecord,
    NpcRecord,
    SkillRecord,
)
from flyff_bot.features.quests.client_tables import (
    STRING_REFERENCE_PREFIX,
    TABLE_EMPTY_FIELD,
)

# A client table's column header is a commented tab-separated line naming every column.
TABLE_HEADER_PREFIX = "//"
# The client writes an unset numeric column as this placeholder rather than as a zero.
TABLE_UNSET_NUMBER = "="
# Column names `propMover.txt` uses for the fields a farming policy reasons about. The
# symbol column is `dwID` even though it holds `MI_*`, which is why it is looked up by name.
MOVER_SYMBOL_COLUMN = "dwID"
MOVER_LEVEL_COLUMN = "dwLevel"
MOVER_ATTACK_MINIMUM_COLUMN = "dwAtkMin"
MOVER_ATTACK_MAXIMUM_COLUMN = "dwAtkMax"
MOVER_HIT_POINTS_COLUMN = "dwAddHp"
MOVER_ATTACK_SPEED_COLUMN = "dwAtkSpeed"
MOVER_MOVEMENT_SPEED_COLUMN = "dwSpeed"
MOVER_SIGHT_RANGE_COLUMN = "dwSightRange"
MOVER_BELLIGERENCE_COLUMN = "dwBelligerence"
MOVER_EXPERIENCE_COLUMN = "dwExpValue"

# `PropMoverEx.inc` declares a block per mover symbol, each holding `DropItem` calls:
#     MI_AIBATT1 { DropItem( II_STONE, 3000000, 1, 1 ) }
DROP_BLOCK_PATTERN = re.compile(
    r"(?P<symbol>MI_\w+)\s*\{(?P<body>[^{}]*)\}",
    re.DOTALL,
)
DROP_ITEM_PATTERN = re.compile(
    r"DropItem\s*\(\s*(?P<item>II_\w+)\s*,\s*(?P<weight>-?\d+)\s*"
    r"(?:,\s*(?P<minimum>-?\d+)\s*)?(?:,\s*(?P<maximum>-?\d+)\s*)?\)",
)
# A drop that states no quantity range drops exactly one item.
DEFAULT_DROP_QUANTITY = 1


def parse_table_header(text: str) -> tuple[str, ...]:
    """Return the column names a table declares, aligned to its *data* columns.

    Only the first commented line naming more than one column is treated as the header;
    later comment lines in these tables are prose rather than layout.

    The comment marker occupies a tab-separated field that data rows do not have, so any
    leading blank fields are dropped. Without that every column name would be shifted by one
    and a caller would read the neighbouring value as if the client had stated it.
    """

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(TABLE_HEADER_PREFIX):
            continue
        columns = [column.strip() for column in stripped[len(TABLE_HEADER_PREFIX) :].split("\t")]
        while columns and not columns[0]:
            columns.pop(0)
        if len([column for column in columns if column]) > 1:
            return tuple(columns)
    return ()


def _column_index(header: tuple[str, ...], name: str) -> int | None:
    for index, column in enumerate(header):
        if column == name:
            return index
    return None


def _numeric(columns: list[str], index: int | None) -> int | None:
    """Return one declared integer column, or ``None`` when it is absent or unset."""

    if index is None or index >= len(columns):
        return None
    value = columns[index].strip()
    if not value or value in (TABLE_UNSET_NUMBER, TABLE_EMPTY_FIELD):
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _decimal(columns: list[str], index: int | None) -> float | None:
    if index is None or index >= len(columns):
        return None
    value = columns[index].strip()
    if not value or value in (TABLE_UNSET_NUMBER, TABLE_EMPTY_FIELD):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _combat_properties(columns: list[str], header: tuple[str, ...]) -> MoverCombatProperties:
    return MoverCombatProperties(
        level=_numeric(columns, _column_index(header, MOVER_LEVEL_COLUMN)),
        attack_minimum=_numeric(columns, _column_index(header, MOVER_ATTACK_MINIMUM_COLUMN)),
        attack_maximum=_numeric(columns, _column_index(header, MOVER_ATTACK_MAXIMUM_COLUMN)),
        hit_points=_numeric(columns, _column_index(header, MOVER_HIT_POINTS_COLUMN)),
        attack_speed=_numeric(columns, _column_index(header, MOVER_ATTACK_SPEED_COLUMN)),
        movement_speed=_decimal(columns, _column_index(header, MOVER_MOVEMENT_SPEED_COLUMN)),
        sight_range=_numeric(columns, _column_index(header, MOVER_SIGHT_RANGE_COLUMN)),
        belligerence=_numeric(columns, _column_index(header, MOVER_BELLIGERENCE_COLUMN)),
        experience_value=_numeric(columns, _column_index(header, MOVER_EXPERIENCE_COLUMN)),
    )


def parse_symbol_table(
    text: str,
    *,
    table: CatalogTable,
    symbol_prefix: str,
    catalog: Mapping[str, str],
    rejections: list[CatalogRejection],
) -> tuple[tuple[str, str | None, list[str]], ...]:
    """Return one row per declared symbol as ``(symbol, display_name, columns)``.

    A duplicated symbol rejects *both* occurrences rather than keeping the first, because a
    consumer joining on that symbol could not tell which row the client actually means.
    """

    rows: dict[str, tuple[str | None, list[str]]] = {}
    duplicated: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(TABLE_HEADER_PREFIX):
            continue
        columns = [column.strip() for column in line.split("\t")]
        symbol_index = next(
            (index for index, column in enumerate(columns) if column.startswith(symbol_prefix)),
            None,
        )
        if symbol_index is None:
            continue
        symbol = columns[symbol_index]
        if symbol in rows:
            duplicated.add(symbol)
            continue
        reference = columns[symbol_index + 1] if symbol_index + 1 < len(columns) else ""
        display_name: str | None = None
        if reference.startswith(STRING_REFERENCE_PREFIX):
            resolved = catalog.get(reference, "")
            if resolved and resolved != TABLE_EMPTY_FIELD:
                display_name = resolved
            else:
                rejections.append(
                    CatalogRejection(table, CatalogRejectionReason.NAME_UNRESOLVED, symbol)
                )
        rows[symbol] = (display_name, columns)
    for symbol in sorted(duplicated):
        rows.pop(symbol, None)
        rejections.append(CatalogRejection(table, CatalogRejectionReason.SYMBOL_DUPLICATED, symbol))
    return tuple((symbol, name, columns) for symbol, (name, columns) in rows.items())


def parse_mover_table(
    text: str,
    catalog: Mapping[str, str],
    rejections: list[CatalogRejection],
) -> tuple[MoverRecord, ...]:
    """Return every mover the table declares, with combat columns when it names them."""

    header = parse_table_header(text)
    has_layout = _column_index(header, MOVER_SYMBOL_COLUMN) is not None
    if not has_layout:
        rejections.append(
            CatalogRejection(
                CatalogTable.MOVERS,
                CatalogRejectionReason.LAYOUT_UNVERIFIED,
                MOVER_SYMBOL_COLUMN,
            )
        )
    rows = parse_symbol_table(
        text,
        table=CatalogTable.MOVERS,
        symbol_prefix="MI_",
        catalog=catalog,
        rejections=rejections,
    )
    return tuple(
        MoverRecord(
            symbol,
            display_name,
            _combat_properties(columns, header) if has_layout else MoverCombatProperties(),
        )
        for symbol, display_name, columns in rows
    )


def parse_item_table(
    text: str,
    catalog: Mapping[str, str],
    rejections: list[CatalogRejection],
) -> tuple[ItemRecord, ...]:
    """Return every item the table declares."""

    return tuple(
        ItemRecord(symbol, display_name)
        for symbol, display_name, _columns in parse_symbol_table(
            text,
            table=CatalogTable.ITEMS,
            symbol_prefix="II_",
            catalog=catalog,
            rejections=rejections,
        )
    )


def parse_skill_table(
    text: str,
    catalog: Mapping[str, str],
    rejections: list[CatalogRejection],
) -> tuple[SkillRecord, ...]:
    """Return every skill the table declares."""

    return tuple(
        SkillRecord(symbol, display_name)
        for symbol, display_name, _columns in parse_symbol_table(
            text,
            table=CatalogTable.SKILLS,
            symbol_prefix="SI_",
            catalog=catalog,
            rejections=rejections,
        )
    )


def parse_npc_table(
    text: str,
    catalog: Mapping[str, str],
    rejections: list[CatalogRejection],
) -> tuple[NpcRecord, ...]:
    """Return every NPC the table declares.

    The client declares NPCs in the same mover table space, so they carry the ``MI_`` prefix
    and are distinguished by the caller supplying the NPC declaration file.
    """

    return tuple(
        NpcRecord(symbol, display_name)
        for symbol, display_name, _columns in parse_symbol_table(
            text,
            table=CatalogTable.NPCS,
            symbol_prefix="MI_",
            catalog=catalog,
            rejections=rejections,
        )
    )


def parse_drop_declarations(
    text: str,
    known_mover_symbols: frozenset[str],
    rejections: list[CatalogRejection],
) -> tuple[DropRecord, ...]:
    """Return every declared mover drop, rejecting blocks for movers no table declares.

    Joining a drop to a mover the mover table never stated would attach loot semantics to a
    guess, so such a block is reported rather than kept.
    """

    drops: list[DropRecord] = []
    for block in DROP_BLOCK_PATTERN.finditer(text):
        mover_symbol = block.group("symbol")
        if mover_symbol not in known_mover_symbols:
            rejections.append(
                CatalogRejection(
                    CatalogTable.DROPS,
                    CatalogRejectionReason.DROP_MOVER_UNKNOWN,
                    mover_symbol,
                )
            )
            continue
        for entry in DROP_ITEM_PATTERN.finditer(block.group("body")):
            minimum_text = entry.group("minimum")
            maximum_text = entry.group("maximum")
            minimum = DEFAULT_DROP_QUANTITY if minimum_text is None else int(minimum_text)
            maximum = minimum if maximum_text is None else int(maximum_text)
            if minimum < 0 or maximum < minimum:
                rejections.append(
                    CatalogRejection(
                        CatalogTable.DROPS,
                        CatalogRejectionReason.FIELD_NOT_NUMERIC,
                        f"{mover_symbol}:{entry.group('item')}",
                    )
                )
                continue
            drops.append(
                DropRecord(
                    mover_symbol,
                    entry.group("item"),
                    int(entry.group("weight")),
                    minimum,
                    maximum,
                )
            )
    return tuple(drops)
