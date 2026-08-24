"""Discrete tactical action contracts for offline RL."""

from __future__ import annotations

from enum import IntEnum, unique

from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    TacticalActionKind,
    TargetAction,
    WaitAction,
)


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


class TacticalActionCatalog:
    """Encode and decode typed payloads without exposing keyboard or mouse details."""

    @staticmethod
    def encode(
        action: TargetAction
        | NavigateAction
        | AttackPointAction
        | CorridorAction
        | InteractAction
        | WaitAction,
    ) -> int:
        """Return the stable integer action accepted by Gymnasium-style APIs."""

        if isinstance(action, WaitAction):
            return int(TacticalAction.WAIT)
        if isinstance(action, TargetAction):
            return int(TacticalAction.SELECT_TARGET)
        if isinstance(action, NavigateAction):
            return int(TacticalAction.GO_TO_POSITION)
        if isinstance(action, AttackPointAction):
            return int(TacticalAction.GO_TO_ATTACK_POINT)
        if isinstance(action, CorridorAction):
            return int(TacticalAction.SELECT_CORRIDOR)
        if isinstance(action, InteractAction):
            return int(TacticalAction.INTERACT_WITH_OBJECT)
        raise TypeError("Unsupported tactical action payload.")


_ACTION_BY_KIND = {
    TacticalActionKind.TARGET: TacticalAction.SELECT_TARGET,
    TacticalActionKind.NAVIGATE: TacticalAction.GO_TO_POSITION,
    TacticalActionKind.ATTACK_POINT: TacticalAction.GO_TO_ATTACK_POINT,
    TacticalActionKind.CORRIDOR: TacticalAction.SELECT_CORRIDOR,
    TacticalActionKind.INTERACT: TacticalAction.INTERACT_WITH_OBJECT,
    TacticalActionKind.WAIT: TacticalAction.WAIT,
}
