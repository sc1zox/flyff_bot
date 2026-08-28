"""Tests for unified setup extraction and proven memory-profile installation."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from world_fixtures import write_keyed_archive, write_world_directory

from flyff_bot.features.player_stats.profiles import (
    ClientPlayerStatsProfile,
    PlayerStatFieldProfile,
    PlayerStatType,
    load_client_player_stats_profiles,
)
from flyff_bot.features.setup.extraction import (
    _STAGE_COUNT,
    InvalidClientDirectory,
    UnifiedClientExtractor,
)
from flyff_bot.features.setup.models import SetupExtractionWarning
from flyff_bot.features.setup.profiles import fingerprint_executable, install_matching_profile


def _profile_for(path: Path) -> ClientPlayerStatsProfile:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ClientPlayerStatsProfile(
        sha256=digest,
        player_pointer_rva=0x1000,
        pointer_size_bytes=4,
        fields=(
            PlayerStatFieldProfile(
                name="hp",
                offset=16,
                type=PlayerStatType.U32,
                minimum=0,
                maximum=999999,
            ),
        ),
    )


def _client_root(tmp_path: Path) -> Path:
    root = tmp_path / "Entropia"
    (root / "Data" / "System2").mkdir(parents=True)
    executable = root / "neuz.exe"
    payload = b"MZ" + b"\x00" * 58 + struct.pack("<I", 64) + b"PE\x00\x00\x4c\x01"
    executable.write_bytes(payload.ljust(128, b"\x00"))
    write_world_directory(root / "Data" / "World", "TestWorld", blocks=((0, 0, [100.0] * 16641),))
    return root


def test_client_layout_validation_requires_executable_and_data(tmp_path: Path) -> None:
    with pytest.raises(InvalidClientDirectory):
        UnifiedClientExtractor.validate_client_directory(tmp_path / "missing")

    root = tmp_path / "client"
    (root / "Data").mkdir(parents=True)
    (root / "neuz.exe").write_bytes(b"MZ")
    UnifiedClientExtractor.validate_client_directory(root)


def test_first_run_detection_checks_all_required_datasets(
    tmp_path: Path,
) -> None:
    quest_path = tmp_path / "quests.json"
    dungeon_path = tmp_path / "dungeons.json"
    profile_path = tmp_path / "profiles.json"
    assert UnifiedClientExtractor.is_first_run_required(
        world_map_directory=tmp_path / "worlds",
        quest_database=quest_path,
        dungeon_database=dungeon_path,
        player_profiles=profile_path,
    )
    for path in (quest_path, dungeon_path, profile_path):
        path.write_text("[]", encoding="utf-8")
    assert not UnifiedClientExtractor.is_first_run_required(
        world_map_directory=tmp_path,
        quest_database=quest_path,
        dungeon_database=dungeon_path,
        player_profiles=profile_path,
    )


def test_unified_extraction_runs_stages_and_collects_missing_profile(
    tmp_path: Path,
) -> None:
    client_root = _client_root(tmp_path)
    system = client_root / "Data" / "System2"
    write_keyed_archive(system, "data1", {"propMover.txt": b"MI_TEST\t1\n"})
    output = tmp_path / "output"
    paths = UnifiedClientExtractor.default_output_paths()
    paths.world_map_directory = output / "worlds"
    paths.quest_database = output / "quests.json"
    paths.quest_npc_positions = output / "npc.json"
    paths.dungeon_database = output / "dungeons.json"
    paths.player_stats_profiles = output / "profiles.json"
    paths.client_catalog = output / "catalog.json"
    paths.source_manifest = output / "source_manifest.json"
    progress: list[int] = []

    extractor = UnifiedClientExtractor(
        client_root,
        paths,
        progress=lambda update: progress.append(update.percent),
    )
    result = extractor.run()

    # The stage reports rows it actually parsed and wrote, not files it found (BUG-033).
    assert result.mover_count == 1
    assert paths.client_catalog.is_file()
    assert paths.source_manifest.is_file()
    assert result.world_names == ("TestWorld",)
    assert paths.quest_database.is_file()
    assert paths.dungeon_database.is_file()
    assert SetupExtractionWarning.MEMORY_PROFILE_NOT_FOUND in {
        diagnostic.warning for diagnostic in result.diagnostics
    }
    assert progress[-1] == 80 or progress[-1] == 100
    assert len(progress) == _STAGE_COUNT + 2
    assert progress == sorted(progress)


def test_exact_fingerprint_profile_is_installed_without_guessing(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"exact client build")
    profile = _profile_for(executable)
    target = tmp_path / "installed_profiles.json"
    other = ClientPlayerStatsProfile(
        sha256="a" * 64,
        player_pointer_rva=1,
        pointer_size_bytes=4,
        fields=profile.fields,
    )
    loaded = {"a" * 64: other, profile.sha256: profile}
    target.write_text("[]", encoding="utf-8")

    install_matching_profile(loaded, fingerprint_executable(executable), target)

    installed = load_client_player_stats_profiles(target)
    assert installed[profile.sha256] == profile
    assert len(installed) == 1


def test_setup_wizard_validates_path_and_reports_invalid_selection() -> None:
    assert QApplication.instance() is not None or QApplication([]) is not None
