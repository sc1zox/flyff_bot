"""Deadline, exception, and invalid-action fallback coverage."""

from flyff_bot.features.automation.models import Position, Viewport, WorldState
from flyff_bot.features.policy.models import PolicyContext, TargetAction
from flyff_bot.features.policy.runner import PolicyRunner


class _ExplodingPolicy:
    def evaluate(self, _state: WorldState, _context: PolicyContext) -> TargetAction:
        raise ValueError("invalid_output")


def _world_state() -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=0,
        inventory=(),
        progress_marker=0,
        viewport=Viewport(100, 100),
    )


def test_exception_triggers_immediate_heuristic_fallback() -> None:
    runner = PolicyRunner(_ExplodingPolicy())

    action = runner.evaluate(_world_state(), PolicyContext((), frozenset(), ()))

    assert runner.fell_back
    assert "invalid_output" in str(runner.last_fallback_reason)
    assert action is not None and action.kind.value == "wait"


def test_latency_budget_is_enforced() -> None:
    class _SlowValidPolicy:
        @staticmethod
        def evaluate(_state: WorldState, _context: PolicyContext) -> None:
            return None

    times = iter((0.0, 0.006))
    runner = PolicyRunner(_SlowValidPolicy(), monotonic=lambda: next(times))

    runner.evaluate(_world_state(), PolicyContext((), frozenset(), ()))

    assert runner.last_fallback_reason == "policy_latency_budget_exceeded"
