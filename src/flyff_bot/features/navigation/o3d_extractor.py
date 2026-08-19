"""Read the collision geometry embedded in Flyff ``.o3d`` model assets.

The reader is deliberately narrow: it implements the version-22 layout observed in the
configured Entropia client and refuses any layout it cannot prove.  It reads files only;
neither archives nor client assets are ever changed.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

from flyff_bot.features.navigation.client_archive import ClientWorldArchive, encode_archive_payload

O3D_FILENAME_XOR = 0xCD
O3D_VERSION_WITH_FORCE_VECTORS = 22
O3D_VECTOR_BYTES = 12
O3D_BOUNDS_VECTOR_COUNT = 2
O3D_RESERVED_BYTES = 16
O3D_GMOBJECT_RESERVED_BYTES = 28
O3D_NORMAL_VERTEX_BYTES = 32
O3D_INDEX_BYTES = 2
O3D_MAXIMUM_ELEMENTS = 2_000_000


class O3DExtractionError(ValueError):
    """Raised when an O3D payload is malformed or uses an unsupported layout."""


@dataclass(frozen=True, slots=True, order=True)
class ModelVertex:
    """One local-space point from a model collision hull."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise O3DExtractionError("An O3D vertex must be finite.")


@dataclass(frozen=True, slots=True)
class ModelBounds:
    """The authoritative model-space bounding box stored in an O3D header."""

    minimum: ModelVertex
    maximum: ModelVertex


@dataclass(frozen=True, slots=True)
class CollisionMesh:
    """A triangle collision hull, addressed by its source model vertices."""

    vertices: tuple[ModelVertex, ...]
    triangles: tuple[tuple[int, int, int], ...]
    bounds: ModelBounds


@dataclass(frozen=True, slots=True)
class O3DGeometry:
    """The navigation-relevant, reproducibly decoded part of one model asset."""

    file_name: str
    version: int
    bounds: ModelBounds
    collision_mesh: CollisionMesh | None


class _Reader:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def read(self, size: int) -> bytes:
        if size < 0 or self._offset + size > len(self._payload):
            raise O3DExtractionError("An O3D payload ended before its declared data.")
        result = self._payload[self._offset : self._offset + size]
        self._offset += size
        return result

    def integer(self) -> int:
        (value,) = struct.unpack("<i", self.read(4))
        return int(value)

    def unsigned(self) -> int:
        (value,) = struct.unpack("<I", self.read(4))
        return int(value)

    def vector(self) -> ModelVertex:
        return ModelVertex(*struct.unpack("<3f", self.read(O3D_VECTOR_BYTES)))


def extract_o3d_geometry(payload: bytes, file_name: str) -> O3DGeometry:
    """Extract one version-22 O3D's collision hull and header bounds.

    The format stores an encrypted basename before the binary header.  Matching it protects
    archive/model-name mix-ups: a payload may be decoded only with the file name it names.
    Rendering data is skipped because the dedicated collision object is the client physics
    authority and avoids baking dense visual-only meshes.
    """

    reader = _Reader(payload)
    name_length = reader.read(1)[0]
    encoded_name = reader.read(name_length)
    stored_name = bytes(value ^ O3D_FILENAME_XOR for value in encoded_name).decode(
        "cp1252", errors="strict"
    )
    expected_name = Path(file_name).name
    if stored_name.casefold() != expected_name.casefold():
        raise O3DExtractionError("An O3D header names a different model file.")
    version = reader.integer()
    if version < O3D_VERSION_WITH_FORCE_VECTORS:
        raise O3DExtractionError(f"Unsupported O3D version: {version}.")
    reader.integer()  # Stable serial ID, not needed for collision extraction.
    for _ in range(4):
        reader.vector()
    reader.read(8)  # Scroll U/V.
    reader.read(O3D_RESERVED_BYTES)
    bounds = ModelBounds(reader.vector(), reader.vector())
    reader.read(4)  # Per-slerp value.
    reader.integer()  # Animation frame count.
    event_count = _checked_count(reader.integer(), "event")
    reader.read(event_count * O3D_VECTOR_BYTES)
    has_collision_mesh = reader.integer()
    collision_mesh = _read_collision_mesh(reader) if has_collision_mesh else None
    return O3DGeometry(expected_name, version, bounds, collision_mesh)


def extract_o3d_file(path: Path) -> O3DGeometry:
    """Read one loose client model without writing to its source location."""

    return extract_o3d_geometry(path.read_bytes(), path.name)


def extract_packed_o3d(index_path: Path, data_path: Path, file_name: str) -> O3DGeometry | None:
    """Extract one known-name O3D from a read-only client ``.hdr`` / ``.one`` pair.

    Packed index entries intentionally carry opaque identities.  An O3D's encrypted basename
    header is predictable from the requested filename, just as US-052 recognises terrain
    headers, so no archive enumeration or client-file mutation is required.
    """

    expected_name = Path(file_name).name
    prefix = _o3d_header_prefix(expected_name)
    stored_prefix = encode_archive_payload(prefix, expected_name)
    with ClientWorldArchive(index_path, data_path) as archive:
        payload = archive.read(expected_name, stored_prefix)
    return None if payload is None else extract_o3d_geometry(payload, expected_name)


def _read_collision_mesh(reader: _Reader) -> CollisionMesh:
    bounds = ModelBounds(reader.vector(), reader.vector())
    reader.read(12)  # Opacity, bump, and rigid flags.
    reader.read(O3D_GMOBJECT_RESERVED_BYTES)
    vertex_count = _checked_count(reader.integer(), "collision vertex")
    indexed_vertex_count = _checked_count(reader.integer(), "indexed collision vertex")
    reader.integer()  # Face-list count; the index buffer below is authoritative.
    index_count = _checked_count(reader.integer(), "collision index")
    if index_count % 3:
        raise O3DExtractionError("A collision index buffer must contain whole triangles.")
    vertices = tuple(reader.vector() for _ in range(vertex_count))
    reader.read(indexed_vertex_count * O3D_NORMAL_VERTEX_BYTES)
    indexed = struct.unpack(f"<{index_count}H", reader.read(index_count * O3D_INDEX_BYTES))
    source_indices = struct.unpack(
        f"<{indexed_vertex_count}H", reader.read(indexed_vertex_count * O3D_INDEX_BYTES)
    )
    if reader.unsigned():
        reader.read(vertex_count * 4)  # Optional physique metadata.
    triangles: list[tuple[int, int, int]] = []
    for first, second, third in zip(indexed[::3], indexed[1::3], indexed[2::3], strict=True):
        if max(first, second, third) >= len(source_indices):
            raise O3DExtractionError("A collision index refers past its indexed vertex buffer.")
        triangle = (source_indices[first], source_indices[second], source_indices[third])
        if max(triangle) >= len(vertices):
            raise O3DExtractionError("A collision index refers past its vertex list.")
        if len(set(triangle)) == 3:
            triangles.append(triangle)
    return CollisionMesh(vertices, tuple(triangles), bounds)


def _o3d_header_prefix(file_name: str) -> bytes:
    encoded_name = bytes(value ^ O3D_FILENAME_XOR for value in file_name.encode("cp1252"))
    if len(encoded_name) > 255:
        raise O3DExtractionError("An O3D file name is too long for its one-byte header length.")
    return bytes((len(encoded_name),)) + encoded_name


def _checked_count(value: int, kind: str) -> int:
    if not 0 <= value <= O3D_MAXIMUM_ELEMENTS:
        raise O3DExtractionError(f"An O3D {kind} count is outside the supported range.")
    return value
