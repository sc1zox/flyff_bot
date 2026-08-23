"""Offline extraction of vector spawn zones and terrain passability from client world files.

The Flyff client ships each region as a directory of small description files next to one
packed ``.one`` archive. The loose files are the world script (``.wld``) stating the map
dimensions, the region script (``.rgn``) listing the monster respawn zones, the
dynamic-object file (``.dyo``) placing props, and whichever terrain blocks (``.lnd``) a
patch has replaced on disk. The rest of the region's terrain lives inside the archive, and
US-052 reads it through :mod:`flyff_bot.features.navigation.client_archive`, so a region's
height field now covers every block the client ships rather than only its patched ones.

Reading is strictly offline file I/O: no game process is opened, and no client file is
written. Extracted height fields are written to the local navigation data directory as
plain ``.lnd`` heightfields.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Iterable, Mapping, MutableSequence, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from flyff_bot.features.navigation.client_archive import (
    ClientArchiveError,
    ClientWorldArchive,
    encode_archive_payload,
)

WORLD_SCRIPT_SUFFIX = ".wld"
REGION_SCRIPT_SUFFIX = ".rgn"
LAND_BLOCK_SUFFIX = ".lnd"
DYNAMIC_OBJECT_SUFFIX = ".dyo"

# The client writes its scripts as UTF-16 with a byte-order mark; a few are plain ANSI.
UTF16_BYTE_ORDER_MARKS = (b"\xff\xfe", b"\xfe\xff")
WORLD_TEXT_FALLBACK_ENCODINGS = ("utf-8", "cp1252")

# `.wld` directives that carry geometry. Everything else is presentation (sky, fog, music).
WORLD_SIZE_DIRECTIVE = "size"
WORLD_METERS_PER_UNIT_DIRECTIVE = "MPU"
DEFAULT_METERS_PER_UNIT = 4.0

# `.rgn` monster respawn record: `respawn7 <kind> <mob id> <x> <y> <z> <capacity>
# <respawn seconds> <flag> <x1> <z1> <x2> <z2> ...`. Only the leading fields are geometry;
# the trailing ones are aggression, level, and script hooks the bot does not act on.
RESPAWN_DIRECTIVE = "respawn7"
RESPAWN_MONSTER_KIND = "5"
RESPAWN_FIELD_KIND = 1
RESPAWN_FIELD_MONSTER_ID = 2
RESPAWN_FIELD_CENTER_X = 3
RESPAWN_FIELD_CENTER_Y = 4
RESPAWN_FIELD_CENTER_Z = 5
RESPAWN_FIELD_CAPACITY = 6
RESPAWN_FIELD_RESPAWN_SECONDS = 7
RESPAWN_FIELD_MINIMUM_X = 9
RESPAWN_FIELD_MINIMUM_Z = 10
RESPAWN_FIELD_MAXIMUM_X = 11
RESPAWN_FIELD_MAXIMUM_Z = 12
RESPAWN_MINIMUM_FIELDS = RESPAWN_FIELD_MAXIMUM_Z + 1

# `.lnd` terrain block: `<version> <block x> <block z>` followed by the raw height grid.
# A block spans 128 quads, so it stores 129 vertices per side, the last of which is shared
# with the next block.
SUPPORTED_LAND_BLOCK_VERSION = 3
LAND_BLOCK_CELLS_PER_SIDE = 128
LAND_BLOCK_VERTICES_PER_SIDE = LAND_BLOCK_CELLS_PER_SIDE + 1
LAND_BLOCK_HEADER_BYTES = 12
FLOAT32_BYTES = 4
LAND_BLOCK_SAMPLE_COUNT = LAND_BLOCK_VERTICES_PER_SIDE * LAND_BLOCK_VERTICES_PER_SIDE
LAND_BLOCK_HEIGHTFIELD_BYTES = LAND_BLOCK_HEADER_BYTES + LAND_BLOCK_SAMPLE_COUNT * FLOAT32_BYTES
# The client names a packed terrain block after its region and its two-digit block indices.
LAND_BLOCK_NAME_TEMPLATE = "{world}{block_x:02d}-{block_z:02d}{suffix}"

# A gradient above one metre of rise per metre of run is a cliff face the client's physics
# refuses to walk up (US-045), so the quad it belongs to is impassable.
IMPASSABLE_SLOPE_GRADIENT = 1.0

# `.dyo` placed object: one leading version integer, then fixed-size records. The offsets
# below are read off the shipped Eden file, whose single record ends exactly on the file
# boundary; a payload that does not divide into whole records is rejected rather than
# guessed at.
DYNAMIC_OBJECT_HEADER_BYTES = 4
DYNAMIC_OBJECT_RECORD_BYTES = 200
DYNAMIC_OBJECT_POSITION_OFFSET = 16
DYNAMIC_OBJECT_MODEL_NAME_OFFSET = 156
DYNAMIC_OBJECT_MODEL_NAME_BYTES = 32
# No collision hull is stored with a placed object, so its footprint is the finest square
# the passability grid itself resolves: one terrain quad.
DEFAULT_DYNAMIC_OBJECT_RADIUS_UNITS = DEFAULT_METERS_PER_UNIT

WORLD_VECTOR_MAP_SCHEMA_VERSION = 3


class WorldExtractionError(ValueError):
    """Raised when a client world file cannot be read as the format it claims to be."""


class ObstacleKind(StrEnum):
    """Why a rectangle of world ground may not be walked through."""

    # A terrain quad whose slope exceeds the walkable gradient.
    SLOPE = "slope"
    # The footprint of a placed static object.
    OBJECT = "object"


class ExtractionWarning(StrEnum):
    """Why one part of a region was skipped instead of extracted."""

    # The region's `.hdr` index does not use the layout this reader supports.
    UNSUPPORTED_ARCHIVE_INDEX = "unsupported_archive_index"
    # One packed terrain block decoded into something that is not a version 3 height field.
    UNREADABLE_ARCHIVE_BLOCK = "unreadable_archive_block"
    # The region's `.dyo` file uses one of the placement layouts this reader does not know.
    UNREADABLE_OBJECT_FILE = "unreadable_object_file"


@dataclass(frozen=True, slots=True)
class ExtractionDiagnostic:
    """One skipped part of a region, named so the operator can see what was lost."""

    warning: ExtractionWarning
    detail: str


@dataclass(frozen=True, slots=True)
class WorldCoordinate:
    """One position on the world ground plane, in client world units."""

    x: float
    z: float


@dataclass(frozen=True, slots=True)
class WorldDimensions:
    """The extent of one region and the world units spanned by one terrain vertex."""

    blocks_x: int
    blocks_z: int
    meters_per_unit: float = DEFAULT_METERS_PER_UNIT

    def __post_init__(self) -> None:
        if self.blocks_x <= 0 or self.blocks_z <= 0:
            raise WorldExtractionError("A world must span at least one terrain block per axis.")
        if self.meters_per_unit <= 0.0:
            raise WorldExtractionError("A world's meters-per-unit must be positive.")

    @property
    def block_span_units(self) -> float:
        """Return the world units covered by one terrain block along one axis."""

        return LAND_BLOCK_CELLS_PER_SIDE * self.meters_per_unit

    @property
    def width_units(self) -> float:
        """Return the world units covered by the region along the x axis."""

        return self.blocks_x * self.block_span_units

    @property
    def depth_units(self) -> float:
        """Return the world units covered by the region along the z axis."""

        return self.blocks_z * self.block_span_units

    def contains(self, point: WorldCoordinate) -> bool:
        """Return whether a position lies inside the region's ground plane."""

        return 0.0 <= point.x <= self.width_units and 0.0 <= point.z <= self.depth_units


