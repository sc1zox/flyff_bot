"""Foreground- and END-guarded dispatch for learned pathing movement."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # Importing the controller module eagerly would close the
    # navigation -> automation -> navigation import cycle at module load time.
    from flyff_bot.features.navigation.pathing import PathingDecision


class PathingInputAdapter(Protocol):
    """Platform operations that can stop a held pathing key on lost focus."""

    def is_aborted(self) -> bool: ...

    def is_foreground(self, window_handle: int) -> bool: ...

    def send_key_while_guarded(
        self, window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None: ...


class PathingInputDispatcher:
    """Dispatch pathing movement only while the client remains safe to control."""

    def __init__(self, adapter: PathingInputAdapter, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, decision: PathingDecision) -> bool:
        """Return whether one guarded pathing movement was issued."""

        if decision.virtual_key is None or decision.key_press_duration_seconds is None:
            return False
        if self._adapter.is_aborted() or not self._adapter.is_foreground(self._window_handle):
            return False
        self._adapter.send_key_while_guarded(
            self._window_handle, decision.virtual_key, decision.key_press_duration_seconds
        )
        return True
