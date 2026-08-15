"""Foreground- and END-guarded dispatch for staged search requests."""

from __future__ import annotations

from typing import Protocol

from flyff_bot.features.automation.controllers import SearchDecision, SearchInputKind


class SearchInputAdapter(Protocol):
    """Platform operations that can stop a held search key on lost focus."""

    def is_aborted(self) -> bool: ...

    def is_foreground(self, window_handle: int) -> bool: ...

    def send_key_while_guarded(
        self, window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None: ...

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None: ...


class SearchInputDispatcher:
    """Dispatch search keys and clicks only while the client remains safe to control."""

    def __init__(self, adapter: SearchInputAdapter, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, decision: SearchDecision) -> bool:
        """Return whether one guarded search request was issued."""

        if self._adapter.is_aborted() or not self._adapter.is_foreground(self._window_handle):
            return False
        if decision.input_kind is SearchInputKind.KEY:
            if decision.virtual_key is None or decision.key_press_duration_seconds is None:
                return False
            self._adapter.send_key_while_guarded(
                self._window_handle, decision.virtual_key, decision.key_press_duration_seconds
            )
            return True
        if decision.input_kind is SearchInputKind.CLICK and decision.position is not None:
            self._adapter.click_client(
                self._window_handle, decision.position.x, decision.position.y
            )
            return True
        return False
