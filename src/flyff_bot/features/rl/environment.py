"""Gymnasium-compatible offline tactical environment adapter."""

from __future__ import annotations

from typing import Any, SupportsFloat

from flyff_bot.features.rl.actions import TACTICAL_ACTION_COUNT
from flyff_bot.features.rl.models import RlObservation, Transition


class TacticalRlEnvironment:
    """Expose recorded transitions through a standard Gymnasium-shaped API."""

    def __init__(self, transitions: list[Transition]) -> None:
        if not transitions:
            raise ValueError("A tactical RL environment needs at least one transition.")
        self._transitions = transitions
        self._index = 0
        self._closed = False

    @property
    def action_space_size(self) -> int:
        return TACTICAL_ACTION_COUNT

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[RlObservation, dict[str, Any]]:
        del seed, options
        if self._closed:
            raise RuntimeError("The tactical RL environment is closed.")
        self._index = 0
        transition = self._transitions[0]
        return transition.observation, {"action_mask": transition.action_mask}

    def step(self, action: int) -> tuple[RlObservation, SupportsFloat, bool, bool, dict[str, Any]]:
        if self._closed:
            raise RuntimeError("The tactical RL environment is closed.")
        if not isinstance(action, int) or not 0 <= action < TACTICAL_ACTION_COUNT:
            raise ValueError("Unknown tactical action index.")
        transition = self._transitions[self._index]
        if not transition.action_mask[action]:
            raise ValueError("Masked tactical action selected.")
        observation = transition.next_observation
        terminated = transition.terminated
        truncated = self._index + 1 >= len(self._transitions) and not terminated
        if not terminated:
            self._index += 1
        return (
            observation,
            transition.reward,
            terminated,
            truncated,
            {"action_mask": transition.action_mask},
        )

    def close(self) -> None:
        self._closed = True
