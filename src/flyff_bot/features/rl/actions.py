"""Loss-free encoding, masking and decoding of the shared tactical action contract.

The vocabularies themselves live in :mod:`flyff_bot.features.policy.action_payloads`; this
module only turns typed payloads into the discrete, parameterized form offline RL records.
"""

from __future__ import annotations

from dataclasses import dataclass

from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    TacticalAction,
    TacticalActionPayload,
    TargetAction,
    WaitAction,
)

# A quest interaction that names an NPC encodes to a different discrete action than one that
# names a world object, so the recorded interaction type decides the index.
NPC_INTERACTION_TYPE = "npc"

WorldPoint = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class ParameterizedAction:
    """One discrete action together with every parameter that identifies the exact choice.

    The discrete index alone cannot describe a decision: selecting one of four visible mobs and
    selecting a different one are the same index. ``candidate_index`` is the per-instance
    identity of the chosen candidate inside its own decision, never a class identifier.
    """

    action: TacticalAction
    candidate_index: int | None = None
    target_class_id: int | None = None
    destination: WorldPoint | None = None
    attack_point: WorldPoint | None = None
    approach_angle: float | None = None
    corridor_id: str | None = None
    interaction_target_id: str | None = None
    interaction_type: str | None = None
    wait_seconds: float | None = None
    wait_reason: str | None = None
    navigate_reason: str | None = None


# These actions name one specific candidate, so their legality depends on the per-instance
# candidate mask and not only on the discrete action mask.
CANDIDATE_BOUND_ACTIONS = frozenset(
    {
        TacticalAction.SELECT_TARGET,
        TacticalAction.GO_TO_ATTACK_POINT,
        TacticalAction.SELECT_CORRIDOR,
    }
)


@dataclass(frozen=True, slots=True)
class TacticalActionMask:
    """The discrete action mask paired with the per-candidate mask it depends on.

    An empty mask permits nothing: a transition that carries no recorded mask must not be
    treated as if every action had been legal.
    """

    actions: tuple[bool, ...] = ()
    candidates: tuple[bool, ...] = ()

    def allows(self, action: ParameterizedAction) -> bool:
        """Return whether this mask permits one exact parameterized choice."""

        index = int(action.action)
        if not 0 <= index < len(self.actions) or not self.actions[index]:
            return False
        if action.action not in CANDIDATE_BOUND_ACTIONS:
            return True
        candidate_index = action.candidate_index
        if candidate_index is None or not 0 <= candidate_index < len(self.candidates):
            return False
        return self.candidates[candidate_index]


class TacticalActionCatalog:
    """Encode and decode typed payloads without exposing keyboard or mouse details."""

    @staticmethod
    def index_for(action: TacticalActionPayload) -> int:
        """Return the stable integer action accepted by Gymnasium-style APIs."""

        return int(TacticalActionCatalog.encode(action).action)

    @staticmethod
    def encode(
        action: TacticalActionPayload, *, candidate_index: int | None = None
    ) -> ParameterizedAction:
        """Return the loss-free parameterized form of one typed tactical payload."""

        if isinstance(action, WaitAction):
            return ParameterizedAction(
                TacticalAction.WAIT,
                wait_seconds=action.duration_seconds,
                wait_reason=action.reason,
            )
        if isinstance(action, TargetAction):
            attack_point = action.attack_point
            return ParameterizedAction(
                TacticalAction.SELECT_TARGET,
                candidate_index=(
                    action.candidate_index if candidate_index is None else candidate_index
                ),
                target_class_id=action.target_id,
                attack_point=None if attack_point is None else attack_point.attack_point,
                approach_angle=None if attack_point is None else attack_point.approach_angle,
            )
        if isinstance(action, NavigateAction):
            return ParameterizedAction(
                TacticalAction.GO_TO_POSITION,
                candidate_index=candidate_index,
                destination=action.destination,
                navigate_reason=action.reason,
            )
        if isinstance(action, AttackPointAction):
            return ParameterizedAction(
                TacticalAction.GO_TO_ATTACK_POINT,
                candidate_index=(
                    action.candidate_index if candidate_index is None else candidate_index
                ),
                target_class_id=action.target_id,
                attack_point=action.attack_point,
                approach_angle=action.approach_angle,
            )
        if isinstance(action, CorridorAction):
            return ParameterizedAction(
                TacticalAction.SELECT_CORRIDOR,
                candidate_index=(
                    action.candidate_index if candidate_index is None else candidate_index
                ),
                target_class_id=action.target_id,
                corridor_id=action.preferred_corridor_id,
            )
        if isinstance(action, InteractAction):
            return ParameterizedAction(
                (
                    TacticalAction.INTERACT_WITH_NPC
                    if action.interaction_type == NPC_INTERACTION_TYPE
                    else TacticalAction.INTERACT_WITH_OBJECT
                ),
                candidate_index=candidate_index,
                interaction_target_id=action.interaction_target_id,
                interaction_type=action.interaction_type,
            )
        raise TypeError("Unsupported tactical action payload.")

    @staticmethod
    def decode(action: ParameterizedAction) -> TacticalActionPayload:
        """Rebuild the typed payload a parameterized action was encoded from."""

        match action.action:
            case TacticalAction.WAIT:
                if action.wait_seconds is None:
                    raise ValueError("A wait action needs its recorded duration.")
                return WaitAction(action.wait_seconds, action.wait_reason or "")
            case TacticalAction.SELECT_TARGET:
                if action.target_class_id is None:
                    raise ValueError("A target action needs its recorded class identity.")
                return TargetAction(
                    action.target_class_id,
                    None,
                    None,
                    _attack_point(action),
                    candidate_index=action.candidate_index,
                )
            case TacticalAction.GO_TO_POSITION:
                if action.destination is None:
                    raise ValueError("A navigate action needs its recorded destination.")
                return NavigateAction(action.destination, action.navigate_reason or "")
            case TacticalAction.GO_TO_ATTACK_POINT:
                attack_point = _attack_point(action)
                if attack_point is None:
                    raise ValueError("An attack-point action needs its recorded approach.")
                return attack_point
            case TacticalAction.SELECT_CORRIDOR:
                if action.target_class_id is None or action.corridor_id is None:
                    raise ValueError("A corridor action needs its recorded corridor.")
                return CorridorAction(
                    action.target_class_id, action.corridor_id, action.candidate_index
                )
            case TacticalAction.INTERACT_WITH_OBJECT | TacticalAction.INTERACT_WITH_NPC:
                if action.interaction_target_id is None or action.interaction_type is None:
                    raise ValueError("An interact action needs its recorded interaction.")
                return InteractAction(action.interaction_target_id, action.interaction_type)
        raise TypeError("Unsupported tactical action index.")


def _attack_point(action: ParameterizedAction) -> AttackPointAction | None:
    if action.attack_point is None or action.approach_angle is None:
        return None
    if action.target_class_id is None:
        raise ValueError("An attack point needs the target it belongs to.")
    return AttackPointAction(
        action.target_class_id,
        action.attack_point,
        action.approach_angle,
        action.candidate_index,
    )
