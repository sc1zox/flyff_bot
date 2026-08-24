"""Reproducibility, calibration, Gymnasium shape, and throughput."""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from flyff_bot.features.rl.models import RlObservation
from flyff_bot.features.simulator import (
    CalibrationBaseline,
    CalibrationError,
    CalibrationTolerance,
    FarmingSimulator,
    SimulationMetrics,
    SimulatorConfig,
    SimulatorGymEnvironment,
    validate_calibration,
)


def run_episode(simulation: FarmingSimulator) -> SimulationMetrics:
    simulation.reset(seed=123)
    for _step in range(20):
        mask = simulation.action_mask
        action = next(index for index, allowed in enumerate(mask) if allowed)
        result = simulation.step(action)
        if result[2] or result[3]:
            break
    return simulation.metrics


def test_identical_seeds_produce_bit_identical_metrics(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    first = make_simulator(SimulatorConfig(tick_seconds=0.25))
    second = make_simulator(SimulatorConfig(tick_seconds=0.25))

    assert run_episode(first) == run_episode(second)


def test_calibration_rejects_drifting_baselines() -> None:
    metrics = SimulationMetrics(60.0, 2, 12.0, 20.0, 5.0, 23.0, 100.0, 1)
    baseline = CalibrationBaseline(60.0, 2, 2.0, 6.0, 10.0, 0.5, 5.0)
    drifting_metrics = SimulationMetrics(60.0, 4, 12.0, 20.0, 5.0, 23.0, 100.0, 1)

    assert validate_calibration(metrics, baseline, CalibrationTolerance(0.1, 0.2))
    with pytest.raises(CalibrationError):
        validate_calibration(drifting_metrics, baseline, CalibrationTolerance(0.01, 0.2))


def test_calibration_uses_kill_count_for_matching_baselines() -> None:
    metrics = SimulationMetrics(60.0, 2, 10.0, 20.0, 5.0, 25.0, 100.0, 1)
    baseline = CalibrationBaseline(60.0, 2, 2.0, 5.0, 10.0, 0.5, 5.0)

    assert validate_calibration(metrics, baseline)


def test_gymnasium_shaped_reset_step_and_close(
    make_simulator: Callable[[], FarmingSimulator],
) -> None:
    environment = SimulatorGymEnvironment(make_simulator())
    reset_result = environment.reset(seed=7)
    assert isinstance(reset_result, tuple)
    observation = reset_result[0]
    info = reset_result[1]
    assert isinstance(observation, RlObservation)
    action_mask = info["action_mask"]
    assert isinstance(action_mask, tuple)
    action = next(index for index, allowed in enumerate(action_mask) if allowed)
    step_result = environment.step(action)
    environment.close()

    assert len(step_result) == 5
    assert isinstance(step_result[1], float)
    assert len(action_mask) == 4
    assert observation.kinematics.speed >= 0.0
    with pytest.raises(RuntimeError):
        environment.step(action)


def test_simulation_runs_at_least_one_hundred_times_real_time(
    make_simulator: Callable[[SimulatorConfig], FarmingSimulator],
) -> None:
    simulation = make_simulator(SimulatorConfig(tick_seconds=0.5, maximum_episode_seconds=100.0))
    simulation.reset()
    started = time.perf_counter()

    while True:
        action = next(index for index, allowed in enumerate(simulation.action_mask) if allowed)
        _observation, _reward, terminated, truncated, _info = simulation.step(action)
        if terminated or truncated:
            break

    wall_seconds = max(time.perf_counter() - started, 0.000001)
    assert simulation.metrics.elapsed_seconds / wall_seconds >= 100.0
