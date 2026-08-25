"""Regression coverage for BUG-032: simulated dynamics that a client could produce.

Every metric the hierarchical training run reports is derived from this simulator's clock,
its action mask, and its movement, so each of these tests pins one dynamic the training
metrics would otherwise silently overstate.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from flyff_bot.features.navigation.world_extractor import WorldCoordinate, WorldVectorMap
from flyff_bot.features.rl.rewards import (
    REWARD_CONFIG_VERSION,
    RewardConfig,
    RewardEngine,
    RewardEvent,
)
from flyff_bot.features.simulator import (
    FarmingSimulator,
    IllegalSimulatorAction,
    MonsterLifecycle,
    QuestObjective,
    QuestObjectiveKind,
    SimulatorConfig,
    TacticalAction,
)
from flyff_bot.features.simulator.engine import MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS

FARMING_PRIORITY = (
    TacticalAction.INTERACT,
    TacticalAction.GO_TO_OBJECTIVE,
    TacticalAction.TARGET_NEAREST,
    TacticalAction.WAIT,
)
ACCOUNTING_TOLERANCE_SECONDS = 1e-6
START = WorldCoordinate(10.0, 10.0)


def farm(simulation: FarmingSimulator, *, step_limit: int = 2000) -> bool:
    """Play the deterministic farming priority; return whether the episode ended."""

    for _step in range(step_limit):
        mask = simulation.action_mask
        action = next(item for item in FARMING_PRIORITY if mask[int(item)])
        _observation, _reward, terminated, truncated, _info = simulation.step(int(action))
        if terminated or truncated:
            return True
    return False


def kill_objective(count: int = 1) -> tuple[QuestObjective, ...]:
    return (QuestObjective(QuestObjectiveKind.KILL, monster_id=7, required_count=count),)


def test_engaging_a_distant_monster_costs_travel_time_and_distance(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(tick_seconds=0.5, maximum_episode_seconds=120.0),
        objectives=kill_objective(),
    )
    observation, _info = simulation.reset(seed=17)
    nearest = min(candidate.path_distance or 0.0 for candidate in observation.candidates)

    assert nearest > MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS
    assert not simulation.action_mask[int(TacticalAction.INTERACT)]

    farm(simulation)
    metrics = simulation.metrics

    assert metrics.kill_count >= 1
    assert metrics.distance_units >= nearest - MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS
    assert metrics.travel_seconds >= metrics.distance_units / simulation.nominal_speed
    assert metrics.combat_seconds > 0.0


def test_the_player_only_moves_by_travelling(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(tick_seconds=0.5, maximum_episode_seconds=60.0),
        objectives=kill_objective(3),
    )
    observation, _info = simulation.reset(seed=23)
    previous = (observation.kinematics.position_x, observation.kinematics.position_z)
    previous_distance = 0.0

    for _step in range(120):
        mask = simulation.action_mask
        action = next(item for item in FARMING_PRIORITY if mask[int(item)])
        observation, _reward, terminated, truncated, _info = simulation.step(int(action))
        moved = math.hypot(
            observation.kinematics.position_x - previous[0],
            observation.kinematics.position_z - previous[1],
        )
        travelled = simulation.metrics.distance_units - previous_distance
        assert moved == pytest.approx(travelled, abs=1e-9)
        previous = (observation.kinematics.position_x, observation.kinematics.position_z)
        previous_distance = simulation.metrics.distance_units
        if terminated or truncated:
            break


def test_elapsed_time_equals_the_sum_of_the_activity_buckets(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(
            tick_seconds=0.5,
            maximum_episode_seconds=180.0,
            stuck_probability_per_unit=0.05,
        ),
        objectives=(),
    )
    simulation.reset(seed=29)

    farm(simulation)
    metrics = simulation.metrics

    assert metrics.stuck_count > 0
    assert metrics.recovery_seconds > 0.0
    assert metrics.elapsed_seconds == pytest.approx(
        metrics.travel_seconds
        + metrics.combat_seconds
        + metrics.recovery_seconds
        + metrics.idle_seconds,
        abs=ACCOUNTING_TOLERANCE_SECONDS,
    )


def test_recovery_blocks_every_action_but_waiting(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(
            tick_seconds=0.5,
            maximum_episode_seconds=180.0,
            stuck_probability_per_unit=0.5,
            recovery_time_mu=5.0,
            recovery_time_sigma=0.0,
        ),
        objectives=(),
    )
    simulation.reset(seed=31)

    for _step in range(200):
        mask = simulation.action_mask
        action = next(item for item in FARMING_PRIORITY if mask[int(item)])
        simulation.step(int(action))
        if simulation.metrics.stuck_count:
            break

    assert simulation.metrics.stuck_count > 0
    assert simulation.action_mask == (False, False, False, True)
    with pytest.raises(IllegalSimulatorAction):
        simulation.step(int(TacticalAction.GO_TO_OBJECTIVE))


def test_step_rejects_masked_actions_and_closes_an_illegal_interaction(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(tick_seconds=0.5),
        objectives=kill_objective(),
    )
    simulation.reset(seed=17)

    assert not simulation.action_mask[int(TacticalAction.INTERACT)]
    with pytest.raises(IllegalSimulatorAction):
        simulation.step(int(TacticalAction.INTERACT))
    with pytest.raises(ValueError):
        simulation.step(len(TacticalAction))


def test_every_configured_zone_spawns_and_respawns(
    multi_zone_world_map: WorldVectorMap,
) -> None:
    simulation = FarmingSimulator(
        multi_zone_world_map,
        start=START,
        config=SimulatorConfig(tick_seconds=0.5, maximum_episode_seconds=60.0),
        seed=7,
    )
    simulation.reset(seed=7)
    capacity = sum(zone.capacity for zone in multi_zone_world_map.zones)

    assert len(simulation._monsters) == capacity
    assert {monster.zone_index for monster in simulation._monsters} == {0, 1}

    simulation._monsters = [
        type(monster)(
            monster.monster_slot,
            monster.monster_id,
            monster.zone_index,
            monster.position_x,
            monster.position_z,
            MonsterLifecycle.DEAD,
            available_at_seconds=1.0,
        )
        for monster in simulation._monsters
    ]
    for _tick in range(4):
        simulation.step(int(TacticalAction.WAIT))

    assert len(simulation._monsters) == capacity
    assert {monster.zone_index for monster in simulation._monsters} == {0, 1}
    assert all(monster.lifecycle is MonsterLifecycle.ALIVE for monster in simulation._monsters)


def test_dead_monsters_are_not_offered_as_candidates(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(tick_seconds=0.5, maximum_episode_seconds=120.0),
        objectives=kill_objective(),
    )
    simulation.reset(seed=17)

    while simulation.metrics.kill_count == 0:
        mask = simulation.action_mask
        action = next(item for item in FARMING_PRIORITY if mask[int(item)])
        observation, _reward, _terminated, truncated, _info = simulation.step(int(action))
        if truncated:
            break

    dead = [
        monster for monster in simulation._monsters if monster.lifecycle is MonsterLifecycle.DEAD
    ]
    observation = simulation.observation

    assert simulation.metrics.kill_count == 1
    assert dead
    assert not any(candidate.is_dead for candidate in observation.candidates)
    assert len(observation.candidates) == len(simulation._monsters) - len(dead)


def test_an_objective_free_episode_runs_to_truncation_and_kills(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(tick_seconds=0.5, maximum_episode_seconds=60.0),
        objectives=(),
    )
    _observation, _info = simulation.reset(seed=42)

    terminated = False
    truncated = False
    while not terminated and not truncated:
        mask = simulation.action_mask
        action = next(item for item in FARMING_PRIORITY if mask[int(item)])
        _observation, _reward, terminated, truncated, _info = simulation.step(int(action))

    assert truncated
    assert not terminated
    assert simulation.metrics.kill_count > 0


def test_an_impassable_wall_forces_a_corridor_detour(
    blocked_world_map: WorldVectorMap,
) -> None:
    goal = QuestObjective(
        QuestObjectiveKind.GO_TO, position_x=60.0, position_z=10.0, radius_units=1.0
    )
    simulation = FarmingSimulator(
        blocked_world_map,
        start=START,
        objectives=(goal,),
        config=SimulatorConfig(tick_seconds=0.5, maximum_episode_seconds=120.0),
        seed=13,
    )
    simulation.reset(seed=13)
    straight_line = math.hypot(60.0 - START.x, 10.0 - START.z)

    assert simulation.has_route_detour
    farm(simulation)

    assert simulation.metrics.distance_units > straight_line
    assert all(
        not obstacle.contains(WorldCoordinate(simulation._x, simulation._z))
        for obstacle in blocked_world_map.obstacles
    )


def test_the_simulator_scores_ticks_with_the_shared_reward_configuration(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    loud_idle = RewardConfig(idle_weight=0.5)
    default = make_simulator(SimulatorConfig(tick_seconds=0.5), objectives=())
    configured = make_simulator(SimulatorConfig(tick_seconds=0.5, reward=loud_idle), objectives=())
    default.reset(seed=3)
    configured.reset(seed=3)

    _observation, default_reward, _t, _tr, _info = default.step(int(TacticalAction.WAIT))
    _observation, custom_reward, _t, _tr, _info = configured.step(int(TacticalAction.WAIT))

    assert SimulatorConfig().reward.version == REWARD_CONFIG_VERSION
    assert default_reward == pytest.approx(
        RewardEngine(RewardConfig()).reward(RewardEvent(idle_seconds=0.5))
    )
    assert custom_reward == pytest.approx(
        RewardEngine(loud_idle).reward(RewardEvent(idle_seconds=0.5))
    )
