"""Typed results for the initial setup extraction workflow."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SetupExtractionWarning(StrEnum):
    """Why one optional setup pass or client build profile was skipped."""

    NO_WORLD_REGIONS = "no_world_regions"
    WORLD_FAILED = "world_failed"
    QUESTS_EMPTY = "quests_empty"
    DUNGEONS_EMPTY = "dungeons_empty"
    MEMORY_PROFILE_NOT_FOUND = "memory_profile_not_found"
    INVALID_MEMORY_PROFILE = "invalid_memory_profile"
    BINARY_ARCHITECTURE_UNKNOWN = "binary_architecture_unknown"
    CATALOG_EMPTY = "catalog_empty"
    CATALOG_TABLE_REJECTED = "catalog_table_rejected"


@dataclass(frozen=True, slots=True)
class SetupDiagnostic:
    """One non-fatal extraction issue with the file or stage that produced it."""

    warning: SetupExtractionWarning
    detail: str


@dataclass(frozen=True, slots=True)
class SetupProgress:
    """One granular background-worker update."""

    completed_stages: int
    total_stages: int
    detail: str

    @property
    def percent(self) -> int:
        if self.total_stages == 0:
            return 0
        return min(100, max(0, round(100 * self.completed_stages / self.total_stages)))


@dataclass(slots=True)
class ClientSetupPaths:
    """Output locations owned by unified extraction."""

    world_map_directory: Path
    quest_database: Path
    quest_npc_positions: Path
    dungeon_database: Path
    player_stats_profiles: Path
    client_catalog: Path
    source_manifest: Path


@dataclass(slots=True)
class SetupMemoryProfile:
    """A proven profile selected for one exact executable fingerprint."""

    sha256: str
    pointer_size_bytes: int
    field_count: int
    source_path: Path | None = None


@dataclass(slots=True)
class SetupExtractionResult:
    """Counts and diagnostics shown after every stage has run or been skipped."""

    world_names: tuple[str, ...] = ()
    quest_count: int = 0
    dungeon_count: int = 0
    # Records actually parsed, validated and written. A found file name is not ingestion,
    # so these stay zero until the corresponding rows reach the persisted catalog (US-083).
    mover_count: int = 0
    drop_count: int = 0
    item_count: int = 0
    skill_count: int = 0
    npc_count: int = 0
    memory_profile: SetupMemoryProfile | None = None
    diagnostics: tuple[SetupDiagnostic, ...] = ()

    @property
    def world_count(self) -> int:
        return len(self.world_names)


@dataclass(frozen=True, slots=True)
class SetupRequiredDatasets:
    """Files whose absence makes first-run setup necessary."""

    worlds: tuple[Path, ...]
    quests: Path
    dungeons: Path
    player_profiles: Path
    client_catalog: Path
    source_manifest: Path

    def is_complete(self) -> bool:
        return bool(self.worlds) and all(
            path.is_file()
            for path in (
                self.quests,
                self.dungeons,
                self.player_profiles,
                self.client_catalog,
                self.source_manifest,
            )
        )


def missing_required_datasets(paths: SetupRequiredDatasets) -> tuple[str, ...]:
    """Return stable dataset identifiers suitable for progress and tests."""

    missing: list[str] = []
    if not paths.worlds or not any(path.is_file() for path in paths.worlds):
        missing.append("navigation")
    for dataset_name, path in (
        ("quests", paths.quests),
        ("dungeons", paths.dungeons),
        ("player_profiles", paths.player_profiles),
        ("client_catalog", paths.client_catalog),
        ("source_manifest", paths.source_manifest),
    ):
        if not path.is_file():
            missing.append(dataset_name)
    return tuple(missing)
