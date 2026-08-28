"""Normalized client-table extraction and its typed rejections (US-083)."""

from __future__ import annotations

from pathlib import Path

import pytest
from world_fixtures import utf16_text, write_keyed_archive

from flyff_bot.features.client_data.extraction import (
    DROP_TABLE_FILE,
    ITEM_TABLE_FILE,
    MOVER_TABLE_FILE,
    MOVER_TEXT_CATALOG,
    SKILL_TABLE_FILE,
    extract_client_catalog,
)
from flyff_bot.features.client_data.models import (
    CLIENT_CATALOG_SCHEMA_VERSION,
    CatalogRejectionReason,
    CatalogTable,
    ClientCatalog,
    MoverCombatProperties,
    MoverRecord,
)
from flyff_bot.features.client_data.persistence import (
    CatalogSchemaError,
    load_client_catalog,
    save_client_catalog,
)
from flyff_bot.features.client_data.tables import (
    parse_drop_declarations,
    parse_mover_table,
    parse_table_header,
)

MOVER_HEADER = "//\tdwID\tszName\tdwLevel\tdwAtkMin\tdwAtkMax\tdwAddHp\tdwBelligerence\n"


def _mover_row(symbol: str, reference: str, level: int, aggro: int = 1) -> str:
    return f"{symbol}\t{reference}\t{level}\t12\t34\t560\t{aggro}\n"


def test_a_column_header_locates_every_declared_mover_field() -> None:
    """Numeric columns are read by the client's own header, never by a fixed index."""

    rejections: list[object] = []
    movers = parse_mover_table(
        MOVER_HEADER + _mover_row("MI_FLAME", "IDS_FLAME", 15),
        {"IDS_FLAME": "Flame"},
        rejections,  # type: ignore[arg-type]
    )

    assert len(movers) == 1
    mover = movers[0]
    assert mover.symbol == "MI_FLAME"
    assert mover.display_name == "Flame"
    assert mover.combat.level == 15
    assert mover.combat.attack_minimum == 12
    assert mover.combat.attack_maximum == 34
    assert mover.combat.hit_points == 560
    assert mover.combat.is_aggressive is True


def test_a_table_without_a_header_yields_no_invented_combat_values() -> None:
    """Without a declared layout the numeric columns stay missing rather than guessed."""

    rejections: list[object] = []
    movers = parse_mover_table(
        _mover_row("MI_FLAME", "IDS_FLAME", 15),
        {"IDS_FLAME": "Flame"},
        rejections,  # type: ignore[arg-type]
    )

    assert movers[0].combat == MoverCombatProperties()
    assert movers[0].combat.is_aggressive is None
    assert any(
        rejection.reason is CatalogRejectionReason.LAYOUT_UNVERIFIED  # type: ignore[attr-defined]
        for rejection in rejections
    )


def test_a_duplicated_symbol_rejects_both_rows_instead_of_keeping_the_first() -> None:
    """A consumer joining on the symbol could not tell which row the client means."""

    rejections: list[object] = []
    movers = parse_mover_table(
        MOVER_HEADER
        + _mover_row("MI_FLAME", "IDS_FLAME", 15)
        + _mover_row("MI_FLAME", "IDS_FLAME", 99),
        {"IDS_FLAME": "Flame"},
        rejections,  # type: ignore[arg-type]
    )

    assert movers == ()
    assert any(
        rejection.reason is CatalogRejectionReason.SYMBOL_DUPLICATED  # type: ignore[attr-defined]
        for rejection in rejections
    )


def test_a_name_missing_from_the_catalog_is_reported_and_not_back_filled() -> None:
    rejections: list[object] = []
    movers = parse_mover_table(
        MOVER_HEADER + _mover_row("MI_FLAME", "IDS_FLAME", 15),
        {},
        rejections,  # type: ignore[arg-type]
    )

    assert movers[0].display_name is None
    assert any(
        rejection.reason is CatalogRejectionReason.NAME_UNRESOLVED  # type: ignore[attr-defined]
        for rejection in rejections
    )


def test_parse_table_header_aligns_column_names_with_the_data_columns() -> None:
    """The comment marker is not a data column, so it must not shift every name by one."""

    assert parse_table_header("// a note\n" + MOVER_HEADER)[0] == "dwID"


