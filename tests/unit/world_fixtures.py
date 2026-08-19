"""Synthetic client world files for the world extraction tests.

The real client tree is the operator's own game installation and is never part of this
repository, so every extraction test builds the byte layout it needs from these helpers.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from flyff_bot.features.navigation.client_archive import encode_archive_payload
from flyff_bot.features.navigation.world_extractor import (
    DYNAMIC_OBJECT_MODEL_NAME_BYTES,
    DYNAMIC_OBJECT_MODEL_NAME_OFFSET,
    DYNAMIC_OBJECT_POSITION_OFFSET,
    DYNAMIC_OBJECT_RECORD_BYTES,
    LAND_BLOCK_VERTICES_PER_SIDE,
    SUPPORTED_LAND_BLOCK_VERSION,
    land_block_file_name,
)

# The client's index stores an opaque digest of the file name rather than the name itself,
# so the synthetic archives do the same: nothing here may depend on reading it back.
ARCHIVE_IDENTITY_LENGTH = 64

WORLD_SCRIPT = """// World script

size 2, 2
indoor 0
MPU 4
sky default default default
"""

RESPAWN_TRAILER = "1 30 1 24 1 1 2 0.000000 -1 0 0"


def region_script(records: Iterable[str]) -> str:
    """Return a `.rgn` script body around a set of record lines."""

    return "// Region Script File\n\n" + "\n".join(records) + "\n"


def respawn_record(
    monster_id: int,
    center: tuple[float, float, float],
    bounds: tuple[int, int, int, int],
    capacity: int,
    respawn_seconds: int,
    kind: int = 5,
) -> str:
    """Return one `respawn7` line in the client's field order."""

    x, y, z = center
    left, top, right, bottom = bounds
    return (
        f"respawn7 {kind} {monster_id} {x:.6f} {y:.6f} {z:.6f} {capacity} {respawn_seconds} 0 "
        f"{left} {top} {right} {bottom} {RESPAWN_TRAILER}"
    )


def utf16_payload(text: str) -> bytes:
    """Return one script encoded the way the client writes it: UTF-16 with a byte-order mark."""

    return b"\xff\xfe" + text.encode("utf-16-le")


def land_block_payload(
    block_x: int, block_z: int, heights: Sequence[float], version: int | None = None
) -> bytes:
    """Return one `.lnd` payload around a full height grid."""

    header = struct.pack(
        "<3i", SUPPORTED_LAND_BLOCK_VERSION if version is None else version, block_x, block_z
    )
    return header + struct.pack(f"<{len(heights)}f", *heights)


def flat_heights(height: float = 100.0) -> list[float]:
    """Return a level height grid of one whole terrain block."""

    return [height] * (LAND_BLOCK_VERTICES_PER_SIDE * LAND_BLOCK_VERTICES_PER_SIDE)


def raise_vertex(heights: list[float], column: int, row: int, height: float) -> list[float]:
    """Return the grid with one vertex lifted, which makes its four quads a cliff."""

    updated = list(heights)
    updated[row * LAND_BLOCK_VERTICES_PER_SIDE + column] = height
    return updated


def dynamic_object_payload(
    positions: Sequence[tuple[float, float, float]], model_name: str = "TestProp"
) -> bytes:
    """Return one `.dyo` payload placing a set of objects."""

    body = bytearray()
    for x, y, z in positions:
        record = bytearray(DYNAMIC_OBJECT_RECORD_BYTES)
        struct.pack_into("<3f", record, DYNAMIC_OBJECT_POSITION_OFFSET, x, y, z)
        encoded = model_name.encode("cp1252")[: DYNAMIC_OBJECT_MODEL_NAME_BYTES - 1]
        record[
            DYNAMIC_OBJECT_MODEL_NAME_OFFSET : DYNAMIC_OBJECT_MODEL_NAME_OFFSET + len(encoded)
        ] = encoded
        body.extend(record)
    return struct.pack("<i", len(positions)) + bytes(body)


def archive_identity(file_name: str) -> str:
    """Return one opaque index identity, standing in for the client's own name digest."""

    return hashlib.sha256(file_name.encode("cp1252")).hexdigest()[:ARCHIVE_IDENTITY_LENGTH]


def archive_payloads(files: Mapping[str, bytes]) -> tuple[bytes, bytes]:
    """Return the `.hdr` index and the `.one` payload of one synthetic archive pair."""

    index = bytearray(struct.pack("<i", len(files)))
    payload = bytearray()
    for file_name, content in files.items():
        identity = archive_identity(file_name).encode("ascii")
        index.extend(struct.pack("<i", len(identity)))
        index.extend(identity)
        index.extend(struct.pack("<2i", len(payload), len(content)))
        payload.extend(encode_archive_payload(content, file_name))
    return bytes(index), bytes(payload)


def archive_index_bytes(files: Mapping[str, bytes]) -> bytes:
    """Return only the `.hdr` index of one synthetic archive pair."""

    return archive_payloads(files)[0]


def write_archive(directory: Path, stem: str, files: Mapping[str, bytes]) -> None:
    """Create one synthetic `.hdr` / `.one` archive pair holding the given packed files."""

    index, payload = archive_payloads(files)
    (directory / f"{stem}.hdr").write_bytes(index)
    (directory / f"{stem}.one").write_bytes(payload)


def unsupported_archive_index(entry_count: int = 1) -> bytes:
    """Return an index in the other layout the client ships, which this reader refuses.

    Its records carry one extra leading field, so every later field lands on the wrong
    offset and the index cannot describe itself.
    """

    index = bytearray(struct.pack("<i", entry_count))
    for number in range(entry_count):
        identity = archive_identity(str(number)).encode("ascii")
        index.extend(struct.pack("<i", -1))
        index.extend(struct.pack("<i", len(identity)))
        index.extend(identity)
        index.extend(struct.pack("<2i", 0, 0))
    return bytes(index)


def write_world_directory(
    root: Path,
    name: str,
    *,
    region_records: Iterable[str] = (),
    blocks: Iterable[tuple[int, int, Sequence[float]]] = (),
    archived_blocks: Iterable[tuple[int, int, Sequence[float]]] = (),
    archived_files: Mapping[str, bytes] | None = None,
    objects: Sequence[tuple[float, float, float]] = (),
) -> Path:
    """Create one synthetic client region directory and return its path."""

    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.wld").write_bytes(WORLD_SCRIPT.encode("cp1252"))
    records = list(region_records)
    if records:
        (directory / f"{name}.rgn").write_bytes(utf16_payload(region_script(records)))
    for block_x, block_z, heights in blocks:
        block_name = land_block_file_name(name, block_x, block_z)
        (directory / block_name).write_bytes(land_block_payload(block_x, block_z, heights))
    packed = dict(archived_files or {})
    for block_x, block_z, heights in archived_blocks:
        packed[land_block_file_name(name, block_x, block_z)] = land_block_payload(
            block_x, block_z, heights
        )
    if packed:
        write_archive(directory, name, packed)
    if objects:
        (directory / f"{name}.dyo").write_bytes(dynamic_object_payload(objects))
    return directory
