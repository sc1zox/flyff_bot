"""Values and errors exposed by the input-control feature."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class WindowRef:
    """A visible top-level window owned by the target process."""

    handle: int
    title: str


class InputErrorCode(StrEnum):
    """Stable failures mapped to localized text at the UI boundary."""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    FOCUS_FAILED = "focus_failed"


class InputControlError(RuntimeError):
    """A known input-control failure."""

    def __init__(self, code: InputErrorCode) -> None:
        super().__init__(code.value)
        self.code = code