def test_a_drop_for_an_undeclared_mover_is_rejected_rather_than_attached() -> None:
    """Loot semantics must not be bound to a mover the client never declared."""

    rejections: list[object] = []
    drops = parse_drop_declarations(
        "MI_FLAME { DropItem( II_STONE, 3000000, 1, 2 ) }\n"
        "MI_GHOST { DropItem( II_GEM, 10, 1, 1 ) }\n",
        frozenset({"MI_FLAME"}),
        rejections,  # type: ignore[arg-type]
    )

    assert [drop.item_symbol for drop in drops] == ["II_STONE"]
    assert drops[0].minimum_quantity == 1
    assert drops[0].maximum_quantity == 2
    assert drops[0].probability_weight == 3000000
    assert [
        rejection.locator  # type: ignore[attr-defined]
        for rejection in rejections
        if rejection.reason is CatalogRejectionReason.DROP_MOVER_UNKNOWN  # type: ignore[attr-defined]
    ] == ["MI_GHOST"]


def test_a_drop_without_a_quantity_range_drops_exactly_one() -> None:
    rejections: list[object] = []
    drops = parse_drop_declarations(
        "MI_FLAME { DropItem( II_STONE, 500 ) }\n",
        frozenset({"MI_FLAME"}),
        rejections,  # type: ignore[arg-type]
    )

    assert (drops[0].minimum_quantity, drops[0].maximum_quantity) == (1, 1)


def test_a_missing_table_is_reported_rather_than_counted(tmp_path: Path) -> None:
    """Finding no table yields a typed rejection, never a silent zero-record success."""

    data_root = tmp_path / "Data"
    (data_root / "System2").mkdir(parents=True)
    write_keyed_archive(data_root / "System2", "data1", {"unrelated.txt": b"x"})

    catalog = extract_client_catalog(data_root)

    assert catalog.movers == ()
    reasons = {rejection.reason for rejection in catalog.rejections_for(CatalogTable.MOVERS)}
    assert CatalogRejectionReason.TABLE_MISSING in reasons


def test_real_rows_are_parsed_from_packed_client_archives(tmp_path: Path) -> None:
    """A count is reported only for rows this pass actually parsed (BUG-033)."""

    data_root = tmp_path / "Data"
    system = data_root / "System2"
    language = system / "Lang" / "English"
    system.mkdir(parents=True)
    language.mkdir(parents=True)
    write_keyed_archive(
        system,
        "data1",
        {
            MOVER_TABLE_FILE: utf16_text(MOVER_HEADER + _mover_row("MI_FLAME", "IDS_FLAME", 15)),
            DROP_TABLE_FILE: utf16_text("MI_FLAME { DropItem( II_STONE, 700, 1, 3 ) }\n"),
            ITEM_TABLE_FILE: utf16_text("II_STONE\tIDS_STONE\t1\n"),
            SKILL_TABLE_FILE: utf16_text("SI_BLAZE\tIDS_BLAZE\t1\n"),
        },
    )
    write_keyed_archive(
        language,
        "english",
        {
            MOVER_TEXT_CATALOG: utf16_text("IDS_FLAME\tFlame\r\n"),
            "propItem.txt.txt": utf16_text("IDS_STONE\tStone\r\n"),
            "propSkill.txt.txt": utf16_text("IDS_BLAZE\tBlaze\r\n"),
        },
    )

    catalog = extract_client_catalog(data_root)

    assert [mover.symbol for mover in catalog.movers] == ["MI_FLAME"]
    assert catalog.movers[0].display_name == "Flame"
    assert catalog.movers[0].combat.level == 15
    assert [drop.item_symbol for drop in catalog.drops] == ["II_STONE"]
    assert [item.display_name for item in catalog.items] == ["Stone"]
    assert [skill.display_name for skill in catalog.skills] == ["Blaze"]
    assert catalog.record_count(CatalogTable.MOVERS) == 1


def test_a_catalog_round_trips_through_its_persisted_document(tmp_path: Path) -> None:
    catalog = ClientCatalog(
        movers=(MoverRecord("MI_FLAME", "Flame", MoverCombatProperties(level=15, hit_points=560)),),
    )
    path = tmp_path / "catalog.json"

    save_client_catalog(catalog, path)

    assert load_client_catalog(path) == catalog


def test_a_catalog_of_another_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text('{"schema_version": "us000-v0"}', encoding="utf-8")

    with pytest.raises(CatalogSchemaError) as error:
        load_client_catalog(path)

    assert error.value.expected == CLIENT_CATALOG_SCHEMA_VERSION
    assert error.value.found == "us000-v0"
