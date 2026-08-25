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
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext, TacticalAction


def validate_policy_action(action: TacticalAction, context: PolicyContext) -> bool:
    """Return whether an action exactly matches a currently prevalidated option."""

    if isinstance(action, TargetAction):
        candidate = next(
            (
                item
                for item in context.candidates
                if item.is_eligible
                and item.mob.class_id == action.target_id
                and _target_position_matches(action, item)
            ),
            None,
        )
        if candidate is None or not _finite_optional(action.expected_cost):
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
        return _finite_position(action.attack_point) and action in context.valid_attack_points
    if isinstance(action, CorridorAction):
        return action.preferred_corridor_id in context.valid_corridor_ids and _eligible_target(
            action.target_id, context
        )
    if isinstance(action, InteractAction):
        return (action.interaction_target_id, action.interaction_type) in context.valid_interactions
    return isinstance(action, WaitAction) and math.isfinite(action.duration_seconds)


def _eligible_target(target_id: int, context: PolicyContext) -> bool:
    return any(
        candidate.is_eligible and candidate.mob.class_id == target_id
        for candidate in context.candidates
    )


def _finite_position(position: tuple[float, float, float]) -> bool:
    return all(math.isfinite(value) for value in position)


def _finite_optional(value: float | None) -> bool:
    return value is None or math.isfinite(value)


def _target_position_matches(action: TargetAction, candidate: PolicyCandidate) -> bool:
    if action.target_pos is None:
        return action.target_pos is None
    mob = candidate.mob
    return action.target_pos in (
        type(action.target_pos)(mob.x, mob.y),
        type(action.target_pos)(mob.x + mob.width // 2, mob.y + mob.height // 2),
    )
