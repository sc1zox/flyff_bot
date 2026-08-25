"""Payload contracts for tactical policy actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING


class TacticalActionKind(StrEnum):
    TARGET = "target"
    NAVIGATE = "navigate"
    ATTACK_POINT = "attack_point"
    CORRIDOR = "corridor"
    INTERACT = "interact"
    WAIT = "wait"


if TYPE_CHECKING:
    from flyff_bot.features.automation.models import Position


@dataclass(frozen=True, slots=True)
class TargetAction:
    """One selected target candidate.

    ``target_id`` is the detector class identity and is ambiguous whenever two mobs of the same
    class are visible. ``candidate_index`` is the per-instance identity of the chosen candidate
    inside the decision it belongs to and is what the execution boundary matches on (BUG-031).
    """

    target_id: int
    target_pos: Position | None
    expected_cost: float | None = None
    attack_point: AttackPointAction | None = None
    candidate_index: int | None = None
    kind: TacticalActionKind = TacticalActionKind.TARGET


@dataclass(frozen=True, slots=True)
class NavigateAction:
    destination: tuple[float, float, float]
    reason: str
    kind: TacticalActionKind = TacticalActionKind.NAVIGATE


@dataclass(frozen=True, slots=True)
class AttackPointAction:
    target_id: int
    attack_point: tuple[float, float, float]
    approach_angle: float
    candidate_index: int | None = None
    kind: TacticalActionKind = TacticalActionKind.ATTACK_POINT


@dataclass(frozen=True, slots=True)
class CorridorAction:
    target_id: int
    preferred_corridor_id: str
    candidate_index: int | None = None
    kind: TacticalActionKind = TacticalActionKind.CORRIDOR


@dataclass(frozen=True, slots=True)
class InteractAction:
    interaction_target_id: str
    interaction_type: str
    kind: TacticalActionKind = TacticalActionKind.INTERACT


@dataclass(frozen=True, slots=True)
class WaitAction:
    duration_seconds: float
    reason: str
    kind: TacticalActionKind = TacticalActionKind.WAIT

    def __post_init__(self) -> None:
        if not 0.0 < self.duration_seconds <= 1.0:
            raise ValueError("Policy wait duration must be between zero and one second.")
