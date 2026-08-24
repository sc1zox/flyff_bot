"""Unit tests for telemetry-to-NavMesh empirical cost aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from navigation_fixtures import line_mesh
from navigation_fixtures import mesh_digest as digest_of_mesh

from flyff_bot.features.navigation.empirical_routing import (
    EdgeTraversalStats,
    EmpiricalCostError,
    EmpiricalCostIndex,
    ExperienceRoutingConfig,
    PolygonTraversalStats,
    load_empirical_cost_index,
    save_empirical_cost_index,
)
from flyff_bot.features.telemetry.models import NavigationEpisode, TelemetryPosition
from flyff_bot.features.telemetry.navmesh_correlation import correlate_navigation_episodes


def _episode(
    polygon_ids: tuple[str | None, str | None],
    *,
    stalled: tuple[bool, bool] = (False, False),
) -> NavigationEpisode:
    trajectory = (
        (1_000_000_000, TelemetryPosition(0.0, 0.0, 0.5), 1.0, polygon_ids[0], stalled[0]),
        (3_000_000_000, TelemetryPosition(4.0, 0.0, 1.5), 2.0, polygon_ids[1], stalled[1]),
    )
    return NavigationEpisode(
        started_at_ns=trajectory[0][0],
        ended_at_ns=trajectory[-1][0],
        start_position=trajectory[0][1],
        target_position=trajectory[-1][1],
        planned_route=(trajectory[0][1], trajectory[-1][1]),
        planned_length=4.123,
        actual_travel_distance=4.123,
        trajectory=trajectory,
        replans_count=0,
        stall_events=int(any(stalled)),
        stall_duration_seconds=2.0 if any(stalled) else 0.0,
        collision_evasions=0,
        outcome="reached_target",
    )


def test_navigation_episodes_aggregate_polygon_and_edge_statistics() -> None:
    mesh, digest = line_mesh()
    index = correlate_navigation_episodes(
        (_episode(("1", "2"), stalled=(False, True)),),
        mesh,
        mesh_digest=digest,
    )

    assert set(index.polygons) == {1, 2}
    assert index.edges[(1, 2)].traversal_count == 1
    assert index.edges[(1, 2)].stall_count == 1
    assert index.edges[(1, 2)].mean_travel_seconds == pytest.approx(2.0)
    assert index.edges[(1, 2)].stuck_probability == 1.0
    assert index.edges[(1, 2)].expected_cost_seconds == pytest.approx(4.0)
    assert index.polygons[1].traversal_count == index.polygons[2].traversal_count == 1
    assert index.polygons[1].traversal_count == 1


def test_empirical_cost_round_trip_and_mismatched_mesh_are_rejected(tmp_path: Path) -> None:
    stats = EdgeTraversalStats(1, 2, 10, 2, 8.0, 2.0, 4.0)
    index = EmpiricalCostIndex(
        "a" * 64,
        {1: PolygonTraversalStats(1, 10, 2, 2.0, 4.0)},
        {(1, 2): stats},
        ExperienceRoutingConfig(),
    )
    path = tmp_path / "world.empirical.json"
    saved = save_empirical_cost_index(index, path)

    loaded = load_empirical_cost_index(path, "a" * 64)

    assert saved.content_digest == save_empirical_cost_index(index, path).content_digest
    assert loaded.edge_stats(2, 1) == stats
    assert loaded.weighted_edge_cost(8.0, 1, 2) == pytest.approx(2.4)
    with pytest.raises(EmpiricalCostError, match="digest"):
        load_empirical_cost_index(path, "b" * 64)

    document = json.loads(path.read_text(encoding="utf-8"))
    document["payload"]["edges"][0]["stall_count"] += 1
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(EmpiricalCostError, match="integrity"):
        load_empirical_cost_index(path, "a" * 64)


def test_unmapped_gps_samples_do_not_create_edges() -> None:
    mesh, digest = line_mesh()
    index = correlate_navigation_episodes(
        (_episode((None, "999")),),
        mesh,
        mesh_digest=digest,
    )
    assert not index.polygons
    assert not index.edges
    assert digest_of_mesh(mesh) == digest
