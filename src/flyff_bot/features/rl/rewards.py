"""The one versioned reward configuration the simulator, exporter and evaluation share.

A reward number only means something together with the weights that produced it. A weight that
changes without the version changing would silently make two datasets incomparable, so the
version string identifies the weights: changing a weight requires declaring a new version, and
the version is stamped into every artifact and dataset the configuration produced (US-079).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

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

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("A reward configuration must state its version.")
        if self.version == REWARD_CONFIG_VERSION and self.weights != _default_weights():
            raise ValueError("A reward configuration that changes a weight needs its own version.")

    @property
    def weights(self) -> tuple[float, ...]:
        """Return every weight of this configuration in declaration order."""

        return tuple(getattr(self, field.name) for field in fields(self) if field.name != "version")

    def as_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def _default_weights() -> tuple[float, ...]:
    """Return the weights the shared reward version is defined as."""

    return tuple(
        float(field.default)  # type: ignore[arg-type]
        for field in fields(RewardConfig)
        if field.name != "version"
    )


# The one configuration every reward interval is computed with unless a caller declares its
# own version. Sharing this instance is what makes "the reward config" a single object.
DEFAULT_REWARD_CONFIG = RewardConfig()


class RewardEngine:
    """Compute the versioned reward from observed transition facts only."""

    def __init__(self, config: RewardConfig | None = None) -> None:
        self.config = config or DEFAULT_REWARD_CONFIG

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
