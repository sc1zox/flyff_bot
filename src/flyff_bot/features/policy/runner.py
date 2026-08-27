"""Deadline-guarded policy execution that fails closed instead of degrading silently."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
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

HEURISTIC_MODE_REASON = "heuristic_mode"


class PolicyFaultCode(StrEnum):
    """Machine-readable reasons learned automation must stop instead of continuing."""

    MODEL_UNAVAILABLE = "model_unavailable"
    NO_VALID_ACTION = "no_valid_action"
    INVALID_OR_MASKED_ACTION = "invalid_or_masked_action"
    LATENCY_BUDGET_EXCEEDED = "latency_budget_exceeded"
    POLICY_EXCEPTION = "policy_exception"


@dataclass(frozen=True, slots=True)
class PolicyFault:
    """One learned-policy failure, ready to be shown as a localized diagnostic."""

    code: PolicyFaultCode
    detail: str | None = None

    @property
    def reason(self) -> str:
        """Return the compact operator-facing reason string for this fault."""

        return self.code.value if self.detail is None else f"{self.code.value}:{self.detail}"


class LearnedPolicyProtocol(Protocol):
    """The minimal learned-policy surface used by the runner."""

    def evaluate(self, world_state: WorldState, context: PolicyContext) -> TacticalAction | None:
        """Evaluate one legal learned action."""


@runtime_checkable
class GoalConditionedPolicy(Protocol):
    """A learned policy whose decision is conditioned on the currently pursued goal."""

    objective: HierarchicalObjective


FallbackPolicyFactory = Callable[[], LearnedPolicyProtocol]


class PolicyRunner:
    """Evaluate a learned policy, reporting a fault rather than quietly acting heuristically.

    A missing, incompatible, non-finite, masked, or late learned result is a fault the session
    has to react to. Substituting :class:`HeuristicPolicy` for it would present heuristic
    behaviour as learned behaviour, so the runner refuses to do that (BUG-031). The
    deterministic baseline is only produced when no learned policy is configured at all.
    """

    def __init__(
        self,
        learned: LearnedPolicyProtocol | None = None,
        *,
        heuristic_factory: FallbackPolicyFactory = HeuristicPolicy,
        monotonic: Callable[[], float] = time.monotonic,
        load_fault: PolicyFault | None = None,
    ) -> None:
        self._learned = learned
        self._heuristic_factory = heuristic_factory
        self._monotonic = monotonic
        self._load_fault = load_fault
        self._objective: HierarchicalObjective | None = None
        self.last_fault: PolicyFault | None = None
        self.last_fallback_reason: str | None = None

    @property
    def has_learned_policy(self) -> bool:
        """Return whether a learned artifact is actually loaded and servable."""

        return self._learned is not None

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

    def reset_fault(self) -> None:
        """Clear the recorded fault after an operator acknowledged it."""

        self.last_fault = None
        self.last_fallback_reason = None

    def evaluate(self, world_state: WorldState, context: PolicyContext) -> TacticalAction | None:
        """Return one legal learned action, or ``None`` alongside a recorded fault."""

        if self._learned is None:
            if self._load_fault is not None:
                self._fail(self._load_fault)
                return None
            self.last_fault = None
            self.last_fallback_reason = HEURISTIC_MODE_REASON
            return self._heuristic_factory().evaluate(world_state, context)

        started_at = self._monotonic()
        try:
            action = self._learned.evaluate(world_state, context)
            elapsed = self._monotonic() - started_at
        except (AttributeError, TypeError, ValueError, OSError) as error:
            self._fail(PolicyFault(PolicyFaultCode.POLICY_EXCEPTION, str(error) or None))
            return None
        except Exception as error:
            self._fail(PolicyFault(PolicyFaultCode.POLICY_EXCEPTION, type(error).__name__))
            return None
        if elapsed > POLICY_LATENCY_BUDGET_SECONDS:
            self._fail(PolicyFault(PolicyFaultCode.LATENCY_BUDGET_EXCEEDED))
            return None
        if action is None:
            self._fail(PolicyFault(PolicyFaultCode.NO_VALID_ACTION))
            return None
        if not validate_policy_action(action, context):
            self._fail(PolicyFault(PolicyFaultCode.INVALID_OR_MASKED_ACTION))
            return None
        self.last_fault = None
        self.last_fallback_reason = None
        return action

    def _fail(self, fault: PolicyFault) -> None:
        self.last_fault = fault
        self.last_fallback_reason = fault.reason
