"""Tests for the synthetic, platform-independent automation foundation."""

from __future__ import annotations

from flyff_bot.features.automation.controllers import (
    CombatController,
    ControllerMode,
    LootController,
    NavigationController,
)
from flyff_bot.features.automation.executor import VerifiedExecutor
from flyff_bot.features.automation.models import (
    Action,
    ActionKind,
    DesiredState,
    FailureFlag,
    InventoryEntry,
    Observation,
    ObservationKind,
    Position,
    WorldState,
)
from flyff_bot.features.automation.planner import Goal, Planner, PlanningAction
from flyff_bot.features.automation.supervisor import Supervisor, SupervisorConfig


def _state(
    *,
    observed_at_seconds: float = 0.0,
    mob_count: int = 0,
    inventory: tuple[InventoryEntry, ...] = (),
    marker: int = 0,
    is_stuck: bool = False,
) -> WorldState:
    return WorldState(
        observed_at_seconds=observed_at_seconds,
        position=Position(0, 0),
        nearby_mob_count=mob_count,
        inventory=inventory,
        progress_marker=marker,
        is_stuck=is_stuck,
    )


def test_planner_returns_shortest_strips_sequence() -> None:
    find_mob = PlanningAction("find-mob", frozenset(), frozenset({"mob-found"}))
    defeat_mob = PlanningAction("defeat-mob", frozenset({"mob-found"}), frozenset({"mob-defeated"}))

    plan = Planner().plan(frozenset(), Goal(frozenset({"mob-defeated"})), (find_mob, defeat_mob))

    assert plan == (find_mob, defeat_mob)


def test_planner_returns_none_when_preconditions_cannot_be_met() -> None:
    action = PlanningAction("defeat-mob", frozenset({"mob-found"}), frozenset({"mob-defeated"}))

    assert Planner().plan(frozenset(), Goal(frozenset({"mob-defeated"})), (action,)) is None


def test_supervisor_detects_all_configured_failures() -> None:
    supervisor = Supervisor(SupervisorConfig(no_progress_timeout_seconds=5.0))
    desired = DesiredState(minimum_mob_count=1, required_inventory=(InventoryEntry("potion", 2),))
    supervisor.reconcile(desired, _state(marker=1))

    result = supervisor.reconcile(
        desired,
        _state(observed_at_seconds=5.0, marker=1, is_stuck=True),
    )

    assert result.failures == frozenset(FailureFlag)


def test_supervisor_resets_no_progress_timeout_after_progress() -> None:
    supervisor = Supervisor(SupervisorConfig(no_progress_timeout_seconds=5.0))
    desired = DesiredState()
    supervisor.reconcile(desired, _state(marker=1))
    supervisor.reconcile(desired, _state(observed_at_seconds=5.0, marker=1))

    result = supervisor.reconcile(desired, _state(observed_at_seconds=6.0, marker=2))

    assert result.is_healthy


class _Dispatcher:
    def __init__(self) -> None:
        self.actions: list[Action] = []

    def dispatch(self, action: Action) -> None:
        self.actions.append(action)


class _Reader:
    def __init__(self, observation: Observation) -> None:
        self.observation = observation

    def observe(self) -> Observation:
        return self.observation


def test_executor_only_confirms_matching_post_action_observation() -> None:
    action = Action("attack", ActionKind.ATTACK, ObservationKind.TARGET_ENGAGED)
    dispatcher = _Dispatcher()
    reader = _Reader(Observation(ObservationKind.TARGET_ENGAGED, 1.0, True))

    result = VerifiedExecutor(dispatcher, reader).execute(action)

    assert dispatcher.actions == [action]
    assert result.is_successful


def test_executor_rejects_unconfirmed_observation() -> None:
    action = Action("attack", ActionKind.ATTACK, ObservationKind.TARGET_ENGAGED)
    reader = _Reader(Observation(ObservationKind.TARGET_ENGAGED, 1.0, False))

    assert not VerifiedExecutor(_Dispatcher(), reader).execute(action).is_successful


def test_controllers_transition_from_synthetic_state_feed() -> None:
    combat = CombatController()
    navigation = NavigationController()
    loot = LootController()
    loot_state = _state(inventory=(InventoryEntry("coin", 1),))

    assert combat.step(_state(mob_count=1)).mode is ControllerMode.ACTIVE
    assert navigation.step(_state(is_stuck=True)).mode is ControllerMode.RECOVERING
    assert loot.step(loot_state).mode is ControllerMode.ACTIVE
    assert loot.step(loot_state).mode is ControllerMode.IDLE
