"""Configurable deterministic progress rewards."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

REWARD_CONFIG_VERSION = "us071-v1"


@dataclass(frozen=True, slots=True)
class RewardEvent:
    verified_kill: bool = False
    quest_progress_delta: float = 0.0
    objective_completed: bool = False
    travel_seconds: float = 0.0
    idle_seconds: float = 0.0
    stuck_seconds: float = 0.0
    recovery_seconds: float = 0.0
    failed_action: bool = False


@dataclass(frozen=True, slots=True)
class RewardConfig:
    kill_weight: float = 1.0
    quest_step_weight: float = 0.5
    objective_complete_weight: float = 2.0
    travel_weight: float = 0.01
    idle_weight: float = 0.02
    stuck_weight: float = 0.05
    recovery_weight: float = 0.05
    failed_action_weight: float = 0.25
    version: str = REWARD_CONFIG_VERSION

    def as_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


class RewardEngine:
    """Compute the versioned reward from observed transition facts only."""

    def __init__(self, config: RewardConfig | None = None) -> None:
        self.config = config or RewardConfig()

    def reward(self, event: RewardEvent) -> float:
        penalty = (
            self.config.travel_weight * event.travel_seconds
            + self.config.idle_weight * event.idle_seconds
            + self.config.stuck_weight * event.stuck_seconds
            + self.config.recovery_weight * event.recovery_seconds
            + self.config.failed_action_weight * float(event.failed_action)
        )
        return (
            self.config.kill_weight * float(event.verified_kill)
            + self.config.quest_step_weight * max(0.0, event.quest_progress_delta)
            + self.config.objective_complete_weight * float(event.objective_completed)
            - penalty
        )
