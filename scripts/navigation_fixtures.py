"""Small deterministic NavMesh fixtures shared by routing tests."""

from __future__ import annotations

import hashlib
import json

from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshBaker
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex


def triangle(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> WorldTriangle:
    return WorldTriangle(WorldVertex(*first), WorldVertex(*second), WorldVertex(*third), "fixture")


def line_mesh() -> tuple[BakedNavMesh, str]:
    """Return a two-lane ladder whose lower middle transition is the risky shortcut."""

    triangles: list[WorldTriangle] = []
    for square_index in range(3):
        left = float(square_index * 4)
        right = left + 4.0
        triangles.extend(
            (
                triangle((left, 0.0, 0.0), (right, 0.0, 0.0), (right, 0.0, 4.0)),
                triangle((left, 0.0, 0.0), (right, 0.0, 4.0), (left, 0.0, 4.0)),
                triangle((left, 0.0, 4.0), (left, 0.0, 8.0), (right, 0.0, 8.0)),
                triangle((left, 0.0, 4.0), (right, 0.0, 8.0), (right, 0.0, 4.0)),
            )
        )
    mesh = NavMeshBaker().bake(tuple(triangles))
    document = {
        "polygons": [
            [vertex.x, vertex.y, vertex.z]
            for polygon in mesh.polygons
            for vertex in (
                polygon.triangle.first,
                polygon.triangle.second,
                polygon.triangle.third,
            )
        ]
    }
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode("utf-8")).hexdigest()
    return mesh, digest


def mesh_digest(mesh: BakedNavMesh) -> str:
    """Return a stable local fixture identity for correlation assertions."""

    document = {
        "polygons": [
            [vertex.x, vertex.y, vertex.z]
            for polygon in mesh.polygons
            for vertex in (
                polygon.triangle.first,
                polygon.triangle.second,
                polygon.triangle.third,
            )
        ]
    }
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode("utf-8")).hexdigest()


__all__ = ["line_mesh", "mesh_digest", "triangle"]
