"""Shadow-mode isolation: learned output never governs the execution baseline."""

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.policy.heuristic import HeuristicPolicy
from flyff_bot.features.policy.models import (
    PolicyCandidate,
    PolicyContext,
    TargetAction,
)


class _LearnedPolicy:
    @staticmethod
    def evaluate(_state: WorldState, context: PolicyContext) -> TargetAction | None:
        eligible = [candidate for candidate in context.candidates if candidate.is_eligible]
        if not eligible:
            return None
        mob = eligible[0].mob
        return TargetAction(mob.class_id, Position(mob.x, mob.y))


def _context(first: VisibleMob, second: VisibleMob) -> PolicyContext:
    candidates = tuple(
        PolicyCandidate(mob, True, True, True, True, True) for mob in (first, second)
    )
    return PolicyContext(candidates, frozenset(), (False, False))


def test_shadow_records_learned_choice_without_replacing_execution_baseline() -> None:
    first = VisibleMob(class_id=1, class_name="A", confidence=0.9, x=10, y=10, width=5, height=5)
    second = VisibleMob(class_id=2, class_name="B", confidence=0.9, x=80, y=80, width=5, height=5)
    state = WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=2,
        progress_marker=0,
        visible_mobs=(first, second),
        viewport=Viewport(100, 100),
    )
    learned = _LearnedPolicy.evaluate(state, _context(first, second))
    executed = HeuristicPolicy().evaluate(state, _context(first, second))

    assert isinstance(learned, TargetAction) and learned.target_id == 1
    assert isinstance(executed, TargetAction) and executed.target_id == 2
