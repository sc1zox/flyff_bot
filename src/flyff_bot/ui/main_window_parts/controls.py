from __future__ import annotations

from PySide6.QtCore import Qt

from flyff_bot.features.input_control import parse_virtual_key

DEFAULT_ATTACK_KEY_NAME = "F3"
HOTKEY_CHOICES = [
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "F8",
    "F9",
    "F10",
    "F11",
    "F12",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
    "C",
    "Space",
]


def key_label(key_code: int) -> str | None:
    if Qt.Key.Key_F1 <= key_code <= Qt.Key.Key_F12:
        return f"F{key_code - int(Qt.Key.Key_F1) + 1}"
    if Qt.Key.Key_0 <= key_code <= Qt.Key.Key_9:
        return chr(key_code)
    if Qt.Key.Key_A <= key_code <= Qt.Key.Key_Z:
        return chr(key_code)
    if key_code == Qt.Key.Key_Space:
        return "Space"
    return None


def default_attack_virtual_key() -> int:
    return parse_virtual_key(DEFAULT_ATTACK_KEY_NAME)
