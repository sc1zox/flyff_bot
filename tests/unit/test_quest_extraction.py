"""Tests for keyed client archives, quest script parsing, and quest persistence."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest
from world_fixtures import encode_keyed_payload, utf16_text, write_keyed_archive

from flyff_bot.features.navigation.client_archive import (
    KEYED_ARCHIVE_IDENTITY_SALT,
    ClientArchiveError,
    KeyedClientArchive,
    decode_keyed_payload,
    keyed_archive_identity,
    read_keyed_archive_index,
)
from flyff_bot.features.quests.client_tables import (
    ITEM_SYMBOL_PREFIX,
    MONSTER_SYMBOL_PREFIX,
    decode_client_text,
    parse_symbol_names,
    parse_text_catalog,
)
from flyff_bot.features.quests.extraction import (
    ClientDataArchives,
    QuestExtractionWarning,
    extract_quest_database,
)
from flyff_bot.features.quests.models import QuestCollection, QuestDatabase, QuestDefinition
from flyff_bot.features.quests.persistence import (
    QuestDatabaseError,
    load_quest_database,
    save_quest_database,
)
from flyff_bot.features.quests.script_parser import parse_quest_script, strip_comments

QUEST_SCRIPT = """
// A comment naming the file
6050
{
\tSetTitle( IDS_Q_GROUP );
}

QUEST_HUNT_AIBATT
{
\tSetTitle( IDS_Q_TITLE );
\tsetting
\t{
\t\tSetCharacter( "MaDa_Hent" );
\t\tSetBeginCondLevel( 15, 20 );
\t\tSetEndCondKillNPC( 0, MI_AIBATT1, 10, 7128, 3333, 1 );
\t\tSetEndRewardGold( 1500, 1500 );
\t\tSetHeadQuest( 6050 );
\t}
\tstate 0
\t{
\t\tSetCond( IDS_Q_COND );
\t}
}

