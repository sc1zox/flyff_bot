"""Foreground and emergency-stop guard for combat input requests."""

from __future__ import annotations

from typing import Protocol

from flyff_bot.features.automation.controllers import CombatDecision, CombatInputKind


class CombatInputAdapter(Protocol):
    """The minimal safe platform boundary used to dispatch combat input."""

    def is_aborted(self) -> bool:
        """Return whether the emergency stop is active."""

    def is_foreground(self, window_handle: int) -> bool:
        """Return whether the target client remains foregrounded."""

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        """Click one client-relative coordinate."""

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        """Press and release one configured virtual key."""


class CombatInputDispatcher:
    """Dispatch only a non-empty decision while END is clear and the window is foregrounded."""

    def __init__(self, adapter: CombatInputAdapter, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, decision: CombatDecision) -> bool:
        """Return whether an input was sent; never refocus a window during combat."""

        if (
            decision.input_kind is None
            or self._adapter.is_aborted()
            or not self._adapter.is_foreground(self._window_handle)
        ):
            return False
        if decision.input_kind is CombatInputKind.CLICK:
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
