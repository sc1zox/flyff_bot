"""Movement and terrain behavior of the US-072 offline simulator."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from flyff_bot.features.rl.state_space import ObservationSpace
from flyff_bot.features.simulator import FarmingSimulator, SimulatorConfig


def test_movement_uses_nominal_speed_turn_time_and_real_heights(
    make_simulator: Callable[[SimulatorConfig], FarmingSimulator],
) -> None:
    simulation = make_simulator(
        SimulatorConfig(tick_seconds=2.0, nominal_speed_units_per_second=10.0)
    )
    simulation.reset()

    observation, _reward, _terminated, _truncated, info = simulation.step(1)

    assert info["action_mask"] == simulation.action_mask
    assert observation.kinematics.position_y == pytest.approx(10.0)
    assert observation.kinematics.position_x == pytest.approx(15.0, abs=5.01)
    assert observation.kinematics.position_z == pytest.approx(10.0)
    assert ObservationSpace.encode(observation).shape == (52,)


def test_a_completed_go_to_objective_terminates_the_episode(
    simulator: FarmingSimulator,
) -> None:
    simulator.reset()

    _observation, _reward, terminated, truncated, _info = simulator.step(2)

    assert terminated
    assert not truncated
