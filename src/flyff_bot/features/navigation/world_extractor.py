"""Offline extraction of vector spawn zones and terrain passability from client world files.

The Flyff client ships each region as a directory of small, unencrypted description files
next to one packed ``.one`` archive. Everything this module reads is a loose file: the world
script (``.wld``) states the map dimensions, the region script (``.rgn``) lists the monster
respawn zones, each terrain block (``.lnd``) carries a raw float32 height grid, and the
dynamic-object file (``.dyo``) places props. The packed archive is obfuscated and is
deliberately not touched (US-045), so a region whose terrain blocks live only inside it
extracts its spawn zones and no passability geometry.

Reading is strictly offline file I/O: no game process is opened, read, or written.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

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

WORLD_VECTOR_MAP_SCHEMA_VERSION = 1


class WorldExtractionError(ValueError):
    """Raised when a client world file cannot be read as the format it claims to be."""


class ObstacleKind(StrEnum):
    """Why a rectangle of world ground may not be walked through."""

    # A terrain quad whose slope exceeds the walkable gradient.
    SLOPE = "slope"
    # The footprint of a placed static object.
    OBJECT = "object"


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


@dataclass(frozen=True, slots=True)
class WorldVectorMap:
    """The extracted vector description of one region: its zones and its no-go geometry."""

    world_name: str
    dimensions: WorldDimensions
    zones: tuple[VectorSpawnZone, ...] = ()
    obstacles: tuple[ObstacleRectangle, ...] = ()
    terrain_block_count: int = 0

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
            "terrain_block_count": self.terrain_block_count,
            "zones": [zone.to_dict() for zone in self.zones],
            "obstacles": [obstacle.to_dict() for obstacle in self.obstacles],
        }

    @classmethod
    def from_dict(cls, payload: object) -> WorldVectorMap:
        """Rebuild an extracted map, raising ``WorldExtractionError`` for anything unusable."""

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
            terrain_block_count=_integer(
                document.get("terrain_block_count"), "terrain block count"
            ),
        )


@dataclass(frozen=True, slots=True)
class WorldExtractionSummary:
    """What one extraction produced, as the operator-facing dialog reports it."""

    world_name: str
    zone_count: int
    obstacle_count: int
    terrain_block_count: int
    monster_names: tuple[str, ...]
    output_path: Path


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
    sample_count = LAND_BLOCK_VERTICES_PER_SIDE * LAND_BLOCK_VERTICES_PER_SIDE
    required = LAND_BLOCK_HEADER_BYTES + sample_count * FLOAT32_BYTES
    if len(payload) < required:
        raise WorldExtractionError("A terrain block is too short to carry its height grid.")
    heights = struct.unpack_from(f"<{sample_count}f", payload, LAND_BLOCK_HEADER_BYTES)
    return LandBlock(block_x, block_z, heights)


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
    world_directory: Path, *, monster_names: Mapping[int, str] | None = None
) -> WorldVectorMap:
    """Extract the vector spawn zones and passability geometry of one client region."""

    script_path = _world_script_path(world_directory)
    if script_path is None:
        raise WorldExtractionError(f"No world script was found in {world_directory.name}.")
    dimensions = parse_world_script(read_world_text(script_path.read_bytes()))
    zones: tuple[VectorSpawnZone, ...] = ()
    region_path = _first_file(world_directory, REGION_SCRIPT_SUFFIX)
    if region_path is not None:
        zones = parse_region_script(read_world_text(region_path.read_bytes()), monster_names)
    obstacles: list[ObstacleRectangle] = []
    block_count = 0
    for block_path in _files(world_directory, LAND_BLOCK_SUFFIX):
        block = decode_land_block(block_path.read_bytes())
        obstacles.extend(land_block_obstacles(block, dimensions))
        block_count += 1
    object_path = _first_file(world_directory, DYNAMIC_OBJECT_SUFFIX)
    if object_path is not None:
        obstacles.extend(parse_dynamic_objects(object_path.read_bytes(), dimensions))
    return WorldVectorMap(
        world_name=script_path.stem,
        dimensions=dimensions,
        zones=zones,
        obstacles=tuple(obstacles),
        terrain_block_count=block_count,
    )


def world_map_path(directory: Path, world_name: str) -> Path:
    """Return the file one region's extracted map is stored at."""

    return directory / f"{world_name.lower()}.json"


def save_world_map(world_map: WorldVectorMap, directory: Path) -> Path:
    """Write one extracted map as JSON and return the path it was written to."""

    directory.mkdir(parents=True, exist_ok=True)
    target = world_map_path(directory, world_map.world_name)
    target.write_text(
        json.dumps(world_map.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return target


def load_world_map(path: Path) -> WorldVectorMap:
    """Read one extracted map from disk."""

    return WorldVectorMap.from_dict(json.loads(path.read_text(encoding="utf-8")))


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


def summarize(world_map: WorldVectorMap, output_path: Path) -> WorldExtractionSummary:
    """Return the operator-facing summary of one completed extraction."""

    return WorldExtractionSummary(
        world_name=world_map.world_name,
        zone_count=len(world_map.zones),
        obstacle_count=len(world_map.obstacles),
        terrain_block_count=world_map.terrain_block_count,
        monster_names=world_map.monster_names,
        output_path=output_path,
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
