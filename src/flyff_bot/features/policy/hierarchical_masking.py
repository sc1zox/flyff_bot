"""Deterministic final validation for policy-produced tactical intents."""

from __future__ import annotations

import math

from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    TargetAction,
    WaitAction,
)
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext, TacticalActionPayload
from flyff_bot.features.tactical_parameters import (
    TACTICAL_PARAMETER_DEFINITIONS,
    TacticalParameterName,
)


def validate_policy_action(action: TacticalActionPayload, context: PolicyContext) -> bool:
    """Return whether an action exactly matches a currently prevalidated option."""

    if isinstance(action, TargetAction):
        candidate = next(
            (
                item
                for item in context.candidates
                if item.is_eligible
                and _identifies(action.candidate_index, action.target_id, item)
                and _target_position_matches(action, item)
            ),
            None,
        )
        if candidate is None or not _finite_optional(action.expected_cost):
            return False
        if action.attack_point is not None and not _valid_approach_distance(
            action.attack_point.approach_distance_units
        ):
            return False
        return not (
            action.attack_point is not None
            and action.attack_point not in context.valid_attack_points
        )
    if isinstance(action, NavigateAction):
        return (
            _finite_position(action.destination)
            and action.destination in context.valid_destinations
        )
    if isinstance(action, AttackPointAction):
        return (
            _finite_position(action.attack_point)
            and _valid_approach_distance(action.approach_distance_units)
            and action in context.valid_attack_points
        )
    if isinstance(action, CorridorAction):
        return action.preferred_corridor_id in context.valid_corridor_ids and _eligible_target(
            action.candidate_index, action.target_id, context
        )
    if isinstance(action, InteractAction):
        return (action.interaction_target_id, action.interaction_type) in context.valid_interactions
    return isinstance(action, WaitAction) and math.isfinite(action.duration_seconds)


def _eligible_target(candidate_index: int | None, target_id: int, context: PolicyContext) -> bool:
    return any(
        candidate.is_eligible and _identifies(candidate_index, target_id, candidate)
        for candidate in context.candidates
    )


def _identifies(candidate_index: int | None, target_id: int, candidate: PolicyCandidate) -> bool:
    """Match a chosen candidate by its per-instance identity whenever the action declares one.

    A detector class identifier cannot distinguish two mobs of the same class, so an action that
    names a candidate index is resolved by that index alone (BUG-031).
    """

    if candidate_index is not None:
        return candidate.original_position == candidate_index
    return candidate.mob.class_id == target_id


def _finite_position(position: tuple[float, float, float]) -> bool:
    return all(math.isfinite(value) for value in position)


def _finite_optional(value: float | None) -> bool:
    return value is None or math.isfinite(value)


def _valid_approach_distance(value: float | None) -> bool:
    if value is None:
        return True
    definition = TACTICAL_PARAMETER_DEFINITIONS[TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS]
    return math.isfinite(value) and definition.minimum <= value <= definition.maximum


def _target_position_matches(action: TargetAction, candidate: PolicyCandidate) -> bool:
    if action.target_pos is None:
        return action.target_pos is None
    mob = candidate.mob
    return action.target_pos in (
        type(action.target_pos)(mob.x, mob.y),
        type(action.target_pos)(mob.x + mob.width // 2, mob.y + mob.height // 2),
    )
