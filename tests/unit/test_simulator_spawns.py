"""Spawn caps, respawn timing, stochastic combat, and stall behavior."""

from __future__ import annotations

from collections.abc import Callable

from flyff_bot.features.policy.action_payloads import (
    StrategicGoalKind,
    strategic_goal_index,
)
from flyff_bot.features.simulator import (
    FarmingSimulator,
    MonsterLifecycle,
    ObjectiveKind,
    QuestObjective,
    SimulatorConfig,
)

FARMING_PRIORITY = tuple(
    strategic_goal_index(goal)
    for goal in (
        StrategicGoalKind.INTERACT,
        StrategicGoalKind.NAVIGATE,
        StrategicGoalKind.TARGET,
        StrategicGoalKind.WAIT,
    )
)


def farm_until_first_kill(simulation: FarmingSimulator, *, step_limit: int = 400) -> int:
    """Play the deterministic farming priority until the first kill is recorded."""

    for step_index in range(step_limit):
        mask = simulation.action_mask
        action = next(item for item in FARMING_PRIORITY if mask[item])
        _observation, _reward, terminated, truncated, _info = simulation.step(action)
        if simulation.metrics.kill_count or terminated or truncated:
            return step_index
    return step_limit


def test_combat_samples_are_positive_and_deterministic(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    objectives = (QuestObjective(ObjectiveKind.KILL, monster_id=7, required_count=1),)
    config = SimulatorConfig(combat_time_mu=1.5, tick_seconds=0.1)
    first = make_simulator(config, objectives=objectives)
    second = make_simulator(config, objectives=objectives)
    first.reset(seed=42)
    second.reset(seed=42)

    farm_until_first_kill(first)
    farm_until_first_kill(second)

    assert first.metrics.kill_count == 1
    assert second.metrics.kill_count == first.metrics.kill_count
    assert second.metrics.combat_seconds == first.metrics.combat_seconds
    assert first.metrics.combat_seconds > 0.0


def test_a_kill_costs_the_sampled_combat_duration(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(combat_time_mu=3.0, combat_time_sigma=0.0, tick_seconds=0.5),
        objectives=(QuestObjective(ObjectiveKind.KILL, monster_id=7, required_count=1),),
    )
    simulation.reset(seed=5)

    farm_until_first_kill(simulation)

    assert simulation.metrics.kill_count == 1
    assert simulation.metrics.combat_seconds >= 3.0


def test_dead_monsters_respawn_after_the_zone_timer_without_exceeding_capacity(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(tick_seconds=0.5),
        objectives=(QuestObjective(ObjectiveKind.KILL, monster_id=7, required_count=4),),
    )
    observation, _info = simulation.reset(seed=3)

    assert len(observation.candidates) <= 4
    farm_until_first_kill(simulation)
    dead_after_kill = [
        monster for monster in simulation._monsters if monster.lifecycle is MonsterLifecycle.DEAD
    ]

    assert len(simulation._monsters) == 2
    assert len(dead_after_kill) == 1
    for _tick in range(4):
        simulation.step(strategic_goal_index(StrategicGoalKind.WAIT))
    assert all(monster.lifecycle is not MonsterLifecycle.DEAD for monster in simulation._monsters)
