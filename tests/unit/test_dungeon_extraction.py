"""Tests for dungeon archive extraction and versioned persistence (US-063)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from world_fixtures import utf16_text, write_keyed_archive

from flyff_bot.features.dungeons.extraction import (
    DungeonExtractionDiagnostic,
    DungeonExtractionWarning,
    extract_dungeon_definitions,
    parse_dungeon_ranking,
    parse_dungeon_script,
)
from flyff_bot.features.dungeons.models import DungeonDefinition, format_cooldown
from flyff_bot.features.dungeons.persistence import (
    DungeonDatabaseError,
    load_dungeon_database,
    save_dungeon_database,
)

DUNGEON_SCRIPT = """
AddDungeon( "WI_WORLD_101" )
{
    SetLevel( 60, 300 )
    SetCoolTime( MIN(60) )
}

AddDungeon( "WI_WORLD_102" )
{
    SetLevel( 70, 250 )
    SetCoolTime( 90 )
    SetEntryCount( 3 )
}
"""


def _dungeon() -> DungeonDefinition:
    return DungeonDefinition(
        dungeon_id=101,
        name="Ominous",
        minimum_level=60,
        maximum_level=300,
        base_cooldown_seconds=3600,
        daily_entry_limit=2,
    )


def test_parser_reads_verified_level_and_minute_cooldown_fields() -> None:
    parsed = parse_dungeon_script(DUNGEON_SCRIPT)

    assert ("WI_WORLD_101", (60, 300), 3600, 0) in parsed
    assert ("WI_WORLD_102", (70, 250), 90, 3) in parsed


def test_extractor_resolves_names_and_world_ids_from_synthetic_keyed_archive(
    tmp_path: Path,
) -> None:
    system = tmp_path / "System2"
    write_keyed_archive(
        system,
        "data9",
        {
            "PartyDungeon.lua": utf16_text(DUNGEON_SCRIPT),
            "propQuest-DungeonandPKtxt.txt": utf16_text(
                "IDS_WI_WORLD_101\tOminous\r\nWI_WORLD_102\tWorld 102\r\n"
            ),
        },
    )

    dungeons = extract_dungeon_definitions(tmp_path)

    assert {(dungeon.dungeon_id, dungeon.name) for dungeon in dungeons} == {
        (101, "Ominous"),
        (102, "World 102"),
    }


def test_missing_client_data_is_reported_without_guessing_entries(tmp_path: Path) -> None:
    diagnostics: list[DungeonExtractionDiagnostic] = []

    assert extract_dungeon_definitions(tmp_path / "missing", diagnostics=diagnostics) == ()
    assert [item.warning for item in diagnostics] == [DungeonExtractionWarning.NO_CLIENT_ARCHIVE]


def test_database_round_trip_preserves_definitions_and_rejects_unknown_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "dungeons.json"
    save_dungeon_database((_dungeon(),), path, language="English", client_digest="a" * 64)

    loaded = load_dungeon_database(path)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert loaded == (_dungeon(),)
    assert document["schema_version"] == 1
    document["schema_version"] = 99
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DungeonDatabaseError, match="schema version"):
        load_dungeon_database(path)


def test_duplicate_loaded_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "dungeons.json"
    path.write_text(
        json.dumps({"schema_version": 1, "dungeons": [_dungeon().as_document()] * 2}),
        encoding="utf-8",
    )

    with pytest.raises(DungeonDatabaseError, match="repeats"):
        load_dungeon_database(path)


def test_cooldown_format_is_zero_padded_hours_minutes_seconds() -> None:
    assert format_cooldown(0) == "00:00:00"
    assert format_cooldown(3661.4) == "01:01:01"
    assert format_cooldown(-1) == "00:00:00"


DUNGEON_RANKING_TABLE = """7//Days till next DungeonReset
121 //Aminus Dungeon
{
\tAddReward 1 0
\t{
\t\t55542 15\t//15x Ultra Sunstone (Weapon)
\t}
\tSetTexture("AminusRanking.tga")
}
357 // WI_DUNGEON_DACULAMAUSOLEUM
{
\tSetTexture("MausoleumRanking.tga")
}
//353 //Ruins of Desire
//{
//\tAddReward 1 0
//}
"""


def test_ranking_table_declares_dungeons_without_inventing_levels_or_cooldowns() -> None:
    parsed = parse_dungeon_ranking(DUNGEON_RANKING_TABLE)

    assert parsed == ((121, "Aminus Dungeon"), (357, "WI_DUNGEON_DACULAMAUSOLEUM"))


def test_extractor_falls_back_to_the_ranking_table_when_no_dungeon_script_is_packed(
    tmp_path: Path,
) -> None:
    system = tmp_path / "System2"
    write_keyed_archive(
        system,
        "data9",
        {
            "DungeonRanking.inc": utf16_text(DUNGEON_RANKING_TABLE),
            "propQuest-DungeonandPKtxt.txt": utf16_text(
                "WI_DUNGEON_DACULAMAUSOLEUM\tDacula Mausoleum\r\n"
            ),
        },
    )
    diagnostics: list[DungeonExtractionDiagnostic] = []

    dungeons = extract_dungeon_definitions(tmp_path, diagnostics=diagnostics)

    assert {(dungeon.dungeon_id, dungeon.name) for dungeon in dungeons} == {
        (121, "Aminus Dungeon"),
        (357, "Dacula Mausoleum"),
    }
    assert all(dungeon.minimum_level is None for dungeon in dungeons)
    assert all(dungeon.base_cooldown_seconds is None for dungeon in dungeons)
    assert [item.warning for item in diagnostics] == [
        DungeonExtractionWarning.MISSING_DUNGEON_SCRIPT
    ]


def test_client_without_any_dungeon_declaration_reports_both_missing_sources(
    tmp_path: Path,
) -> None:
    write_keyed_archive(tmp_path / "System2", "data9", {"propMover.txt": utf16_text("x\n")})
    diagnostics: list[DungeonExtractionDiagnostic] = []

    assert extract_dungeon_definitions(tmp_path, diagnostics=diagnostics) == ()
    assert [item.warning for item in diagnostics] == [
        DungeonExtractionWarning.MISSING_DUNGEON_SCRIPT,
        DungeonExtractionWarning.MISSING_DUNGEON_RANKING,
    ]


def test_undeclared_levels_and_cooldowns_survive_a_database_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "dungeons.json"
    undeclared = DungeonDefinition(dungeon_id=121, name="Aminus Dungeon")
    save_dungeon_database((undeclared,), path, language="English", client_digest="b" * 64)

    assert load_dungeon_database(path) == (undeclared,)
