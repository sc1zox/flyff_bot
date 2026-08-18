"""Tests for Windows input controller adapter and guards."""

from __future__ import annotations

import ctypes
import sys
import time

import pytest

from flyff_bot.features.input_control.controller import (
    ABSOLUTE_COORDINATE_RANGE,
    MOUSE_EVENT_ABSOLUTE,
    MOUSE_EVENT_MOVE,
    MOUSE_EVENT_RIGHT_DOWN,
    MOUSE_EVENT_RIGHT_UP,
    MOUSE_EVENT_VIRTUAL_DESK,
    MOUSE_EVENT_WHEEL,
    WHEEL_DELTA,
    Input,
    WindowsInputController,
)
from flyff_bot.features.input_control.models import ScreenRect

VIRTUAL_SCREEN = {76: 0, 77: 0, 78: 1000, 79: 1000}
CLIENT_BOUNDS = ScreenRect(left=100, top=200, width=800, height=600)
CLIENT_CENTRE = (500, 500)


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


def _recording_wheel_controller(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bounds: ScreenRect | None = CLIENT_BOUNDS,
    foreground: bool = True,
) -> tuple[WindowsInputController, list[Input], list[float]]:
    """Bind a controller to recorded mouse events and sleeps instead of the desktop."""

    controller = WindowsInputController()
    events: list[Input] = []
    sleeps: list[float] = []
    monkeypatch.setattr(controller, "client_screen_bounds", lambda _handle: bounds)
    monkeypatch.setattr(controller, "is_aborted", lambda: False)
    monkeypatch.setattr(controller, "is_foreground", lambda _handle: foreground)
    monkeypatch.setattr(
        controller._user32, "GetSystemMetrics", lambda metric: VIRTUAL_SCREEN[metric]
    )
    monkeypatch.setattr(controller, "_send_mouse_event", events.append)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    return controller, events, sleeps


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_scroll_wheel_injects_a_pointer_move_over_the_client_before_the_notches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-015/BUG-016: Flyff ignores notches sent at a pointer position it never saw move."""

    controller, events, sleeps = _recording_wheel_controller(monkeypatch)
    cursor_positions: list[tuple[int, int]] = []

    def record_cursor(x: int, y: int) -> bool:
        cursor_positions.append((x, y))
        return True

    monkeypatch.setattr(controller._user32, "SetCursorPos", record_cursor)

    controller.scroll_wheel_while_guarded(12345, 20)

    assert cursor_positions == [CLIENT_CENTRE]
    move = events[0].mouse
    assert move.dwFlags == MOUSE_EVENT_MOVE | MOUSE_EVENT_ABSOLUTE | MOUSE_EVENT_VIRTUAL_DESK
    # The client centre normalized onto the absolute range of the 1000x1000 virtual screen.
    assert (move.dx, move.dy) == (
        round(CLIENT_CENTRE[0] * ABSOLUTE_COORDINATE_RANGE / 1000),
        round(CLIENT_CENTRE[1] * ABSOLUTE_COORDINATE_RANGE / 1000),
    )
    # The move and right-click focus pulse are dispatched and settled before the first notch.
    assert len(events) == 23
    assert len(sleeps) == 21
    assert events[1].mouse.dwFlags == MOUSE_EVENT_RIGHT_DOWN
    assert events[2].mouse.dwFlags == MOUSE_EVENT_RIGHT_UP
    assert all(event.mouse.dwFlags == MOUSE_EVENT_WHEEL for event in events[3:])
    assert all(event.mouse.mouseData == WHEEL_DELTA for event in events[3:])


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_scroll_wheel_sends_nothing_when_the_client_area_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-015: without the client rectangle the notches would land on the HUD."""

    controller, events, _sleeps = _recording_wheel_controller(monkeypatch, bounds=None)

    controller.scroll_wheel_while_guarded(12345, 15)

    assert events == []


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_right_click_client_dispatches_down_and_up_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WindowsInputController()
    dispatched_events: list[Input] = []

    def mock_send_input(count: int, events_array: ctypes.Array[Input], _size: int) -> int:
        for i in range(count):
            dispatched_events.append(events_array[i])
        return count

    monkeypatch.setattr(controller._user32, "ClientToScreen", lambda _h, _p: True)
    monkeypatch.setattr(controller._user32, "SetCursorPos", lambda _x, _y: True)
    monkeypatch.setattr(controller._user32, "SendInput", mock_send_input)

    controller.right_click_client(12345, 100, 200)

    assert len(dispatched_events) == 2
    assert dispatched_events[0].mouse.dwFlags == MOUSE_EVENT_RIGHT_DOWN
    assert dispatched_events[1].mouse.dwFlags == MOUSE_EVENT_RIGHT_UP


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_scroll_wheel_stops_immediately_when_the_client_loses_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US-042: neither the pointer move nor a notch is dispatched without focus."""

    controller, events, _sleeps = _recording_wheel_controller(monkeypatch, foreground=False)

    controller.scroll_wheel_while_guarded(12345, 15)

    assert events == []
