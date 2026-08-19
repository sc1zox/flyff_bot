"""Regression coverage for offline Flyff O3D collision extraction."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from world_fixtures import write_archive

from flyff_bot.features.navigation.o3d_extractor import (
    O3DExtractionError,
    extract_o3d_geometry,
    extract_packed_o3d,
)
from flyff_bot.features.navigation.world_geometry import (
    DynamicObjectPlacement,
    WorldGeometryError,
    WorldVertex,
    parse_dynamic_placements,
    transform_collision_mesh,
)


def _vector(x: float, y: float, z: float) -> bytes:
    return struct.pack("<3f", x, y, z)


def _o3d_payload(name: str, *, collision: bool = True) -> bytes:
    encoded_name = bytes(ord(character) ^ 0xCD for character in name)
    header = bytearray()
    header.extend(bytes((len(encoded_name),)))
    header.extend(encoded_name)
    header.extend(struct.pack("<2i", 22, 101))
    header.extend(_vector(0.0, 0.0, 0.0) * 4)
    header.extend(struct.pack("<2f", 0.0, 0.0))
    header.extend(bytes(16))
    header.extend(_vector(-1.0, 0.0, -1.0))
    header.extend(_vector(1.0, 2.0, 1.0))
    header.extend(struct.pack("<f2i", 0.0, 0, 0))
    header.extend(struct.pack("<i", int(collision)))
    if not collision:
        return bytes(header)
    vertices = (
        _vector(-1.0, 0.0, -1.0),
        _vector(1.0, 0.0, -1.0),
        _vector(1.0, 0.0, 1.0),
        _vector(-1.0, 0.0, 1.0),
    )
    header.extend(_vector(-1.0, 0.0, -1.0))
    header.extend(_vector(1.0, 0.0, 1.0))
    header.extend(struct.pack("<3i", 0, 0, 0))
    header.extend(bytes(28))
    header.extend(struct.pack("<4i", 4, 4, 2, 6))
    header.extend(b"".join(vertices))
    header.extend(bytes(4 * 32))
    header.extend(struct.pack("<6H", 0, 1, 2, 0, 2, 3))
    header.extend(struct.pack("<4H", 0, 1, 2, 3))
    header.extend(struct.pack("<I", 0))
    return bytes(header)


def _dyo_payload() -> bytes:
    record = bytearray(200)
    struct.pack_into("<f", record, 0, 90.0)
    struct.pack_into("<3f", record, 4, 10.0, 0.0, 0.0)
    struct.pack_into("<3f", record, 16, 100.0, 50.0, 200.0)
    struct.pack_into("<3f", record, 28, 2.0, 3.0, 4.0)
    struct.pack_into("<2I", record, 40, 5, 1234)
    record[156:166] = b"bridge.o3d"
    return struct.pack("<I", 5) + bytes(record)


def test_collision_mesh_is_preferred_and_reconstructed_from_index_buffers() -> None:
    geometry = extract_o3d_geometry(_o3d_payload("bridge.o3d"), "bridge.o3d")

    assert geometry.collision_mesh is not None
    assert len(geometry.collision_mesh.vertices) == 4
    assert geometry.collision_mesh.triangles == ((0, 1, 2), (0, 2, 3))
    assert geometry.bounds.minimum.y == pytest.approx(0.0)


def test_o3d_payload_must_name_the_file_used_to_decode_it() -> None:
    with pytest.raises(O3DExtractionError, match="different model"):
        extract_o3d_geometry(_o3d_payload("bridge.o3d"), "other.o3d")


def test_a_model_without_a_collision_hull_retains_only_its_bounds() -> None:
    geometry = extract_o3d_geometry(_o3d_payload("visual.o3d", collision=False), "visual.o3d")

    assert geometry.collision_mesh is None
    assert geometry.bounds.maximum.y == pytest.approx(2.0)


def test_known_name_o3d_collision_geometry_is_extracted_from_an_archive(tmp_path: Path) -> None:
    name = "bridge.o3d"
    write_archive(tmp_path, "model", {name: _o3d_payload(name)})

    geometry = extract_packed_o3d(tmp_path / "model.hdr", tmp_path / "model.one", name)

    assert geometry is not None
    assert geometry.collision_mesh is not None
    assert len(geometry.collision_mesh.triangles) == 2


def test_dyo_placements_retain_translation_rotation_scale_and_model_name() -> None:
    (placement,) = parse_dynamic_placements(_dyo_payload())

    assert placement.model_name == "bridge.o3d"
    assert placement.position.x == pytest.approx(100.0)
    assert placement.position.y == pytest.approx(50.0)
    assert placement.position.z == pytest.approx(200.0)
    assert placement.angle_degrees == pytest.approx(90.0)
    assert placement.scale.z == pytest.approx(4.0)


def test_placed_collision_triangles_share_the_terrain_world_coordinate_frame() -> None:
    geometry = extract_o3d_geometry(_o3d_payload("bridge.o3d"), "bridge.o3d")
    assert geometry.collision_mesh is not None
    placement = DynamicObjectPlacement(
        "bridge.o3d",
        WorldVertex(100.0, 50.0, 200.0),
        0.0,
        WorldVertex(0.0, 0.0, 0.0),
        WorldVertex(1.0, 1.0, 1.0),
        5,
        1234,
    )

    triangles = transform_collision_mesh(geometry.collision_mesh, placement)

    assert triangles[0].first == WorldVertex(99.0, 50.0, 199.0)
    assert triangles[0].second == WorldVertex(101.0, 50.0, 199.0)


def test_dyo_payloads_with_partial_records_are_refused() -> None:
    with pytest.raises(WorldGeometryError):
        parse_dynamic_placements(_dyo_payload()[:-1])
