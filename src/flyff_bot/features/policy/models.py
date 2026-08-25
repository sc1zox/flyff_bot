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
    TacticalActionKind,
    TargetAction,
    WaitAction,
)

__all__ = [
    "AttackPointAction",
    "CorridorAction",
    "InteractAction",
    "NavigateAction",
    "StrategicDecision",
    "StrategicGoalKind",
    "TacticalActionKind",
    "TargetAction",
    "WaitAction",
]

POLICY_LATENCY_BUDGET_SECONDS = 0.005
DEFAULT_POLICY_WAIT_SECONDS = 0.1


class StrategicGoalKind(StrEnum):
    """Macro sub-goals selected only by the high-level policy tier."""

    TARGET = "target"
    NAVIGATE = "navigate"
    INTERACT = "interact"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class StrategicDecision:
    """An immutable high-level intent consumed by the mid-level tactical tier."""

    goal: StrategicGoalKind
    reason: str
    quest_id: str | None = None
    objective_index: int = 0
    progress: float = 0.0
    destination: tuple[float, float, float] | None = None
    target_candidate_index: int | None = None
    interaction_target_id: str | None = None
    interaction_type: str | None = None


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
    """Prevalidated options and session facts supplied to every policy.

    Coordinates, corridor identifiers, and interaction identifiers are populated only by the
    deterministic navigation/quest layers. A policy may rank these values but cannot invent new
    ones and still pass the runner's final mask validation.
    """

    candidates: tuple[PolicyCandidate, ...]
    allowed_class_names: frozenset[str]
    is_locked_out: tuple[bool, ...]
    feature_matrix: npt.NDArray[np.float64] | None = None
    valid_destinations: frozenset[tuple[float, float, float]] = frozenset()
    valid_corridor_ids: frozenset[str] = frozenset()
    valid_interactions: frozenset[tuple[str, str]] = frozenset()
    valid_attack_points: tuple[AttackPointAction, ...] = ()
    macro_event_token: tuple[object, ...] = ()


class TacticalPolicy(Protocol):
    """The stable policy boundary that later hierarchical RL policies will implement."""

    def evaluate(self, world_state: WorldState, context: PolicyContext) -> TacticalAction | None:
        """Return at most one legal tactical action for this cycle."""
