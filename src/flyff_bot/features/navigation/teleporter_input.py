"""Concrete guarded input adapter for the deterministic teleporter UI sequence."""

from __future__ import annotations

from typing import Protocol

from flyff_bot.features.input_control import WindowsInputController, parse_virtual_key
from flyff_bot.features.navigation.teleporter_dispatch import (
    ClientPoint,
    TeleporterDialogGeometry,
)


class TeleporterDialogLocator(Protocol):
    """Locate the visible dialog and derive all points from its measured rectangle."""

    def locate(self, window_handle: int) -> TeleporterDialogGeometry | None: ...


class TeleporterWindowsInput:
    """Send teleporter UI actions only while the client is foreground and F12 is clear."""

    def __init__(
        self,
        controller: WindowsInputController,
        window_handle: int,
        *,
        dialog_locator: TeleporterDialogLocator,
    ) -> None:
        self._controller = controller
        self._window_handle = window_handle
        self._dialog_locator = dialog_locator

    def is_aborted(self) -> bool:
        return self._controller.is_aborted()

    def is_foreground(self, window_handle: int) -> bool:
        return self._controller.is_foreground(window_handle)

    def pulse_teleporter_hotkey(self, virtual_key: int, duration_seconds: float) -> None:
        self._controller.send_key_while_guarded(
            self._window_handle,
            virtual_key,
            duration_seconds,
        )

    def type_search_text(self, window_handle: int, text: str) -> None:
        self._controller.type_text_while_guarded(window_handle, text)

    def locate_dialog(self, window_handle: int) -> TeleporterDialogGeometry | None:
        return self._dialog_locator.locate(window_handle)

    def click_client_point(self, window_handle: int, point: ClientPoint) -> None:
        self._controller.click_client(window_handle, point.x, point.y)

    def close_teleporter_window(self, window_handle: int) -> None:
        self._controller.send_key_while_guarded(
            window_handle,
            parse_virtual_key("escape"),
            0.05,
        )
