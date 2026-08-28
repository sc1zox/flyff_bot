"""Fingerprint-matched installation of proven client player-stat profiles."""

from __future__ import annotations

import json
import os
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from flyff_bot.features.player_stats.profiles import (
    ClientPlayerStatsProfile,
    load_client_player_stats_profiles,
)

PROFILE_SOURCE_ENVIRONMENT = "FLYFF_BOT_CLIENT_PLAYER_PROFILES"
_PE_HEADER_OFFSET = 0x3C
_PE_MACHINE_OFFSET = 4
_MACHINE_X86 = 0x14C
_MACHINE_X64 = 0x8664
# Named so the handler below stays a single-name `except` clause. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
PROFILE_DOCUMENT_ERRORS = (OSError, json.JSONDecodeError)


@dataclass(frozen=True, slots=True)
class ExecutableFingerprint:
    """The exact binary identity and declared architecture used to select a profile."""

    sha256: str
    machine_type: int | None

    @property
    def architecture(self) -> str:
        if self.machine_type == _MACHINE_X86:
            return "x86"
        if self.machine_type == _MACHINE_X64:
            return "x64"
        return "unknown"


def fingerprint_executable(path: Path) -> ExecutableFingerprint:
    """Hash the executable and inspect its PE machine field without writing it."""

    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return ExecutableFingerprint(digest.hexdigest(), _pe_machine_type(path))


def profile_source_path(explicit_path: Path | None = None) -> Path | None:
    """Return an explicit source or the operator-provided environment override."""

    if explicit_path is not None:
        return explicit_path
    configured = os.environ.get(PROFILE_SOURCE_ENVIRONMENT)
    return Path(configured) if configured else None


def load_proven_profiles(
    source_path: Path | None,
) -> tuple[Mapping[str, ClientPlayerStatsProfile], Path | None, str | None]:
    """Load a validated operator profile registry without inventing entries."""

    resolved_source = profile_source_path(source_path)
    if resolved_source is None or not resolved_source.is_file():
        return {}, resolved_source, None
    try:
        return load_client_player_stats_profiles(resolved_source), resolved_source, None
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {}, resolved_source, str(error)


def install_matching_profile(
    loaded_profiles: Mapping[str, ClientPlayerStatsProfile],
    fingerprint: ExecutableFingerprint,
    target_path: Path,
) -> Path:
    """Write only the exact-fingerprint profile, preserving other installed profiles."""

    profile = loaded_profiles[fingerprint.sha256]
    existing = _read_existing_profiles(target_path)
    retained = [item for item in existing if not _is_same_profile(item, fingerprint.sha256)]
    retained.append(_profile_document(profile))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(retained, indent=2), encoding="utf-8")
    return target_path


def _is_same_profile(item: dict[str, object], digest: str) -> bool:
    raw_digest = item.get("sha256")
    if not isinstance(raw_digest, str):
        return False
    return raw_digest.lower() == digest.lower()


def _pe_machine_type(path: Path) -> int | None:
    try:
        with path.open("rb") as stream:
            stream.seek(_PE_HEADER_OFFSET)
            offset_bytes = stream.read(4)
            if len(offset_bytes) != 4:
                return None
            stream.seek(struct.unpack("<I", offset_bytes)[0] + _PE_MACHINE_OFFSET)
            machine_bytes = stream.read(2)
            return struct.unpack("<H", machine_bytes)[0] if len(machine_bytes) == 2 else None
    except OSError:
        return None


def _read_existing_profiles(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except PROFILE_DOCUMENT_ERRORS:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _profile_document(profile: ClientPlayerStatsProfile) -> dict[str, object]:
    return {
        "sha256": profile.sha256,
        "player_pointer_rva": profile.player_pointer_rva,
        "pointer_size_bytes": profile.pointer_size_bytes,
        "fields": [
            {
                "name": field.name,
                "offset": field.offset,
                "type": field.type.value,
                "minimum": field.minimum,
                "maximum": field.maximum,
                "is_unknown": field.is_unknown,
            }
            for field in profile.fields
        ],
    }
