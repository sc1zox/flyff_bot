"""Deterministic baseline policy that preserves the existing target-selection behavior."""

from __future__ import annotations

from flyff_bot.features.automation.models import Position, WorldState
from flyff_bot.features.policy.models import (
    DEFAULT_POLICY_WAIT_SECONDS,
    PolicyCandidate,
    PolicyContext,
    TacticalActionPayload,
    TargetAction,
    WaitAction,
)


def _candidate_sort_key(
    candidate: PolicyCandidate, center: Position
) -> tuple[int, float, float, int, str]:
    mob = candidate.mob
    distance = (mob.x - center.x) ** 2 + (mob.y - center.y) ** 2
    return (
        0 if mob.navmesh_path_distance is not None else 1,
        mob.navmesh_path_distance or 0.0,
        distance,
        mob.class_id,
        mob.class_name,
    )


class HeuristicPolicy:
    """Select the same NavMesh-first, viewport-distance-first candidate as the baseline."""

    def evaluate(
        self, world_state: WorldState, context: PolicyContext
    ) -> TacticalActionPayload | None:
        eligible = [candidate for candidate in context.candidates if candidate.is_eligible]
        if not eligible:
            return WaitAction(DEFAULT_POLICY_WAIT_SECONDS, "no_eligible_target")
        if not world_state.viewport.has_size:
            if any(candidate.mob.navmesh_path_distance is not None for candidate in eligible):
                selected = min(eligible, key=_navmesh_candidate_key)
            else:
                selected = max(
                    eligible,
                    key=lambda candidate: (
                        candidate.mob.confidence,
                        -candidate.mob.class_id,
                        candidate.mob.class_name,
                    ),
                )
        else:
            center = Position(world_state.viewport.width // 2, world_state.viewport.height // 2)
            selected = min(eligible, key=lambda candidate: _candidate_sort_key(candidate, center))
        return TargetAction(selected.mob.class_id, Position(selected.mob.x, selected.mob.y))


def _navmesh_candidate_key(candidate: PolicyCandidate) -> tuple[int, float]:
    mob = candidate.mob
    if mob.navmesh_path_distance is not None:
        return (0, mob.navmesh_path_distance)
    return (1, float("inf"))
