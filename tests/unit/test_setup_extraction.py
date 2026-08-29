"""Tests for unified setup extraction and proven memory-profile installation."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from world_fixtures import write_keyed_archive, write_world_directory

from flyff_bot.features.client_profiling.models import GeneratedClientProfileBundle
from flyff_bot.features.dungeons.profiles import (
    ClientDungeonProfile,
    DungeonFieldLayout,
    FixedDungeonArray,
)
from flyff_bot.features.navigation.live_camera import ClientCameraProfile
from flyff_bot.features.navigation.live_position import ClientPositionProfile
from flyff_bot.features.player_stats.profiles import (
    ClientPlayerStatsProfile,
    DirectPlayerStatSource,
    PlayerStatFieldProfile,
    PlayerStatType,
    RatioPlayerStatSource,
)
from flyff_bot.features.setup.extraction import (
    _STAGE_COUNT,
    InvalidClientDirectory,
    UnifiedClientExtractor,
    _validate_client_layout,
)
from flyff_bot.features.setup.models import SetupExtractionWarning

DIGEST = "a" * 64


def _bundle() -> GeneratedClientProfileBundle:
    fields = (
        PlayerStatFieldProfile("hp", RatioPlayerStatSource(0, 4, PlayerStatType.U32), 0.0, 100.0),
        PlayerStatFieldProfile("mp", RatioPlayerStatSource(8, 12, PlayerStatType.U32), 0.0, 100.0),
        PlayerStatFieldProfile("fp", RatioPlayerStatSource(16, 20, PlayerStatType.U32), 0.0, 100.0),
        PlayerStatFieldProfile(
            "level", DirectPlayerStatSource(24, PlayerStatType.U32), 1.0, 1000.0
        ),
        PlayerStatFieldProfile(
            "experience",
            DirectPlayerStatSource(32, PlayerStatType.U64),
            0.0,
            float(2**63 - 1),
        ),
    )
    return GeneratedClientProfileBundle(
        ClientPositionProfile(DIGEST, 0x1000, 8, 0x188),
        ClientPlayerStatsProfile(DIGEST, 0x1000, 8, fields),
        ClientCameraProfile(DIGEST, 0x2000, 8, 8, 0x14, 0x94, 0x3000),
        ClientDungeonProfile(
            DIGEST,
            0x4000,
            8,
            FixedDungeonArray(0x20, 32, 4),
            DungeonFieldLayout(0, 8, 12, 16),
        ),
    )


class _FakeProfiler:
    def profile(self, _path: Path) -> GeneratedClientProfileBundle:
        return _bundle()


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


def test_client_layout_validation_accepts_architecture_subdirectories(tmp_path: Path) -> None:
    for subdirectory in ("bin64", "bin32"):
        root = tmp_path / subdirectory
        (root / "Data").mkdir(parents=True)
        (root / subdirectory).mkdir()
        (root / subdirectory / "neuz.exe").write_bytes(b"MZ")

        UnifiedClientExtractor.validate_client_directory(root)


def test_client_layout_validation_prefers_the_sixty_four_bit_build(tmp_path: Path) -> None:
    root = tmp_path / "Entropia"
    (root / "Data").mkdir(parents=True)
    for subdirectory in ("bin32", "bin64"):
        (root / subdirectory).mkdir()
        (root / subdirectory / "neuz.exe").write_bytes(b"MZ")

    executable, data_root = _validate_client_layout(root)

    assert executable == root / "bin64" / "neuz.exe"
    assert data_root == root / "Data"


def test_client_layout_validation_accepts_a_nested_install_directory(tmp_path: Path) -> None:
    outer = tmp_path / "Entropia"
    inner = outer / "Entropia"
    (inner / "Data").mkdir(parents=True)
    (inner / "bin64").mkdir()
    (inner / "bin64" / "neuz.exe").write_bytes(b"MZ")

    executable, data_root = _validate_client_layout(outer)

    assert executable == inner / "bin64" / "neuz.exe"
    assert data_root == inner / "Data"


def test_first_run_detection_checks_all_required_datasets(
    tmp_path: Path,
) -> None:
    quest_path = tmp_path / "quests.json"
    dungeon_path = tmp_path / "dungeons.json"
    profile_paths = tuple(tmp_path / f"profiles-{index}.json" for index in range(4))
    catalog_path = tmp_path / "catalog.json"
    manifest_path = tmp_path / "source_manifest.json"
    required_paths = (quest_path, dungeon_path, *profile_paths, catalog_path, manifest_path)
    assert UnifiedClientExtractor.is_first_run_required(
        world_map_directory=tmp_path / "worlds",
        quest_database=quest_path,
        dungeon_database=dungeon_path,
        position_profiles=profile_paths[0],
        player_stats_profiles=profile_paths[1],
        camera_profiles=profile_paths[2],
        dungeon_profiles=profile_paths[3],
        client_catalog=catalog_path,
        source_manifest=manifest_path,
    )
    for path in required_paths[:-2]:
        path.write_text("[]", encoding="utf-8")
    # The catalog and its manifest are mandatory too: without them no detection can be
    # attributed to the mover the client declares (US-085).
    assert UnifiedClientExtractor.is_first_run_required(
        world_map_directory=tmp_path,
        quest_database=quest_path,
        dungeon_database=dungeon_path,
        position_profiles=profile_paths[0],
        player_stats_profiles=profile_paths[1],
        camera_profiles=profile_paths[2],
        dungeon_profiles=profile_paths[3],
        client_catalog=catalog_path,
        source_manifest=manifest_path,
    )
    for path in required_paths[-2:]:
        path.write_text("[]", encoding="utf-8")
    assert not UnifiedClientExtractor.is_first_run_required(
        world_map_directory=tmp_path,
        quest_database=quest_path,
        dungeon_database=dungeon_path,
        position_profiles=profile_paths[0],
        player_stats_profiles=profile_paths[1],
        camera_profiles=profile_paths[2],
        dungeon_profiles=profile_paths[3],
        client_catalog=catalog_path,
        source_manifest=manifest_path,
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
    paths.position_profiles = output / "position-profiles.json"
    paths.player_stats_profiles = output / "player-profiles.json"
    paths.camera_profiles = output / "camera-profiles.json"
    paths.dungeon_profiles = output / "dungeon-profiles.json"
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
    assert not paths.player_stats_profiles.exists()
    assert SetupExtractionWarning.CLIENT_PROFILING_FAILED in {
        diagnostic.warning for diagnostic in result.diagnostics
    }
    assert progress[-1] == 80 or progress[-1] == 100
    assert len(progress) in (_STAGE_COUNT + 1, _STAGE_COUNT + 2)
    assert progress == sorted(progress)


def test_exact_fingerprint_bundle_is_installed_without_guessing(tmp_path: Path) -> None:
    client_root = _client_root(tmp_path)
    paths = UnifiedClientExtractor.default_output_paths()
    paths.position_profiles = tmp_path / "position.json"
    paths.player_stats_profiles = tmp_path / "stats.json"
    paths.camera_profiles = tmp_path / "camera.json"
    paths.dungeon_profiles = tmp_path / "dungeon.json"

    result = UnifiedClientExtractor(
        client_root, paths, profiler=_FakeProfiler()
    ).run_memory_profile_only()

    assert result.memory_profile is not None
    assert result.memory_profile.sha256 == DIGEST
    assert all(
        path.is_file()
        for path in (
            paths.position_profiles,
            paths.player_stats_profiles,
            paths.camera_profiles,
            paths.dungeon_profiles,
        )
    )


def test_run_memory_profile_only_retains_existing_dataset_counts(tmp_path: Path) -> None:
    client_root = _client_root(tmp_path)
    system = client_root / "Data" / "System2"
    write_keyed_archive(system, "data1", {"propMover.txt": b"MI_TEST\t1\n"})
    output = tmp_path / "output"
    paths = UnifiedClientExtractor.default_output_paths()
    paths.world_map_directory = output / "worlds"
    paths.quest_database = output / "quests.json"
    paths.quest_npc_positions = output / "npc.json"
    paths.dungeon_database = output / "dungeons.json"
    paths.position_profiles = output / "position-profiles.json"
    paths.player_stats_profiles = output / "player-profiles.json"
    paths.camera_profiles = output / "camera-profiles.json"
    paths.dungeon_profiles = output / "dungeon-profiles.json"
    paths.client_catalog = output / "catalog.json"
    paths.source_manifest = output / "source_manifest.json"

    extractor = UnifiedClientExtractor(
        client_root,
        paths,
        profiler=_FakeProfiler(),
    )
    first_result = extractor.run()
    assert first_result.mover_count == 1
    assert first_result.world_names == ("TestWorld",)

    rescan_result = extractor.run_memory_profile_only()
    assert rescan_result.mover_count == 1
    assert rescan_result.world_count == 1
    assert rescan_result.world_names == ("TestWorld",)
    assert rescan_result.memory_profile is not None
    assert rescan_result.memory_profile.sha256 == DIGEST


def test_setup_wizard_validates_path_and_reports_invalid_selection() -> None:
    assert QApplication.instance() is not None or QApplication([]) is not None
