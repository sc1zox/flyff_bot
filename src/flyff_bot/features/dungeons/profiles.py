"""Validated fingerprint profiles for bounded, read-only dungeon reads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

MAXIMUM_DUNGEON_RECORD_BYTES = 1024
MAXIMUM_DUNGEON_RECORD_COUNT = 4096


class DungeonContainerKind(StrEnum):
    """The two contiguous container layouts permitted for live dungeon reads."""

    FIXED_ARRAY = "fixed_array"
    BEGIN_END_SPAN = "begin_end_span"


@dataclass(frozen=True, slots=True)
class FixedDungeonArray:
    """A fixed number of contiguous records inside the manager object."""

    records_offset: int
    record_size_bytes: int
    record_count: int
    kind: DungeonContainerKind = DungeonContainerKind.FIXED_ARRAY

    def __post_init__(self) -> None:
        _validate_container_numbers(
            self.records_offset,
            self.record_size_bytes,
            self.record_count,
        )


@dataclass(frozen=True, slots=True)
class BeginEndDungeonSpan:
    """A fixed header containing begin/end pointers to contiguous records."""

    container_offset: int
    begin_pointer_offset: int
    end_pointer_offset: int
    record_size_bytes: int
    maximum_record_count: int
    kind: DungeonContainerKind = DungeonContainerKind.BEGIN_END_SPAN

    def __post_init__(self) -> None:
        _validate_container_numbers(
            self.container_offset,
            self.record_size_bytes,
            self.maximum_record_count,
        )
        if min(self.begin_pointer_offset, self.end_pointer_offset) < 0:
            raise ValueError("Dungeon span pointer offsets must be non-negative.")
        if self.begin_pointer_offset == self.end_pointer_offset:
            raise ValueError("Dungeon span begin/end pointers must use distinct offsets.")


DungeonContainerProfile = FixedDungeonArray | BeginEndDungeonSpan


@dataclass(frozen=True, slots=True)
class DungeonFieldLayout:
    """The four reader-consumed fields within one proven record."""

    dungeon_id_offset: int
    cooldown_end_timestamp_offset: int
    entries_used_offset: int
    daily_entry_limit_offset: int

    def __post_init__(self) -> None:
        offsets = (
            self.dungeon_id_offset,
            self.cooldown_end_timestamp_offset,
            self.entries_used_offset,
            self.daily_entry_limit_offset,
        )
        if min(offsets) < 0:
            raise ValueError("Dungeon record field offsets must be non-negative.")


@dataclass(frozen=True, slots=True)
class ClientDungeonProfile:
    """A complete exact-fingerprint plan for one bounded contiguous container."""

    sha256: str
    runtime_state_pointer_rva: int
    pointer_size_bytes: int
    container: DungeonContainerProfile
    fields: DungeonFieldLayout

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("A client dungeon profile needs a lowercase SHA-256 digest.")
        if self.runtime_state_pointer_rva <= 0 or self.pointer_size_bytes not in {4, 8}:
            raise ValueError("A dungeon pointer RVA and size must describe a valid pointer.")
        record_size = self.container.record_size_bytes
        field_ends = (
            self.fields.dungeon_id_offset + 4,
            self.fields.cooldown_end_timestamp_offset + 4,
            self.fields.entries_used_offset + 4,
            self.fields.daily_entry_limit_offset + 4,
        )
        if max(field_ends) > record_size:
            raise ValueError("Dungeon profile fields must fit inside their record.")

    @property
    def maximum_record_count(self) -> int:
        if isinstance(self.container, FixedDungeonArray):
            return self.container.record_count
        return self.container.maximum_record_count


def load_client_dungeon_profiles(path: Path) -> dict[str, ClientDungeonProfile]:
    """Load complete explicit profiles; legacy/default-based entries are rejected."""

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
            "container",
            "fields",
        }
        if missing := required.difference(item):
            raise ValueError(
                f"Dungeon profile entry {index} is missing {', '.join(sorted(missing))}."
            )
        sha256 = item["sha256"]
        if not isinstance(sha256, str):
            raise ValueError(f"Dungeon profile entry {index} has a non-string digest.")
        pointer_values = (item["runtime_state_pointer_rva"], item["pointer_size_bytes"])
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in pointer_values
        ):
            raise ValueError(f"Dungeon profile entry {index} has an invalid pointer declaration.")
        try:
            profile = ClientDungeonProfile(
                sha256.lower(),
                item["runtime_state_pointer_rva"],
                item["pointer_size_bytes"],
                _load_container(index, item["container"]),
                _load_fields(index, item["fields"]),
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"Dungeon profile entry {index} is invalid: {error}") from error
        if profile.sha256 in profiles:
            raise ValueError(f"Dungeon profiles repeat SHA-256 {profile.sha256}.")
        profiles[profile.sha256] = profile
    return profiles


def _load_container(index: int, payload: object) -> DungeonContainerProfile:
    if not isinstance(payload, dict):
        raise ValueError(f"Dungeon profile entry {index} container must be an object.")
    try:
        kind = DungeonContainerKind(payload["kind"])
    except (KeyError, ValueError) as error:
        raise ValueError(f"Dungeon profile entry {index} has an unsupported container.") from error
    if kind is DungeonContainerKind.FIXED_ARRAY:
        keys = ("records_offset", "record_size_bytes", "record_count")
        values = _integer_values(index, payload, keys)
        return FixedDungeonArray(values[0], values[1], values[2])
    span_keys = (
        "container_offset",
        "begin_pointer_offset",
        "end_pointer_offset",
        "record_size_bytes",
        "maximum_record_count",
    )
    values = _integer_values(index, payload, span_keys)
    return BeginEndDungeonSpan(values[0], values[1], values[2], values[3], values[4])


def _load_fields(index: int, payload: object) -> DungeonFieldLayout:
    if not isinstance(payload, dict):
        raise ValueError(f"Dungeon profile entry {index} fields must be an object.")
    keys = (
        "dungeon_id_offset",
        "cooldown_end_timestamp_offset",
        "entries_used_offset",
        "daily_entry_limit_offset",
    )
    return DungeonFieldLayout(*_integer_values(index, payload, keys))


def _integer_values(
    index: int,
    payload: dict[object, object],
    keys: tuple[str, ...],
) -> tuple[int, ...]:
    if missing := set(keys).difference(payload):
        raise ValueError(f"Dungeon profile entry {index} is missing {', '.join(sorted(missing))}.")
    values = tuple(payload[key] for key in keys)
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        raise ValueError(f"Dungeon profile entry {index} contains a non-integer layout value.")
    return cast(tuple[int, ...], values)


def _validate_container_numbers(offset: int, record_size: int, record_count: int) -> None:
    if offset < 0:
        raise ValueError("A dungeon container offset must be non-negative.")
    if not 1 <= record_size <= MAXIMUM_DUNGEON_RECORD_BYTES:
        raise ValueError("A dungeon memory record has an unsafe or unusable size.")
    if not 1 <= record_count <= MAXIMUM_DUNGEON_RECORD_COUNT:
        raise ValueError("A dungeon memory read count is outside the safety bound.")
