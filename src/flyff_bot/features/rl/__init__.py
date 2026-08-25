"""Offline tactical reinforcement-learning contracts and deterministic training support."""

from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    TacticalActionKind,
    TargetAction,
    WaitAction,
)
from flyff_bot.features.rl.actions import (
    TACTICAL_ACTION_COUNT,
    ParameterizedAction,
    TacticalAction,
    TacticalActionCatalog,
    TacticalActionMask,
)
from flyff_bot.features.rl.environment import TacticalRlEnvironment
from flyff_bot.features.rl.masking import build_action_mask, build_tactical_mask
from flyff_bot.features.rl.models import (
    CandidateObservation,
    NavMeshContext,
    ObjectiveState,
    ObservationSpace,
    OperationalState,
    PlayerKinematics,
    PlayerVitals,
    ReadinessObservation,
    RlObservation,
    Transition,
)
from flyff_bot.features.rl.rewards import RewardConfig, RewardEngine

__all__ = [
    "TACTICAL_ACTION_COUNT",
    "AttackPointAction",
    "CandidateObservation",
    "CorridorAction",
    "InteractAction",
    "NavMeshContext",
    "NavigateAction",
    "ObjectiveState",
    "ObservationSpace",
    "OperationalState",
    "ParameterizedAction",
    "PlayerKinematics",
    "PlayerVitals",
    "ReadinessObservation",
    "RewardConfig",
    "RewardEngine",
    "RlObservation",
    "TacticalAction",
    "TacticalActionCatalog",
    "TacticalActionKind",
    "TacticalActionMask",
    "TacticalRlEnvironment",
    "TargetAction",
    "Transition",
    "WaitAction",
    "build_action_mask",
    "build_tactical_mask",
]
