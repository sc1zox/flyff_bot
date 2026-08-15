"""Unit tests for virtual-key parsing."""

import pytest

from flyff_bot.features.input_control.keymap import parse_virtual_key


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("W", ord("W")),
        ("5", ord("5")),
        ("space", 0x20),
        ("left", 0x25),
        ("right", 0x27),
        ("F1", 0x70),
        ("f12", 0x7B),
    ],
)
def test_parse_virtual_key_accepts_supported_labels(label: str, expected: int) -> None:
    assert parse_virtual_key(label) == expected


@pytest.mark.parametrize("label", ["", "F0", "F13", "shift", "WW"])
def test_parse_virtual_key_rejects_unsupported_labels(label: str) -> None:
    with pytest.raises(ValueError):
        parse_virtual_key(label)
