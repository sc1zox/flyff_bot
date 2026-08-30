"""Deadline, exception, and invalid-action fail-closed coverage."""

from flyff_bot.features.automation.models import Position, Viewport, WorldState
from flyff_bot.features.policy.models import PolicyContext, TargetAction
from flyff_bot.features.policy.runner import (
    HEURISTIC_MODE_REASON,
    PolicyFaultCode,
    PolicyRunner,
)


class _ExplodingPolicy:
    def evaluate(self, _state: WorldState, _context: PolicyContext) -> TargetAction:
        raise ValueError("invalid_output")


def _world_state() -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=0,
        progress_marker=0,
        viewport=Viewport(100, 100),
    )


def test_exception_stops_learned_automation_without_a_silent_heuristic_substitute() -> None:
    runner = PolicyRunner(_ExplodingPolicy())

    action = runner.evaluate(_world_state(), PolicyContext((), frozenset(), ()))

    assert action is None
    assert runner.last_fault is not None
    assert runner.last_fault.code is PolicyFaultCode.POLICY_EXCEPTION
    assert "invalid_output" in str(runner.last_fault.detail)


def test_latency_budget_is_enforced() -> None:
    class _SlowValidPolicy:
        @staticmethod
        def evaluate(_state: WorldState, _context: PolicyContext) -> None:
            return None

    times = iter((0.0, 0.006))
    runner = PolicyRunner(_SlowValidPolicy(), monotonic=lambda: next(times))

    action = runner.evaluate(_world_state(), PolicyContext((), frozenset(), ()))

    assert action is None
    assert runner.last_fault is not None
    assert runner.last_fault.code is PolicyFaultCode.LATENCY_BUDGET_EXCEEDED


def test_without_a_learned_policy_the_deterministic_baseline_still_runs() -> None:
    runner = PolicyRunner(None)

    action = runner.evaluate(_world_state(), PolicyContext((), frozenset(), ()))

    assert runner.last_fault is None
    assert runner.last_fallback_reason == HEURISTIC_MODE_REASON
    assert action is not None and action.kind.value == "wait"
