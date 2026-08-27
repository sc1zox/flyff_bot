"""Two-tier tactical policy for farming, navigation, and quest objectives."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.automation.models import Position, WorldState
from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    InteractAction,
    NavigateAction,
    TacticalActionKind,
    TargetAction,
    WaitAction,
)
from flyff_bot.features.policy.heuristic import HeuristicPolicy
from flyff_bot.features.policy.models import (
    POLICY_LATENCY_BUDGET_SECONDS,
    PolicyCandidate,
    PolicyContext,
    StrategicDecision,
    StrategicGoalKind,
    TacticalActionPayload,
)

DEFAULT_HIGH_LEVEL_REEVALUATION_SECONDS = 2.0
DEFAULT_POLICY_WAIT_SECONDS = 0.1


class HierarchicalObjectiveKind(StrEnum):
    """The objective families understood by the strategic tier."""

    FARMING = "farming"
    NAVIGATION = "navigation"
    QUEST = "quest"


@dataclass(frozen=True, slots=True)
class HierarchicalObjective:
    """Current quota, travel goal, or one step in a quest sequence."""

    kind: HierarchicalObjectiveKind = HierarchicalObjectiveKind.FARMING
    target_class_names: frozenset[str] | None = None
    destination: tuple[float, float, float] | None = None
    quest_id: str | None = None
    objective_index: int = 0
    objective_count: int = 1
    progress: float = 0.0
    required_progress: float = 1.0
    destination_reached: bool = False
    interaction_target_id: str | None = None
    interaction_type: str = "quest"

    def __post_init__(self) -> None:
        if self.objective_count < 1:
            raise ValueError("A hierarchical objective needs at least one step.")
        if not 0 <= self.objective_index < self.objective_count:
            raise ValueError("Hierarchical objective index is outside the quest sequence.")
        if self.required_progress <= 0.0:
            raise ValueError("Hierarchical required progress must be positive.")
        if not 0.0 <= self.progress <= self.required_progress:
            raise ValueError("Hierarchical objective progress is outside its required range.")
        if self.kind is HierarchicalObjectiveKind.NAVIGATION and self.destination is None:
            raise ValueError("A navigation objective needs a destination.")
        if self.interaction_target_id is not None and not self.interaction_type:
            raise ValueError("A hierarchical interaction needs a type.")


@dataclass(frozen=True, slots=True)
class HierarchicalTelemetry:
    """Diagnostics for the most recent two-tier decision cycle."""

    goal: StrategicGoalKind
    reason: str
    inference_seconds: float
    used_fallback: bool
    fallback_reason: str | None = None
    mid_level_action: TacticalActionKind | None = None


class HighLevelStrategicPolicy:
    """Choose and retain a macro sub-goal until a material event occurs."""

    def __init__(
        self,
        *,
        reevaluation_seconds: float = DEFAULT_HIGH_LEVEL_REEVALUATION_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if reevaluation_seconds <= 0.0:
            raise ValueError("High-level re-evaluation interval must be positive.")
        self._reevaluation_seconds = reevaluation_seconds
        self._monotonic = monotonic
        self._decision: tuple[StrategicDecision, float, tuple[object, ...]] | None = None

    @property
    def decision(self) -> StrategicDecision | None:
        return self._decision[0] if self._decision else None

    def evaluate(
        self,
        world_state: WorldState,
        context: PolicyContext,
        objective: HierarchicalObjective,
    ) -> StrategicDecision:
        now = self._monotonic()
        token = self._event_token(context, objective)
        previous = self._decision
        if (
            previous is not None
            and now - previous[1] < self._reevaluation_seconds
            and previous[2] == token
            and self._decision_is_valid(previous[0], context)
        ):
            return previous[0]
        decision = self._select(world_state, context, objective)
        self._decision = (decision, now, token)
        return decision

    @staticmethod
    def _event_token(
        context: PolicyContext, objective: HierarchicalObjective
    ) -> tuple[object, ...]:
        candidate_state = tuple(
            (candidate.original_position, candidate.mob.class_id, candidate.is_eligible)
            for candidate in context.candidates
        )
        return (
            objective.kind,
            objective.quest_id,
            objective.objective_index,
            objective.progress,
            objective.destination_reached,
            candidate_state,
            context.macro_event_token,
        )

    @staticmethod
    def _decision_is_valid(decision: StrategicDecision, context: PolicyContext) -> bool:
        if decision.goal is StrategicGoalKind.TARGET:
            return any(
                candidate.is_eligible
                and candidate.original_position == decision.target_candidate_index
                for candidate in context.candidates
            )
        if decision.goal is StrategicGoalKind.NAVIGATE:
            return decision.destination in context.valid_destinations
        if decision.goal is StrategicGoalKind.INTERACT:
            return (
                decision.interaction_target_id,
                decision.interaction_type,
            ) in context.valid_interactions
        return True

    def _select(
        self,
        world_state: WorldState,
        context: PolicyContext,
        objective: HierarchicalObjective,
    ) -> StrategicDecision:
        if objective.kind is HierarchicalObjectiveKind.NAVIGATION:
            if objective.destination_reached:
                return self._decision_for(objective, StrategicGoalKind.WAIT, "destination_reached")
            return self._navigation_decision(objective, context)
        allowed_names = context.allowed_class_names
        if objective.target_class_names is not None:
            allowed_names = (
                objective.target_class_names
                if not allowed_names
                else allowed_names & objective.target_class_names
            )
        eligible = [
            candidate
            for candidate in context.candidates
            if candidate.is_eligible
            and (not allowed_names or candidate.mob.class_name in allowed_names)
        ]
        progress_complete = objective.progress >= objective.required_progress
        if objective.kind is HierarchicalObjectiveKind.QUEST and progress_complete:
            if objective.interaction_target_id is not None and objective.destination_reached:
                interaction = (objective.interaction_target_id, objective.interaction_type)
                if interaction in context.valid_interactions:
                    return self._decision_for(
                        objective, StrategicGoalKind.INTERACT, "quest_interaction"
                    )
                return self._decision_for(objective, StrategicGoalKind.WAIT, "interaction_masked")
            if objective.destination is not None and not objective.destination_reached:
                return self._navigation_decision(objective, context)
            return self._decision_for(objective, StrategicGoalKind.WAIT, "quest_step_complete")
        if objective.destination is not None and not eligible and not objective.destination_reached:
            return self._navigation_decision(objective, context)
        if not eligible:
            return self._decision_for(objective, StrategicGoalKind.WAIT, "no_legal_subgoal")
        selected = min(
            eligible,
            key=lambda candidate: (
                candidate.mob.navmesh_path_distance is None,
                candidate.mob.navmesh_path_distance
                if candidate.mob.navmesh_path_distance is not None
                else float("inf"),
                _screen_distance_squared(candidate, world_state.position),
                candidate.mob.class_name,
            ),
        )
        return StrategicDecision(
            StrategicGoalKind.TARGET,
            "eligible_target",
            objective.quest_id,
            objective.objective_index,
            objective.progress,
            target_candidate_index=selected.original_position,
        )

    @staticmethod
    def _decision_for(
        objective: HierarchicalObjective, goal: StrategicGoalKind, reason: str
    ) -> StrategicDecision:
        return StrategicDecision(
            goal,
            reason,
            objective.quest_id,
            objective.objective_index,
            objective.progress,
            objective.destination,
            interaction_target_id=objective.interaction_target_id,
            interaction_type=objective.interaction_type,
        )

    @staticmethod
    def _navigation_decision(
        objective: HierarchicalObjective, context: PolicyContext
    ) -> StrategicDecision:
        if objective.destination not in context.valid_destinations:
            return HighLevelStrategicPolicy._decision_for(
                objective, StrategicGoalKind.WAIT, "destination_masked"
            )
        return HighLevelStrategicPolicy._decision_for(
            objective, StrategicGoalKind.NAVIGATE, "objective_destination"
        )


class MidLevelTacticalPolicy(HeuristicPolicy):
    """Translate one strategic decision into an already masked tactical intent."""

    def evaluate_for_goal(
        self,
        world_state: WorldState,
        context: PolicyContext,
        decision: StrategicDecision,
    ) -> TacticalActionPayload | None:
        if decision.goal is StrategicGoalKind.NAVIGATE and decision.destination is not None:
            return NavigateAction(decision.destination, decision.reason)
        if decision.goal is StrategicGoalKind.INTERACT:
            if decision.interaction_target_id is None or decision.interaction_type is None:
                return None
            return InteractAction(decision.interaction_target_id, decision.interaction_type)
        if decision.goal is StrategicGoalKind.WAIT:
            return WaitAction(DEFAULT_POLICY_WAIT_SECONDS, decision.reason)
        selected = self._candidate(context, decision.target_candidate_index)
        if selected is None:
            return None
        mob = selected.mob
        attack_point = _attack_point_for(context, selected)
        return TargetAction(
            mob.class_id,
            Position(mob.x, mob.y),
            round(math.hypot(mob.x - world_state.position.x, mob.y - world_state.position.y), 6),
            attack_point,
            candidate_index=selected.original_position,
        )

    @staticmethod
    def _candidate(
        context: PolicyContext, target_candidate_index: int | None
    ) -> PolicyCandidate | None:
        if target_candidate_index is None:
            return None
        return next(
            (
                item
                for item in context.candidates
                if item.is_eligible and item.original_position == target_candidate_index
            ),
            None,
        )


class HierarchicalPolicy:
    """Compose high- and mid-level decisions behind the TacticalPolicy protocol."""

    def __init__(
        self,
        *,
        objective: HierarchicalObjective | None = None,
        high_level: HighLevelStrategicPolicy | None = None,
        mid_level: MidLevelTacticalPolicy | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.objective = objective or HierarchicalObjective()
        self.high_level = high_level or HighLevelStrategicPolicy(monotonic=monotonic)
        self.mid_level = mid_level or MidLevelTacticalPolicy()
        self._monotonic = monotonic
        self.last_telemetry: HierarchicalTelemetry | None = None

    def evaluate(
        self,
        world_state: WorldState,
        context: PolicyContext,
        objective: HierarchicalObjective | None = None,
    ) -> TacticalActionPayload | None:
        active_objective = objective or self.objective
        started_at = self._monotonic()
        try:
            decision = self.high_level.evaluate(world_state, context, active_objective)
            action = self.mid_level.evaluate_for_goal(world_state, context, decision)
        except (TypeError, ValueError) as error:
            self.last_telemetry = HierarchicalTelemetry(
                StrategicGoalKind.WAIT,
                "hierarchy_fault",
                max(self._monotonic() - started_at, 0.0),
                True,
                str(error) or type(error).__name__,
            )
            return None
        elapsed = self._monotonic() - started_at
        action_kind = action.kind if action is not None else None
        if elapsed > POLICY_LATENCY_BUDGET_SECONDS:
            self.last_telemetry = HierarchicalTelemetry(
                decision.goal,
                decision.reason,
                elapsed,
                True,
                "policy_latency_budget_exceeded",
                action_kind,
            )
            return None
        fallback_reason = None if action is not None else "no_valid_action"
        self.last_telemetry = HierarchicalTelemetry(
            decision.goal,
            decision.reason,
            elapsed,
            action is None,
            fallback_reason,
            action_kind,
        )
        return action


def _attack_point_for(
    context: PolicyContext, candidate: PolicyCandidate
) -> AttackPointAction | None:
    """Resolve the approach belonging to this exact candidate instance, never to its class."""

    return next(
        (
            item
            for item in context.valid_attack_points
            if (
                item.candidate_index == candidate.original_position
                if item.candidate_index is not None
                else item.target_id == candidate.mob.class_id
            )
        ),
        None,
    )


def _screen_distance_squared(candidate: PolicyCandidate, center: Position) -> float:
    delta_x = candidate.mob.x + candidate.mob.width // 2 - center.x
    delta_y = candidate.mob.y + candidate.mob.height // 2 - center.y
    return delta_x * delta_x + delta_y * delta_y
