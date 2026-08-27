"""Deterministic tactical action masking."""

from __future__ import annotations

from flyff_bot.features.policy.action_payloads import (
    TACTICAL_ACTION_COUNT,
    TacticalAction,
)
from flyff_bot.features.rl.actions import TacticalActionMask
from flyff_bot.features.rl.models import RlObservation


def build_action_mask(
    observation: RlObservation,
    *,
    patrol_center: tuple[float, float, float],
    patrol_radius: float,
) -> tuple[bool, ...]:
    """Return a stable mask where invalid tactical actions are disabled."""

    return build_tactical_mask(
        observation, patrol_center=patrol_center, patrol_radius=patrol_radius
    ).actions


def build_tactical_mask(
    observation: RlObservation,
    *,
    patrol_center: tuple[float, float, float],
    patrol_radius: float,
) -> TacticalActionMask:
    """Return the discrete and per-candidate masks for one observed state."""

    candidate_mask = _candidate_mask(observation, patrol_radius)
    if observation.readiness.action_blocked:
        return TacticalActionMask(
            tuple(index == int(TacticalAction.WAIT) for index in range(TACTICAL_ACTION_COUNT)),
            tuple(False for _ in candidate_mask),
        )

    has_valid_candidate = any(candidate_mask)
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
    actions = (
        has_valid_candidate,
        go_to_position_valid,
        has_valid_candidate,
        corridor_valid and has_valid_candidate,
        object_or_npc_valid,
        object_or_npc_valid,
        True,
    )[:TACTICAL_ACTION_COUNT]
    return TacticalActionMask(actions, candidate_mask)


def _candidate_mask(observation: RlObservation, patrol_radius: float) -> tuple[bool, ...]:
    """Return one legality flag per candidate index observed in this state."""

    indices = [candidate.candidate_index for candidate in observation.candidates]
    if not indices:
        return ()
    eligible = {
        candidate.candidate_index
        for candidate in observation.candidates
        if not candidate.is_dead
        and not candidate.is_locked_out
        and not candidate.is_unreachable
        and candidate.path_distance is not None
        and candidate.path_distance <= patrol_radius
    }
    return tuple(index in eligible for index in range(max(indices) + 1))


def _inside_patrol(value: float, center: float, radius: float) -> bool:
    return abs(value - center) <= radius
