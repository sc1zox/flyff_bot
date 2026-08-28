"""The declared Gymnasium environment over the offline farming simulator (BUG-030).

This is the one interactive environment the offline trainer is allowed to learn in. It is a
real :class:`gymnasium.Env`, so `gymnasium.utils.env_checker.check_env` — not a hand-written
approximation of it — decides whether the spaces, seeding, reset and step semantics are
correct.

Gymnasium is an optional `rl` extra and is imported only here. Nothing in the live
application imports this module, which is why `flyff_bot.features.simulator` deliberately
does not re-export it: an operator running the bot needs no reinforcement-learning runtime.
"""

from __future__ import annotations

from typing import Any, SupportsFloat

import gymnasium
import numpy as np
import numpy.typing as npt
from gymnasium import spaces

from flyff_bot.features.policy.action_payloads import STRATEGIC_GOAL_COUNT
from flyff_bot.features.rl.models import OBSERVATION_DIMENSION, ObservationSpace
from flyff_bot.features.simulator.calibration import validate_calibration
from flyff_bot.features.simulator.engine import FarmingSimulator
from flyff_bot.features.simulator.models import (
    CalibrationBaseline,
    CalibrationTolerance,
    fit_calibration,
)
from flyff_bot.features.telemetry.models import KillCycle

# `ObservationSpace.encode` guarantees this range, so the observation space states it
# rather than an unbounded box that would hide an encoding regression from the checker.
OBSERVATION_LOW = -1.0
OBSERVATION_HIGH = 1.0
OBSERVATION_DTYPE = np.float64
# Gymnasium's mask convention for `Discrete.sample(mask=...)`: one int8 per action.
ACTION_MASK_DTYPE = np.int8

ObservationArray = npt.NDArray[np.float64]


class SimulatorGymEnvironment(gymnasium.Env[ObservationArray, np.int64]):
    """Expose the seeded offline simulator through the standard Gymnasium API.

    The simulator itself speaks in typed observations. This adapter is the only place that
    converts them into the encoded vector the training frameworks consume, so the contract
    the artifact is stamped with and the vector the model is fitted on cannot drift apart.
    """

    def __init__(
        self,
        simulator: FarmingSimulator,
        *,
        kill_cycles: tuple[KillCycle, ...] = (),
        session_duration_seconds: float | None = None,
        tolerance: CalibrationTolerance | None = None,
        baseline: CalibrationBaseline | None = None,
    ) -> None:
        super().__init__()
        # The simulator has no visual surface at all, so the environment advertises no
        # render mode rather than letting the framework assume a default one.
        self.metadata = {"render_modes": []}
        self.render_mode = None
        self._simulator = simulator
        self._closed = False
        self._tolerance = tolerance or CalibrationTolerance()
        self._baseline = baseline or (
            fit_calibration(kill_cycles, session_duration_seconds)
            if session_duration_seconds is not None and kill_cycles
            else None
        )
        self.action_space = spaces.Discrete(STRATEGIC_GOAL_COUNT)
        self.observation_space = spaces.Box(
            low=OBSERVATION_LOW,
            high=OBSERVATION_HIGH,
            shape=(OBSERVATION_DIMENSION,),
            dtype=OBSERVATION_DTYPE,
        )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[ObservationArray, dict[str, Any]]:
        """Reseed and return the encoded start observation with its current mask."""

        del options
        self._ensure_open()
        super().reset(seed=seed)
        observation, info = self._simulator.reset(seed=seed)
        return ObservationSpace.encode(observation), _info(info["action_mask"])

    def step(
        self, action: np.int64 | int
    ) -> tuple[ObservationArray, SupportsFloat, bool, bool, dict[str, Any]]:
        """Advance one tick and return the encoded next observation and its mask."""

        self._ensure_open()
        observation, reward, terminated, truncated, info = self._simulator.step(int(action))
        return (
            ObservationSpace.encode(observation),
            reward,
            terminated,
            truncated,
            _info(info["action_mask"]),
        )

    def action_mask(self) -> npt.NDArray[np.int8]:
        """Return the current mask in the form ``Discrete.sample`` accepts."""

        self._ensure_open()
        return _mask_array(self._simulator.action_mask)

    def close(self) -> None:
        """Release the environment; a later reset or step is a programming error."""

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


def _info(action_mask: object) -> dict[str, Any]:
    mask = tuple(bool(allowed) for allowed in _as_sequence(action_mask))
    return {"action_mask": mask, "action_mask_array": _mask_array(mask)}


def _as_sequence(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, list | tuple) else ()


def _mask_array(mask: tuple[bool, ...]) -> npt.NDArray[np.int8]:
    return np.asarray([int(allowed) for allowed in mask], dtype=ACTION_MASK_DTYPE)
