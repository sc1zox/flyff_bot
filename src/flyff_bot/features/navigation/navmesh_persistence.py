"""Strict, offline persistence for deterministic baked navigation meshes."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from flyff_bot.features.navigation.navmesh import (
    NAVMESH_SCHEMA_VERSION,
    AgentNavigationConfig,
    BakedNavMesh,
    NavMeshPolygon,
    SurfaceSpan,
)
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex


class NavMeshPersistenceError(ValueError):
    """Raised when a persisted NavMesh artifact is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class NavMeshArtifact:
    """A loaded or saved mesh with its stable content identity for telemetry metadata."""

    mesh: BakedNavMesh
    path: Path
    content_digest: str


def world_navmesh_path(directory: Path, world_name: str) -> Path:
    """Return the dedicated artifact path for one extracted world region."""

    return directory / f"{world_name.lower()}.navmesh.json"


def save_baked_navmesh(mesh: BakedNavMesh, path: Path) -> NavMeshArtifact:
    """Write a versioned mesh artifact without changing client assets."""

    document = _document(mesh)
    encoded = _encode(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return NavMeshArtifact(mesh, path, _digest(encoded))


def load_baked_navmesh(path: Path) -> NavMeshArtifact:
    """Load one strict schema-v1 mesh artifact without regenerating stable IDs."""

    try:
        encoded = path.read_bytes()
        value: object = json.loads(encoded)
    except (OSError, json.JSONDecodeError) as error:
        raise NavMeshPersistenceError(f"Cannot read NavMesh artifact {path}.") from error
    document = _mapping(value, "NavMesh document")
    if _integer(document.get("schema_version"), "schema_version") != NAVMESH_SCHEMA_VERSION:
        raise NavMeshPersistenceError("Unsupported NavMesh schema version.")
    config_data = _mapping(document.get("config"), "config")
    config = AgentNavigationConfig(
        maximum_walkable_slope_degrees=_number(
            config_data.get("maximum_walkable_slope_degrees"), "maximum_walkable_slope_degrees"
        ),
        agent_radius_units=_number(config_data.get("agent_radius_units"), "agent_radius_units"),
        agent_height_units=_number(config_data.get("agent_height_units"), "agent_height_units"),
        maximum_step_height_units=_number(
            config_data.get("maximum_step_height_units"), "maximum_step_height_units"
        ),
        cell_size_units=_number(config_data.get("cell_size_units"), "cell_size_units"),
    )
    polygons = _polygons(document.get("polygons"))
    adjacency = _adjacency(document.get("adjacency"), polygons)
    spans = _spans(document.get("surface_spans"), polygons, config)
    mesh = BakedNavMesh(polygons, adjacency, spans, config)
    return NavMeshArtifact(mesh, path, _digest(_encode(_document(mesh))))


def _document(mesh: BakedNavMesh) -> dict[str, object]:
    return {
        "schema_version": NAVMESH_SCHEMA_VERSION,
        "config": {
            "maximum_walkable_slope_degrees": mesh.config.maximum_walkable_slope_degrees,
            "agent_radius_units": mesh.config.agent_radius_units,
            "agent_height_units": mesh.config.agent_height_units,
            "maximum_step_height_units": mesh.config.maximum_step_height_units,
            "cell_size_units": mesh.config.cell_size_units,
        },
        "polygons": [
            {
                "polygon_id": polygon.polygon_id,
                "region_id": polygon.region_id,
                "source": polygon.triangle.source,
                "vertices": [
                    [vertex.x, vertex.y, vertex.z]
                    for vertex in (
                        polygon.triangle.first,
                        polygon.triangle.second,
                        polygon.triangle.third,
                    )
                ],
            }
            for polygon in mesh.polygons
        ],
        "adjacency": {str(key): list(value) for key, value in sorted(mesh.adjacency.items())},
        "surface_spans": [
            {
                "cell_x": span.cell_x,
                "cell_z": span.cell_z,
                "polygon_ids": list(span.polygon_ids),
            }
            for span in mesh.surface_spans
        ],
    }


def _encode(document: dict[str, object]) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _digest(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def _polygons(value: object) -> tuple[NavMeshPolygon, ...]:
    entries = _sequence(value, "polygons")
    polygons: list[NavMeshPolygon] = []
    for index, entry in enumerate(entries, start=1):
        data = _mapping(entry, "polygon")
        polygon_id = _integer(data.get("polygon_id"), "polygon_id")
        if polygon_id != index:
            raise NavMeshPersistenceError("NavMesh polygon IDs must be contiguous and ordered.")
        region_id = _integer(data.get("region_id"), "region_id")
        if region_id <= 0:
            raise NavMeshPersistenceError("NavMesh region IDs must be positive.")
        source = data.get("source")
        if not isinstance(source, str):
            raise NavMeshPersistenceError("NavMesh polygon source must be a string.")
        vertices = _sequence(data.get("vertices"), "vertices")
        if len(vertices) != 3:
            raise NavMeshPersistenceError("NavMesh polygons must have exactly three vertices.")
        triangle = WorldTriangle(*(_vertex(item) for item in vertices), source)
        polygons.append(NavMeshPolygon(polygon_id, region_id, triangle))
    return tuple(polygons)


def _adjacency(value: object, polygons: tuple[NavMeshPolygon, ...]) -> dict[int, tuple[int, ...]]:
    data = _mapping(value, "adjacency")
    ids = {polygon.polygon_id for polygon in polygons}
    if {int(key) for key in data} != ids:
        raise NavMeshPersistenceError("NavMesh adjacency must cover every polygon exactly once.")
    adjacency: dict[int, tuple[int, ...]] = {}
    for raw_key, raw_neighbours in data.items():
        polygon_id = _integer_from_string(raw_key, "adjacency polygon ID")
        neighbours = tuple(_integer(item, "adjacent polygon ID") for item in _sequence(raw_neighbours, "adjacency neighbours"))
        if neighbours != tuple(sorted(set(neighbours))) or polygon_id in neighbours or not set(neighbours) <= ids:
            raise NavMeshPersistenceError("NavMesh adjacency must be sorted, distinct, and in range.")
        adjacency[polygon_id] = neighbours
    if any(polygon_id not in adjacency[neighbour] for polygon_id, neighbours in adjacency.items() for neighbour in neighbours):
        raise NavMeshPersistenceError("NavMesh adjacency must be symmetric.")
    return adjacency


def _spans(
    value: object, polygons: tuple[NavMeshPolygon, ...], config: AgentNavigationConfig
) -> tuple[SurfaceSpan, ...]:
    entries = _sequence(value, "surface_spans")
    ids = {polygon.polygon_id for polygon in polygons}
    spans = tuple(
        SurfaceSpan(
            _integer(_mapping(entry, "surface span").get("cell_x"), "cell_x"),
            _integer(_mapping(entry, "surface span").get("cell_z"), "cell_z"),
            tuple(
                _integer(item, "surface span polygon ID")
                for item in _sequence(_mapping(entry, "surface span").get("polygon_ids"), "polygon_ids")
            ),
        )
        for entry in entries
    )
    if any(
        not span.polygon_ids
        or span.polygon_ids != tuple(sorted(set(span.polygon_ids)))
        or not set(span.polygon_ids) <= ids
        for span in spans
    ):
        raise NavMeshPersistenceError("NavMesh surface spans must contain sorted valid polygon IDs.")
    expected = _expected_spans(polygons, config.cell_size_units)
    if spans != expected:
        raise NavMeshPersistenceError("NavMesh surface spans do not match the persisted polygons.")
    return spans


def _expected_spans(
    polygons: tuple[NavMeshPolygon, ...], cell_size: float
) -> tuple[SurfaceSpan, ...]:
    cells: dict[tuple[int, int], list[int]] = {}
    for polygon in polygons:
        centroid = polygon.centroid
        cell = math.floor(centroid.x / cell_size), math.floor(centroid.z / cell_size)
        cells.setdefault(cell, []).append(polygon.polygon_id)
    return tuple(
        SurfaceSpan(cell_x, cell_z, tuple(sorted(polygon_ids)))
        for (cell_x, cell_z), polygon_ids in sorted(cells.items())
    )


def _vertex(value: object) -> WorldVertex:
    values = _sequence(value, "vertex")
    if len(values) != 3:
        raise NavMeshPersistenceError("NavMesh vertices must contain three coordinates.")
    return WorldVertex(*(_number(item, "vertex coordinate") for item in values))


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise NavMeshPersistenceError(f"Persisted {label} must be an object.")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise NavMeshPersistenceError(f"Persisted {label} must be a list.")
    return tuple(value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NavMeshPersistenceError(f"Persisted {label} must be an integer.")
    return value


def _integer_from_string(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise NavMeshPersistenceError(f"Persisted {label} must be an integer.") from error


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise NavMeshPersistenceError(f"Persisted {label} must be a number.")
    number = float(value)
    if not math.isfinite(number):
        raise NavMeshPersistenceError(f"Persisted {label} must be finite.")
    return number
