"""Correlate recorded GPS trajectories with stable baked NavMesh topology."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from flyff_bot.features.navigation.empirical_routing import (
    EdgeTraversalStats,
    EmpiricalCostIndex,
    ExperienceRoutingConfig,
    PolygonTraversalStats,
)
from flyff_bot.features.navigation.navmesh import BakedNavMesh
from flyff_bot.features.telemetry.models import NavigationEpisode


@dataclass(slots=True)
class _Accumulator:
    """Numerically stable sums behind one empirical statistic."""

    traversal_seconds: float = 0.0
    recovery_seconds: float = 0.0
    traversal_count: int = 0
    stall_count: int = 0
    distance_units: float = 0.0

    def polygon_stats(self, polygon_id: int) -> PolygonTraversalStats:
        return PolygonTraversalStats(
            polygon_id=polygon_id,
            traversal_count=self.traversal_count,
            stall_count=self.stall_count,
            mean_traversal_seconds=self.traversal_seconds / self.traversal_count,
            mean_recovery_seconds=self.recovery_seconds / self.traversal_count,
        )

    def edge_stats(self, from_polygon_id: int, to_polygon_id: int) -> EdgeTraversalStats:
        return EdgeTraversalStats(
            from_polygon_id=from_polygon_id,
            to_polygon_id=to_polygon_id,
            traversal_count=self.traversal_count,
            stall_count=self.stall_count,
            distance_units=self.distance_units / self.traversal_count,
            mean_travel_seconds=self.traversal_seconds / self.traversal_count,
            mean_recovery_seconds=self.recovery_seconds / self.traversal_count,
        )


def correlate_navigation_episodes(
    episodes: Iterable[NavigationEpisode],
    mesh: BakedNavMesh,
    *,
    mesh_digest: str,
    config: ExperienceRoutingConfig | None = None,
) -> EmpiricalCostIndex:
    """Aggregate mapped GPS segments and sampled stalls into a digest-bound index."""

    polygon_accumulators: dict[int, _Accumulator] = defaultdict(_Accumulator)
    edge_accumulators: dict[tuple[int, int], _Accumulator] = defaultdict(_Accumulator)
    for episode in episodes:
        for previous, current in zip(episode.trajectory, episode.trajectory[1:], strict=False):
            previous_id = _polygon_id(previous[3])
            current_id = _polygon_id(current[3])
            if previous_id is None or current_id is None:
                continue
            elapsed_seconds = max(0.0, (current[0] - previous[0]) / 1_000_000_000)
            previous_position, current_position = previous[1], current[1]
            distance_units = (
                (current_position.x - previous_position.x) ** 2
                + (current_position.y - previous_position.y) ** 2
                + (current_position.z - previous_position.z) ** 2
            ) ** 0.5
            stalled = bool(previous[4] or current[4])
            recovery_seconds = elapsed_seconds if stalled else 0.0
            for polygon_id in (previous_id, current_id):
                _observe(
                    polygon_accumulators[polygon_id],
                    elapsed_seconds / 2.0,
                    distance_units / 2.0,
                    recovery_seconds / 2.0,
                    stalled,
                )
            edge_key = (previous_id, current_id)
            if edge_key[1] in mesh.adjacency.get(edge_key[0], ()):
                _observe(
                    edge_accumulators[edge_key],
                    elapsed_seconds,
                    distance_units,
                    recovery_seconds,
                    stalled,
                )
    return EmpiricalCostIndex(
        mesh_digest=mesh_digest,
        polygons={
            polygon_id: accumulator.polygon_stats(polygon_id)
            for polygon_id, accumulator in sorted(polygon_accumulators.items())
        },
        edges={
            edge_key: accumulator.edge_stats(*edge_key)
            for edge_key, accumulator in sorted(edge_accumulators.items())
        },
        config=config or ExperienceRoutingConfig(),
    )


def _observe(
    accumulator: _Accumulator,
    traversal_seconds: float,
    distance_units: float,
    recovery_seconds: float,
    stalled: bool,
) -> None:
    accumulator.traversal_seconds += traversal_seconds
    accumulator.recovery_seconds += recovery_seconds
    accumulator.distance_units += distance_units
    accumulator.traversal_count += 1
    accumulator.stall_count += int(stalled)


def _polygon_id(value: object) -> int | None:
    if not isinstance(value, str) or not value.isdigit():
        return None
    return int(value)
