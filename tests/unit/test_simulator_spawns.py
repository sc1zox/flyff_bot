"""Spawn caps, respawn timing, stochastic combat, and stall behavior."""

from __future__ import annotations

import math
from collections.abc import Callable

from flyff_bot.features.simulator import (
    FarmingSimulator,
    MonsterLifecycle,
    QuestObjective,
    QuestObjectiveKind,
    SimulatorConfig,
)


def test_combat_samples_are_positive_and_deterministic(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    first = make_simulator(
        SimulatorConfig(combat_time_mu=1.5, tick_seconds=0.1),
        objectives=(QuestObjective(QuestObjectiveKind.KILL, monster_id=7, required_count=1),),
    )
    second = make_simulator(
        SimulatorConfig(combat_time_mu=1.5, tick_seconds=0.1),
        objectives=(QuestObjective(QuestObjectiveKind.KILL, monster_id=7, required_count=1),),
    )
    first.reset()
    second.reset()

    nearest = min(
        (monster for monster in first._monsters if monster.lifecycle is MonsterLifecycle.ALIVE),
        key=lambda monster: math.hypot(
            monster.position_x - 10.0,
            monster.position_z - 10.0,
        ),
    )
    first._target = nearest
    second._monsters = [second._monsters[0]]
    second._target = second._monsters[0]
    first._monsters = [nearest]
    first.step(2)
    second.step(2)

    assert first.metrics.kill_count == 1
    assert second.metrics.kill_count == first.metrics.kill_count
    assert second.metrics.combat_seconds == first.metrics.combat_seconds
    assert first.metrics.combat_seconds > 0.0


def test_dead_monsters_respawn_after_the_zone_timer_without_exceeding_capacity(
    make_simulator: Callable[[], FarmingSimulator],
) -> None:
    simulation = make_simulator()
    observation, _info = simulation.reset()
    initial_alive = sum(
        monster.lifecycle is MonsterLifecycle.ALIVE for monster in simulation._monsters
    )

    assert initial_alive == 2
    assert len(observation.candidates) <= 4
    simulation._monsters[0] = type(simulation._monsters[0])(
        7,
        0,
        simulation._monsters[0].position_x,
        simulation._monsters[0].position_z,
        MonsterLifecycle.DEAD,
        available_at_seconds=1.0,
    )
    simulation.step(3)

    alive_after_tick = sum(
        monster.lifecycle is MonsterLifecycle.ALIVE for monster in simulation._monsters
    )
    assert len(simulation._monsters) == 2
    assert alive_after_tick == 1
