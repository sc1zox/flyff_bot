"""Gymnasium-shaped adapter over the offline farming simulator."""

from __future__ import annotations

from typing import Any, SupportsFloat

from flyff_bot.features.policy.action_payloads import STRATEGIC_GOAL_COUNT
from flyff_bot.features.simulator.calibration import validate_calibration
from flyff_bot.features.simulator.engine import FarmingSimulator
from flyff_bot.features.simulator.models import (
    CalibrationBaseline,
    CalibrationTolerance,
    fit_calibration,
)
from flyff_bot.features.telemetry.models import KillCycle


class SimulatorGymEnvironment:
    """Expose the simulator through reset/step semantics without importing Gymnasium."""

    def __init__(
        self,
        simulator: FarmingSimulator,
        *,
        kill_cycles: tuple[KillCycle, ...] = (),
        session_duration_seconds: float | None = None,
        tolerance: CalibrationTolerance | None = None,
        baseline: CalibrationBaseline | None = None,
    ) -> None:
        self._simulator = simulator
        self._closed = False
        self._tolerance = tolerance or CalibrationTolerance()
        self._baseline = baseline or (
            fit_calibration(kill_cycles, session_duration_seconds)
            if session_duration_seconds is not None and kill_cycles
            else None
        )

    @property
    def action_space_size(self) -> int:
        return STRATEGIC_GOAL_COUNT

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[object, dict[str, object]]:
        del options
        self._ensure_open()
        observation, info = self._simulator.reset(seed=seed)
        return observation, {"action_mask": info["action_mask"]}

    def step(self, action: int) -> tuple[object, SupportsFloat, bool, bool, dict[str, object]]:
        self._ensure_open()
        return self._simulator.step(action)

    def close(self) -> None:
        self._closed = True

    def validate_against_baseline(self) -> bool:
        """Return whether a completed episode matches measured KPM/travel baselines."""

        if self._baseline is None:
            raise ValueError("Calibration requires recorded kill cycles and session duration.")
        metrics = self._simulator.metrics
        validate_calibration(metrics, self._baseline, self._tolerance)
        return True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("The offline simulation environment is closed.")
