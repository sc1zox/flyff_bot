"""Hierarchical training adapter over the seeded US-072 simulator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from flyff_bot.features.navigation.world_extractor import WorldCoordinate, WorldVectorMap
from flyff_bot.features.policy.action_payloads import (
    StrategicGoalKind,
    TacticalActionKind,
    strategic_goal_at,
    strategic_goal_index,
)
from flyff_bot.features.rl.models import FloatArray, ObservationSpace, RlObservation
from flyff_bot.features.simulator.engine import FarmingSimulator
from flyff_bot.features.simulator.models import (
    QuestObjective,
    SimulationMetrics,
    SimulatorConfig,
)

PolicyFunction = Callable[[RlObservation, tuple[bool, ...]], int]


@dataclass(frozen=True, slots=True)
class HierarchicalEpisodeMetrics:
    """Aggregate evidence from one paired offline policy episode."""

    elapsed_seconds: float
    kill_count: int
    quest_progress_count: int
    terminated: bool
    invalid_action_count: int = 0

    @property
    def kills_per_minute(self) -> float:
        return self.kill_count * 60.0 / self.elapsed_seconds if self.elapsed_seconds else 0.0

    @property
    def objectives_per_minute(self) -> float:
        return (
            self.quest_progress_count * 60.0 / self.elapsed_seconds if self.elapsed_seconds else 0.0
        )


@dataclass(frozen=True, slots=True)
class TrainingObjective:
    """A reproducible multi-step mission evaluated inside US-072."""

    objectives: tuple[QuestObjective, ...]

    def __post_init__(self) -> None:
        if not self.objectives:
            raise ValueError("Hierarchical training needs at least one simulator objective.")


class HierarchicalTrainingSimulator:
    """Expose policy rollouts without duplicating US-072 dynamics or rewards."""

    def __init__(
        self,
        world_map: WorldVectorMap,
        *,
        start: WorldCoordinate,
        objective: TrainingObjective,
        config: SimulatorConfig | None = None,
    ) -> None:
        self.config = config or SimulatorConfig(maximum_episode_seconds=60.0)
        self._simulator = FarmingSimulator(
            world_map,
            start=start,
            objectives=objective.objectives,
            config=self.config,
        )

    def tactical_kind(self, action: int) -> TacticalActionKind:
        """Return the tactical action the current state gives one strategic goal.

        The two heads answer different questions, so their labels must be read from
        different facts: the strategic goal alone does not say whether travelling needs a
        corridor detour or whether interacting means engaging a monster.
        """

        goal = strategic_goal_at(action)
        if goal is StrategicGoalKind.TARGET:
            return TacticalActionKind.TARGET
        if goal is StrategicGoalKind.NAVIGATE:
            return (
                TacticalActionKind.CORRIDOR
                if self._simulator.has_route_detour
                else TacticalActionKind.NAVIGATE
            )
        if goal is StrategicGoalKind.INTERACT:
            return (
                TacticalActionKind.ATTACK_POINT
                if self._simulator.is_combat_engagement
                else TacticalActionKind.INTERACT
            )
        return TacticalActionKind.WAIT

    @staticmethod
    def approach_distance_target(observation: RlObservation) -> float:
        """Return the normalized expert label for the contextual distance head.

        Multiple eligible monsters favor the far prevalidated option to retain separation from
        a cluster. A single candidate scales with measured NavMesh path distance. Missing
        distance stays neutral instead of being fabricated as zero.
        """

        candidates = tuple(
            item
            for item in observation.candidates
            if not item.is_dead and not item.is_locked_out and not item.is_unreachable
        )
        if len(candidates) > 1:
            return 1.0
        if not candidates or candidates[0].path_distance is None:
            return 0.5
        return min(max(candidates[0].path_distance / 30.0, 0.0), 1.0)

    def reset(self, *, seed: int) -> tuple[RlObservation, tuple[bool, ...]]:
        observation, info = self._simulator.reset(seed=seed)
        mask = _bool_tuple(info["action_mask"])
        return observation, mask

    def step(
        self, action: int
    ) -> tuple[RlObservation, float, bool, bool, tuple[bool, ...], tuple[str, ...]]:
        observation, reward, terminated, truncated, info = self._simulator.step(action)
        return (
            observation,
            reward,
            terminated,
            truncated,
            _bool_tuple(info["action_mask"]),
            _string_tuple(info["events"]),
        )

    @staticmethod
    def encode(observation: RlObservation) -> FloatArray:
        return ObservationSpace.encode(observation)

    @property
    def metrics(self) -> SimulationMetrics:
        """Return the aggregate outcome of the episode the simulator last ran."""

        return self._simulator.metrics

    def run_episode(self, policy: PolicyFunction, *, seed: int) -> HierarchicalEpisodeMetrics:
        observation, mask = self.reset(seed=seed)
        quest_progress_count = 0
        terminated = False
        truncated = False
        invalid_action_count = 0
        while not terminated and not truncated:
            action = int(policy(observation, mask))
            if not 0 <= action < len(mask) or not mask[action]:
                invalid_action_count += 1
                break
            observation, _reward, terminated, truncated, mask, events = self.step(action)
            quest_progress_count += events.count("quest_progress")
        metrics = self._simulator.metrics
        return HierarchicalEpisodeMetrics(
            metrics.elapsed_seconds,
            metrics.kill_count,
            quest_progress_count,
            terminated,
            invalid_action_count,
        )


class HierarchicalPolicyLearner:
    """Reward-aligned expert used to seed the compact masked policy heads."""

    @staticmethod
    def predict_action(_observation: RlObservation, mask: tuple[bool, ...]) -> int:
        priority = (
            StrategicGoalKind.INTERACT,
            StrategicGoalKind.NAVIGATE,
            StrategicGoalKind.TARGET,
            StrategicGoalKind.WAIT,
        )
        return next(index for index in map(strategic_goal_index, priority) if mask[index])


def policy_from_logits(
    weights: NDArray[np.float64],
) -> PolicyFunction:
    """Return a masked greedy policy backed by one fitted linear head."""

    numeric_weights = np.asarray(weights, dtype=np.float64)

    def evaluate(observation: RlObservation, mask: tuple[bool, ...]) -> int:
        logits = ObservationSpace.encode(observation) @ numeric_weights
        masked = np.where(np.asarray(mask, dtype=bool), logits, -np.inf)
        return int(np.argmax(masked))

    return evaluate


def _bool_tuple(value: object) -> tuple[bool, ...]:
    if not isinstance(value, tuple):
        raise ValueError("Simulator action mask is malformed.")
    return tuple(bool(item) for item in value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError("Simulator event payload is malformed.")
    return tuple(str(item) for item in value)
