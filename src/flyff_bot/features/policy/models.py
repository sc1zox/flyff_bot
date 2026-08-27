"""Typed tactical-policy contracts shared by heuristic and learned decision layers.

Policies observe immutable world snapshots and request tactical intent only. They never own
input adapters, controllers, or safety guards: those remain downstream in the existing
automation execution boundary (US-067).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

from flyff_bot.features.automation.models import VisibleMob, WorldState
from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    StrategicGoalKind,
    TacticalActionKind,
    TacticalActionPayload,
    TargetAction,
    WaitAction,
)
from flyff_bot.features.rl.models import NavMeshContext, PlayerKinematics

__all__ = [
    "AttackPointAction",
    "CorridorAction",
    "InteractAction",
    "LiveObservationState",
    "NavigateAction",
    "StrategicDecision",
    "StrategicGoalKind",
    "TacticalActionKind",
    "TacticalActionPayload",
    "TargetAction",
    "WaitAction",
]

POLICY_LATENCY_BUDGET_SECONDS = 0.005
DEFAULT_POLICY_WAIT_SECONDS = 0.1


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


@dataclass(frozen=True, slots=True)
class LiveObservationState:
    """Decision-time world facts a learned policy needs beyond the visible candidates.

    A model trained on simulator rollouts saw real coordinates, heading, velocity, route
    distance, and objective progress. Serving it zeroed placeholders instead is a train/serve
    mismatch, so these values are supplied explicitly or the learned policy fails closed
    (BUG-031).
    """

    kinematics: PlayerKinematics
    navmesh: NavMeshContext
    current_target_index: int | None = None
    recent_kill_rate_per_minute: float = 0.0
    recent_stuck_count: int = 0
    objective_target_distance: float | None = None


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
    live_state: LiveObservationState | None = None


class TacticalPolicy(Protocol):
    """The stable policy boundary that later hierarchical RL policies will implement."""

    def evaluate(
        self, world_state: WorldState, context: PolicyContext
    ) -> TacticalActionPayload | None:
        """Return at most one legal tactical action for this cycle."""
