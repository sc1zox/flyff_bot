"""Strict attack-point geometry and class-radius behavior for US-070."""

from __future__ import annotations

import math

import pytest

from flyff_bot.features.navigation.attack_point_planner import (
    MELEE_ENGAGEMENT_RADII,
    RANGED_ENGAGEMENT_RADII,
    AttackPointPlanner,
    EngagementRadii,
)
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshBaker
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex


def _triangle(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> WorldTriangle:
    return WorldTriangle(WorldVertex(*first), WorldVertex(*second), WorldVertex(*third), "fixture")


def _flat_mesh() -> BakedNavMesh:
    return NavMeshBaker().bake(
        (
            _triangle((-20.0, 0.0, -20.0), (20.0, 0.0, -20.0), (20.0, 0.0, 20.0)),
            _triangle((-20.0, 0.0, -20.0), (20.0, 0.0, 20.0), (-20.0, 0.0, 20.0)),
        )
    )


def test_engagement_radii_validate_class_bands() -> None:
    assert (MELEE_ENGAGEMENT_RADII.minimum_units, MELEE_ENGAGEMENT_RADII.maximum_units) == (
        2.5,
        3.5,
    )
    assert (RANGED_ENGAGEMENT_RADII.minimum_units, RANGED_ENGAGEMENT_RADII.maximum_units) == (
        12.0,
        15.0,
    )
    with pytest.raises(ValueError, match="below the minimum"):
        EngagementRadii(4.0, 3.0)


def test_contained_surface_requires_exact_polygon_membership() -> None:
    mesh = _flat_mesh()
    assert mesh.contained_surface(WorldPosition(5.0, 0.0, 5.0)) is not None
    assert mesh.contained_surface(WorldPosition(21.0, 0.0, 5.0)) is None
    assert mesh.contained_surface(WorldPosition(20.0, 0.0, 5.0)) is not None


def test_sampler_rejects_points_outside_or_above_the_mesh() -> None:
    mesh = NavMeshBaker().bake(
        (
            _triangle((2.5, 0.0, 0.0), (7.5, 0.0, 0.0), (7.5, 0.0, 5.0)),
            _triangle((2.5, 0.0, 0.0), (7.5, 0.0, 5.0), (2.5, 0.0, 5.0)),
        )
    )
    plan = AttackPointPlanner(mesh, sample_count=8).plan(
        WorldPosition(0.0, 0.0, 2.5),
        WorldPosition(5.0, 0.0, 2.5),
        MELEE_ENGAGEMENT_RADII,
        heading_degrees=90.0,
    )
    assert plan is None


def test_melee_and_ranged_samples_remain_inside_their_annulus() -> None:
    mesh = _flat_mesh()
    target = WorldPosition(0.0, 0.0, 0.0)
    player = WorldPosition(-1.0, 0.0, 0.0)
    for radii in (MELEE_ENGAGEMENT_RADII, RANGED_ENGAGEMENT_RADII):
        plan = AttackPointPlanner(mesh).plan(
            player,
            target,
            EngagementRadii(radii.minimum_units, radii.maximum_units),
            heading_degrees=0.0,
            timeout_seconds=1.0,
        )
        assert plan is not None
        distance = math.dist(
            (plan.selected.position.x, plan.selected.position.z),
            (target.x, target.z),
        )
        assert radii.minimum_units <= distance <= radii.maximum_units
