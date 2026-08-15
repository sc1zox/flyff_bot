"""Application-wide constants with stable domain meaning."""

from enum import IntEnum

DEFAULT_PROCESS_NAME = "neuz.exe"
DEFAULT_KEY_DURATION_SECONDS = 0.08
DEFAULT_START_DELAY_SECONDS = 3.0
MINIMUM_KEY_DURATION_SECONDS = 0.01


class ExitCode(IntEnum):
    """Process exit codes exposed by the command-line interface."""

    SUCCESS = 0
    WINDOW_NOT_FOUND = 1
    ABORTED = 2
    INPUT_FAILURE = 3
    DETECTION_FAILURE = 4
    LOOT_OCR_FAILURE = 5
