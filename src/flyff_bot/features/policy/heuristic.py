"""Deterministic baseline policy over the canonical candidate economics."""

from __future__ import annotations

from flyff_bot.features.automation.models import Position, WorldState
from flyff_bot.features.policy.candidate_economics import rank_candidates
from flyff_bot.features.policy.models import (
    DEFAULT_POLICY_WAIT_SECONDS,
    PolicyContext,
    TacticalActionPayload,
    TargetAction,
    WaitAction,
)


class HeuristicPolicy:
    """Select the highest-value eligible candidate through the one canonical ranker."""

    def evaluate(
        self, world_state: WorldState, context: PolicyContext
    ) -> TacticalActionPayload | None:
        eligible = tuple(candidate for candidate in context.candidates if candidate.is_eligible)
        if not eligible:
            return WaitAction(DEFAULT_POLICY_WAIT_SECONDS, "no_eligible_target")
        ranked = rank_candidates(
            tuple(candidate.mob for candidate in eligible),
            world_state,
            heading_degrees=context.heading_degrees,
            quota_class_names=context.quota_class_names,
        )
        selected_mob = ranked[0][0]
        selected = next(candidate for candidate in eligible if candidate.mob is selected_mob)
        return TargetAction(
            selected_mob.class_id,
            Position(selected_mob.x, selected_mob.y),
            candidate_index=selected.original_position,
        )
