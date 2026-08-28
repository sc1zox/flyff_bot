"""The declared Gymnasium contract of the offline simulator (BUG-030).

These tests hand the environment to Gymnasium's own checker rather than re-asserting a
hand-written approximation of the API, so a regression in the spaces, seeding or step
semantics fails here instead of silently producing an untrainable environment.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from gymnasium import spaces
from gymnasium.utils.env_checker import check_env

from flyff_bot.features.policy.action_payloads import STRATEGIC_GOAL_COUNT
from flyff_bot.features.rl.models import OBSERVATION_DIMENSION
from flyff_bot.features.simulator.engine import FarmingSimulator
from flyff_bot.features.simulator.environment import SimulatorGymEnvironment


def test_environment_passes_the_gymnasium_framework_check(
    make_simulator: Callable[[], FarmingSimulator],
) -> None:
    environment = SimulatorGymEnvironment(make_simulator())

    check_env(environment, skip_render_check=True)


def test_environment_declares_typed_action_and_observation_spaces(
    make_simulator: Callable[[], FarmingSimulator],
) -> None:
    environment = SimulatorGymEnvironment(make_simulator())

    assert environment.action_space == spaces.Discrete(STRATEGIC_GOAL_COUNT)
    assert isinstance(environment.observation_space, spaces.Box)
    assert environment.observation_space.shape == (OBSERVATION_DIMENSION,)
    assert environment.observation_space.dtype == np.float64


def test_reset_seeding_is_reproducible(
    make_simulator: Callable[[], FarmingSimulator],
) -> None:
    first, _info = SimulatorGymEnvironment(make_simulator()).reset(seed=11)
    second, _other = SimulatorGymEnvironment(make_simulator()).reset(seed=11)

    assert np.array_equal(first, second)


def test_observations_stay_inside_the_declared_space(
    make_simulator: Callable[[], FarmingSimulator],
) -> None:
    environment = SimulatorGymEnvironment(make_simulator())
    observation, info = environment.reset(seed=3)

    assert environment.observation_space.contains(observation)
    for _tick in range(10):
        action = int(np.argmax(info["action_mask_array"]))
        observation, _reward, terminated, truncated, info = environment.step(action)
        assert environment.observation_space.contains(observation)
        if terminated or truncated:
            break


def test_the_reported_mask_is_the_mask_step_enforces(
    make_simulator: Callable[[], FarmingSimulator],
) -> None:
    environment = SimulatorGymEnvironment(make_simulator())
    _observation, info = environment.reset(seed=5)
    mask = info["action_mask"]
    masked_out = [index for index, allowed in enumerate(mask) if not allowed]

    assert np.array_equal(environment.action_mask(), info["action_mask_array"])
    for action in masked_out:
        with pytest.raises(Exception, match="masked out"):
            environment.step(action)


def test_a_closed_environment_refuses_further_use(
    make_simulator: Callable[[], FarmingSimulator],
) -> None:
    environment = SimulatorGymEnvironment(make_simulator())
    environment.reset(seed=1)
    environment.close()

    with pytest.raises(RuntimeError):
        environment.step(0)
