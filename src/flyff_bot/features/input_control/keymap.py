"""Translate supported key names to Windows virtual-key codes."""

from types import MappingProxyType

NAMED_VIRTUAL_KEYS = MappingProxyType(
    {
        "space": 0x20,
        "tab": 0x09,
        "enter": 0x0D,
        "escape": 0x1B,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
    }
)
FUNCTION_KEY_PREFIX = "f"
FUNCTION_KEY_MINIMUM = 1
FUNCTION_KEY_MAXIMUM = 12
FUNCTION_KEY_OFFSET = 0x6F
SUPPORTED_SINGLE_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

# Movement and camera virtual-key codes. They live in this dependency-free module so that
# navigation and automation can both name them without importing each other, which is what
# used to make `flyff_bot.features.automation` unimportable from a cold interpreter.
VIRTUAL_KEY_A = 0x41
VIRTUAL_KEY_D = 0x44
VIRTUAL_KEY_S = 0x53
VIRTUAL_KEY_W = 0x57
VIRTUAL_KEY_SPACE = 0x20
VIRTUAL_KEY_LEFT = 0x25
VIRTUAL_KEY_UP = 0x26
VIRTUAL_KEY_RIGHT = 0x27
VIRTUAL_KEY_DOWN = 0x28


def parse_virtual_key(value: str) -> int:
    """Parse a supported key label into a Windows virtual-key code."""

    normalized = value.lower()
    if normalized in NAMED_VIRTUAL_KEYS:
        return NAMED_VIRTUAL_KEYS[normalized]

    uppercase = value.upper()
    if len(value) == 1 and uppercase in SUPPORTED_SINGLE_CHARACTERS:
        return ord(uppercase)

    if normalized.startswith(FUNCTION_KEY_PREFIX):
        suffix = normalized.removeprefix(FUNCTION_KEY_PREFIX)
        if suffix.isdigit():
            number = int(suffix)
            if FUNCTION_KEY_MINIMUM <= number <= FUNCTION_KEY_MAXIMUM:
                return FUNCTION_KEY_OFFSET + number

    raise ValueError(value)
