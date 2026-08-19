"""Offline fusion of terrain and placed O3D collision geometry into world triangles."""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass

from flyff_bot.features.navigation.o3d_extractor import CollisionMesh, ModelVertex
from flyff_bot.features.navigation.world_extractor import (
    DYNAMIC_OBJECT_MODEL_NAME_BYTES,
    DYNAMIC_OBJECT_MODEL_NAME_OFFSET,
    DYNAMIC_OBJECT_RECORD_BYTES,
    LAND_BLOCK_CELLS_PER_SIDE,
    LandBlock,
    WorldDimensions,
)

DYNAMIC_OBJECT_ANGLE_OFFSET = 0
DYNAMIC_OBJECT_AXIS_OFFSET = 4
DYNAMIC_OBJECT_POSITION_OFFSET = 16
DYNAMIC_OBJECT_SCALE_OFFSET = 28
DYNAMIC_OBJECT_TYPE_OFFSET = 40
DYNAMIC_OBJECT_INDEX_OFFSET = 44
DYNAMIC_OBJECT_TYPE_BYTES = 4
DEGREES_PER_FULL_ROTATION = 360.0


class WorldGeometryError(ValueError):
    """Raised when a static placement cannot safely enter the world geometry."""


@dataclass(frozen=True, slots=True, order=True)
class WorldVertex:
    """One point in the client world coordinate frame, with Y as elevation."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise WorldGeometryError("World geometry coordinates must be finite.")


@dataclass(frozen=True, slots=True)
class WorldTriangle:
    """A source-labelled static triangle in the shared terrain/object coordinate frame."""

    first: WorldVertex
    second: WorldVertex
    third: WorldVertex
    source: str


@dataclass(frozen=True, slots=True)
class DynamicObjectPlacement:
    """A fixed-size Flyff DYO record needed to place an O3D in world space."""

    model_name: str
    position: WorldVertex
    angle_degrees: float
    axis_rotation_degrees: WorldVertex
    scale: WorldVertex
    object_type: int
    object_index: int


@dataclass(frozen=True, slots=True)
class WorldGeometry:
    """Terrain and collision triangles expressed in the single client-world frame."""

    triangles: tuple[WorldTriangle, ...]

    @property
    def terrain_triangle_count(self) -> int:
        """Return the terrain contribution while retaining source-labelled object geometry."""

        return sum(triangle.source.startswith("terrain:") for triangle in self.triangles)

    @property
    def object_triangle_count(self) -> int:
        """Return placed collision triangles, never visual render meshes."""

        return len(self.triangles) - self.terrain_triangle_count


def parse_dynamic_placements(payload: bytes) -> tuple[DynamicObjectPlacement, ...]:
    """Decode the observed 200-byte DYO records without guessing variant layouts."""

    if len(payload) % (DYNAMIC_OBJECT_TYPE_BYTES + DYNAMIC_OBJECT_RECORD_BYTES) == 0:
        records = tuple(
            payload[
                offset + DYNAMIC_OBJECT_TYPE_BYTES : offset
                + DYNAMIC_OBJECT_TYPE_BYTES
                + DYNAMIC_OBJECT_RECORD_BYTES
            ]
            for offset in range(
                0, len(payload), DYNAMIC_OBJECT_TYPE_BYTES + DYNAMIC_OBJECT_RECORD_BYTES
            )
        )
    elif (
        len(payload) >= DYNAMIC_OBJECT_TYPE_BYTES
        and (len(payload) - DYNAMIC_OBJECT_TYPE_BYTES) % DYNAMIC_OBJECT_RECORD_BYTES == 0
    ):
        # The older US-052 fixture layout stores the leading object type only once.
        records = tuple(
            payload[offset : offset + DYNAMIC_OBJECT_RECORD_BYTES]
            for offset in range(
                DYNAMIC_OBJECT_TYPE_BYTES, len(payload), DYNAMIC_OBJECT_RECORD_BYTES
            )
        )
    else:
        raise WorldGeometryError("A DYO file does not divide into complete placement records.")
    placements: list[DynamicObjectPlacement] = []
    for record in records:
        angle = struct.unpack_from("<f", record, DYNAMIC_OBJECT_ANGLE_OFFSET)[0]
        axis = WorldVertex(*struct.unpack_from("<3f", record, DYNAMIC_OBJECT_AXIS_OFFSET))
        position = WorldVertex(*struct.unpack_from("<3f", record, DYNAMIC_OBJECT_POSITION_OFFSET))
        scale = WorldVertex(*struct.unpack_from("<3f", record, DYNAMIC_OBJECT_SCALE_OFFSET))
        object_type, object_index = struct.unpack_from("<2I", record, DYNAMIC_OBJECT_TYPE_OFFSET)
        raw_name = record[
            DYNAMIC_OBJECT_MODEL_NAME_OFFSET : DYNAMIC_OBJECT_MODEL_NAME_OFFSET
            + DYNAMIC_OBJECT_MODEL_NAME_BYTES
        ]
        model_name = raw_name.split(b"\x00", 1)[0].decode("cp1252", errors="replace")
        if not model_name or not all(math.isfinite(value) for value in (angle,)):
            raise WorldGeometryError("A DYO placement has no usable model name or rotation.")
        placements.append(
            DynamicObjectPlacement(
                model_name, position, angle, axis, scale, object_type, object_index
            )
        )
    return tuple(placements)


def transform_collision_mesh(
    mesh: CollisionMesh, placement: DynamicObjectPlacement
) -> tuple[WorldTriangle, ...]:
    """Apply the client DYO scale, X/Y/Z Euler rotation, then translation to a collision hull."""

    transformed = tuple(_transform(vertex, placement) for vertex in mesh.vertices)
    return tuple(
        WorldTriangle(
            transformed[first], transformed[second], transformed[third], placement.model_name
        )
        for first, second, third in mesh.triangles
    )


def terrain_triangles(
    blocks: tuple[LandBlock, ...], dimensions: WorldDimensions
) -> tuple[WorldTriangle, ...]:
    """Triangulate existing US-052 height fields without altering their representation."""

    result: list[WorldTriangle] = []
    span = dimensions.meters_per_unit
    for block in blocks:
        origin_x = block.block_x * dimensions.block_span_units
        origin_z = block.block_z * dimensions.block_span_units
        for row in range(LAND_BLOCK_CELLS_PER_SIDE):
            for column in range(LAND_BLOCK_CELLS_PER_SIDE):
                lower_left = WorldVertex(
                    origin_x + column * span, block.height(column, row), origin_z + row * span
                )
                lower_right = WorldVertex(
                    origin_x + (column + 1) * span,
                    block.height(column + 1, row),
                    origin_z + row * span,
                )
                upper_left = WorldVertex(
                    origin_x + column * span,
                    block.height(column, row + 1),
                    origin_z + (row + 1) * span,
                )
                upper_right = WorldVertex(
                    origin_x + (column + 1) * span,
                    block.height(column + 1, row + 1),
                    origin_z + (row + 1) * span,
                )
                source = f"terrain:{block.block_x}:{block.block_z}"
                result.extend(
                    (
                        WorldTriangle(lower_left, lower_right, upper_left, source),
                        WorldTriangle(lower_right, upper_right, upper_left, source),
                    )
                )
    return tuple(result)


def fuse_world_geometry(
    blocks: tuple[LandBlock, ...],
    dimensions: WorldDimensions,
    placements: tuple[DynamicObjectPlacement, ...],
    collision_meshes: Mapping[str, CollisionMesh],
) -> WorldGeometry:
    """Fuse US-052 terrain and resolved collision hulls without inventing missing models.

    A model without a known collision mesh is omitted rather than replaced by its render mesh
    or a guessed footprint.  The pre-existing US-052 obstacle rectangles stay available as
    the live-routing fallback for precisely that conservative case.
    """

    triangles = list(terrain_triangles(blocks, dimensions))
    for placement in placements:
        mesh = collision_meshes.get(placement.model_name.casefold())
        if mesh is not None:
            triangles.extend(transform_collision_mesh(mesh, placement))
    return WorldGeometry(tuple(triangles))


def _transform(vertex: ModelVertex, placement: DynamicObjectPlacement) -> WorldVertex:
    x, y, z = (
        vertex.x * placement.scale.x,
        vertex.y * placement.scale.y,
        vertex.z * placement.scale.z,
    )
    # CObj stores its yaw separately and axis X/Z rotation separately.  DirectX applies
    # those local rotations before translating the model into the common client frame.
    x, y, z = _rotate_x(x, y, z, placement.axis_rotation_degrees.x)
    x, y, z = _rotate_y(x, y, z, placement.angle_degrees + placement.axis_rotation_degrees.y)
    x, y, z = _rotate_z(x, y, z, placement.axis_rotation_degrees.z)
    return WorldVertex(x + placement.position.x, y + placement.position.y, z + placement.position.z)


def _rotate_x(x: float, y: float, z: float, degrees: float) -> tuple[float, float, float]:
    radians = math.radians(degrees % DEGREES_PER_FULL_ROTATION)
    return (
        x,
        y * math.cos(radians) - z * math.sin(radians),
        y * math.sin(radians) + z * math.cos(radians),
    )


def _rotate_y(x: float, y: float, z: float, degrees: float) -> tuple[float, float, float]:
    radians = math.radians(degrees % DEGREES_PER_FULL_ROTATION)
    return (
        x * math.cos(radians) + z * math.sin(radians),
        y,
        -x * math.sin(radians) + z * math.cos(radians),
    )


def _rotate_z(x: float, y: float, z: float, degrees: float) -> tuple[float, float, float]:
    radians = math.radians(degrees % DEGREES_PER_FULL_ROTATION)
    return (
        x * math.cos(radians) - y * math.sin(radians),
        x * math.sin(radians) + y * math.cos(radians),
        z,
    )
