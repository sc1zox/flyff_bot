"""Concrete guarded input adapter for the deterministic teleporter UI sequence."""

from __future__ import annotations

from flyff_bot.features.input_control import (
    InputControlError,
    InputErrorCode,
    WindowsInputController,
    parse_virtual_key,
)
from flyff_bot.features.navigation.teleporter_dispatch import TeleporterDispatchConfig


class TeleporterWindowsInput:
    """Send teleporter UI actions only while the client is foreground and END is clear."""

    def __init__(
        self,
        controller: WindowsInputController,
        *,
        config: TeleporterDispatchConfig | None = None,
    ) -> None:
        self._controller = controller
        self._config = config or TeleporterDispatchConfig()

    def is_aborted(self) -> bool:
        return self._controller.is_aborted()

    def is_foreground(self, window_handle: int) -> bool:
        return self._controller.is_foreground(window_handle)

    def pulse_teleporter_hotkey(self, virtual_key: int, duration_seconds: float) -> None:
        self._controller.send_key(virtual_key, duration_seconds)

    def type_search_text(self, window_handle: int, text: str) -> None:
        self._controller.type_text_while_guarded(window_handle, text)

    def click_search_field(self, window_handle: int) -> None:
        bounds = self._controller.client_screen_bounds(window_handle)
        if bounds is None:
            raise InputControlError(InputErrorCode.FOCUS_FAILED)
        self._controller.click_client(
            window_handle,
            round(bounds.width * self._config.search_field_x_fraction),
            round(bounds.height * self._config.search_field_y_fraction),
        )

    def select_first_result(self, window_handle: int) -> None:
        bounds = self._controller.client_screen_bounds(window_handle)
        if bounds is None:
            raise InputControlError(InputErrorCode.FOCUS_FAILED)
        self._controller.click_client(
            window_handle,
            round(bounds.width * self._config.first_result_x_fraction),
            round(bounds.height * self._config.first_result_y_fraction),
        )

    def click_teleport_button(self, window_handle: int) -> None:
        bounds = self._controller.client_screen_bounds(window_handle)
        if bounds is None:
            raise InputControlError(InputErrorCode.FOCUS_FAILED)
        self._controller.click_client(
            window_handle,
            round(bounds.width * self._config.teleport_button_x_fraction),
            round(bounds.height * self._config.teleport_button_y_fraction),
        )

    def close_teleporter_window(self, window_handle: int) -> None:
        self._controller.send_key_while_guarded(
            window_handle,
            parse_virtual_key("escape"),
            0.05,
        )
