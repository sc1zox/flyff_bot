"""Experience-weighted NavMesh A* behavior and performance guards."""

from __future__ import annotations

import time
from itertools import pairwise

import pytest
from navigation_fixtures import line_mesh

from flyff_bot.features.navigation.empirical_routing import (
    DEFAULT_EXPERIENCE_WEIGHT,
    DEFAULT_MINIMUM_EDGE_SAMPLES,
    EdgeTraversalStats,
    EmpiricalCostIndex,
    ExperienceRoutingConfig,
)
from flyff_bot.features.navigation.live_position import WorldPosition


def weighted_index(edge: EdgeTraversalStats | None) -> EmpiricalCostIndex:
    edges = {} if edge is None else {(edge.from_polygon_id, edge.to_polygon_id): edge}
    return EmpiricalCostIndex("a" * 64, {}, edges)


def test_default_weight_is_configurable_and_validated() -> None:
    config = ExperienceRoutingConfig()
    assert config.experience_weight == DEFAULT_EXPERIENCE_WEIGHT == 0.5
    assert ExperienceRoutingConfig(experience_weight=0.25).experience_weight == 0.25
    with pytest.raises(ValueError, match="between zero and one"):
        ExperienceRoutingConfig(experience_weight=1.01)


def test_sparse_edges_smoothly_fall_back_to_geometric_cost() -> None:
    sparse = EdgeTraversalStats(1, 2, 1, 1, 8.0, 20.0, 20.0)
    dense = EdgeTraversalStats(1, 2, DEFAULT_MINIMUM_EDGE_SAMPLES, 1, 8.0, 20.0, 20.0)
    config = ExperienceRoutingConfig()
    index = EmpiricalCostIndex("a" * 64, {}, {(1, 2): sparse})

    assert index.weighted_edge_cost(8.0, 1, 2, config) == pytest.approx(2.95)
    assert EmpiricalCostIndex("a" * 64, {}, {(1, 2): dense}).weighted_edge_cost(
        8.0, 1, 2, config
    ) == pytest.approx(13.0)


def test_router_prefers_open_detour_but_preserves_reachability_under_penalties() -> None:
    mesh, digest = line_mesh()
    start = WorldPosition(0.5, 0.0, 6.5)
    goal = WorldPosition(11.5, 0.0, 1.5)
    geometric_path = mesh.find_path(start, goal)
    assert len(geometric_path) == 3

    geometric_polygon_path = mesh.find_polygon_path(start, goal)
    assert len(geometric_polygon_path) == 8
    first_id, second_id = geometric_polygon_path[1], geometric_polygon_path[2]
    index = weighted_index(EdgeTraversalStats(first_id, second_id, 10, 10, 4.0, 30.0, 30.0))
    index = EmpiricalCostIndex(digest, index.polygons, index.edges)
    mesh.attach_empirical_cost_index(index, mesh_digest=digest)

    weighted_path = mesh.find_path(start, goal)
    weighted_polygon_path = mesh.find_polygon_path(start, goal)
    assert len(weighted_polygon_path) == 8
    assert len(weighted_path) == 3
    weighted_polygon_path = mesh.find_polygon_path(start, goal)
    weighted_edges = tuple(pairwise(weighted_polygon_path))
    assert (first_id, second_id) not in weighted_edges and (
        second_id,
        first_id,
    ) not in weighted_edges
    assert mesh.is_reachable(start, goal)
    unweighted = ExperienceRoutingConfig(experience_weight=0.0)
    assert mesh.find_path(start, goal, routing_config=unweighted)


@pytest.mark.parametrize("edge_count", [100])
def test_empirical_lookup_and_route_remain_within_budget(edge_count: int) -> None:
    edges = {
        (polygon_id, polygon_id + 1): EdgeTraversalStats(
            polygon_id, polygon_id + 1, 10, 1, 1.0, 1.0, 1.0
        )
        for polygon_id in range(1, edge_count + 1)
    }
    index = EmpiricalCostIndex("a" * 64, {}, edges)
    started = time.perf_counter()
    costs = [
        index.weighted_edge_cost(4.0, polygon_id, polygon_id + 1)
        for polygon_id in range(1, edge_count + 1)
    ]
    lookup_seconds = time.perf_counter() - started
    assert all(cost == pytest.approx(1.05) for cost in costs)
    assert lookup_seconds / edge_count < 0.0005

    mesh, digest = line_mesh()
    mesh.attach_empirical_cost_index(EmpiricalCostIndex(digest, {}, edges), mesh_digest=digest)
    started = time.perf_counter()
    mesh.find_path(WorldPosition(0.5, 0.0, 6.5), WorldPosition(11.5, 0.0, 1.5))
    assert time.perf_counter() - started < 0.002
