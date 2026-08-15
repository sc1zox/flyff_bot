"""Action dispatch that only confirms success after a fresh observation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from flyff_bot.features.automation.models import Action, Observation


class ActionDispatcher(Protocol):
    """Platform adapter responsible for foreground-safe input dispatch."""

    def dispatch(self, action: Action) -> None:
        """Dispatch one action after enforcing platform safety requirements."""


class ObservationReader(Protocol):
    """Perception adapter providing a post-dispatch observation."""

    def observe(self) -> Observation:
        """Read the latest observation."""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Typed outcome of a verified action attempt."""

    action: Action
    is_successful: bool
    observation: Observation


class VerifiedExecutor:
    """Dispatch actions and require a matching confirmed observation afterwards."""

    def __init__(self, dispatcher: ActionDispatcher, observation_reader: ObservationReader) -> None:
        self._dispatcher = dispatcher
        self._observation_reader = observation_reader

    def execute(self, action: Action) -> ExecutionResult:
        """Dispatch an action then verify it using a newly-read observation."""

        self._dispatcher.dispatch(action)
        observation = self._observation_reader.observe()
        successful = observation.is_confirmed and observation.kind is action.required_observation
        return ExecutionResult(action=action, is_successful=successful, observation=observation)
