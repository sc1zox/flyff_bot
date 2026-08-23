"""Validated, exact-fingerprint profiles for bounded player-stat reads."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SUPPORTED_POINTER_SIZES_BYTES = frozenset({4, 8})
SHA256_CHARACTER_SET = frozenset("0123456789abcdef")
SHA256_LENGTH = 64
MINIMUM_FIELD_SIZE_BYTES = 1


class PlayerStatType(StrEnum):
    """The bounded primitive types supported by player-stat profiles."""

    U8 = "u8"
    U16 = "u16"
    U32 = "u32"
    U64 = "u64"
    I8 = "i8"
    I16 = "i16"
    I32 = "i32"
    I64 = "i64"
    F32 = "f32"
    F64 = "f64"


_PLAYER_STAT_STRUCT_FORMATS: dict[PlayerStatType, str] = {
    PlayerStatType.U8: "B",
    PlayerStatType.U16: "H",
    PlayerStatType.U32: "I",
    PlayerStatType.U64: "Q",
    PlayerStatType.I8: "b",
    PlayerStatType.I16: "h",
    PlayerStatType.I32: "i",
    PlayerStatType.I64: "q",
    PlayerStatType.F32: "f",
    PlayerStatType.F64: "d",
}


@dataclass(frozen=True, slots=True)
class PlayerStatFieldProfile:
    """One fixed offset and primitive decoder for a proven player statistic."""

    name: str
    offset: int
    type: PlayerStatType
    minimum: float = 0.0
    maximum: float = math.inf
    is_unknown: bool = False

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("A player statistic name must be non-empty and trimmed.")
        if self.offset < 0:
            raise ValueError(f"The {self.name} offset must be non-negative.")
        if not math.isfinite(self.minimum):
            raise ValueError(f"The {self.name} minimum must be finite.")
        if not math.isfinite(self.maximum) and self.maximum != math.inf:
            raise ValueError(f"The {self.name} maximum must be finite or infinite.")
        if self.minimum > self.maximum:
            raise ValueError(f"The {self.name} bounds must be ordered.")

    @property
    def size_bytes(self) -> int:
        return struct.calcsize("<" + _PLAYER_STAT_STRUCT_FORMATS[self.type])


@dataclass(frozen=True, slots=True)
class ClientPlayerStatsProfile:
    """A complete, bounded read plan for one executable fingerprint."""

    sha256: str
    player_pointer_rva: int
    pointer_size_bytes: int
    fields: tuple[PlayerStatFieldProfile, ...]

    def __post_init__(self) -> None:
        if len(self.sha256) != SHA256_LENGTH or any(
            character not in SHA256_CHARACTER_SET for character in self.sha256
        ):
            raise ValueError("A client fingerprint must be a lowercase SHA-256 digest.")
        if self.player_pointer_rva <= 0:
            raise ValueError("The player pointer RVA must be positive.")
        if self.pointer_size_bytes not in SUPPORTED_POINTER_SIZES_BYTES:
            raise ValueError("A player pointer must be either 4 or 8 bytes wide.")
        if not self.fields:
            raise ValueError("A player-stats profile must declare at least one proven field.")
        names: set[str] = set()
        for field in self.fields:
            if field.name in names:
                raise ValueError(f"The player-stats profile repeats field {field.name}.")
            names.add(field.name)
        ordered_fields = sorted(
            self.fields,
            key=lambda field: (field.offset, field.offset + field.size_bytes),
        )
        previous_end = 0
        for field in ordered_fields:
            field_end = field.offset + field.size_bytes
            if field.offset < previous_end:
                raise ValueError(f"The {field.name} range overlaps another player-stat field.")
            previous_end = field_end

    @property
    def read_start_offset(self) -> int:
        return min(field.offset for field in self.fields)

    @property
    def read_size_bytes(self) -> int:
        end = max(field.offset + field.size_bytes for field in self.fields)
        return end - self.read_start_offset

    def decode(self, payload: bytes) -> dict[str, float | bool]:
        """Decode one bounded structure read without allowing partial values."""

        if len(payload) != self.read_size_bytes:
            raise ValueError("The player-stat structure read was incomplete.")
        decoded: dict[str, float | bool] = {}
        for field in self.fields:
            relative_offset = field.offset - self.read_start_offset
            raw_value = struct.unpack_from(
                "<" + _PLAYER_STAT_STRUCT_FORMATS[field.type],
                payload,
                relative_offset,
            )[0]
            value = float(raw_value)
            if not math.isfinite(value) or not field.minimum <= value <= field.maximum:
                raise ValueError(f"The {field.name} value is outside its validated range.")
            decoded[field.name] = value
        return decoded


def load_client_player_stats_profiles(path: Path) -> dict[str, ClientPlayerStatsProfile]:
    """Load and fully validate operator profiles before any process handle opens."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Player-stats profile configuration is invalid: {error}") from error
    if not isinstance(payload, list):
        raise ValueError("Player-stats profile configuration must contain a JSON list.")

    profiles: dict[str, ClientPlayerStatsProfile] = {}
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Player-stats profile entry {index} must be an object.")
        required = {"sha256", "player_pointer_rva", "pointer_size_bytes", "fields"}
        if missing := required.difference(item):
            raise ValueError(
                f"Player-stats profile entry {index} is missing {', '.join(sorted(missing))}."
            )
        if not isinstance(item["sha256"], str):
            raise ValueError(f"Player-stats profile entry {index} has a non-string digest.")
        integer_values = (
            item["player_pointer_rva"],
            item["pointer_size_bytes"],
        )
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in integer_values
        ):
            raise ValueError(
                f"Player-stats profile entry {index} has an invalid pointer declaration."
            )
        sha256 = item["sha256"].lower()
        try:
            fields = _load_field_profiles(index, item["fields"])
            profile = ClientPlayerStatsProfile(
                sha256=sha256,
                player_pointer_rva=item["player_pointer_rva"],
                pointer_size_bytes=item["pointer_size_bytes"],
                fields=fields,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"Player-stats profile entry {index} is invalid: {error}") from error
        if sha256 in profiles:
            raise ValueError(f"Player-stats profiles repeat SHA-256 {sha256}.")
        profiles[sha256] = profile
    return profiles


def _load_field_profiles(
    profile_index: int,
    payload: object,
) -> tuple[PlayerStatFieldProfile, ...]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("fields must be a non-empty JSON list.")
    fields: list[PlayerStatFieldProfile] = []
    for field_index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"field {field_index} must be an object.")
        required = {"name", "offset", "type", "minimum", "maximum"}
        if missing := required.difference(item):
            raise ValueError(f"field {field_index} is missing {', '.join(sorted(missing))}.")
        try:
            stat_type = PlayerStatType(item["type"])
        except ValueError as error:
            raise ValueError(f"field {field_index} has an unsupported type.") from error
        if not isinstance(item["name"], str) or not isinstance(item["offset"], int):
            raise ValueError(f"field {field_index} has an invalid name or offset.")
        bounds = (item["minimum"], item["maximum"])
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in bounds
        ):
            raise ValueError(f"field {field_index} has non-numeric bounds.")
        try:
            fields.append(
                PlayerStatFieldProfile(
                    name=item["name"],
                    offset=item["offset"],
                    type=stat_type,
                    minimum=float(item["minimum"]),
                    maximum=float(item["maximum"]),
                    is_unknown=bool(item.get("is_unknown", False)),
                )
            )
        except ValueError as error:
            raise ValueError(f"field {field_index} is invalid: {error}") from error
    return tuple(fields)
