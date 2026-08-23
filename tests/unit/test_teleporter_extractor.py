"""Tests for offline teleporter extraction and persistence (US-065)."""

from __future__ import annotations

import json
from pathlib import Path

from world_fixtures import utf16_text, write_keyed_archive

from flyff_bot.features.navigation.teleporter_extraction import (
    TeleporterExtractionDiagnostic,
    TeleporterExtractionWarning,
    extract_teleporter_catalog,
    parse_teleporter_destinations,
    save_teleporter_catalog,
)
from flyff_bot.features.navigation.teleporter_models import TeleporterCatalog

SOURCE = """
// comment AddTeleportOption(999, "Hidden", 1)
AddTeleportOption(1, "Flarine", 0, "Starting town", 1, 99, "city");
AddTeleportOptions(2, "Darkon", 1, "High level", 80, -1, "field", "Darkon City", 100.0, 200.0);
AddTeleportOption(3, "Broken", not-a-number, "", 1, 99, "field");
AddTeleportOption(4, "Wrong", 0, "", 1, 99);
"""


def test_parses_all_well_formed_destination_records() -> None:
    destinations = parse_teleporter_destinations(SOURCE)

    assert [destination.destination_id for destination in destinations] == [1, 2]
    assert destinations[0].name == "Flarine"
    assert destinations[0].search_text == "Flarine"
    assert (destinations[0].world_id, destinations[0].minimum_level) == (0, 1)
    assert destinations[0].maximum_level == 99
    assert destinations[0].category == "city"
    assert destinations[1].anchor_x == 100.0
    assert destinations[1].anchor_z == 200.0


def test_reports_malformed_records_without_stopping_the_scan() -> None:
    diagnostics: list[TeleporterExtractionDiagnostic] = []
    destinations = parse_teleporter_destinations(SOURCE, diagnostics)

    assert len(destinations) == 2
    assert {diagnostic.warning for diagnostic in diagnostics} == {
        TeleporterExtractionWarning.MALFORMED_RECORD
    }


def test_extracts_a_packed_client_asset(tmp_path: Path) -> None:
    write_keyed_archive(
        tmp_path / "System3",
        "data1",
        {"TeleportOption.inc": utf16_text(SOURCE)},
    )

    catalog = extract_teleporter_catalog(tmp_path)

    assert len(catalog.destinations) == 2
    assert catalog.find_exact("darkon city") is catalog.destinations[1]


def test_prefers_a_loose_client_asset(tmp_path: Path) -> None:
    system = tmp_path / "System3"
    system.mkdir()
    (system / "TeleportOption.inc").write_bytes(utf16_text('AddTeleportOption(9, "Loose", 4);'))

    catalog = extract_teleporter_catalog(tmp_path)

    assert len(catalog.destinations) == 1
    assert catalog.destinations[0].name == "Loose"


def test_reports_a_missing_asset_without_guessing(
    tmp_path: Path,
) -> None:
    diagnostics: list[TeleporterExtractionDiagnostic] = []
    catalog = extract_teleporter_catalog(tmp_path, diagnostics=diagnostics)

    assert catalog.destinations == ()
    assert diagnostics[0].warning is TeleporterExtractionWarning.MISSING_CLIENT_ARCHIVE


def test_saves_a_canonical_schema_document(tmp_path: Path) -> None:
    destination = parse_teleporter_destinations(SOURCE)[0]
    path = save_teleporter_catalog(
        TeleporterCatalog((destination,)),
        tmp_path / "out.json",
    )

    document = json.loads(path.read_text(encoding="utf-8"))

    assert path == tmp_path / "out.json"
    assert document["schema_version"] == 1
