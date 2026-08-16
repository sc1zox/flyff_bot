"""Tests for Windows input controller adapter and guards."""

from __future__ import annotations

import sys

import pytest

from flyff_bot.features.input_control.controller import (
    WindowsInputController,
)


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
