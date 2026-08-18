"""Tests for Windows input controller adapter and guards."""

from __future__ import annotations

import sys
import time

import pytest

from flyff_bot.features.input_control.controller import (
    WindowsInputController,
)
from flyff_bot.features.input_control.models import ScreenRect


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_is_foreground_handles_none_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = WindowsInputController()
    monkeypatch.setattr(controller._user32, "GetForegroundWindow", lambda: None)

    assert controller.is_foreground(12345) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_is_foreground_matches_target_window(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = WindowsInputController()
    monkeypatch.setattr(controller._user32, "GetForegroundWindow", lambda: 12345)

    assert controller.is_foreground(12345) is True
    assert controller.is_foreground(99999) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_focus_window_succeeds_when_window_becomes_foreground(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WindowsInputController()
    monkeypatch.setattr(controller._user32, "ShowWindow", lambda _h, _cmd: True)
    monkeypatch.setattr(controller._user32, "BringWindowToTop", lambda _h: True)
    monkeypatch.setattr(controller._user32, "SetForegroundWindow", lambda _h: True)
    monkeypatch.setattr(controller._user32, "GetForegroundWindow", lambda: 12345)

    # Should succeed without raising
    controller.focus_window(12345)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_focus_window_raises_when_window_remains_unfocused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flyff_bot.features.input_control.models import InputControlError, InputErrorCode

    controller = WindowsInputController()
    monkeypatch.setattr(controller._user32, "ShowWindow", lambda _h, _cmd: True)
    monkeypatch.setattr(controller._user32, "BringWindowToTop", lambda _h: False)
    monkeypatch.setattr(controller._user32, "SetForegroundWindow", lambda _h: False)
    monkeypatch.setattr(controller._user32, "GetForegroundWindow", lambda: 99999)

    with pytest.raises(InputControlError) as exc_info:
        controller.focus_window(12345)

    assert exc_info.value.code == InputErrorCode.FOCUS_FAILED


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_scroll_wheel_centers_the_cursor_and_sends_one_event_per_notch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US-042: the zoom hard-stop needs discrete notches over the client area."""

    controller = WindowsInputController()
    cursor_positions: list[tuple[int, int]] = []
    sent = 0

    def _send_input(count: int, _events: object, _size: int) -> int:
        nonlocal sent
        sent += count
        return count

    monkeypatch.setattr(
        controller,
        "client_screen_bounds",
        lambda _handle: ScreenRect(left=100, top=200, width=800, height=600),
    )
    monkeypatch.setattr(controller, "is_aborted", lambda: False)
    monkeypatch.setattr(controller, "is_foreground", lambda _handle: True)
    monkeypatch.setattr(
        controller._user32, "SetCursorPos", lambda x, y: cursor_positions.append((x, y))
    )
    monkeypatch.setattr(controller._user32, "SendInput", _send_input)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    controller.scroll_wheel_while_guarded(12345, -15)

    assert cursor_positions == [(500, 500)]
    assert sent == 15


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_scroll_wheel_stops_immediately_when_the_client_loses_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US-042: no notch is dispatched once the game window is no longer foregrounded."""

    controller = WindowsInputController()
    sent = 0

    def _send_input(count: int, _events: object, _size: int) -> int:
        nonlocal sent
        sent += count
        return count

    monkeypatch.setattr(controller, "client_screen_bounds", lambda _handle: None)
    monkeypatch.setattr(controller, "is_aborted", lambda: False)
    monkeypatch.setattr(controller, "is_foreground", lambda _handle: False)
    monkeypatch.setattr(controller._user32, "SendInput", _send_input)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    controller.scroll_wheel_while_guarded(12345, -15)

    assert sent == 0
