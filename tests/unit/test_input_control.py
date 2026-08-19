"""Tests for Windows input controller adapter and guards."""

from __future__ import annotations

import sys
import time

import pytest

from flyff_bot.features.input_control.controller import (
    ABSOLUTE_COORDINATE_RANGE,
    MOUSE_EVENT_ABSOLUTE,
    MOUSE_EVENT_MOVE,
    MOUSE_EVENT_VIRTUAL_DESK,
    MOUSE_EVENT_WHEEL,
    WHEEL_DELTA,
    WINDOW_MESSAGE_CLOSE,
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
    """BUG-015: Flyff ignores notches sent at a pointer position it never saw move."""

    controller, events, sleeps = _recording_wheel_controller(monkeypatch)

    controller.scroll_wheel_while_guarded(12345, 15)

    move = events[0].mouse
    assert move.dwFlags == MOUSE_EVENT_MOVE | MOUSE_EVENT_ABSOLUTE | MOUSE_EVENT_VIRTUAL_DESK
    # The client centre normalized onto the absolute range of the 1000x1000 virtual screen.
    assert (move.dx, move.dy) == (
        round(CLIENT_CENTRE[0] * ABSOLUTE_COORDINATE_RANGE / 1000),
        round(CLIENT_CENTRE[1] * ABSOLUTE_COORDINATE_RANGE / 1000),
    )
    # The move is dispatched and given time to be processed before the first notch.
    assert len(events) == 16
    assert len(sleeps) == 16
    assert all(event.mouse.dwFlags == MOUSE_EVENT_WHEEL for event in events[1:])
    assert all(event.mouse.mouseData == WHEEL_DELTA for event in events[1:])


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_scroll_wheel_sends_nothing_when_the_client_area_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-015: without the client rectangle the notches would land on the HUD."""

    controller, events, _sleeps = _recording_wheel_controller(monkeypatch, bounds=None)

    controller.scroll_wheel_while_guarded(12345, 15)

    assert events == []


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_scroll_wheel_stops_immediately_when_the_client_loses_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US-042: neither the pointer move nor a notch is dispatched without focus."""

    controller, events, _sleeps = _recording_wheel_controller(monkeypatch, foreground=False)

    controller.scroll_wheel_while_guarded(12345, 15)

    assert events == []


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_close_window_posts_a_standard_close_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """US-035: a completed session asks the client to close, it never terminates it."""

    controller = WindowsInputController()
    posted: list[tuple[int, int, int, int]] = []

    def _post(handle: int, message: int, wparam: int, lparam: int) -> bool:
        posted.append((handle, message, wparam, lparam))
        return True

    monkeypatch.setattr(controller._user32, "PostMessageW", _post)

    assert controller.close_window(12345) is True
    assert posted == [(12345, WINDOW_MESSAGE_CLOSE, 0, 0)]


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 platform")
def test_close_window_reports_a_refused_request_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WindowsInputController()
    monkeypatch.setattr(
        controller._user32, "PostMessageW", lambda _handle, _message, _wparam, _lparam: 0
    )

    assert controller.close_window(12345) is False
