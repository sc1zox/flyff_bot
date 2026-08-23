"""Immutable contracts for fingerprinted client player statistics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class PlayerStatField:
    """One decoded client statistic and its profile-defined unit."""

    name: str
    value: float
    is_unknown: bool

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("A player statistic must have a non-empty trimmed name.")
        if self.value < 0.0:
            raise ValueError(f"The {self.name} statistic cannot be negative.")


class PlayerStatsReadErrorCode(StrEnum):
    """Why one poll could not produce a complete player-stat snapshot."""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    WINDOW_NOT_FOREGROUND = "window_not_foreground"
    PROCESS_UNAVAILABLE = "process_unavailable"
    WRONG_PROCESS = "wrong_process"
    UNSUPPORTED_BUILD = "unsupported_build"
    HANDLE_LOST = "handle_lost"
    MALFORMED_READ = "malformed_read"
    INVALID_POINTER = "invalid_pointer"
    INVALID_PROFILE_CONFIGURATION = "invalid_profile_configuration"
    NO_PROFILE = "no_profile"


@dataclass(frozen=True, slots=True)
class PlayerStatsReadError:
    """A typed diagnostic for an unavailable or partial stats read."""

    code: PlayerStatsReadErrorCode
    detail: str = ""


class PlayerStatsSource(StrEnum):
    """Whether a snapshot came from the exact-profile client memory reader."""

    CLIENT_MEMORY = "client_memory"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ClientPlayerStatsSnapshot:
    """An immutable result of one bounded client-memory polling operation."""

    source: PlayerStatsSource
    sampled_at_seconds: float | None = None
    client_sha256: str | None = None
    fields: tuple[PlayerStatField, ...] = ()
    error: PlayerStatsReadError | None = None
    unavailable_field_names: tuple[str, ...] = ()
    unknown_field_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.client_sha256 or "") not in {0, 64}:
            raise ValueError("A player-stats digest must be a SHA-256 digest.")
        if (self.source is PlayerStatsSource.CLIENT_MEMORY) != (
            self.sampled_at_seconds is not None
            and self.client_sha256 is not None
            and bool(self.fields)
        ):
            raise ValueError("Client-memory snapshots require a timestamp and decoded fields.")
        if self.source is PlayerStatsSource.UNAVAILABLE and (
            bool(self.fields) or self.error is None
        ):
            raise ValueError("Unavailable snapshots require diagnostics and no fabricated fields.")

    @property
    def field_values(self) -> dict[str, float]:
        """Return decoded values keyed by stable statistic names."""

        return {field.name: field.value for field in self.fields}

    @property
    def unknown_fields(self) -> tuple[PlayerStatField, ...]:
        """Return fields decoded from profile-marked unverified structures."""

        return tuple(field for field in self.fields if field.is_unknown)
