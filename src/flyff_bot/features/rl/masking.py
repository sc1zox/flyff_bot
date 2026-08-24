"""Deterministic tactical action masking."""

from __future__ import annotations

from flyff_bot.features.rl.actions import TACTICAL_ACTION_COUNT
from flyff_bot.features.rl.models import RlObservation


def build_action_mask(
    observation: RlObservation,
    *,
    patrol_center: tuple[float, float, float],
    patrol_radius: float,
) -> tuple[bool, ...]:
    """Return a stable mask where invalid tactical actions are disabled."""

    valid_candidates = [
        candidate
        for candidate in observation.candidates
        if not candidate.is_dead
        and not candidate.is_locked_out
        and not candidate.is_unreachable
        and candidate.path_distance is not None
        and candidate.path_distance <= patrol_radius
    ]
    has_valid_candidate = bool(valid_candidates)
    has_attack_point = any(
        candidate.path_distance is not None and candidate.path_distance <= patrol_radius
        for candidate in valid_candidates
    )
    go_to_position_valid = all(
        _inside_patrol(value, center, radius)
        for value, center, radius in zip(
            (
                observation.kinematics.position_x,
                observation.kinematics.position_y,
                observation.kinematics.position_z,
            ),
            patrol_center,
            (patrol_radius,) * 3,
            strict=False,
        )
    )
    corridor_valid = bool(observation.navmesh.current_polygon_id)
    object_or_npc_valid = bool(observation.objective.quest_id)
    return (
        has_valid_candidate,
        go_to_position_valid,
        has_attack_point,
        corridor_valid,
        object_or_npc_valid,
        object_or_npc_valid,
        True,
    )[:TACTICAL_ACTION_COUNT]


def _inside_patrol(value: float, center: float, radius: float) -> bool:
    return abs(value - center) <= radius
