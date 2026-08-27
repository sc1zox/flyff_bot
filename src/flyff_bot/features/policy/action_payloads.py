"""The single action contract shared by the simulator, the exporter and every live policy.

Three vocabularies live here and nowhere else (US-079):

* :class:`StrategicGoalKind` - the macro sub-goal the high-level tier picks. Its wire order is
  :data:`STRATEGIC_GOAL_ORDER`, which is also the offline simulator's discrete action space and
  the high-level head's output column order.
* :class:`TacticalActionKind` - the kind of tactical payload the mid-level tier picks.
* :class:`TacticalAction` - the stable discrete index a tactical payload encodes to.

Defining any of them a second time would let an offline rollout and a live decision disagree
about what an index means, which is exactly the drift BUG-031 recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum, unique
from typing import TYPE_CHECKING


@unique
class StrategicGoalKind(StrEnum):
    """Macro sub-goals selected only by the high-level policy tier."""

    TARGET = "target"
    NAVIGATE = "navigate"
    INTERACT = "interact"
    WAIT = "wait"


# The discrete strategic action space. Trained artifacts record this order, and the offline
# simulator steps on these indices, so the sequence is a wire contract and must stay stable.
STRATEGIC_GOAL_ORDER: tuple[StrategicGoalKind, ...] = (
    StrategicGoalKind.TARGET,
    StrategicGoalKind.NAVIGATE,
    StrategicGoalKind.INTERACT,
    StrategicGoalKind.WAIT,
)
STRATEGIC_GOAL_COUNT = len(STRATEGIC_GOAL_ORDER)


def strategic_goal_index(goal: StrategicGoalKind) -> int:
    """Return the discrete index one strategic goal occupies in every artifact and mask."""

    return STRATEGIC_GOAL_ORDER.index(goal)


def strategic_goal_at(index: int) -> StrategicGoalKind:
    """Return the strategic goal one discrete index names."""

    if not 0 <= index < STRATEGIC_GOAL_COUNT:
        raise ValueError("Unknown strategic goal index.")
    return STRATEGIC_GOAL_ORDER[index]


@unique
class TacticalActionKind(StrEnum):
    TARGET = "target"
    NAVIGATE = "navigate"
    ATTACK_POINT = "attack_point"
    CORRIDOR = "corridor"
    INTERACT = "interact"
    WAIT = "wait"


@unique
class TacticalAction(IntEnum):
    """Stable discrete action indices at the tactical abstraction layer."""

    SELECT_TARGET = 0
    GO_TO_POSITION = 1
    GO_TO_ATTACK_POINT = 2
    SELECT_CORRIDOR = 3
    INTERACT_WITH_OBJECT = 4
    INTERACT_WITH_NPC = 5
    WAIT = 6

    @classmethod
    def for_kind(cls, kind: TacticalActionKind) -> TacticalAction:
        return _ACTION_BY_KIND[kind]


TACTICAL_ACTION_COUNT = len(TacticalAction)

# An interaction that names an NPC is a different discrete action than one that names a world
# object, so the recorded interaction type decides which index a payload encodes to.
_ACTION_BY_KIND = {
    TacticalActionKind.TARGET: TacticalAction.SELECT_TARGET,
    TacticalActionKind.NAVIGATE: TacticalAction.GO_TO_POSITION,
    TacticalActionKind.ATTACK_POINT: TacticalAction.GO_TO_ATTACK_POINT,
    TacticalActionKind.CORRIDOR: TacticalAction.SELECT_CORRIDOR,
    TacticalActionKind.INTERACT: TacticalAction.INTERACT_WITH_OBJECT,
    TacticalActionKind.WAIT: TacticalAction.WAIT,
}


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


TacticalActionPayload = (
    TargetAction | NavigateAction | AttackPointAction | CorridorAction | InteractAction | WaitAction
)