@dataclass(frozen=True, slots=True)
class VectorSpawnZone:
    """One monster respawn area with its authoritative centroid and bounding rectangle."""

    monster_id: int
    center_x: float
    center_y: float
    center_z: float
    minimum_x: float
    minimum_z: float
    maximum_x: float
    maximum_z: float
    capacity: int
    respawn_seconds: int
    monster_name: str | None = None

    def __post_init__(self) -> None:
        if self.maximum_x < self.minimum_x or self.maximum_z < self.minimum_z:
            raise WorldExtractionError("A spawn zone's bounding rectangle must not be inverted.")

    @property
    def centroid(self) -> WorldCoordinate:
        """Return the zone's centre on the ground plane."""

        return WorldCoordinate(self.center_x, self.center_z)

    @property
    def anchor(self) -> WorldCoordinate:
        """Return the patrol anchor of this zone: the centre of its bounding rectangle."""

        return WorldCoordinate(
            (self.minimum_x + self.maximum_x) / 2.0, (self.minimum_z + self.maximum_z) / 2.0
        )

    @property
    def radius_units(self) -> float:
        """Return the half-diagonal of the bounding rectangle, in world units."""

        return math.hypot(self.maximum_x - self.minimum_x, self.maximum_z - self.minimum_z) / 2.0

    def contains(self, point: WorldCoordinate) -> bool:
        """Return whether a position lies inside this zone's bounding rectangle."""

        return (
            self.minimum_x <= point.x <= self.maximum_x
            and self.minimum_z <= point.z <= self.maximum_z
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible record of this zone."""

        return {
            "monster_id": self.monster_id,
            "monster_name": self.monster_name,
            "center": [self.center_x, self.center_y, self.center_z],
            "bounds": [self.minimum_x, self.minimum_z, self.maximum_x, self.maximum_z],
            "capacity": self.capacity,
            "respawn_seconds": self.respawn_seconds,
        }

    @classmethod
    def from_dict(cls, payload: object) -> VectorSpawnZone:
        """Rebuild one zone from a persisted record."""

        document = _mapping(payload, "spawn zone")
        center = _numbers(document.get("center"), "spawn zone centre", 3)
        bounds = _numbers(document.get("bounds"), "spawn zone bounds", 4)
        name = document.get("monster_name")
        if name is not None and not isinstance(name, str):
            raise WorldExtractionError("A persisted monster name must be a string.")
        return cls(
            monster_id=_integer(document.get("monster_id"), "monster id"),
            center_x=center[0],
            center_y=center[1],
            center_z=center[2],
            minimum_x=bounds[0],
            minimum_z=bounds[1],
            maximum_x=bounds[2],
            maximum_z=bounds[3],
            capacity=_integer(document.get("capacity"), "spawn capacity"),
            respawn_seconds=_integer(document.get("respawn_seconds"), "respawn seconds"),
            monster_name=name,
        )


@dataclass(frozen=True, slots=True)
class ObstacleRectangle:
    """One axis-aligned rectangle of ground the planner must route around."""

    minimum_x: float
    minimum_z: float
    maximum_x: float
    maximum_z: float
    kind: ObstacleKind = ObstacleKind.SLOPE

    def __post_init__(self) -> None:
        if self.maximum_x <= self.minimum_x or self.maximum_z <= self.minimum_z:
            raise WorldExtractionError("An obstacle rectangle must have a positive area.")

    def inflated(self, margin: float) -> ObstacleRectangle:
        """Return this rectangle grown by a clearance margin on every side."""

        return ObstacleRectangle(
            self.minimum_x - margin,
            self.minimum_z - margin,
            self.maximum_x + margin,
            self.maximum_z + margin,
            self.kind,
        )

    def contains(self, point: WorldCoordinate) -> bool:
        """Return whether a position lies inside this rectangle."""

        return (
            self.minimum_x <= point.x <= self.maximum_x
            and self.minimum_z <= point.z <= self.maximum_z
        )

    @property
    def corners(self) -> tuple[WorldCoordinate, ...]:
        """Return the four corners, which are the candidate detour points of a route."""

        return (
            WorldCoordinate(self.minimum_x, self.minimum_z),
            WorldCoordinate(self.maximum_x, self.minimum_z),
            WorldCoordinate(self.maximum_x, self.maximum_z),
            WorldCoordinate(self.minimum_x, self.maximum_z),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible record of this rectangle."""

        return {
            "bounds": [self.minimum_x, self.minimum_z, self.maximum_x, self.maximum_z],
            "kind": self.kind.value,
        }

    @classmethod
    def from_dict(cls, payload: object) -> ObstacleRectangle:
        """Rebuild one rectangle from a persisted record."""

        document = _mapping(payload, "obstacle")
        bounds = _numbers(document.get("bounds"), "obstacle bounds", 4)
        raw_kind = document.get("kind")
        if not isinstance(raw_kind, str):
            raise WorldExtractionError("A persisted obstacle kind must be a string.")
        try:
            kind = ObstacleKind(raw_kind)
        except ValueError as error:
            raise WorldExtractionError(f"Unknown obstacle kind: {raw_kind}.") from error
        return cls(bounds[0], bounds[1], bounds[2], bounds[3], kind)


@dataclass(frozen=True, slots=True)
class LandBlock:
    """One decoded terrain block: its position in the block grid and its height field."""

    block_x: int
    block_z: int
    heights: tuple[float, ...]

    def __post_init__(self) -> None:
        expected = LAND_BLOCK_VERTICES_PER_SIDE * LAND_BLOCK_VERTICES_PER_SIDE
        if len(self.heights) != expected:
            raise WorldExtractionError(f"A terrain block must carry {expected} height samples.")

    def height(self, column: int, row: int) -> float:
        """Return the height of one vertex, addressed by its x column and z row."""

        return self.heights[row * LAND_BLOCK_VERTICES_PER_SIDE + column]

    def to_bytes(self) -> bytes:
        """Return this block as a ``.lnd`` height field in the client's own byte layout."""

        header = struct.pack("<3i", SUPPORTED_LAND_BLOCK_VERSION, self.block_x, self.block_z)
        return header + struct.pack(f"<{len(self.heights)}f", *self.heights)


@dataclass(frozen=True, slots=True)
class WorldVectorMap:
    """The extracted vector description of one region: its zones and its no-go geometry."""

    world_name: str
    dimensions: WorldDimensions
    zones: tuple[VectorSpawnZone, ...] = ()
    obstacles: tuple[ObstacleRectangle, ...] = ()
    terrain_blocks: tuple[LandBlock, ...] = ()

    @property
    def terrain_block_count(self) -> int:
        """Return how many authoritative height grids are available."""

        return len(self.terrain_blocks)

    @property
    def terrain(self) -> TerrainField:
        """Return height and gradient lookup over the extracted loose blocks."""

        return TerrainField(self.dimensions, self.terrain_blocks)

    @property
    def monster_names(self) -> tuple[str, ...]:
        """Return every named monster class that has at least one zone, sorted."""

        return tuple(sorted({zone.monster_name for zone in self.zones if zone.monster_name}))

    def zones_for(self, monster_name: str) -> tuple[VectorSpawnZone, ...]:
        """Return the zones of one monster class, densest first then nearest the origin."""

        matching = [zone for zone in self.zones if zone.monster_name == monster_name]
        return tuple(
            sorted(matching, key=lambda zone: (-zone.capacity, zone.center_x, zone.center_z))
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible document of the whole extracted map."""

        return {
            "version": WORLD_VECTOR_MAP_SCHEMA_VERSION,
            "world_name": self.world_name,
            "dimensions": {
                "blocks_x": self.dimensions.blocks_x,
                "blocks_z": self.dimensions.blocks_z,
                "meters_per_unit": self.dimensions.meters_per_unit,
            },
            "zones": [zone.to_dict() for zone in self.zones],
            "obstacles": [obstacle.to_dict() for obstacle in self.obstacles],
        }

    @classmethod
    def from_dict(cls, payload: object, terrain_blocks: Iterable[LandBlock] = ()) -> WorldVectorMap:
        """Rebuild an extracted map, raising ``WorldExtractionError`` for anything unusable.

        Height fields are not part of the document: they are persisted as ``.lnd`` files and
        are passed back in, so one JSON map stays small however many blocks a region has.
        """

        document = _mapping(payload, "world vector map")
        version = _integer(document.get("version"), "version")
        if version != WORLD_VECTOR_MAP_SCHEMA_VERSION:
            raise WorldExtractionError(f"Unsupported world vector map version: {version}.")
        name = document.get("world_name")
        if not isinstance(name, str) or not name:
            raise WorldExtractionError("A persisted world vector map must name its world.")
        dimensions_document = _mapping(document.get("dimensions"), "world dimensions")
        dimensions = WorldDimensions(
            blocks_x=_integer(dimensions_document.get("blocks_x"), "blocks x"),
            blocks_z=_integer(dimensions_document.get("blocks_z"), "blocks z"),
            meters_per_unit=_number(dimensions_document.get("meters_per_unit"), "meters per unit"),
        )
        return cls(
            world_name=name,
            dimensions=dimensions,
            zones=tuple(
                VectorSpawnZone.from_dict(entry)
                for entry in _sequence(document.get("zones"), "zones")
            ),
            obstacles=tuple(
                ObstacleRectangle.from_dict(entry)
                for entry in _sequence(document.get("obstacles"), "obstacles")
            ),
            terrain_blocks=tuple(terrain_blocks),
        )


class TerrainField:
    """Bilinear height and slope lookup over extracted ``.lnd`` blocks."""

    def __init__(self, dimensions: WorldDimensions, blocks: Iterable[LandBlock]) -> None:
        self._dimensions = dimensions
        self._blocks = {(block.block_x, block.block_z): block for block in blocks}

    @property
    def is_empty(self) -> bool:
        return not self._blocks

    def covers(self, point: WorldCoordinate) -> bool:
        """Return whether a loose height block covers the point."""

        return self._location(point) is not None

    def height_at(self, point: WorldCoordinate) -> float | None:
        """Return the bilinearly interpolated terrain height, or ``None`` outside coverage."""

        location = self._location(point)
        if location is None:
            return None
        block, column, row, fraction_x, fraction_z = location
        lower_left = block.height(column, row)
        lower_right = block.height(column + 1, row)
        upper_left = block.height(column, row + 1)
        upper_right = block.height(column + 1, row + 1)
        lower = lower_left + (lower_right - lower_left) * fraction_x
        upper = upper_left + (upper_right - upper_left) * fraction_x
        return lower + (upper - lower) * fraction_z

    def gradient_at(self, point: WorldCoordinate) -> float | None:
        """Return the local steepest rise-over-run gradient."""

        location = self._location(point)
        if location is None:
            return None
        block, column, row, _fraction_x, _fraction_z = location
        return _quad_gradient(block, column, row, self._dimensions.meters_per_unit)

    def samples(self, stride: int = 8) -> tuple[tuple[float, float, float], ...]:
        """Return a bounded topographic sample set for the dashboard."""

        if stride <= 0:
            raise ValueError("Terrain sample stride must be positive.")
        samples: list[tuple[float, float, float]] = []
        span = self._dimensions.meters_per_unit
        for (block_x, block_z), block in sorted(self._blocks.items()):
            origin_x = block_x * self._dimensions.block_span_units
            origin_z = block_z * self._dimensions.block_span_units
            for row in range(0, LAND_BLOCK_VERTICES_PER_SIDE, stride):
                for column in range(0, LAND_BLOCK_VERTICES_PER_SIDE, stride):
                    samples.append(
                        (
                            origin_x + column * span,
                            block.height(column, row),
                            origin_z + row * span,
                        )
                    )
        return tuple(samples)

    def _location(self, point: WorldCoordinate) -> tuple[LandBlock, int, int, float, float] | None:
        if point.x < 0.0 or point.z < 0.0:
            return None
        block_span = self._dimensions.block_span_units
        block_x = min(int(point.x // block_span), self._dimensions.blocks_x - 1)
        block_z = min(int(point.z // block_span), self._dimensions.blocks_z - 1)
        block = self._blocks.get((block_x, block_z))
        if block is None and point.x % block_span == 0.0 and block_x > 0:
            block_x -= 1
            block = self._blocks.get((block_x, block_z))
        if block is None and point.z % block_span == 0.0 and block_z > 0:
            block_z -= 1
            block = self._blocks.get((block_x, block_z))
        if block is None:
            return None
        span = self._dimensions.meters_per_unit
        local_x = (point.x - block_x * block_span) / span
        local_z = (point.z - block_z * block_span) / span
        if not 0.0 <= local_x <= LAND_BLOCK_CELLS_PER_SIDE:
            return None
        if not 0.0 <= local_z <= LAND_BLOCK_CELLS_PER_SIDE:
            return None
        column = min(math.floor(local_x), LAND_BLOCK_CELLS_PER_SIDE - 1)
        row = min(math.floor(local_z), LAND_BLOCK_CELLS_PER_SIDE - 1)
        return block, column, row, local_x - column, local_z - row


@dataclass(frozen=True, slots=True)
class WorldExtractionSummary:
    """What one extraction produced, as the operator-facing dialog reports it."""

    world_name: str
    zone_count: int
    obstacle_count: int
    terrain_block_count: int
    monster_names: tuple[str, ...]
    output_path: Path
    declared_block_count: int = 0
    diagnostics: tuple[ExtractionDiagnostic, ...] = ()


def read_world_text(payload: bytes) -> str:
    """Decode one client script, which is UTF-16 when it carries a byte-order mark."""

    if payload[:2] in UTF16_BYTE_ORDER_MARKS:
        return payload.decode("utf-16")
    for encoding in WORLD_TEXT_FALLBACK_ENCODINGS:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise WorldExtractionError("A client world script used an unsupported text encoding.")


def parse_world_script(text: str) -> WorldDimensions:
    """Return the region extent and terrain scale stated by one ``.wld`` script."""

    blocks_x: int | None = None
    blocks_z: int | None = None
    meters_per_unit = DEFAULT_METERS_PER_UNIT
    for line in text.splitlines():
        fields = line.replace(",", " ").split()
        if not fields:
            continue
        directive = fields[0].lstrip("﻿")
        if directive == WORLD_SIZE_DIRECTIVE and len(fields) >= 3:
            blocks_x = _parse_integer(fields[1], "world size")
            blocks_z = _parse_integer(fields[2], "world size")
        elif directive == WORLD_METERS_PER_UNIT_DIRECTIVE and len(fields) >= 2:
            meters_per_unit = _parse_number(fields[1], "meters per unit")
    if blocks_x is None or blocks_z is None:
        raise WorldExtractionError("A world script must declare its size.")
    return WorldDimensions(blocks_x, blocks_z, meters_per_unit)


def parse_region_script(
    text: str, monster_names: Mapping[int, str] | None = None
) -> tuple[VectorSpawnZone, ...]:
    """Return every monster respawn zone declared by one ``.rgn`` script.

    Records of any other kind — item drops, region triggers, titles — carry no monster and
    are skipped rather than reported as malformed.
    """

    names = monster_names or {}
    zones: list[VectorSpawnZone] = []
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0].lstrip("﻿") != RESPAWN_DIRECTIVE:
            continue
        if len(fields) < RESPAWN_MINIMUM_FIELDS:
            raise WorldExtractionError("A respawn record is missing its geometry fields.")
        if fields[RESPAWN_FIELD_KIND] != RESPAWN_MONSTER_KIND:
            continue
        monster_id = _parse_integer(fields[RESPAWN_FIELD_MONSTER_ID], "monster id")
        minimum_x = _parse_number(fields[RESPAWN_FIELD_MINIMUM_X], "zone bounds")
        minimum_z = _parse_number(fields[RESPAWN_FIELD_MINIMUM_Z], "zone bounds")
        maximum_x = _parse_number(fields[RESPAWN_FIELD_MAXIMUM_X], "zone bounds")
        maximum_z = _parse_number(fields[RESPAWN_FIELD_MAXIMUM_Z], "zone bounds")
        zones.append(
            VectorSpawnZone(
                monster_id=monster_id,
                center_x=_parse_number(fields[RESPAWN_FIELD_CENTER_X], "zone centre"),
                center_y=_parse_number(fields[RESPAWN_FIELD_CENTER_Y], "zone centre"),
                center_z=_parse_number(fields[RESPAWN_FIELD_CENTER_Z], "zone centre"),
                minimum_x=min(minimum_x, maximum_x),
                minimum_z=min(minimum_z, maximum_z),
                maximum_x=max(minimum_x, maximum_x),
                maximum_z=max(minimum_z, maximum_z),
                capacity=_parse_integer(fields[RESPAWN_FIELD_CAPACITY], "zone capacity"),
                respawn_seconds=_parse_integer(
                    fields[RESPAWN_FIELD_RESPAWN_SECONDS], "respawn seconds"
                ),
                monster_name=names.get(monster_id),
            )
        )
    return tuple(zones)


def decode_land_block(payload: bytes) -> LandBlock:
    """Return the block coordinates and height grid stored in one ``.lnd`` file."""

    if len(payload) < LAND_BLOCK_HEADER_BYTES:
        raise WorldExtractionError("A terrain block is too short to carry a header.")
    version, block_x, block_z = struct.unpack_from("<3i", payload, 0)
    if version != SUPPORTED_LAND_BLOCK_VERSION:
        raise WorldExtractionError(f"Unsupported terrain block version: {version}.")
    if block_x < 0 or block_z < 0:
        raise WorldExtractionError("A terrain block must sit at non-negative block coordinates.")
    if len(payload) < LAND_BLOCK_HEIGHTFIELD_BYTES:
        raise WorldExtractionError("A terrain block is too short to carry its height grid.")
    heights = struct.unpack_from(f"<{LAND_BLOCK_SAMPLE_COUNT}f", payload, LAND_BLOCK_HEADER_BYTES)
    return LandBlock(block_x, block_z, heights)


def land_block_file_name(world_name: str, block_x: int, block_z: int) -> str:
    """Return the client's own file name for one terrain block of one region."""

    return LAND_BLOCK_NAME_TEMPLATE.format(
        world=world_name, block_x=block_x, block_z=block_z, suffix=LAND_BLOCK_SUFFIX
    )


def land_block_obstacles(
    block: LandBlock,
    dimensions: WorldDimensions,
    *,
    maximum_gradient: float = IMPASSABLE_SLOPE_GRADIENT,
) -> tuple[ObstacleRectangle, ...]:
    """Return the impassable terrain of one block as maximal axis-aligned rectangles.

    A quad is impassable when the steepest rise between two of its adjacent corners exceeds
    the walkable gradient. Contiguous impassable quads are merged greedily into whole
    rectangles, because the planner only ever needs their outer corners and a raster of
    single quads would give it thousands of redundant ones.
    """

    if maximum_gradient <= 0.0:
        raise WorldExtractionError("The walkable slope gradient must be positive.")
    span = dimensions.meters_per_unit
    cells = LAND_BLOCK_CELLS_PER_SIDE
    blocked = [
        [_quad_gradient(block, column, row, span) > maximum_gradient for column in range(cells)]
        for row in range(cells)
    ]
    origin_x = block.block_x * dimensions.block_span_units
    origin_z = block.block_z * dimensions.block_span_units
    rectangles: list[ObstacleRectangle] = []
    for row in range(cells):
        column = 0
        while column < cells:
            if not blocked[row][column]:
                column += 1
                continue
            last_column = column
            while last_column + 1 < cells and blocked[row][last_column + 1]:
                last_column += 1
            last_row = row
            while last_row + 1 < cells and all(
                blocked[last_row + 1][index] for index in range(column, last_column + 1)
            ):
                last_row += 1
            for claimed_row in range(row, last_row + 1):
                for claimed_column in range(column, last_column + 1):
                    blocked[claimed_row][claimed_column] = False
            rectangles.append(
                ObstacleRectangle(
                    origin_x + column * span,
                    origin_z + row * span,
                    origin_x + (last_column + 1) * span,
                    origin_z + (last_row + 1) * span,
                    ObstacleKind.SLOPE,
                )
            )
            column = last_column + 1
    return tuple(rectangles)


def parse_dynamic_objects(
    payload: bytes,
    dimensions: WorldDimensions,
    *,
    radius_units: float = DEFAULT_DYNAMIC_OBJECT_RADIUS_UNITS,
) -> tuple[ObstacleRectangle, ...]:
    """Return the square footprints of the static objects placed by one ``.dyo`` file.

    No collision hull is stored with a placement, so each object contributes one square of
    the configured radius around its position. A record whose position falls outside the
    region is discarded: it is the clearest available evidence that the offsets read here do
    not describe this file's layout, and inventing a no-go area from it would be worse than
    ignoring it.
    """

    if radius_units <= 0.0:
        raise WorldExtractionError("A placed object's footprint radius must be positive.")
    if len(payload) < DYNAMIC_OBJECT_HEADER_BYTES:
        raise WorldExtractionError("A dynamic-object file is too short to carry a header.")
    body = payload[DYNAMIC_OBJECT_HEADER_BYTES:]
    if len(body) % DYNAMIC_OBJECT_RECORD_BYTES != 0:
        raise WorldExtractionError("A dynamic-object file does not divide into whole records.")
    footprints: list[ObstacleRectangle] = []
    for offset in range(0, len(body), DYNAMIC_OBJECT_RECORD_BYTES):
        x, _y, z = struct.unpack_from("<3f", body, offset + DYNAMIC_OBJECT_POSITION_OFFSET)
        position = WorldCoordinate(x, z)
        if not dimensions.contains(position):
            continue
        footprints.append(
            ObstacleRectangle(
                position.x - radius_units,
                position.z - radius_units,
                position.x + radius_units,
                position.z + radius_units,
                ObstacleKind.OBJECT,
            )
        )
    return tuple(footprints)


def dynamic_object_model_names(payload: bytes) -> tuple[str, ...]:
    """Return the model name of every placed object, in file order."""

    body = payload[DYNAMIC_OBJECT_HEADER_BYTES:]
    if len(body) % DYNAMIC_OBJECT_RECORD_BYTES != 0:
        raise WorldExtractionError("A dynamic-object file does not divide into whole records.")
    names: list[str] = []
    for offset in range(0, len(body), DYNAMIC_OBJECT_RECORD_BYTES):
        start = offset + DYNAMIC_OBJECT_MODEL_NAME_OFFSET
        raw = body[start : start + DYNAMIC_OBJECT_MODEL_NAME_BYTES]
        names.append(raw.split(b"\x00", 1)[0].decode("cp1252", errors="replace"))
    return tuple(names)


def dynamic_object_placements(payload: bytes) -> tuple[tuple[str, WorldCoordinate], ...]:
    """Return every named client placement with its authoritative world position."""

    body = payload[DYNAMIC_OBJECT_HEADER_BYTES:]
    if len(body) % DYNAMIC_OBJECT_RECORD_BYTES != 0:
        raise WorldExtractionError("A dynamic-object file does not divide into whole records.")
    placements: list[tuple[str, WorldCoordinate]] = []
    for offset in range(0, len(body), DYNAMIC_OBJECT_RECORD_BYTES):
        x, _y, z = struct.unpack_from("<3f", body, offset + DYNAMIC_OBJECT_POSITION_OFFSET)
        start = offset + DYNAMIC_OBJECT_MODEL_NAME_OFFSET
        raw = body[start : start + DYNAMIC_OBJECT_MODEL_NAME_BYTES]
        name = raw.split(b"\x00", 1)[0].decode("cp1252", errors="replace")
        placements.append((name, WorldCoordinate(x, z)))
    return tuple(placements)


def load_monster_names(path: Path) -> dict[int, str]:
    """Return the monster-id to detector-class mapping stored at one JSON path."""

    payload: object = json.loads(path.read_text(encoding="utf-8"))
    document = _mapping(payload, "monster name table")
    names: dict[int, str] = {}
    for key, value in document.items():
        if not isinstance(value, str) or not value:
            raise WorldExtractionError("A monster name table maps ids to non-empty names.")
        names[_parse_integer(key, "monster id")] = value
    return names


def discover_world_directories(root: Path) -> tuple[Path, ...]:
    """Return every client region directory under one world root, sorted by name."""

    if not root.is_dir():
        return ()
    regions = [
        candidate
        for candidate in root.iterdir()
        if candidate.is_dir() and _world_script_path(candidate) is not None
    ]
    return tuple(sorted(regions, key=lambda path: path.name.lower()))


def extract_world(
    world_directory: Path,
    *,
    monster_names: Mapping[int, str] | None = None,
    diagnostics: MutableSequence[ExtractionDiagnostic] | None = None,
) -> WorldVectorMap:
    """Extract the vector spawn zones and passability geometry of one client region.

    Terrain comes from two places. A block a patch has left loose on disk is authoritative
    and is read first; every remaining block declared by the ``.wld`` grid is read out of
    the region's packed archive. Anything the archive cannot deliver is appended to
    ``diagnostics`` and skipped, so one unreadable block never costs the whole region.

    The map is named after the region *directory* rather than its world script, because
    several regions ship a script of the same name - the seasonal Madrigal variants all
    declare ``wdmadrigal`` - and a shared name would have them overwrite each other's
    extracted map.
    """

    script_path = _world_script_path(world_directory)
    if script_path is None:
        raise WorldExtractionError(f"No world script was found in {world_directory.name}.")
    dimensions = parse_world_script(read_world_text(script_path.read_bytes()))
    zones: tuple[VectorSpawnZone, ...] = ()
    region_path = _first_file(world_directory, REGION_SCRIPT_SUFFIX)
    if region_path is not None:
        zones = parse_region_script(read_world_text(region_path.read_bytes()), monster_names)
    blocks: dict[tuple[int, int], LandBlock] = {}
    for block_path in _files(world_directory, LAND_BLOCK_SUFFIX):
        block = decode_land_block(block_path.read_bytes())
        blocks[(block.block_x, block.block_z)] = block
    reported: MutableSequence[ExtractionDiagnostic] = diagnostics if diagnostics is not None else []
    blocks.update(
        _archive_land_blocks(
            world_directory,
            dimensions,
            already_loaded=frozenset(blocks),
            diagnostics=reported,
        )
    )
    terrain_blocks = tuple(blocks[key] for key in sorted(blocks))
    obstacles: list[ObstacleRectangle] = []
    for block in terrain_blocks:
        obstacles.extend(land_block_obstacles(block, dimensions))
    object_path = _first_file(world_directory, DYNAMIC_OBJECT_SUFFIX)
    if object_path is not None:
        try:
            obstacles.extend(parse_dynamic_objects(object_path.read_bytes(), dimensions))
        except WorldExtractionError:
            # A handful of shipped `.dyo` files use a record layout this reader does not
            # know. Losing their prop footprints costs clearance margin the stall detector
            # still covers; losing the region's whole height field would cost far more.
            reported.append(
                ExtractionDiagnostic(ExtractionWarning.UNREADABLE_OBJECT_FILE, object_path.name)
            )
    return WorldVectorMap(
        world_name=world_directory.name,
        dimensions=dimensions,
        zones=zones,
        obstacles=tuple(obstacles),
        terrain_blocks=terrain_blocks,
    )


def _archive_land_blocks(
    world_directory: Path,
    dimensions: WorldDimensions,
    *,
    already_loaded: frozenset[tuple[int, int]],
    diagnostics: MutableSequence[ExtractionDiagnostic],
) -> dict[tuple[int, int], LandBlock]:
    """Return every declared terrain block the region's packed archive still holds."""

    try:
        archive = ClientWorldArchive.find(world_directory)
    except ClientArchiveError:
        diagnostics.append(
            ExtractionDiagnostic(ExtractionWarning.UNSUPPORTED_ARCHIVE_INDEX, world_directory.name)
        )
        return {}
    if archive is None:
        return {}
    blocks: dict[tuple[int, int], LandBlock] = {}
    with archive:
        for block_x in range(dimensions.blocks_x):
            for block_z in range(dimensions.blocks_z):
                if (block_x, block_z) in already_loaded:
                    continue
                name = land_block_file_name(archive.world_stem, block_x, block_z)
                prefix = encode_archive_payload(
                    struct.pack("<3i", SUPPORTED_LAND_BLOCK_VERSION, block_x, block_z),
                    name,
                )
                try:
                    payload = archive.read(name, prefix)
                except ClientArchiveError:
                    diagnostics.append(
                        ExtractionDiagnostic(ExtractionWarning.UNREADABLE_ARCHIVE_BLOCK, name)
                    )
                    continue
                if payload is None:
                    continue
                try:
                    blocks[(block_x, block_z)] = decode_land_block(payload)
                except WorldExtractionError:
                    diagnostics.append(
                        ExtractionDiagnostic(ExtractionWarning.UNREADABLE_ARCHIVE_BLOCK, name)
                    )
    return blocks


def world_map_path(directory: Path, world_name: str) -> Path:
    """Return the file one region's extracted map is stored at."""

    return directory / f"{world_name.lower()}.json"


def world_terrain_directory(directory: Path, world_name: str) -> Path:
    """Return the directory one region's extracted ``.lnd`` height fields are stored in."""

    return directory / world_name.lower()


def save_world_map(world_map: WorldVectorMap, directory: Path) -> Path:
    """Write one extracted map and return the path of its JSON document.

    Zones and obstacles go into the JSON. Height fields do not: a region can declare
    hundreds of blocks, so each one is written beside the document as a plain ``.lnd``
    height field in the client's own byte layout. The terrain directory is this function's
    own output namespace, so its ``.lnd`` files are replaced wholesale rather than merged
    with the blocks of an earlier, larger extraction.
    """

    directory.mkdir(parents=True, exist_ok=True)
    terrain_directory = world_terrain_directory(directory, world_map.world_name)
    terrain_directory.mkdir(parents=True, exist_ok=True)
    for stale in _files(terrain_directory, LAND_BLOCK_SUFFIX):
        stale.unlink()
    for block in world_map.terrain_blocks:
        name = land_block_file_name(world_map.world_name.lower(), block.block_x, block.block_z)
        (terrain_directory / name).write_bytes(block.to_bytes())
    target = world_map_path(directory, world_map.world_name)
    target.write_text(
        json.dumps(world_map.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return target


def load_world_map(path: Path) -> WorldVectorMap:
    """Read one extracted map and its ``.lnd`` height fields from disk."""

    document: object = json.loads(path.read_text(encoding="utf-8"))
    world_map = WorldVectorMap.from_dict(document)
    terrain_directory = world_terrain_directory(path.parent, world_map.world_name)
    if not terrain_directory.is_dir():
        return world_map
    blocks = [
        decode_land_block(block_path.read_bytes())
        for block_path in _files(terrain_directory, LAND_BLOCK_SUFFIX)
    ]
    return WorldVectorMap.from_dict(document, sorted(blocks, key=_block_order))


def _block_order(block: LandBlock) -> tuple[int, int]:
    return block.block_x, block.block_z


def _quad_gradient(block: LandBlock, column: int, row: int, span: float) -> float:
    """Return the steepest rise-over-run between adjacent corners of one terrain quad."""

    lower_left = block.height(column, row)
    lower_right = block.height(column + 1, row)
    upper_left = block.height(column, row + 1)
    upper_right = block.height(column + 1, row + 1)
    steepest = max(
        abs(lower_left - lower_right),
        abs(upper_left - upper_right),
        abs(lower_left - upper_left),
        abs(lower_right - upper_right),
    )
    return steepest / span


def _world_script_path(directory: Path) -> Path | None:
    return _first_file(directory, WORLD_SCRIPT_SUFFIX)


def _files(directory: Path, suffix: str) -> tuple[Path, ...]:
    matches = [
        candidate
        for candidate in directory.iterdir()
        if candidate.is_file() and candidate.suffix.lower() == suffix
    ]
    return tuple(sorted(matches, key=lambda path: path.name.lower()))


def _first_file(directory: Path, suffix: str) -> Path | None:
    matches = _files(directory, suffix)
    return matches[0] if matches else None


def _parse_integer(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise WorldExtractionError(f"A client world file's {label} must be an integer.") from error


def _parse_number(value: str, label: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise WorldExtractionError(f"A client world file's {label} must be a number.") from error


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorldExtractionError(f"Persisted {label} must be an object.")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise WorldExtractionError(f"Persisted {label} must be a list.")
    return tuple(value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise WorldExtractionError(f"Persisted {label} must be an integer.")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise WorldExtractionError(f"Persisted {label} must be a number.")
    return float(value)


def _numbers(value: object, label: str, count: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != count:
        raise WorldExtractionError(f"Persisted {label} must be {count} numbers.")
    return tuple(_number(entry, label) for entry in value)


def summarize(
    world_map: WorldVectorMap,
    output_path: Path,
    diagnostics: Iterable[ExtractionDiagnostic] = (),
) -> WorldExtractionSummary:
    """Return the operator-facing summary of one completed extraction."""

    return WorldExtractionSummary(
        world_name=world_map.world_name,
        zone_count=len(world_map.zones),
        obstacle_count=len(world_map.obstacles),
        terrain_block_count=world_map.terrain_block_count,
        monster_names=world_map.monster_names,
        output_path=output_path,
        declared_block_count=world_map.dimensions.blocks_x * world_map.dimensions.blocks_z,
        diagnostics=tuple(diagnostics),
    )


def zone_monster_ids(zones: Iterable[VectorSpawnZone]) -> tuple[int, ...]:
    """Return every distinct monster id present in a set of zones, ascending."""

    return tuple(sorted({zone.monster_id for zone in zones}))


def nearest_zone(
    zones: Sequence[VectorSpawnZone], point: WorldCoordinate
) -> VectorSpawnZone | None:
    """Return the zone whose anchor lies closest to a position, or ``None`` for none."""

    if not zones:
        return None
    return min(
        zones,
        key=lambda zone: math.hypot(zone.anchor.x - point.x, zone.anchor.z - point.z),
    )
