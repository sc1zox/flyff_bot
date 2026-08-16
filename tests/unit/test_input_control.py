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
