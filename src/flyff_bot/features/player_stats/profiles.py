"""Validated, exact-fingerprint profiles for bounded player-stat reads."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

SUPPORTED_POINTER_SIZES_BYTES = frozenset({4, 8})
SHA256_CHARACTER_SET = frozenset("0123456789abcdef")
SHA256_LENGTH = 64


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


class PlayerStatSourceKind(StrEnum):
    """The only calculations a generated player-stat profile may request."""

    DIRECT = "direct"
    RATIO = "ratio"
    XOR_PAIR = "xor_pair"


# A player-stat XOR key is one unsigned 64-bit word.
_XOR_PAIR_WORD_BYTES = 8
_UINT64_MASK = (1 << 64) - 1
_XOR_PAIR_PRIMITIVES = frozenset(
    {
        PlayerStatType.U32,
        PlayerStatType.I32,
        PlayerStatType.U64,
        PlayerStatType.I64,
    }
)


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
class DirectPlayerStatSource:
    """One directly readable primitive at a proven structure offset."""

    offset: int
    primitive: PlayerStatType
    kind: PlayerStatSourceKind = PlayerStatSourceKind.DIRECT

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("A direct player-stat offset must be non-negative.")

    @property
    def ranges(self) -> tuple[tuple[int, int], ...]:
        size = struct.calcsize("<" + _PLAYER_STAT_STRUCT_FORMATS[self.primitive])
        return ((self.offset, self.offset + size),)

    def decode(self, payload: bytes, read_start_offset: int) -> float:
        return float(
            struct.unpack_from(
                "<" + _PLAYER_STAT_STRUCT_FORMATS[self.primitive],
                payload,
                self.offset - read_start_offset,
            )[0]
        )


@dataclass(frozen=True, slots=True)
class RatioPlayerStatSource:
    """A bounded numerator/denominator calculation proven by client instructions."""

    numerator_offset: int
    denominator_offset: int
    primitive: PlayerStatType
    scale: float = 100.0
    kind: PlayerStatSourceKind = PlayerStatSourceKind.RATIO

    def __post_init__(self) -> None:
        if min(self.numerator_offset, self.denominator_offset) < 0:
            raise ValueError("Player-stat ratio offsets must be non-negative.")
        if self.numerator_offset == self.denominator_offset:
            raise ValueError("A player-stat ratio needs distinct numerator and denominator fields.")
        if not math.isfinite(self.scale) or self.scale <= 0.0:
            raise ValueError("A player-stat ratio scale must be finite and positive.")

    @property
    def ranges(self) -> tuple[tuple[int, int], ...]:
        size = struct.calcsize("<" + _PLAYER_STAT_STRUCT_FORMATS[self.primitive])
        return (
            (self.numerator_offset, self.numerator_offset + size),
            (self.denominator_offset, self.denominator_offset + size),
        )

    def decode(self, payload: bytes, read_start_offset: int) -> float:
        format_string = "<" + _PLAYER_STAT_STRUCT_FORMATS[self.primitive]
        numerator = float(
            struct.unpack_from(format_string, payload, self.numerator_offset - read_start_offset)[0]
        )
        denominator = float(
            struct.unpack_from(
                format_string,
                payload,
                self.denominator_offset - read_start_offset,
            )[0]
        )
        if not math.isfinite(denominator) or denominator <= 0.0:
            raise ValueError("A player-stat ratio denominator must be finite and positive.")
        return numerator * self.scale / denominator


@dataclass(frozen=True, slots=True)
class XorPairPlayerStatSource:
    """One integer stored as two XOR-obfuscated 64-bit copies with a consistency check.

    The client keeps ``word_a = value ^ key_a`` at ``offset`` and ``word_b = value ^ key_b``
    at ``offset + 8``; it treats a mismatch between the two decoded copies as tampering and
    reads zero. This reader fails the whole poll closed on a mismatch instead of substituting
    a fabricated value.
    """

    offset: int
    key_a: int
    key_b: int
    primitive: PlayerStatType = PlayerStatType.I64
    kind: PlayerStatSourceKind = PlayerStatSourceKind.XOR_PAIR

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("An XOR-pair player-stat offset must be non-negative.")
        if not 0 <= self.key_a <= _UINT64_MASK or not 0 <= self.key_b <= _UINT64_MASK:
            raise ValueError("An XOR-pair player-stat key must be an unsigned 64-bit word.")
        if self.key_a == self.key_b:
            raise ValueError("An XOR-pair player-stat needs two distinct keys.")
        if self.primitive not in _XOR_PAIR_PRIMITIVES:
            raise ValueError("An XOR-pair player-stat must decode to a 32- or 64-bit integer.")

    @property
    def ranges(self) -> tuple[tuple[int, int], ...]:
        return ((self.offset, self.offset + 2 * _XOR_PAIR_WORD_BYTES),)

    def decode(self, payload: bytes, read_start_offset: int) -> float:
        base = self.offset - read_start_offset
        word_a = struct.unpack_from("<Q", payload, base)[0] ^ self.key_a
        word_b = struct.unpack_from("<Q", payload, base + _XOR_PAIR_WORD_BYTES)[0] ^ self.key_b
        if word_a != word_b:
            raise ValueError("The XOR-pair player-stat copies disagree; the read is not trusted.")
        format_string = "<" + _PLAYER_STAT_STRUCT_FORMATS[self.primitive]
        width = struct.calcsize(format_string)
        low_bytes = (word_a & ((1 << (8 * width)) - 1)).to_bytes(width, "little")
        return float(struct.unpack(format_string, low_bytes)[0])


PlayerStatSource = DirectPlayerStatSource | RatioPlayerStatSource | XorPairPlayerStatSource


@dataclass(frozen=True, slots=True)
class PlayerStatFieldProfile:
    """One named, typed output and its statically proven bounded source."""

    name: str
    source: PlayerStatSource
    minimum: float = 0.0
    maximum: float = math.inf
    is_unknown: bool = False

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("A player statistic name must be non-empty and trimmed.")
        if not math.isfinite(self.minimum):
            raise ValueError(f"The {self.name} minimum must be finite.")
        if not math.isfinite(self.maximum) and self.maximum != math.inf:
            raise ValueError(f"The {self.name} maximum must be finite or infinite.")
        if self.minimum > self.maximum:
            raise ValueError(f"The {self.name} bounds must be ordered.")

    @property
    def ranges(self) -> tuple[tuple[int, int], ...]:
        return self.source.ranges


@dataclass(frozen=True, slots=True)
class ClientPlayerStatsProfile:
    """A complete, bounded read plan for one executable fingerprint."""

    sha256: str
    player_pointer_rva: int
    pointer_size_bytes: int
    fields: tuple[PlayerStatFieldProfile, ...]
    monster_kills_rva: int | None = None

    def __post_init__(self) -> None:
        if len(self.sha256) != SHA256_LENGTH or any(
            character not in SHA256_CHARACTER_SET for character in self.sha256
        ):
            raise ValueError("A client fingerprint must be a lowercase SHA-256 digest.")
        if self.player_pointer_rva <= 0:
            raise ValueError("The player pointer RVA must be positive.")
        if self.pointer_size_bytes not in SUPPORTED_POINTER_SIZES_BYTES:
            raise ValueError("A player pointer must be either 4 or 8 bytes wide.")
        if self.monster_kills_rva is not None and self.monster_kills_rva < 0:
            raise ValueError("The monster kills RVA must be non-negative.")
        if not self.fields:
            raise ValueError("A player-stats profile must declare at least one proven field.")
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("A player-stats profile repeats a field name.")
        # A vital may be a proven ``current * 100 / maximum`` ratio, or (when this client build
        # computes the maximum at runtime, ADR-010) a raw current value left to the HUD reader
        # for its percentage. Only a ratio vital is required to output a 0..100 percentage.
        for field in self.fields:
            if (
                field.name in {"hp", "mp", "fp"}
                and isinstance(field.source, RatioPlayerStatSource)
                and (field.minimum != 0.0 or field.maximum != 100.0)
            ):
                raise ValueError(f"The {field.name} ratio output must be bounded from 0 to 100.")
        all_ranges = sorted(
            (start, end, field.name) for field in self.fields for start, end in field.ranges
        )
        for i in range(len(all_ranges) - 1):
            _start_a, end_a, name_a = all_ranges[i]
            start_b, _end_b, name_b = all_ranges[i + 1]
            if start_b < end_a:
                raise ValueError(
                    f"The range of {name_a} overlaps with {name_b} in the player-stats profile."
                )

    @property
    def read_start_offset(self) -> int:
        return min(start for field in self.fields for start, _end in field.ranges)

    @property
    def read_size_bytes(self) -> int:
        end = max(end for field in self.fields for _start, end in field.ranges)
        return end - self.read_start_offset

    def decode(self, payload: bytes) -> dict[str, float | bool]:
        """Decode one bounded structure read without allowing partial values."""

        if len(payload) != self.read_size_bytes:
            raise ValueError("The player-stat structure read was incomplete.")
        decoded: dict[str, float | bool] = {}
        for field in self.fields:
            value = field.source.decode(payload, self.read_start_offset)
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
        sha256 = item["sha256"]
        if not isinstance(sha256, str):
            raise ValueError(f"Player-stats profile entry {index} has a non-string digest.")
        pointer_values = (item["player_pointer_rva"], item["pointer_size_bytes"])
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in pointer_values
        ):
            raise ValueError(
                f"Player-stats profile entry {index} has an invalid pointer declaration."
            )
        monster_kills_rva = item.get("monster_kills_rva")
        if monster_kills_rva is not None and (
            not isinstance(monster_kills_rva, int) or isinstance(monster_kills_rva, bool)
        ):
            raise ValueError(
                f"Player-stats profile entry {index} has an invalid monster_kills_rva."
            )
        normalized_sha256 = sha256.lower()
        try:
            profile = ClientPlayerStatsProfile(
                sha256=normalized_sha256,
                player_pointer_rva=item["player_pointer_rva"],
                pointer_size_bytes=item["pointer_size_bytes"],
                fields=_load_field_profiles(index, item["fields"]),
                monster_kills_rva=monster_kills_rva,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"Player-stats profile entry {index} is invalid: {error}") from error
        if normalized_sha256 in profiles:
            raise ValueError(f"Player-stats profiles repeat SHA-256 {normalized_sha256}.")
        profiles[normalized_sha256] = profile
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
        required = {"name", "source", "minimum", "maximum"}
        if missing := required.difference(item):
            raise ValueError(f"field {field_index} is missing {', '.join(sorted(missing))}.")
        if not isinstance(item["name"], str):
            raise ValueError(f"field {field_index} has an invalid name.")
        bounds = (item["minimum"], item["maximum"])
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in bounds
        ):
            raise ValueError(f"field {field_index} has non-numeric bounds.")
        fields.append(
            PlayerStatFieldProfile(
                name=item["name"],
                source=_load_source(profile_index, field_index, item["source"]),
                minimum=float(item["minimum"]),
                maximum=float(item["maximum"]),
                is_unknown=bool(item.get("is_unknown", False)),
            )
        )
    return tuple(fields)


def _load_source(profile_index: int, field_index: int, payload: object) -> PlayerStatSource:
    if not isinstance(payload, dict):
        raise ValueError(f"profile {profile_index} field {field_index} source must be an object.")
    try:
        kind = PlayerStatSourceKind(payload["kind"])
        primitive = PlayerStatType(payload["primitive"])
    except (KeyError, ValueError) as error:
        raise ValueError(f"field {field_index} has an invalid source kind or primitive.") from error
    if kind is PlayerStatSourceKind.DIRECT:
        offset = payload.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise ValueError(f"field {field_index} direct source needs an integer offset.")
        return DirectPlayerStatSource(offset, primitive)
    if kind is PlayerStatSourceKind.XOR_PAIR:
        numbers = (payload.get("offset"), payload.get("key_a"), payload.get("key_b"))
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in numbers):
            raise ValueError(f"field {field_index} xor_pair source needs integer offset and keys.")
        offset, key_a, key_b = cast(tuple[int, int, int], numbers)
        return XorPairPlayerStatSource(offset, key_a, key_b, primitive)
    numerator = payload.get("numerator_offset")
    denominator = payload.get("denominator_offset")
    scale = payload.get("scale")
    if not all(
        isinstance(value, int) and not isinstance(value, bool) for value in (numerator, denominator)
    ):
        raise ValueError(f"field {field_index} ratio source needs integer offsets.")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool):
        raise ValueError(f"field {field_index} ratio source needs a numeric scale.")
    return RatioPlayerStatSource(
        cast(int, numerator),
        cast(int, denominator),
        primitive,
        float(scale),
    )
