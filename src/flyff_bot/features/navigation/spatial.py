"""Internal spawn heatmap and traversal graph over a relative navigation grid."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

DEFAULT_CELL_SIZE_UNITS = 15.0
DEFAULT_SPAWN_HALF_LIFE_SECONDS = 600.0
DEFAULT_SPAWN_WEIGHT_PER_SIGHTING = 1.0
DEFAULT_STALL_COST_PENALTY = 3.0
DEFAULT_MAXIMUM_STALL_COST_FACTOR = 12.0
DEFAULT_MAXIMUM_LINK_SPAN_CELLS = 3
SPATIAL_MAP_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class WorldPoint:
    """A continuous position estimated relative to the session start point."""

    x: float
    y: float


@dataclass(frozen=True, slots=True, order=True)
class GridCell:
    """One discrete tile of the relative navigation grid."""

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class CellRecord:
    """Accumulated visit history, spawn weight, and stall history of one cell."""

    visits: int = 0
    stalls: int = 0
    spawn_weight: float = 0.0
    spawn_updated_at_seconds: float = 0.0
    last_visited_at_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class EdgeRecord:
    """Traversal and stall history of one recorded navigation-graph edge."""

    traversals: int = 0
    stalls: int = 0


@dataclass(frozen=True, slots=True)
class SpatialMapConfig:
    """Grid resolution, heatmap decay, and stall-cost policy of one learned map."""

    cell_size_units: float = DEFAULT_CELL_SIZE_UNITS
    spawn_half_life_seconds: float = DEFAULT_SPAWN_HALF_LIFE_SECONDS
    spawn_weight_per_sighting: float = DEFAULT_SPAWN_WEIGHT_PER_SIGHTING
    stall_cost_penalty: float = DEFAULT_STALL_COST_PENALTY
    maximum_stall_cost_factor: float = DEFAULT_MAXIMUM_STALL_COST_FACTOR
    maximum_link_span_cells: int = DEFAULT_MAXIMUM_LINK_SPAN_CELLS

    def __post_init__(self) -> None:
        if self.cell_size_units <= 0.0:
            raise ValueError("Navigation cell size must be positive.")
        if self.spawn_half_life_seconds <= 0.0:
            raise ValueError("Spawn heatmap half-life must be positive.")
        if self.spawn_weight_per_sighting <= 0.0:
            raise ValueError("Spawn weight per sighting must be positive.")
        if self.stall_cost_penalty < 0.0:
            raise ValueError("Stall cost penalty must not be negative.")
        if self.maximum_stall_cost_factor < 1.0:
            raise ValueError("Maximum stall cost factor must be at least one.")
        if self.maximum_link_span_cells <= 0:
            raise ValueError("Maximum navigation link span must be positive.")


class SpatialMap:
    """Accumulate spawn sightings, traversed edges, and stall costs on a relative grid."""

    def __init__(self, config: SpatialMapConfig | None = None) -> None:
        self._config = config or SpatialMapConfig()
        self._cells: dict[GridCell, CellRecord] = {}
        self._edges: dict[tuple[GridCell, GridCell], EdgeRecord] = {}
        self._adjacency: dict[GridCell, set[GridCell]] = {}
        self._last_visited: GridCell | None = None
        self._previous_visited: GridCell | None = None

    @property
    def config(self) -> SpatialMapConfig:
        """Return the grid, decay, and cost policy backing this map."""

        return self._config

    def cell_of(self, point: WorldPoint) -> GridCell:
        """Return the grid cell containing one estimated continuous position."""

        size = self._config.cell_size_units
        return GridCell(math.floor(point.x / size), math.floor(point.y / size))

    def center_of(self, cell: GridCell) -> WorldPoint:
        """Return the continuous centre of one grid cell."""

        size = self._config.cell_size_units
        return WorldPoint((cell.x + 0.5) * size, (cell.y + 0.5) * size)

    def known_cells(self) -> tuple[GridCell, ...]:
        """Return every cell that carries visit, spawn, or stall history."""

        return tuple(sorted(self._cells))

    def visit_count(self, cell: GridCell) -> int:
        """Return how often this cell has been traversed."""

        return self._cells.get(cell, CellRecord()).visits

    def last_visited_at_seconds(self, cell: GridCell) -> float:
        """Return the newest visit timestamp recorded for this cell."""

        return self._cells.get(cell, CellRecord()).last_visited_at_seconds

    def stall_count(self, cell: GridCell) -> int:
        """Return how often movement stalled inside this cell."""

        return self._cells.get(cell, CellRecord()).stalls

    def edge_stall_count(self, origin: GridCell, destination: GridCell) -> int:
        """Return how often movement stalled on the edge between two cells."""

        return self._edges.get(_edge_key(origin, destination), EdgeRecord()).stalls

    def neighbors(self, cell: GridCell) -> tuple[GridCell, ...]:
        """Return the cells reachable through previously traversed edges."""

        return tuple(sorted(self._adjacency.get(cell, set())))

    def record_visit(self, point: WorldPoint, at_seconds: float) -> GridCell:
        """Record one traversal step and link it to the previously visited cell."""

        cell = self.cell_of(point)
        record = self._cells.get(cell, CellRecord())
        self._cells[cell] = replace(
            record, visits=record.visits + 1, last_visited_at_seconds=at_seconds
        )
        previous = self._last_visited
        if previous is not None and previous != cell:
            if self._is_linkable(previous, cell):
                key = _edge_key(previous, cell)
                edge = self._edges.get(key, EdgeRecord())
                self._edges[key] = replace(edge, traversals=edge.traversals + 1)
                self._link(previous, cell)
            self._previous_visited = previous
        self._last_visited = cell
        return cell

    def record_spawn(
        self, point: WorldPoint, at_seconds: float, weight: float | None = None
    ) -> GridCell:
        """Add one decayed spawn sighting to the heatmap cell containing this point."""

        cell = self.cell_of(point)
        record = self._cells.get(cell, CellRecord())
        added = self._config.spawn_weight_per_sighting if weight is None else weight
        self._cells[cell] = replace(
            record,
            spawn_weight=self._decayed_weight(record, at_seconds) + added,
            spawn_updated_at_seconds=at_seconds,
        )
        return cell

    def record_stall(self, point: WorldPoint, at_seconds: float) -> GridCell:
        """Raise the pathing cost of the stalled cell and of the edge that reached it."""

        cell = self.cell_of(point)
        record = self._cells.get(cell, CellRecord())
        self._cells[cell] = replace(
            record, stalls=record.stalls + 1, last_visited_at_seconds=at_seconds
        )
        approach = self._previous_visited if cell == self._last_visited else self._last_visited
        if approach is not None and approach != cell:
            key = _edge_key(approach, cell)
            edge = self._edges.get(key, EdgeRecord())
            self._edges[key] = replace(edge, stalls=edge.stalls + 1)
            self._link(approach, cell)
        return cell

    def spawn_weight(self, cell: GridCell, at_seconds: float) -> float:
        """Return the decayed spawn weight of one cell at the given time."""

        record = self._cells.get(cell)
        if record is None:
            return 0.0
        return self._decayed_weight(record, at_seconds)

    def hotspots(
        self, at_seconds: float, minimum_weight: float
    ) -> tuple[tuple[GridCell, float], ...]:
        """Return decayed spawn clusters at or above a weight, densest first."""

        scored = [
            (cell, weight)
            for cell in self._cells
            if (weight := self.spawn_weight(cell, at_seconds)) >= minimum_weight
        ]
        return tuple(sorted(scored, key=lambda entry: (-entry[1], entry[0])))

    def move_cost(self, origin: GridCell, destination: GridCell) -> float:
        """Return the distance cost of one hop scaled by its accumulated stall risk."""

        stalls = self.edge_stall_count(origin, destination) + self.stall_count(destination)
        factor = min(
            1.0 + self._config.stall_cost_penalty * stalls,
            self._config.maximum_stall_cost_factor,
        )
        return math.hypot(destination.x - origin.x, destination.y - origin.y) * factor

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible snapshot of the learned map."""

        return {
            "version": SPATIAL_MAP_SCHEMA_VERSION,
            "cells": [
                {
                    "x": cell.x,
                    "y": cell.y,
                    "visits": record.visits,
                    "stalls": record.stalls,
                    "spawn_weight": record.spawn_weight,
                    "spawn_updated_at_seconds": record.spawn_updated_at_seconds,
                    "last_visited_at_seconds": record.last_visited_at_seconds,
                }
                for cell, record in sorted(self._cells.items())
            ],
            "edges": [
                {
                    "origin_x": origin.x,
                    "origin_y": origin.y,
                    "destination_x": destination.x,
                    "destination_y": destination.y,
                    "traversals": edge.traversals,
                    "stalls": edge.stalls,
                }
                for (origin, destination), edge in sorted(self._edges.items())
            ],
        }

    @classmethod
    def from_dict(cls, payload: object, config: SpatialMapConfig | None = None) -> SpatialMap:
        """Rebuild a learned map from a persisted snapshot."""

        document = _mapping(payload, "spatial map")
        version = _integer(document.get("version"), "version")
        if version != SPATIAL_MAP_SCHEMA_VERSION:
            msg = f"Unsupported spatial map schema version: {version}."
            raise ValueError(msg)
        spatial_map = cls(config)
        for entry in _sequence(document.get("cells"), "cells"):
            cell_document = _mapping(entry, "cell")
            cell = GridCell(
                _integer(cell_document.get("x"), "cell x"),
                _integer(cell_document.get("y"), "cell y"),
            )
            spatial_map._cells[cell] = CellRecord(
                visits=_integer(cell_document.get("visits"), "visits"),
                stalls=_integer(cell_document.get("stalls"), "stalls"),
                spawn_weight=_number(cell_document.get("spawn_weight"), "spawn weight"),
                spawn_updated_at_seconds=_number(
                    cell_document.get("spawn_updated_at_seconds"), "spawn timestamp"
                ),
                last_visited_at_seconds=_number(
                    cell_document.get("last_visited_at_seconds"), "visit timestamp"
                ),
            )
        for entry in _sequence(document.get("edges"), "edges"):
            edge_document = _mapping(entry, "edge")
            origin = GridCell(
                _integer(edge_document.get("origin_x"), "edge origin x"),
                _integer(edge_document.get("origin_y"), "edge origin y"),
            )
            destination = GridCell(
                _integer(edge_document.get("destination_x"), "edge destination x"),
                _integer(edge_document.get("destination_y"), "edge destination y"),
            )
            spatial_map._edges[_edge_key(origin, destination)] = EdgeRecord(
                traversals=_integer(edge_document.get("traversals"), "traversals"),
                stalls=_integer(edge_document.get("stalls"), "edge stalls"),
            )
            spatial_map._link(origin, destination)
        return spatial_map

    def _decayed_weight(self, record: CellRecord, at_seconds: float) -> float:
        elapsed = at_seconds - record.spawn_updated_at_seconds
        if record.spawn_weight <= 0.0 or elapsed <= 0.0:
            return max(record.spawn_weight, 0.0)
        half_lives = elapsed / self._config.spawn_half_life_seconds
        return record.spawn_weight * math.pow(0.5, half_lives)

    def _is_linkable(self, origin: GridCell, destination: GridCell) -> bool:
        span = max(abs(destination.x - origin.x), abs(destination.y - origin.y))
        return span <= self._config.maximum_link_span_cells

    def _link(self, origin: GridCell, destination: GridCell) -> None:
        self._adjacency.setdefault(origin, set()).add(destination)
        self._adjacency.setdefault(destination, set()).add(origin)


def _edge_key(origin: GridCell, destination: GridCell) -> tuple[GridCell, GridCell]:
    return (origin, destination) if origin <= destination else (destination, origin)


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"Persisted {label} must be an object."
        raise ValueError(msg)
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        msg = f"Persisted {label} must be a list."
        raise ValueError(msg)
    return tuple(value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"Persisted {label} must be an integer."
        raise ValueError(msg)
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"Persisted {label} must be a number."
        raise ValueError(msg)
    return float(value)
