"""Unified, cancellable extraction passes for the initial setup workflow."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from flyff_bot.constants import (
    DEFAULT_CLIENT_CATALOG_PATH,
    DEFAULT_CLIENT_PLAYER_STATS_PROFILES_PATH,
    DEFAULT_DUNGEON_DATABASE_PATH,
    DEFAULT_QUEST_DATABASE_PATH,
    DEFAULT_QUEST_NPC_POSITIONS_PATH,
    DEFAULT_SOURCE_MANIFEST_PATH,
    DEFAULT_WORLD_MAP_DIRECTORY,
)
from flyff_bot.features.client_data.extraction import (
    MOVER_TABLE_FILE,
    extract_client_catalog,
)
from flyff_bot.features.client_data.persistence import (
    save_client_catalog,
    save_source_manifest,
)
from flyff_bot.features.client_data.sources import build_source_manifest
from flyff_bot.features.dungeons.extraction import (
    DungeonExtractionDiagnostic,
    extract_dungeon_definitions,
)
from flyff_bot.features.dungeons.persistence import save_dungeon_database
from flyff_bot.features.navigation.world_extractor import (
    ExtractionDiagnostic,
    discover_world_directories,
    extract_world,
    load_monster_names,
    save_world_map,
)
from flyff_bot.features.quests.extraction import (
    QuestExtractionDiagnostic,
    _npc_positions,
    extract_quest_database,
)
from flyff_bot.features.quests.persistence import (
    save_quest_database,
    save_quest_npc_positions,
)
from flyff_bot.features.setup.models import (
    ClientSetupPaths,
    SetupDiagnostic,
    SetupExtractionResult,
    SetupMemoryProfile,
    SetupProgress,
    SetupRequiredDatasets,
    missing_required_datasets,
)
from flyff_bot.features.setup.models import SetupExtractionWarning as WarningCode
from flyff_bot.features.setup.profiles import (
    fingerprint_executable,
    install_matching_profile,
    load_proven_profiles,
)

EXECUTABLE_NAME = "neuz.exe"
DATA_DIRECTORY_NAME = "Data"
WORLD_SUBDIRECTORY = "World"
CLIENT_SYSTEM_DIRECTORY = "System2"
DEFAULT_MEMORY_PROFILE_LANGUAGE = "English"
_STAGE_COUNT = 5


class InvalidClientDirectory(ValueError):
    """Raised before extraction when the selected folder is not a client install."""


class UnifiedClientExtractor:
    """Run all offline client-data stages sequentially with one cancellation flag."""

    def __init__(
        self,
        client_root: Path,
        output_paths: ClientSetupPaths,
        *,
        monster_names_path: Path | None = None,
        profile_source_path: Path | None = None,
        progress: Callable[[SetupProgress], None] | None = None,
    ) -> None:
        self._client_root = client_root
        self._output_paths = output_paths
        self._monster_names_path = monster_names_path
        self._profile_source_path = profile_source_path
        self._progress = progress
        self._cancel_event = threading.Event()

    @staticmethod
    def default_output_paths() -> ClientSetupPaths:
        """Return the project artifact locations used by desktop setup."""

        return ClientSetupPaths(
            world_map_directory=Path(DEFAULT_WORLD_MAP_DIRECTORY),
            quest_database=Path(DEFAULT_QUEST_DATABASE_PATH),
            quest_npc_positions=Path(DEFAULT_QUEST_NPC_POSITIONS_PATH),
            dungeon_database=Path(DEFAULT_DUNGEON_DATABASE_PATH),
            player_stats_profiles=Path(DEFAULT_CLIENT_PLAYER_STATS_PROFILES_PATH),
            client_catalog=Path(DEFAULT_CLIENT_CATALOG_PATH),
            source_manifest=Path(DEFAULT_SOURCE_MANIFEST_PATH),
        )

    @staticmethod
    def validate_client_directory(client_root: Path) -> None:
        executable, data_root = _validate_client_layout(client_root)
        if not executable.is_file() or not data_root.is_dir():
            raise InvalidClientDirectory(str(client_root))

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        self._cancel_event.set()

    @staticmethod
    def required_datasets(
        *,
        world_map_directory: Path = Path(DEFAULT_WORLD_MAP_DIRECTORY),
        quest_database: Path = Path(DEFAULT_QUEST_DATABASE_PATH),
        dungeon_database: Path = Path(DEFAULT_DUNGEON_DATABASE_PATH),
        player_profiles: Path = Path(DEFAULT_CLIENT_PLAYER_STATS_PROFILES_PATH),
    ) -> SetupRequiredDatasets:
        worlds = tuple(world_map_directory.glob("*.json"))
        return SetupRequiredDatasets(
            worlds=worlds,
            quests=quest_database,
            dungeons=dungeon_database,
            player_profiles=player_profiles,
        )

    @staticmethod
    def is_first_run_required(
        *,
        world_map_directory: Path = Path(DEFAULT_WORLD_MAP_DIRECTORY),
        quest_database: Path = Path(DEFAULT_QUEST_DATABASE_PATH),
        dungeon_database: Path = Path(DEFAULT_DUNGEON_DATABASE_PATH),
        player_profiles: Path = Path(DEFAULT_CLIENT_PLAYER_STATS_PROFILES_PATH),
    ) -> bool:
        datasets = UnifiedClientExtractor.required_datasets(
            world_map_directory=world_map_directory,
            quest_database=quest_database,
            dungeon_database=dungeon_database,
            player_profiles=player_profiles,
        )
        return bool(missing_required_datasets(datasets))

    def run(self) -> SetupExtractionResult:
        UnifiedClientExtractor.validate_client_directory(self._client_root)
        diagnostics: list[SetupDiagnostic] = []
        reported: list[SetupDiagnostic] = []
        result = SetupExtractionResult()
        stage_index = 0
        self._report(stage_index, "Mover and static item tables")
        if not self._cancel_event.is_set():
            self._run_mover_stage(result, diagnostics)
        stage_index += 1
        self._report(stage_index, "Quests and NPC locations")
        if not self._cancel_event.is_set():
            self._run_quest_stage(result, diagnostics)
        stage_index += 1
        self._report(stage_index, "Dungeons")
        if not self._cancel_event.is_set():
            self._run_dungeon_stage(result, diagnostics)
        stage_index += 1
        self._report(stage_index, "World regions and terrain")
        if not self._cancel_event.is_set():
            self._run_world_stage(result, diagnostics)
        stage_index += 1
        self._report(stage_index, "Client fingerprint and memory profile")
        if not self._cancel_event.is_set():
            self._run_memory_profile_stage(result, diagnostics)
            self._report(_STAGE_COUNT - 1, "Extraction complete")
        if not self._cancel_event.is_set():
            reported.extend(diagnostics)
            result.diagnostics = tuple(reported)
        return result

    def _run_mover_stage(
        self,
        result: SetupExtractionResult,
        diagnostics: list[SetupDiagnostic],
    ) -> None:
        """Normalize the static gameplay tables and write the catalog and manifest.

        The counts reported here are rows this pass actually parsed and persisted. A table
        that is present but unreadable contributes a typed rejection, never a count (US-083).
        """

        executable, data_root = _validate_client_layout(self._client_root)
        catalog = extract_client_catalog(data_root, language=DEFAULT_MEMORY_PROFILE_LANGUAGE)
        save_client_catalog(catalog, self._output_paths.client_catalog)
        digest = fingerprint_executable(executable).sha256 or ""
        manifest = build_source_manifest(catalog, client_digest=digest)
        save_source_manifest(manifest, self._output_paths.source_manifest)

        result.mover_count = len(catalog.movers)
        result.drop_count = len(catalog.drops)
        result.item_count = len(catalog.items)
        result.skill_count = len(catalog.skills)
        result.npc_count = len(catalog.npcs)
        if not catalog.movers:
            diagnostics.append(SetupDiagnostic(WarningCode.CATALOG_EMPTY, MOVER_TABLE_FILE))
        for rejection in catalog.rejections:
            diagnostics.append(
                SetupDiagnostic(
                    WarningCode.CATALOG_TABLE_REJECTED,
                    f"{rejection.table.value}/{rejection.reason.value}: {rejection.locator}",
                )
            )

    def _run_quest_stage(
        self,
        result: SetupExtractionResult,
        diagnostics: list[SetupDiagnostic],
    ) -> None:
        _executable, data_root = _validate_client_layout(self._client_root)
        quest_diagnostics: list[QuestExtractionDiagnostic] = []
        database = extract_quest_database(
            data_root,
            language=DEFAULT_MEMORY_PROFILE_LANGUAGE,
            diagnostics=quest_diagnostics,
        )
        save_quest_database(database, self._output_paths.quest_database)
        save_quest_npc_positions(
            _npc_positions(data_root),
            self._output_paths.quest_npc_positions,
        )
        result.quest_count = len(database.quests)
        if not database.quests:
            diagnostics.append(SetupDiagnostic(WarningCode.QUESTS_EMPTY, ""))

    def _run_dungeon_stage(
        self,
        result: SetupExtractionResult,
        diagnostics: list[SetupDiagnostic],
    ) -> None:
        executable, data_root = _validate_client_layout(self._client_root)
        dungeon_diagnostics: list[DungeonExtractionDiagnostic] = []
        digest = fingerprint_executable(executable).sha256
        definitions = extract_dungeon_definitions(
            data_root,
            language=DEFAULT_MEMORY_PROFILE_LANGUAGE,
            diagnostics=dungeon_diagnostics,
        )
        save_dungeon_database(
            definitions,
            self._output_paths.dungeon_database,
            language=DEFAULT_MEMORY_PROFILE_LANGUAGE,
            client_digest=digest or "",
        )
        result.dungeon_count = len(definitions)
        if not definitions:
            diagnostics.append(SetupDiagnostic(WarningCode.DUNGEONS_EMPTY, ""))

    def _run_world_stage(
        self,
        result: SetupExtractionResult,
        diagnostics: list[SetupDiagnostic],
    ) -> None:
        _executable, data_root = _validate_client_layout(self._client_root)
        root = data_root / WORLD_SUBDIRECTORY
        world_directories = discover_world_directories(root)
        if not world_directories:
            diagnostics.append(SetupDiagnostic(WarningCode.NO_WORLD_REGIONS, str(root)))
            return
        monster_names: Mapping[int, str] = {}
        if self._monster_names_path is not None and self._monster_names_path.is_file():
            monster_names = load_monster_names(self._monster_names_path)
        names: list[str] = []
        total = len(world_directories)
        for index, world_directory in enumerate(world_directories, start=1):
            if self.is_cancelled:
                break
            self._report(4, f"World {world_directory.name} ({index}/{total})")
            world_diagnostics: list[ExtractionDiagnostic] = []
            try:
                world_map = extract_world(
                    world_directory,
                    monster_names=monster_names,
                    diagnostics=world_diagnostics,
                )
                save_world_map(world_map, self._output_paths.world_map_directory)
                names.append(world_directory.name)
            except (OSError, ValueError) as error:
                diagnostics.append(
                    SetupDiagnostic(WarningCode.WORLD_FAILED, f"{world_directory.name}: {error}")
                )
        result.world_names = tuple(names)

    def _run_memory_profile_stage(
        self,
        result: SetupExtractionResult,
        diagnostics: list[SetupDiagnostic],
    ) -> None:
        executable, _ = _validate_client_layout(self._client_root)
        fingerprint = fingerprint_executable(executable)
        if fingerprint.architecture == "unknown":
            diagnostics.append(
                SetupDiagnostic(WarningCode.BINARY_ARCHITECTURE_UNKNOWN, executable.name)
            )
        profiles, source_path, profile_error = load_proven_profiles(self._profile_source_path)
        if profile_error is not None:
            diagnostics.append(SetupDiagnostic(WarningCode.INVALID_MEMORY_PROFILE, profile_error))
        profile = profiles.get(fingerprint.sha256)
        if profile is None:
            diagnostics.append(
                SetupDiagnostic(WarningCode.MEMORY_PROFILE_NOT_FOUND, fingerprint.sha256)
            )
            return
        install_matching_profile(profiles, fingerprint, self._output_paths.player_stats_profiles)
        result.memory_profile = SetupMemoryProfile(
            sha256=fingerprint.sha256,
            pointer_size_bytes=profile.pointer_size_bytes,
            field_count=len(profile.fields),
            source_path=source_path,
        )

    def _report(self, completed_stages: int, detail: str) -> None:
        if self._progress is None:
            return
        self._progress(SetupProgress(completed_stages, _STAGE_COUNT, detail))


def _validate_client_layout(client_root: Path) -> tuple[Path, Path]:
    executable = client_root / EXECUTABLE_NAME
    data_root = client_root / DATA_DIRECTORY_NAME
    if executable.is_file() and data_root.is_dir():
        return executable, data_root
    nested_executable = client_root / client_root.name / EXECUTABLE_NAME
    nested_data_root = client_root / client_root.name / DATA_DIRECTORY_NAME
    if nested_executable.is_file() and nested_data_root.is_dir():
        return nested_executable, nested_data_root
    raise InvalidClientDirectory(str(client_root))