QUEST_COLLECT_STONES
{
\tSetTitle( IDS_Q_TITLE2 );
\tsetting
\t{
\t\tSetEndCondItem( -1, 0, 0, II_STONE, 5, -1, -1, QUEST_DESTINATION_ID_0002 );
\t\tQuestItem( MI_AIBATT1, II_STONE, 3000000000, 1 );
\t\tQuestItem( MI_AIBATT2, II_STONE, 3000000000, 1 );
\t\tSetEndRewardItem( -1, 0, -1, II_BLINKWING, 2 );
\t}
}
"""

CATALOG = {
    "IDS_Q_GROUP": "Flaris",
    "IDS_Q_TITLE": "Vagrant Master",
    "IDS_Q_TITLE2": "Stone Gathering",
    "IDS_Q_COND": "Kill ten Small Aibatt.",
}
MONSTER_NAMES = {"MI_AIBATT1": "Small Aibatt", "MI_AIBATT2": "Aibatt"}
ITEM_NAMES = {"II_STONE": "Twinkle Stone", "II_BLINKWING": "Blinkwing"}


def test_keyed_payload_decoding_is_the_inverse_of_the_client_transform() -> None:
    plain = b"// world script" + bytes(range(64))
    stored = encode_keyed_payload(plain, "wdverux.wld")

    assert decode_keyed_payload(stored, "wdverux.wld") == plain
    assert decode_keyed_payload(stored, "WDVERUX.WLD") == plain


def test_keyed_payload_decoding_rejects_an_empty_file_name() -> None:
    with pytest.raises(ClientArchiveError):
        decode_keyed_payload(b"\x00", "")


def test_keyed_identity_is_the_salted_digest_of_the_lower_case_name() -> None:
    expected = hashlib.sha256(KEYED_ARCHIVE_IDENTITY_SALT + b"propquest.inc").hexdigest()

    assert keyed_archive_identity("propQuest.inc") == expected


def test_keyed_index_rejects_a_record_that_is_not_in_the_keyed_layout() -> None:
    index = struct.pack("<i", 1) + struct.pack("<i", 7)

    with pytest.raises(ClientArchiveError):
        read_keyed_archive_index(index)


def test_keyed_archive_reads_a_packed_file_by_name(tmp_path: Path) -> None:
    write_keyed_archive(tmp_path, "data1", {"propQuest.inc": utf16_text(QUEST_SCRIPT)})
    archive = KeyedClientArchive.open_pair(tmp_path / "data1.hdr")

    assert archive is not None
    assert archive.entry_count == 1
    assert archive.read("propQuest.inc") == utf16_text(QUEST_SCRIPT)
    assert archive.read("propItem.txt") is None


def test_keyed_archive_ignores_an_index_of_the_other_generation(tmp_path: Path) -> None:
    (tmp_path / "old.hdr").write_bytes(struct.pack("<i", 1) + struct.pack("<i", 64))
    (tmp_path / "old.one").write_bytes(b"")

    assert KeyedClientArchive.open_pair(tmp_path / "old.hdr") is None


def test_client_text_decoding_handles_both_shipped_encodings() -> None:
    assert decode_client_text(utf16_text("Small Aibatt")) == "Small Aibatt"
    assert decode_client_text(b"Small Aibatt") == "Small Aibatt"


def test_text_catalog_reads_the_identifier_and_its_first_text_column() -> None:
    catalog = parse_text_catalog("IDS_A\tEvent\t\r\nIDS_B\tGeneral\r\nnoise line\r\n")

    assert catalog == {"IDS_A": "Event", "IDS_B": "General"}


def test_symbol_names_find_the_symbol_column_whatever_precedes_it() -> None:
    catalog = {"IDS_M": "Small Aibatt", "IDS_I": "Twinkle Stone"}
    movers = parse_symbol_names("MI_AIBATT1\tIDS_M\t15\t20\n", MONSTER_SYMBOL_PREFIX, catalog)
    items = parse_symbol_names("6\tII_STONE\tIDS_I\t1\n", ITEM_SYMBOL_PREFIX, catalog)

    assert movers == {"MI_AIBATT1": "Small Aibatt"}
    assert items == {"II_STONE": "Twinkle Stone"}


def test_symbol_names_skip_a_symbol_whose_string_is_not_in_the_catalog() -> None:
    assert parse_symbol_names("MI_X\tIDS_MISSING\t1\n", MONSTER_SYMBOL_PREFIX, {}) == {}


def test_strip_comments_keeps_string_literals_intact() -> None:
    source = 'SetCharacter( "http://not-a-comment" ); // trailing\n/* block */ SetTitle( A );'

    stripped = strip_comments(source)

    assert '"http://not-a-comment"' in stripped
    assert "trailing" not in stripped
    assert "block" not in stripped


def test_quest_script_parses_kill_requirements_with_their_destination() -> None:
    quests = parse_quest_script(
        QUEST_SCRIPT,
        QuestCollection.GENERAL,
        strings=CATALOG,
        monster_names=MONSTER_NAMES,
        item_names=ITEM_NAMES,
    )
    hunt = next(quest for quest in quests if quest.quest_id.endswith("QUEST_HUNT_AIBATT"))

    assert hunt.title == "Vagrant Master"
    assert hunt.group == "Flaris"
    assert hunt.objective == "Kill ten Small Aibatt."
    assert (hunt.minimum_level, hunt.maximum_level) == (15, 20)
    assert hunt.reward_gold == 1500
    requirement = hunt.kill_requirements[0]
    assert requirement.monster_symbol == "MI_AIBATT1"
    assert requirement.monster_name == "Small Aibatt"
    assert requirement.required_kills == 10
    assert requirement.destination is not None
    assert (requirement.destination.x, requirement.destination.z) == (7128.0, 3333.0)


def test_quest_script_pairs_collection_requirements_with_their_drop_sources() -> None:
    quests = parse_quest_script(
        QUEST_SCRIPT,
        QuestCollection.GENERAL,
        strings=CATALOG,
        monster_names=MONSTER_NAMES,
        item_names=ITEM_NAMES,
    )
    collect = next(quest for quest in quests if quest.quest_id.endswith("QUEST_COLLECT_STONES"))
    requirement = collect.item_requirements[0]

    assert requirement.item_name == "Twinkle Stone"
    assert requirement.required_quantity == 5
    assert [source.display_name for source in requirement.sources] == ["Small Aibatt", "Aibatt"]
    assert collect.reward_items == ("2x Blinkwing",)
    assert collect.monster_names() == ("Small Aibatt", "Aibatt")


def test_quest_script_treats_a_numbered_title_only_block_as_a_group() -> None:
    quests = parse_quest_script(QUEST_SCRIPT, QuestCollection.GENERAL, strings=CATALOG)

    assert all(not quest.quest_id.endswith(":6050") for quest in quests)
    assert len(quests) == 2


def test_quest_script_leaves_an_unresolved_symbol_in_place() -> None:
    quests = parse_quest_script(QUEST_SCRIPT, QuestCollection.GENERAL)
    hunt = next(quest for quest in quests if quest.quest_id.endswith("QUEST_HUNT_AIBATT"))

    assert hunt.title == ""
    assert hunt.kill_requirements[0].display_name == "MI_AIBATT1"


def test_quest_extraction_reads_a_synthetic_client_tree(tmp_path: Path) -> None:
    system = tmp_path / "System2"
    language = system / "Lang" / "English"
    language.mkdir(parents=True)
    write_keyed_archive(
        system,
        "data1",
        {
            "propQuest.inc": utf16_text(QUEST_SCRIPT),
            "propMover.txt": utf16_text("MI_AIBATT1\tIDS_M\t15\n"),
            "Spec_Item.txt": utf16_text("6\tII_STONE\tIDS_I\t1\n"),
        },
    )
    write_keyed_archive(
        language,
        "english",
        {
            "propQuest.txt.txt": utf16_text("IDS_Q_TITLE\tVagrant Master\r\n"),
            "propMover.txt.txt": utf16_text("IDS_M\tSmall Aibatt\r\n"),
            "propItem.txt.txt": utf16_text("IDS_I\tTwinkle Stone\r\n"),
        },
    )
    diagnostics: list[object] = []

    database = extract_quest_database(tmp_path, diagnostics=diagnostics)  # type: ignore[arg-type]
    hunt = database.get("general:QUEST_HUNT_AIBATT")

    assert hunt is not None
    assert hunt.title == "Vagrant Master"
    assert hunt.kill_requirements[0].monster_name == "Small Aibatt"
    assert len(database.farmable) == 2
    warnings = {getattr(entry, "warning", None) for entry in diagnostics}
    assert QuestExtractionWarning.NO_CLIENT_ARCHIVE not in warnings


def test_quest_extraction_reports_a_client_directory_without_archives(tmp_path: Path) -> None:
    diagnostics: list[object] = []

    database = extract_quest_database(tmp_path, diagnostics=diagnostics)  # type: ignore[arg-type]

    assert database.quests == ()
    assert diagnostics
    assert getattr(diagnostics[0], "warning", None) is QuestExtractionWarning.NO_CLIENT_ARCHIVE


def test_client_data_archives_report_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    archives = ClientDataArchives.open_directory(tmp_path / "missing")

    assert archives.is_empty
    assert archives.read("propQuest.inc") is None


def test_quest_database_round_trips_through_its_json_document(tmp_path: Path) -> None:
    quests = parse_quest_script(
        QUEST_SCRIPT,
        QuestCollection.GENERAL,
        strings=CATALOG,
        monster_names=MONSTER_NAMES,
        item_names=ITEM_NAMES,
    )
    database = QuestDatabase(quests=quests, language="English")
    path = save_quest_database(database, tmp_path / "quests" / "quests.json")

    restored = load_quest_database(path)

    assert restored.language == "English"
    assert restored.quests == database.quests


def test_quest_database_rejects_a_foreign_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "quests.json"
    path.write_text('{"schema_version": 99, "quests": []}', encoding="utf-8")

    with pytest.raises(QuestDatabaseError):
        load_quest_database(path)


def test_quest_database_rejects_a_repeated_quest_identifier() -> None:
    quest = QuestDefinition(quest_id="general:A", title="A", collection=QuestCollection.GENERAL)

    with pytest.raises(ValueError):
        QuestDatabase(quests=(quest, quest))


def test_quest_search_matches_title_area_and_monster_name() -> None:
    quests = parse_quest_script(
        QUEST_SCRIPT,
        QuestCollection.GENERAL,
        strings=CATALOG,
        monster_names=MONSTER_NAMES,
        item_names=ITEM_NAMES,
    )
    hunt = next(quest for quest in quests if quest.quest_id.endswith("QUEST_HUNT_AIBATT"))

    assert hunt.matches("vagrant")
    assert hunt.matches("flaris")
    assert hunt.matches("aibatt")
    assert hunt.matches("")
    assert not hunt.matches("nonsense")
