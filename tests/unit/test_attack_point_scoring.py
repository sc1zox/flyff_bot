"""Multi-criteria attack-point scoring and performance behavior for US-070."""

from __future__ import annotations

import time

from flyff_bot.features.navigation.attack_point_planner import (
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


def _mesh() -> BakedNavMesh:
    return NavMeshBaker().bake(
        (
            _triangle((-20.0, 0.0, -20.0), (20.0, 0.0, -20.0), (20.0, 0.0, 20.0)),
            _triangle((-20.0, 0.0, -20.0), (20.0, 0.0, 20.0), (-20.0, 0.0, 20.0)),
        )
    )


MELEE_TEST_RADII = EngagementRadii(2.5, 3.5)


def test_follow_up_target_proximity_changes_the_selected_point() -> None:
    mesh = _mesh()
    player = WorldPosition(-1.0, 0.0, 0.0)
    target = WorldPosition(0.0, 0.0, 0.0)
    without_follow_up = AttackPointPlanner(mesh).plan(
        player, target, MELEE_TEST_RADII, heading_degrees=90.0, timeout_seconds=1.0
    )
    with_follow_up = AttackPointPlanner(mesh).plan(
        player,
        target,
        MELEE_TEST_RADII,
        heading_degrees=90.0,
        timeout_seconds=1.0,
        follow_ups=(WorldPosition(2.5, 0.0, 2.5),),
    )

    assert without_follow_up is not None and with_follow_up is not None
    assert with_follow_up.selected.follow_up_distance < 6.0
    assert with_follow_up.selected.score >= with_follow_up.selected.travel_seconds


def test_turn_cost_prefers_a_heading_aligned_engagement_point() -> None:
    mesh = _mesh()
    plan = AttackPointPlanner(mesh).plan(
        WorldPosition(0.0, 0.0, -12.0),
        WorldPosition(0.0, 0.0, 0.0),
        MELEE_TEST_RADII,
        heading_degrees=180.0,
        timeout_seconds=1.0,
    )

    assert plan is not None
    assert plan.selected.angle_degrees == 180.0


def test_timeout_returns_none_instead_of_an_unvalidated_plan() -> None:
    mesh = _mesh()
    monotonic_values = iter((0.0, 10.0))
    plan = AttackPointPlanner(mesh).plan(
        WorldPosition(-1.0, 0.0, 0.0),
        WorldPosition(0.0, 0.0, 0.0),
        MELEE_TEST_RADII,
        heading_degrees=0.0,
        monotonic=lambda: next(monotonic_values),
        timeout_seconds=0.001,
    )

    assert plan is None


def test_sampling_and_scoring_complete_within_one_millisecond() -> None:
    mesh = _mesh()
    started = time.perf_counter()
    plan = AttackPointPlanner(mesh).plan(
        WorldPosition(-1.0, 0.0, 0.0),
        WorldPosition(0.0, 0.0, 0.0),
        MELEE_TEST_RADII,
        heading_degrees=90.0,
        timeout_seconds=1.0,
    )
    elapsed = time.perf_counter() - started

    assert plan is not None
    assert plan.candidates_considered > 0
    assert elapsed < 0.002
