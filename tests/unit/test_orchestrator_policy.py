"""Orchestrator policy-mode integration and safety isolation coverage."""

from typing import cast

from test_orchestrator import WINDOW_HANDLE, _InputAdapter, _Pipeline, _state

from flyff_bot.features.automation.models import Position, VisibleMob, WorldState
from flyff_bot.features.automation.orchestrator import (
    FarmingMode,
    FarmingOrchestrator,
    PolicyRuntimeMode,
)
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.policy.models import (
    AttackPointAction,
    PolicyContext,
    TargetAction,
)
from flyff_bot.features.policy.runner import PolicyRunner


class _AlwaysFirstPolicy:
    def evaluate(self, _state: WorldState, context: PolicyContext) -> TargetAction | None:
        eligible = [candidate for candidate in context.candidates if candidate.is_eligible]
        if not eligible:
            return None
        mob = eligible[0].mob
        return TargetAction(
            mob.class_id,
            Position(mob.x, mob.y),
            candidate_index=eligible[0].original_position,
        )


def _orchestrator(states: list[WorldState], adapter: _InputAdapter) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
    )


def test_policy_mode_is_selectable_without_changing_farming_mode() -> None:
    state = _state(1.0, mobs=())
    orchestrator = _orchestrator([state], _InputAdapter())

    orchestrator.configure_policy_mode(PolicyRuntimeMode.ML_ACTIVE)

    assert orchestrator._policy_mode is PolicyRuntimeMode.ML_ACTIVE
    assert orchestrator.mode is FarmingMode.PAUSED


def test_learned_target_enters_existing_guarded_combat_state_machine() -> None:
    mob = VisibleMob(
        class_id=2,
        class_name="Learned",
        confidence=0.9,
        x=20,
        y=20,
        width=10,
        height=10,
        world_x=1.0,
        world_y=0.0,
        world_z=1.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    state = _state(1.0, mobs=(mob,))
    adapter = _InputAdapter()
    orchestrator = _orchestrator([state], adapter)
    orchestrator.configure_policy_mode(PolicyRuntimeMode.ML_ACTIVE)
    orchestrator._policy_runner = PolicyRunner(_AlwaysFirstPolicy())
    orchestrator.start()

    orchestrator.tick()

    assert orchestrator.mode in {FarmingMode.SEARCHING, FarmingMode.TARGETING}
    if orchestrator.mode is FarmingMode.TARGETING:
        assert adapter.clicks == [(WINDOW_HANDLE, 25, 25)]


def test_valid_contextual_approach_distance_is_applied_for_one_live_decision() -> None:
    mob = VisibleMob(
        2,
        "Learned",
        0.9,
        20,
        20,
        10,
        10,
        world_x=1.0,
        world_y=0.0,
        world_z=1.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    state = _state(1.0, mobs=(mob,))
    action = TargetAction(
        mob.class_id,
        Position(mob.x, mob.y),
        attack_point=AttackPointAction(
            mob.class_id,
            (1.0, 0.0, 1.0),
            90.0,
            0,
            4.5,
        ),
        candidate_index=0,
    )

    class _ValidatedRunner:
        last_fault = None

        def evaluate(self, _world_state: WorldState, _context: PolicyContext) -> TargetAction:
            return action

    orchestrator = _orchestrator([state], _InputAdapter())
    orchestrator._state = state
    orchestrator.configure_policy_mode(PolicyRuntimeMode.ML_ACTIVE)
    orchestrator._policy_runner = cast(PolicyRunner, _ValidatedRunner())

    selected = orchestrator._evaluate_policy_target()

    assert selected is mob
    assert not orchestrator._should_dispatch_direct_click(mob)
    assert orchestrator.pathing_engagement_distance == 4.5
    assert orchestrator._policy_attack_point_override is action.attack_point
