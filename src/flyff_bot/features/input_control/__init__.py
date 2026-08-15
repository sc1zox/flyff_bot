"""Foreground input-control feature."""

from flyff_bot.features.input_control.controller import WindowsInputController
from flyff_bot.features.input_control.keymap import parse_virtual_key
from flyff_bot.features.input_control.models import InputControlError, InputErrorCode, WindowRef

__all__ = [
    "InputControlError",
    "InputErrorCode",
    "WindowRef",
    "WindowsInputController",
    "parse_virtual_key",
]
