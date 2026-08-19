"""Persistent baked NavMesh artifact tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import NavMeshBaker
from flyff_bot.features.navigation.navmesh_persistence import (
    NavMeshPersistenceError,
    load_baked_navmesh,
    save_baked_navmesh,
)
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex


def _triangle(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> WorldTriangle:
    return WorldTriangle(WorldVertex(*first), WorldVertex(*second), WorldVertex(*third), "fixture")


def test_baked_navmesh_round_trip_preserves_ids_topology_and_queries(tmp_path: Path) -> None:
    mesh = NavMeshBaker().bake(
        (
            _triangle((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 0.0, 4.0)),
            _triangle((4.0, 0.0, 0.0), (4.0, 0.0, 4.0), (0.0, 0.0, 4.0)),
        )
    )
    path = tmp_path / "wdtest.navmesh.json"

    saved = save_baked_navmesh(mesh, path)
    loaded = load_baked_navmesh(path)

    assert loaded.content_digest == saved.content_digest
    assert loaded.mesh.polygons == mesh.polygons
    assert loaded.mesh.adjacency == mesh.adjacency
    assert loaded.mesh.surface_spans == mesh.surface_spans
    assert loaded.mesh.find_path(WorldPosition(0.5, 0.0, 0.5), WorldPosition(3.5, 0.0, 3.5))


def test_baked_navmesh_loader_rejects_asymmetric_topology(tmp_path: Path) -> None:
    path = tmp_path / "invalid.navmesh.json"
    mesh = NavMeshBaker().bake(
        (
            _triangle((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 0.0, 4.0)),
            _triangle((4.0, 0.0, 0.0), (4.0, 0.0, 4.0), (0.0, 0.0, 4.0)),
        )
    )
    save_baked_navmesh(mesh, path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["adjacency"]["2"] = []
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(NavMeshPersistenceError, match="symmetric"):
        load_baked_navmesh(path)
