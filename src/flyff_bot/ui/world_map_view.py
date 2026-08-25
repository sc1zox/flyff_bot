"""Pure viewport transforms and spatial culling for the interactive world map."""

from __future__ import annotations

import math
from dataclasses import dataclass

from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshPolygon
from flyff_bot.features.navigation.world_extractor import (
    LandBlock,
    VectorSpawnZone,
    WorldCoordinate,
    WorldVectorMap,
)

DEFAULT_MINIMUM_MAP_SCALE = 0.005
DEFAULT_MAXIMUM_MAP_SCALE = 20.0
DEFAULT_WHEEL_ZOOM_FACTOR = 1.2
DEFAULT_VIEW_PADDING_FRACTION = 0.08


@dataclass(frozen=True, slots=True)
class ScreenPoint:
    """One point in widget-local logical pixels."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class WorldBounds:
    """An axis-aligned X/Z rectangle in client world units."""

    minimum_x: float
    minimum_z: float
    maximum_x: float
    maximum_z: float

    def intersects(self, other: WorldBounds) -> bool:
        """Return whether this rectangle overlaps another, including shared edges."""

        return not (
            self.maximum_x < other.minimum_x
            or self.minimum_x > other.maximum_x
            or self.maximum_z < other.minimum_z
            or self.minimum_z > other.maximum_z
        )

    def contains(self, point: WorldCoordinate) -> bool:
        """Return whether a world point lies inside the rectangle."""

        return (
            self.minimum_x <= point.x <= self.maximum_x
            and self.minimum_z <= point.z <= self.maximum_z
        )


@dataclass(frozen=True, slots=True)
class ViewportLimits:
    """Bounded scale and wheel sensitivity for one interactive viewport."""

    minimum_scale: float = DEFAULT_MINIMUM_MAP_SCALE
    maximum_scale: float = DEFAULT_MAXIMUM_MAP_SCALE
    wheel_zoom_factor: float = DEFAULT_WHEEL_ZOOM_FACTOR

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.minimum_scale)
            or not math.isfinite(self.maximum_scale)
            or self.minimum_scale <= 0.0
            or self.maximum_scale < self.minimum_scale
        ):
            raise ValueError("Map scale limits must be finite, positive, and ordered.")
        if not math.isfinite(self.wheel_zoom_factor) or self.wheel_zoom_factor <= 1.0:
            raise ValueError("Map wheel zoom factor must be finite and greater than one.")


@dataclass(slots=True)
class ViewportTransform:
    """Persistent north-up mapping between client X/Z and widget-local pixels."""

    center_x: float
    center_z: float
    scale: float
    width: int
    height: int
    limits: ViewportLimits = ViewportLimits()

    def __post_init__(self) -> None:
        self.scale = self._clamp_scale(self.scale)
        self.resize(self.width, self.height)

    def resize(self, width: int, height: int) -> None:
        """Adopt a positive drawable size without changing the world-space centre."""

        self.width = max(1, width)
        self.height = max(1, height)

    def world_to_screen(self, point: WorldCoordinate) -> ScreenPoint:
        """Map a world X/Z point to widget-local logical pixels."""

        return ScreenPoint(
            self.width / 2.0 + (point.x - self.center_x) * self.scale,
            self.height / 2.0 - (point.z - self.center_z) * self.scale,
        )

    def screen_to_world(self, point: ScreenPoint) -> WorldCoordinate:
        """Map widget-local logical pixels back to client X/Z world units."""

        return WorldCoordinate(
            self.center_x + (point.x - self.width / 2.0) / self.scale,
            self.center_z - (point.y - self.height / 2.0) / self.scale,
        )

    def pan_by_pixels(self, delta_x: float, delta_y: float) -> None:
        """Translate the view by a screen-space drag delta."""

        self.center_x -= delta_x / self.scale
        self.center_z += delta_y / self.scale

    def zoom_at(self, factor: float, cursor: ScreenPoint) -> None:
        """Scale around a cursor while preserving the world point beneath it."""

        if not math.isfinite(factor) or factor <= 0.0:
            return
        before = self.screen_to_world(cursor)
        self.scale = self._clamp_scale(self.scale * factor)
        after = self.screen_to_world(cursor)
        self.center_x += before.x - after.x
        self.center_z += before.z - after.z

    def fit(
        self,
        bounds: WorldBounds,
        padding_fraction: float = DEFAULT_VIEW_PADDING_FRACTION,
    ) -> None:
        """Fit a world rectangle inside the current widget dimensions."""

        padding = min(max(padding_fraction, 0.0), 0.45)
        available_width = self.width * (1.0 - 2.0 * padding)
        available_height = self.height * (1.0 - 2.0 * padding)
        span_x = max(bounds.maximum_x - bounds.minimum_x, 1.0)
        span_z = max(bounds.maximum_z - bounds.minimum_z, 1.0)
        self.center_x = (bounds.minimum_x + bounds.maximum_x) / 2.0
        self.center_z = (bounds.minimum_z + bounds.maximum_z) / 2.0
        self.scale = self._clamp_scale(min(available_width / span_x, available_height / span_z))

    @property
    def visible_world_bounds(self) -> WorldBounds:
        """Return the world-space rectangle currently visible in the widget."""

        top_left = self.screen_to_world(ScreenPoint(0.0, 0.0))
        bottom_right = self.screen_to_world(ScreenPoint(float(self.width), float(self.height)))
        return WorldBounds(
            top_left.x,
            bottom_right.z,
            bottom_right.x,
            top_left.z,
        )

    def _clamp_scale(self, value: float) -> float:
        return max(self.limits.minimum_scale, min(self.limits.maximum_scale, value))


class WorldMapScene:
    """Immutable extracted-map scene with block-sized spatial buckets for culling."""

    def __init__(self, world_map: WorldVectorMap, navmesh: BakedNavMesh | None = None) -> None:
        self.world_map = world_map
        self.navmesh = navmesh
        self._tile_span = world_map.dimensions.block_span_units
        self._terrain_by_tile = {
            (block.block_x, block.block_z): block for block in world_map.terrain_blocks
        }
        self._zone_bounds = tuple(_zone_bounds(zone) for zone in world_map.zones)
        self._zones_by_tile = self._bucket_bounds(self._zone_bounds)
        polygons = () if navmesh is None else navmesh.polygons
        self._polygons = polygons
        self._polygon_bounds = tuple(_polygon_bounds(polygon) for polygon in polygons)
        self._polygons_by_tile = self._bucket_bounds(self._polygon_bounds)

    @property
    def world_bounds(self) -> WorldBounds:
        """Return the full declared extent of the extracted region."""

        dimensions = self.world_map.dimensions
        return WorldBounds(0.0, 0.0, dimensions.width_units, dimensions.depth_units)

    def visible_tile_keys(self, bounds: WorldBounds) -> tuple[tuple[int, int], ...]:
        """Return stable block keys overlapped by a visible world rectangle."""

        minimum_x = math.floor(bounds.minimum_x / self._tile_span)
        maximum_x = math.floor(bounds.maximum_x / self._tile_span)
        minimum_z = math.floor(bounds.minimum_z / self._tile_span)
        maximum_z = math.floor(bounds.maximum_z / self._tile_span)
        return tuple(
            (tile_x, tile_z)
            for tile_x in range(minimum_x, maximum_x + 1)
            for tile_z in range(minimum_z, maximum_z + 1)
        )

    def visible_terrain_blocks(self, bounds: WorldBounds) -> tuple[LandBlock, ...]:
        """Return only terrain heightfields intersecting the visible frustum."""

        return tuple(
            block
            for key in self.visible_tile_keys(bounds)
            if (block := self._terrain_by_tile.get(key)) is not None
        )

    def visible_zones(self, bounds: WorldBounds) -> tuple[VectorSpawnZone, ...]:
        """Return only respawn zones whose authoritative bounds touch the viewport."""

        indexes = self._visible_indexes(bounds, self._zones_by_tile, self._zone_bounds)
        return tuple(self.world_map.zones[index] for index in indexes)

    def visible_navmesh_polygons(self, bounds: WorldBounds) -> tuple[NavMeshPolygon, ...]:
        """Return only passable NavMesh triangles whose X/Z bounds touch the viewport."""

        indexes = self._visible_indexes(bounds, self._polygons_by_tile, self._polygon_bounds)
        return tuple(self._polygons[index] for index in indexes)

    def zone_at(self, point: WorldCoordinate) -> VectorSpawnZone | None:
        """Return the smallest containing spawn zone for deterministic hover/click hit-testing."""

        key = self._tile_key(point.x, point.z)
        candidates = self._zones_by_tile.get(key, ())
        containing = [index for index in candidates if self._zone_bounds[index].contains(point)]
        if not containing:
            return None
        selected = min(
            containing,
            key=lambda index: (
                _bounds_area(self._zone_bounds[index]),
                index,
            ),
        )
        return self.world_map.zones[selected]

    def _bucket_bounds(
        self, bounds_items: tuple[WorldBounds, ...]
    ) -> dict[tuple[int, int], tuple[int, ...]]:
        mutable: dict[tuple[int, int], list[int]] = {}
        for index, bounds in enumerate(bounds_items):
            for key in self.visible_tile_keys(bounds):
                mutable.setdefault(key, []).append(index)
        return {key: tuple(indexes) for key, indexes in mutable.items()}

    def _visible_indexes(
        self,
        bounds: WorldBounds,
        buckets: dict[tuple[int, int], tuple[int, ...]],
        item_bounds: tuple[WorldBounds, ...],
    ) -> tuple[int, ...]:
        candidates = {
            index for key in self.visible_tile_keys(bounds) for index in buckets.get(key, ())
        }
        return tuple(index for index in sorted(candidates) if item_bounds[index].intersects(bounds))

    def _tile_key(self, x: float, z: float) -> tuple[int, int]:
        return math.floor(x / self._tile_span), math.floor(z / self._tile_span)


def _zone_bounds(zone: VectorSpawnZone) -> WorldBounds:
    return WorldBounds(zone.minimum_x, zone.minimum_z, zone.maximum_x, zone.maximum_z)


def _polygon_bounds(polygon: NavMeshPolygon) -> WorldBounds:
    vertices = polygon.triangle.first, polygon.triangle.second, polygon.triangle.third
    return WorldBounds(
        min(vertex.x for vertex in vertices),
        min(vertex.z for vertex in vertices),
        max(vertex.x for vertex in vertices),
        max(vertex.z for vertex in vertices),
    )


def _bounds_area(bounds: WorldBounds) -> float:
    return (bounds.maximum_x - bounds.minimum_x) * (bounds.maximum_z - bounds.minimum_z)
