"""Deadline-guarded policy execution with immediate deterministic fallback."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.policy.heuristic import HeuristicPolicy
from flyff_bot.features.policy.hierarchical import HierarchicalObjective
from flyff_bot.features.policy.hierarchical_masking import validate_policy_action
from flyff_bot.features.policy.models import (
    POLICY_LATENCY_BUDGET_SECONDS,
    PolicyContext,
    TacticalAction,
)


class LearnedPolicyProtocol(Protocol):
    """The minimal learned-policy surface used by the fallback runner."""

    def evaluate(self, world_state: WorldState, context: PolicyContext) -> TacticalAction | None:
        """Evaluate one legal learned action."""


@runtime_checkable
class GoalConditionedPolicy(Protocol):
    """A learned policy whose decision is conditioned on the currently pursued goal."""

    objective: HierarchicalObjective


FallbackPolicyFactory = Callable[[], LearnedPolicyProtocol]


class PolicyRunner:
    """Evaluate a learned policy and fall back on every invalid, late, or failed result."""

    def __init__(
        self,
        learned: LearnedPolicyProtocol | None = None,
        *,
        heuristic_factory: FallbackPolicyFactory = HeuristicPolicy,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._learned = learned
        self._heuristic_factory = heuristic_factory
        self._monotonic = monotonic
        self._objective: HierarchicalObjective | None = None
        self.last_fallback_reason: str | None = None

    @property
    def objective(self) -> HierarchicalObjective | None:
        """Return the goal this runner was last conditioned on, if any."""

        return self._objective

    def set_objective(self, objective: HierarchicalObjective) -> bool:
        """Condition the learned policy on one goal and report whether it accepted it.

        A learned policy that is not goal-conditioned still leaves the objective recorded,
        so the session can state which goal a decision was made under either way.
        """

        self._objective = objective
        learned = self._learned
        if not isinstance(learned, GoalConditionedPolicy):
            return False
        learned.objective = objective
        return True

    @property
    def fell_back(self) -> bool:
        """Return whether the latest evaluation used the deterministic baseline."""

        return self.last_fallback_reason is not None

    def evaluate(self, world_state: WorldState, context: PolicyContext) -> TacticalAction | None:
        """Return one legal action, never propagating learned-policy faults upward."""

        if self._learned is not None:
            started_at = self._monotonic()
            try:
                action = self._learned.evaluate(world_state, context)
                elapsed = self._monotonic() - started_at
                if elapsed > POLICY_LATENCY_BUDGET_SECONDS:
                    raise TimeoutError("policy_latency_budget_exceeded")
                if action is not None and validate_policy_action(action, context):
                    self.last_fallback_reason = None
                    return action
                if action is not None:
                    raise ValueError("invalid_or_masked_action")
                self.last_fallback_reason = "no_valid_action"
            except (AttributeError, TypeError, ValueError, OSError, TimeoutError) as error:
                self.last_fallback_reason = str(error) or type(error).__name__
            except Exception as error:
                self.last_fallback_reason = f"policy_exception:{type(error).__name__}"
        else:
            self.last_fallback_reason = "heuristic_mode"
        action = self._heuristic_factory().evaluate(world_state, context)
        if action is None:
            self.last_fallback_reason = self.last_fallback_reason or "no_heuristic_action"
        return action
