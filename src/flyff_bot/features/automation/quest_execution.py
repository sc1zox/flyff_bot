"""Foreground and emergency-stop guard for quest dialogue input requests."""

from __future__ import annotations

from flyff_bot.features.automation.quest_execution_models import (
    CombatInputAdapterLike,
    QuestInputKind,
    QuestInteractionDecision,
)


class QuestInputDispatcher:
    """Dispatch only observed, concrete input while END is clear and the client is foreground."""

    def __init__(self, adapter: CombatInputAdapterLike, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, decision: QuestInteractionDecision) -> bool:
        """Return whether one guarded quest-interaction request was issued."""

        if (
            decision.input_kind is QuestInputKind.NONE
            or self._adapter.is_aborted()
            or not self._adapter.is_foreground(self._window_handle)
        ):
            return False
        if decision.input_kind is QuestInputKind.CLICK:
            if decision.position is None:
                return False
            self._adapter.click_client(
                self._window_handle, decision.position.x, decision.position.y
            )
            return True
        if decision.virtual_key is None or decision.key_press_duration_seconds is None:
            return False
        self._adapter.send_key(decision.virtual_key, decision.key_press_duration_seconds)
        return True
