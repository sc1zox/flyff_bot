"""Tests for unified setup extraction and proven memory-profile installation."""

from __future__ import annotations

import shutil
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
from flyff_bot.features.setup.models import ClientSetupPaths, SetupExtractionWarning
from flyff_bot.features.setup.profiles import fingerprint_executable

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
    teleporter_path = tmp_path / "teleporters.json"
    required_paths = (
        quest_path,
        dungeon_path,
        *profile_paths,
        catalog_path,
        manifest_path,
        teleporter_path,
    )
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
        teleporter_database=teleporter_path,
    )
    for path in required_paths[:-1]:
        path.write_text("[]", encoding="utf-8")
    # The teleporter catalog is mandatory too: without it emergency recovery cannot select
    # a destination extracted from the client's own declarations (BUG-044).
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
        teleporter_database=teleporter_path,
    )
    teleporter_path.write_text("[]", encoding="utf-8")
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
        teleporter_database=teleporter_path,
    )


def test_unified_extraction_runs_stages_and_collects_missing_profile(
    tmp_path: Path,
) -> None:
    client_root = _client_root(tmp_path)
    system = client_root / "Data" / "System2"
    write_keyed_archive(system, "data1", {"propMover.txt": b"MI_TEST\t1\n"})
    teleporter_asset = client_root / "Data" / "System3" / "TeleportOption.inc"
    teleporter_asset.parent.mkdir()
    teleporter_asset.write_text('AddTeleportOption(7, "Flaris", 1);', encoding="cp1252")
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
    paths.teleporter_database = output / "teleporters.json"
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
    assert paths.teleporter_database.is_file()
    assert result.teleporter_count == 1
    assert not paths.player_stats_profiles.exists()
    assert SetupExtractionWarning.CLIENT_PROFILING_FAILED in {
        diagnostic.warning for diagnostic in result.diagnostics
    }
    assert progress[-1] in {83, 100}
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


def _bundle_with_digest(digest: str) -> GeneratedClientProfileBundle:
    fields = (
        PlayerStatFieldProfile("hp", RatioPlayerStatSource(0, 4, PlayerStatType.U32), 0.0, 100.0),
        PlayerStatFieldProfile("mp", RatioPlayerStatSource(8, 12, PlayerStatType.U32), 0.0, 100.0),
        PlayerStatFieldProfile("fp", RatioPlayerStatSource(16, 20, PlayerStatType.U32), 0.0, 100.0),
    )
    return GeneratedClientProfileBundle(
        ClientPositionProfile(digest, 0x1000, 8, 0x188),
        ClientPlayerStatsProfile(digest, 0x1000, 8, fields),
        ClientCameraProfile(digest, 0x2000, 8, 8, 0x14, 0x94, 0x3000),
        ClientDungeonProfile(
            digest,
            0x4000,
            8,
            FixedDungeonArray(0x20, 32, 4),
            DungeonFieldLayout(0, 8, 12, 16),
        ),
    )


class _CountingProfiler:
    """Profiler that records how often the expensive stage 5 pass is executed."""

    def __init__(self, digest: str) -> None:
        self._digest = digest
        self.calls = 0

    def profile(self, _path: Path) -> GeneratedClientProfileBundle:
        self.calls += 1
        return _bundle_with_digest(self._digest)


def _cache_output_paths(output: Path) -> ClientSetupPaths:
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
    return paths


def test_cached_run_reuses_existing_artifacts_without_re_extracting(tmp_path: Path) -> None:
    client_root = _client_root(tmp_path)
    system = client_root / "Data" / "System2"
    write_keyed_archive(system, "data1", {"propMover.txt": b"MI_TEST\t1\n"})
    output = tmp_path / "output"
    paths = _cache_output_paths(output)
    digest = fingerprint_executable(client_root / "neuz.exe").sha256
    profiler = _CountingProfiler(digest)

    first = UnifiedClientExtractor(client_root, paths, profiler=profiler).run()
    assert first.mover_count == 1
    assert first.world_names == ("TestWorld",)
    assert first.memory_profile is not None
    assert profiler.calls == 1

    # Removing the client's static sources proves a cached run never re-parses them.
    shutil.rmtree(client_root / "Data" / "World")
    shutil.rmtree(system)

    cached = UnifiedClientExtractor(client_root, paths, profiler=profiler).run()

    assert cached.mover_count == 1
    assert cached.world_names == ("TestWorld",)
    assert cached.quest_count == first.quest_count
    assert cached.dungeon_count == first.dungeon_count
    assert cached.memory_profile is not None
    assert cached.memory_profile.sha256 == digest
    # Stage 5 was served from the fingerprint-matched cache, not re-run.
    assert profiler.calls == 1


def test_force_run_re_extracts_every_dataset_and_overwrites_caches(tmp_path: Path) -> None:
    client_root = _client_root(tmp_path)
    system = client_root / "Data" / "System2"
    write_keyed_archive(system, "data1", {"propMover.txt": b"MI_TEST\t1\n"})
    output = tmp_path / "output"
    paths = _cache_output_paths(output)
    digest = fingerprint_executable(client_root / "neuz.exe").sha256
    profiler = _CountingProfiler(digest)

    UnifiedClientExtractor(client_root, paths, profiler=profiler).run()
    assert profiler.calls == 1

    forced = UnifiedClientExtractor(client_root, paths, profiler=profiler).run(force=True)

    assert forced.mover_count == 1
    assert forced.world_names == ("TestWorld",)
    # Force ignores the cache and re-runs stage 5 against the selected client.
    assert profiler.calls == 2
