"""Two-tier decision frequency and objective coverage for US-073."""

from __future__ import annotations

from dataclasses import replace

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.policy.action_payloads import InteractAction, NavigateAction, TargetAction
from flyff_bot.features.policy.hierarchical import (
    HierarchicalObjective,
    HierarchicalObjectiveKind,
    HierarchicalPolicy,
    HighLevelStrategicPolicy,
)
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext


def _state() -> WorldState:
    return WorldState(1.0, Position(50, 50), 2, (), 0, viewport=Viewport(100, 100))


def _candidate(identifier: int, position: int, *, reachable: bool = True) -> PolicyCandidate:
    return PolicyCandidate(
        VisibleMob(
            identifier,
            f"Mob{identifier}",
            0.9,
            identifier * 10,
            20,
            5,
            5,
            1.0,
            2.0,
            3.0,
            navmesh_path_distance=float(identifier),
        ),
        True,
        True,
        True,
        reachable,
        True,
        position,
    )


def _context(*candidates: PolicyCandidate, token: object = 0) -> PolicyContext:
    return PolicyContext(
        tuple(candidates),
        frozenset(),
        tuple(not item.is_unlocked for item in candidates),
        macro_event_token=(token,),
    )


def test_high_level_retains_specific_target_until_macro_state_changes() -> None:
    times = iter((0.0, 0.1, 0.2))
    high = HighLevelStrategicPolicy(monotonic=lambda: next(times))
    first = _candidate(1, 10)
    second = _candidate(2, 20)

    initial = high.evaluate(_state(), _context(first, second), HierarchicalObjective())
    retained = high.evaluate(_state(), _context(first, second), HierarchicalObjective())
    changed = high.evaluate(
        _state(),
        _context(replace(first, is_navmesh_reachable=False), second, token="lockout"),
        HierarchicalObjective(),
    )

    assert initial is retained
    assert initial.target_candidate_index == 10
    assert changed.target_candidate_index == 20


def test_navigation_and_multistep_quest_interaction_use_prevalidated_options() -> None:
    destination = (10.0, 2.0, 30.0)
    navigation_context = replace(_context(), valid_destinations=frozenset((destination,)))
    policy = HierarchicalPolicy(
        objective=HierarchicalObjective(
            HierarchicalObjectiveKind.NAVIGATION, destination=destination
        )
    )

    navigation = policy.evaluate(_state(), navigation_context)
    quest = policy.evaluate(
        _state(),
        replace(
            navigation_context,
            valid_interactions=frozenset((("npc-7", "quest"),)),
            macro_event_token=("quest-progress",),
        ),
        HierarchicalObjective(
            HierarchicalObjectiveKind.QUEST,
            destination=destination,
            quest_id="Q1",
            objective_index=1,
            objective_count=2,
            progress=1.0,
            required_progress=1.0,
            destination_reached=True,
            interaction_target_id="npc-7",
        ),
    )

    assert isinstance(navigation, NavigateAction)
    assert isinstance(quest, InteractAction)


def test_hierarchical_policy_returns_typed_target_inside_latency_budget() -> None:
    times = iter((0.0, 0.0001, 0.001))
    policy = HierarchicalPolicy(monotonic=lambda: next(times))

    action = policy.evaluate(_state(), _context(_candidate(1, 0)))

    assert isinstance(action, TargetAction)
    assert action.target_pos == Position(10, 20)
    assert policy.last_telemetry is not None
    assert policy.last_telemetry.inference_seconds < 0.005
