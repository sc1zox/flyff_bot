"""Foreground and emergency-stop guard for loot pickup input requests."""

from __future__ import annotations

from typing import Protocol

from flyff_bot.features.automation.controllers import LootDecision


class LootInputAdapter(Protocol):
    """The minimal safe platform boundary used to dispatch the pickup key."""

    def is_aborted(self) -> bool:
        """Return whether the emergency stop is active."""

    def is_foreground(self, window_handle: int) -> bool:
        """Return whether the target client remains foregrounded."""

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        """Press and release one configured virtual key."""


class LootInputDispatcher:
    """Dispatch a pickup key only while END is clear and the client is foregrounded."""

    def __init__(self, adapter: LootInputAdapter, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, decision: LootDecision) -> bool:
        """Return whether the requested pickup input was safely sent."""

        if (
            decision.virtual_key is None
            or decision.key_press_duration_seconds is None
            or self._adapter.is_aborted()
            or not self._adapter.is_foreground(self._window_handle)
        ):
            return False
        self._adapter.send_key(decision.virtual_key, decision.key_press_duration_seconds)
        return True
