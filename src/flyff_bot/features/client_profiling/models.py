"""Typed results and diagnostics for offline client profiling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.dungeons.profiles import ClientDungeonProfile
from flyff_bot.features.navigation.live_camera import ClientCameraProfile
from flyff_bot.features.navigation.live_position import ClientPositionProfile
from flyff_bot.features.player_stats.profiles import ClientPlayerStatsProfile


class ClientProfilingErrorCode(StrEnum):
    """Stable fail-closed reasons suitable for localized UI mapping."""

    INVALID_PE = "invalid_pe"
    UNSUPPORTED_MACHINE = "unsupported_machine"
    MISSING_SECTION = "missing_section"
    MISSING_RTTI = "missing_rtti"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"
    INCOMPLETE_POSITION = "incomplete_position"
    INCOMPLETE_PLAYER_STATS = "incomplete_player_stats"
    INCOMPLETE_CAMERA = "incomplete_camera"
    INCOMPLETE_DUNGEON = "incomplete_dungeon"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    PERSISTENCE_FAILED = "persistence_failed"


class ClientProfilingError(ValueError):
    """Profiling stopped before any registry was modified."""

    def __init__(self, code: ClientProfilingErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class GeneratedClientProfileBundle:
    """One all-or-nothing set of reader-ready profiles for the same binary."""

    position: ClientPositionProfile
    player_stats: ClientPlayerStatsProfile
    camera: ClientCameraProfile
    dungeon: ClientDungeonProfile

    def __post_init__(self) -> None:
        digests = {
            self.position.sha256,
            self.player_stats.sha256,
            self.camera.sha256,
            self.dungeon.sha256,
        }
        pointer_sizes = {
            self.position.pointer_size_bytes,
            self.player_stats.pointer_size_bytes,
            self.camera.pointer_size_bytes,
            self.dungeon.pointer_size_bytes,
        }
        if len(digests) != 1 or len(pointer_sizes) != 1:
            raise ValueError("Every generated memory profile must describe the same client build.")

    @property
    def sha256(self) -> str:
        return self.position.sha256

    @property
    def pointer_size_bytes(self) -> int:
        return self.position.pointer_size_bytes
