"""Final deterministic masking for every tactical action family."""

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    TargetAction,
)
from flyff_bot.features.policy.hierarchical_masking import validate_policy_action
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext
from flyff_bot.features.policy.runner import PolicyFault, PolicyFaultCode, PolicyRunner


def _candidate(*, eligible: bool = True) -> PolicyCandidate:
    return PolicyCandidate(
        VisibleMob(7, "Aibatt", 0.9, 10, 20, 5, 5, 1.0, 2.0, 3.0),
        eligible,
        eligible,
        eligible,
        eligible,
        eligible,
        0,
    )


def _context(candidate: PolicyCandidate) -> PolicyContext:
    attack = AttackPointAction(7, (1.0, 2.0, 3.0), 0.0)
    return PolicyContext(
        (candidate,),
        frozenset(),
        (not candidate.is_unlocked,),
        valid_destinations=frozenset(((4.0, 5.0, 6.0),)),
        valid_corridor_ids=frozenset(("corridor-1",)),
        valid_interactions=frozenset((("npc-1", "quest"),)),
        valid_attack_points=(attack,),
    )


def test_only_exact_prevalidated_target_route_corridor_and_interaction_are_allowed() -> None:
    context = _context(_candidate())

    assert validate_policy_action(TargetAction(7, Position(10, 20), candidate_index=0), context)
    assert validate_policy_action(NavigateAction((4.0, 5.0, 6.0), "goal"), context)
    assert validate_policy_action(CorridorAction(7, "corridor-1", 0), context)
    assert validate_policy_action(InteractAction("npc-1", "quest"), context)
    assert validate_policy_action(context.valid_attack_points[0], context)
    assert not validate_policy_action(NavigateAction((9.0, 9.0, 9.0), "fabricated"), context)
    assert not validate_policy_action(CorridorAction(7, "blocked", 0), context)
    assert not validate_policy_action(InteractAction("unknown", "quest"), context)


def test_masked_or_fabricated_learned_output_stops_instead_of_acting_heuristically() -> None:
    class _FabricatingPolicy:
        @staticmethod
        def evaluate(_state: WorldState, _context: PolicyContext) -> NavigateAction:
            return NavigateAction((99.0, 0.0, 99.0), "fabricated")

    state = WorldState(1.0, Position(0, 0), 0, 0, viewport=Viewport(100, 100))
    context = _context(_candidate(eligible=False))
    runner = PolicyRunner(_FabricatingPolicy())

    action = runner.evaluate(state, context)

    assert action is None
    assert runner.last_fault == PolicyFault(PolicyFaultCode.INVALID_OR_MASKED_ACTION)
