"""Typed tactical-policy contracts shared by heuristic and learned decision layers.

Policies observe immutable world snapshots and request tactical intent only. They never own
input adapters, controllers, or safety guards: those remain downstream in the existing
automation execution boundary (US-067).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import numpy as np
import numpy.typing as npt

from flyff_bot.features.automation.models import VisibleMob, WorldState
from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    TargetAction,
    WaitAction,
)

__all__ = [
    "AttackPointAction",
    "CorridorAction",
    "InteractAction",
    "NavigateAction",
    "TargetAction",
    "WaitAction",
]

POLICY_LATENCY_BUDGET_SECONDS = 0.005
DEFAULT_POLICY_WAIT_SECONDS = 0.1


class TacticalActionKind(StrEnum):
    """The discrete tactical intents exposed to policies and future RL environments."""

    TARGET = "target"
    NAVIGATE = "navigate"
    ATTACK_POINT = "attack_point"
    CORRIDOR = "corridor"
    INTERACT = "interact"
    WAIT = "wait"


TacticalAction = (
    TargetAction | NavigateAction | AttackPointAction | CorridorAction | InteractAction | WaitAction
)


@dataclass(frozen=True, slots=True)
class PolicyCandidate:
    """A deterministic mask entry paired with its source candidate index."""

    mob: VisibleMob
    is_alive_and_recognized: bool
    is_unlocked: bool
    is_within_leash: bool
    is_navmesh_reachable: bool
    has_valid_world_position: bool
    original_position: int | None = None

    @property
    def is_eligible(self) -> bool:
        """Return whether every US-067 deterministic mask predicate passes."""

        return all(
            (
                self.is_alive_and_recognized,
                self.is_unlocked,
                self.is_within_leash,
                self.is_navmesh_reachable,
                self.has_valid_world_position,
            )
        )


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """The deterministic action mask and session facts supplied to every policy."""

    candidates: tuple[PolicyCandidate, ...]
    allowed_class_names: frozenset[str]
    is_locked_out: tuple[bool, ...]
    feature_matrix: npt.NDArray[np.float64] | None = None


class TacticalPolicy(Protocol):
    """The stable policy boundary that later hierarchical RL policies will implement."""

    def evaluate(self, world_state: WorldState, context: PolicyContext) -> TacticalAction | None:
        """Return at most one legal tactical action for this cycle."""
