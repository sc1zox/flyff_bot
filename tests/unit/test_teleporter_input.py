"""Regression coverage for guarded teleporter hotkey input (BUG-026)."""

from __future__ import annotations

from typing import cast

from flyff_bot.features.input_control import WindowsInputController
from flyff_bot.features.navigation.teleporter_input import (
    TeleporterDialogLocator,
    TeleporterWindowsInput,
)


class _Locator:
    def locate(self, _window_handle: int) -> None:
        return None


class _GuardedController:
    def __init__(self) -> None:
        self.guarded_keys: list[tuple[int, int, float]] = []
        self.unguarded_keys: list[tuple[int, float]] = []

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, window_handle: int) -> bool:
        return True

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.unguarded_keys.append((virtual_key, duration_seconds))

    def send_key_while_guarded(
        self,
        window_handle: int,
        virtual_key: int,
        duration_seconds: float,
    ) -> None:
        self.guarded_keys.append((window_handle, virtual_key, duration_seconds))


def test_teleporter_hotkey_uses_window_guard() -> None:
    controller = _GuardedController()
    adapter = TeleporterWindowsInput(
        cast(WindowsInputController, controller),
        1234,
        dialog_locator=cast(TeleporterDialogLocator, _Locator()),
    )

    adapter.pulse_teleporter_hotkey(0x56, 0.08)

    assert controller.unguarded_keys == []
    assert controller.guarded_keys == [(1234, 0x56, 0.08)]
