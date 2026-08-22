"""Validated fingerprint profiles for fixed-range, read-only dungeon reads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DUNGEON_RECORD_BYTES = 48
MAXIMUM_DUNGEON_RECORD_BYTES = 1024
MAXIMUM_DUNGEON_RECORD_COUNT = 4096


@dataclass(frozen=True, slots=True)
class ClientDungeonProfile:
    """The exact module-relative addresses for one executable fingerprint.

    No profile is guessed at runtime. An operator must supply verified offsets for an
    exact `neuz.exe` SHA-256 before the reader opens or touches client memory.
    """

    sha256: str
    runtime_state_pointer_rva: int
    pointer_size_bytes: int
    state_array_offset: int = 0
    record_size_bytes: int = DEFAULT_DUNGEON_RECORD_BYTES
    record_count: int = 32
    dungeon_id_offset: int = 0
    cooldown_end_timestamp_offset: int = 16
    entries_used_offset: int = 24
    daily_entry_limit_offset: int = 28

    @property
    def array_read_size_bytes(self) -> int:
        """Return the one bounded contiguous range read on every poll."""

        return self.state_array_offset + self.record_count * self.record_size_bytes

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("A client dungeon profile needs a lowercase SHA-256 digest.")
        integers = {
            "runtime_state_pointer_rva": self.runtime_state_pointer_rva,
            "pointer_size_bytes": self.pointer_size_bytes,
            "state_array_offset": self.state_array_offset,
            "record_size_bytes": self.record_size_bytes,
            "record_count": self.record_count,
            "dungeon_id_offset": self.dungeon_id_offset,
            "cooldown_end_timestamp_offset": self.cooldown_end_timestamp_offset,
            "entries_used_offset": self.entries_used_offset,
            "daily_entry_limit_offset": self.daily_entry_limit_offset,
        }
        if any(
            not isinstance(value, int) or isinstance(value, bool) for value in integers.values()
        ):
            raise ValueError("Client dungeon profile offsets and sizes must be integers.")
        if self.runtime_state_pointer_rva <= 0 or self.pointer_size_bytes not in {4, 8}:
            raise ValueError("A dungeon pointer RVA and size must describe a valid pointer.")
        if any(value < 0 for value in integers.values()):
            raise ValueError("Client dungeon profile offsets cannot be negative.")
        field_ends = (
            self.dungeon_id_offset + 4,
            self.cooldown_end_timestamp_offset + 4,
            self.entries_used_offset + 4,
            self.daily_entry_limit_offset + 4,
        )
        if max(field_ends) > self.record_size_bytes:
            raise ValueError("Dungeon profile fields must fit inside their record.")
        if not 1 <= self.record_size_bytes <= MAXIMUM_DUNGEON_RECORD_BYTES:
            raise ValueError("A dungeon memory record has an unsafe or unusable size.")
        if not 1 <= self.record_count <= MAXIMUM_DUNGEON_RECORD_COUNT:
            raise ValueError("A dungeon memory read count is outside the safety bound.")


def load_client_dungeon_profiles(path: Path) -> Mapping[str, ClientDungeonProfile]:
    """Load explicit operator-maintained profiles; malformed input never falls back."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Dungeon profile configuration {path} is invalid: {error}") from error
    if not isinstance(payload, list):
        raise ValueError("Dungeon profile configuration must contain a JSON list.")
    profiles: dict[str, ClientDungeonProfile] = {}
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Dungeon profile entry {index} must be an object.")
        required = {
            "sha256",
            "runtime_state_pointer_rva",
            "pointer_size_bytes",
        }
        if missing := required.difference(item):
            raise ValueError(
                f"Dungeon profile entry {index} is missing {', '.join(sorted(missing))}."
            )
        raw_sha256 = item["sha256"]
        if not isinstance(raw_sha256, str):
            raise ValueError(f"Dungeon profile entry {index} has a non-string digest.")
        normalized_sha256 = raw_sha256.lower()
        arguments = {key: item[key] for key in required - {"sha256"}}
        for key in (
            "state_array_offset",
            "record_size_bytes",
            "record_count",
            "dungeon_id_offset",
            "cooldown_end_timestamp_offset",
            "entries_used_offset",
            "daily_entry_limit_offset",
        ):
            if key in item:
                arguments[key] = item[key]
        try:
            profile = ClientDungeonProfile(normalized_sha256, **arguments)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Dungeon profile entry {index} is invalid: {error}") from error
        if normalized_sha256 in profiles:
            raise ValueError(f"Dungeon profiles repeat SHA-256 {normalized_sha256}.")
        profiles[normalized_sha256] = profile
    return profiles
