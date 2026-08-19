"""Foreground input-control feature."""

from flyff_bot.features.input_control.controller import WindowsInputController
from flyff_bot.features.input_control.keymap import parse_virtual_key
from flyff_bot.features.input_control.models import (
    ForegroundWindowInfo,
    InputControlError,
    InputErrorCode,
    ScreenRect,
    WindowRef,
)

__all__ = [
    "ForegroundWindowInfo",
    "InputControlError",
    "InputErrorCode",
    "ScreenRect",
    "WindowRef",
    "WindowsInputController",
    "parse_virtual_key",
]
