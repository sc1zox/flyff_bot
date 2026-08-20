"""Deterministic viewport initialization for camera zoom and pitch."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from flyff_bot.features.automation.controllers import VIRTUAL_KEY_DOWN, VIRTUAL_KEY_UP

ZOOM_OUT_WHEEL_NOTCHES = 20
PITCH_UP_HOLD_SECONDS = 0.8
PITCH_DOWN_PULSE_SECONDS = 0.55
STEP_SETTLE_SECONDS = 0.2
DEFAULT_AUTO_ALIGN_CAMERA = True


class CameraAlignmentStatus(StrEnum):
    """Outcome of one alignment attempt."""

    ALIGNED = "aligned"
    ABORTED = "aborted"
    FOCUS_LOST = "focus_lost"


@dataclass(frozen=True, slots=True)
class CameraAlignmentConfig:
    """Zoom, pitch, and settle timings of the standardized alignment sequence."""

    zoom_out_notches: int = ZOOM_OUT_WHEEL_NOTCHES
    pitch_up_virtual_key: int = VIRTUAL_KEY_UP
    pitch_up_hold_seconds: float = PITCH_UP_HOLD_SECONDS
    pitch_down_virtual_key: int = VIRTUAL_KEY_DOWN
    pitch_down_pulse_seconds: float = PITCH_DOWN_PULSE_SECONDS
    step_settle_seconds: float = STEP_SETTLE_SECONDS

    def __post_init__(self) -> None:
        if self.zoom_out_notches <= 0:
            raise ValueError("Camera zoom-out notch count must be positive.")
        if self.pitch_up_hold_seconds <= 0.0 or self.pitch_down_pulse_seconds <= 0.0:
            raise ValueError("Camera pitch durations must be positive.")
        if self.step_settle_seconds < 0.0:
            raise ValueError("Camera settle delay must not be negative.")


class CameraInputAdapter(Protocol):
    """Guarded platform operations needed to move the camera."""

    def is_aborted(self) -> bool: ...

    def is_foreground(self, window_handle: int) -> bool: ...

    def scroll_wheel_while_guarded(self, window_handle: int, notches: int) -> None: ...

    def send_key_while_guarded(
        self, window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None: ...

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None: ...


class CameraAligner:
    """Drive one client's camera to the calibrated zoom hard-stop and ~45 degree pitch."""

    def __init__(
        self,
        adapter: CameraInputAdapter,
        window_handle: int,
        *,
        config: CameraAlignmentConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._adapter = adapter
        self._window_handle = window_handle
        self._config = config or CameraAlignmentConfig()
        self._sleep = sleep

    def align(self) -> CameraAlignmentStatus:
        """Run the standardized sequence, halting before any step that is no longer safe."""

        blocked = self._blocked()
        if blocked is not None:
            return blocked

        self._adapter.scroll_wheel_while_guarded(self._window_handle, self._config.zoom_out_notches)
        blocked = self._settle_then_check()
        if blocked is not None:
            return blocked

        self._adapter.send_key_while_guarded(
            self._window_handle,
            self._config.pitch_up_virtual_key,
            self._config.pitch_up_hold_seconds,
        )
        blocked = self._settle_then_check()
        if blocked is not None:
            return blocked

        self._adapter.send_key_while_guarded(
            self._window_handle,
            self._config.pitch_down_virtual_key,
            self._config.pitch_down_pulse_seconds,
        )
        blocked = self._settle_then_check()
        if blocked is not None:
            return blocked
        return CameraAlignmentStatus.ALIGNED

    def _settle_then_check(self) -> CameraAlignmentStatus | None:
        self._sleep(self._config.step_settle_seconds)
        return self._blocked()

    def _blocked(self) -> CameraAlignmentStatus | None:
        """Report why the sequence must not continue, or None while it stays safe."""

        if self._adapter.is_aborted():
            return CameraAlignmentStatus.ABORTED
        if not self._adapter.is_foreground(self._window_handle):
            return CameraAlignmentStatus.FOCUS_LOST
        return None
