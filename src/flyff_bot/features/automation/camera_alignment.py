"""Closed-loop camera positioning from guarded input and live memory feedback."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from flyff_bot.features.input_control.keymap import VIRTUAL_KEY_DOWN, VIRTUAL_KEY_UP
from flyff_bot.features.navigation.live_camera import CameraReading, CameraState
from flyff_bot.features.tactical_parameters import TacticalParameterSpace

ZOOM_OUT_WHEEL_NOTCHES = 20
PITCH_UP_HOLD_SECONDS = 0.08
PITCH_DOWN_PULSE_SECONDS = 0.08
PITCH_MEDIUM_PULSE_SECONDS = 0.05
PITCH_FINE_PULSE_SECONDS = 0.025
PITCH_COARSE_ERROR_DEGREES = 10.0
PITCH_MEDIUM_ERROR_DEGREES = 5.0
STEP_SETTLE_SECONDS = 0.2
DEFAULT_AUTO_ALIGN_CAMERA = True
CALIBRATED_CAMERA_PITCH_DEGREES = 30.0
PITCH_TOLERANCE_DEGREES = 2.5
ZOOM_DELTA_TOLERANCE_UNITS = 0.01
ZOOM_HARD_STOP_CONFIRMATION_STEPS = 2
MAXIMUM_PITCH_STEPS = 20


class CameraAlignmentStatus(StrEnum):
    """Outcome of one alignment attempt."""

    ALIGNED = "aligned"
    ABORTED = "aborted"
    FOCUS_LOST = "focus_lost"
    CAMERA_UNAVAILABLE = "camera_unavailable"
    NOT_CONVERGED = "not_converged"


@dataclass(frozen=True, slots=True)
class CameraAlignmentConfig:
    """Bounded actuator and convergence settings for camera alignment."""

    zoom_out_notches: int = ZOOM_OUT_WHEEL_NOTCHES
    pitch_up_virtual_key: int = VIRTUAL_KEY_UP
    pitch_up_hold_seconds: float = PITCH_UP_HOLD_SECONDS
    pitch_down_virtual_key: int = VIRTUAL_KEY_DOWN
    pitch_down_pulse_seconds: float = PITCH_DOWN_PULSE_SECONDS
    step_settle_seconds: float = STEP_SETTLE_SECONDS
    target_pitch_degrees: float = CALIBRATED_CAMERA_PITCH_DEGREES
    pitch_tolerance_degrees: float = PITCH_TOLERANCE_DEGREES
    zoom_delta_tolerance_units: float = ZOOM_DELTA_TOLERANCE_UNITS
    maximum_pitch_steps: int = MAXIMUM_PITCH_STEPS

    def __post_init__(self) -> None:
        if self.zoom_out_notches <= 0 or self.maximum_pitch_steps <= 0:
            raise ValueError("Camera actuator step budgets must be positive.")
        if self.pitch_up_hold_seconds <= 0.0 or self.pitch_down_pulse_seconds <= 0.0:
            raise ValueError("Camera pitch durations must be positive.")
        if self.step_settle_seconds < 0.0:
            raise ValueError("Camera settle delay must not be negative.")
        if self.pitch_tolerance_degrees <= 0.0 or self.zoom_delta_tolerance_units < 0.0:
            raise ValueError("Camera convergence tolerances are invalid.")


class CameraInputAdapter(Protocol):
    """Guarded platform operations needed to move the camera."""

    def is_aborted(self) -> bool: ...

    def is_foreground(self, window_handle: int) -> bool: ...

    def scroll_wheel_while_guarded(self, window_handle: int, notches: int) -> None: ...

    def send_key_while_guarded(
        self, window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None: ...


class CameraStateSource(Protocol):
    """Read-only source of measured pitch and zoom after each bounded action."""

    def poll(self, at_seconds: float) -> CameraReading: ...


class CameraAligner:
    """Converge to the zoom hard-stop and configured pitch using live feedback."""

    def __init__(
        self,
        adapter: CameraInputAdapter,
        window_handle: int,
        camera_source: CameraStateSource,
        *,
        config: CameraAlignmentConfig | None = None,
        tactical_parameters: TacticalParameterSpace | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._adapter = adapter
        self._window_handle = window_handle
        self._camera_source = camera_source
        self._config = config or CameraAlignmentConfig()
        if tactical_parameters is not None:
            self._config = _camera_config_with_parameters(self._config, tactical_parameters)
        self._sleep = sleep
        self._monotonic = monotonic

    def update_tactical_parameters(self, parameters: TacticalParameterSpace) -> None:
        """Apply bounded actuator targets for the next explicit alignment request."""

        self._config = _camera_config_with_parameters(self._config, parameters)

    def align(self) -> CameraAlignmentStatus:
        """Run a guarded measure-act-measure loop with bounded attempts."""

        blocked = self._blocked()
        if blocked is not None:
            return blocked
        reading = self._poll()
        if reading is None:
            return CameraAlignmentStatus.CAMERA_UNAVAILABLE

        previous_zoom = reading.zoom_distance
        stationary_zoom_steps = 0
        zoom_stopped = False
        for _step in range(self._config.zoom_out_notches):
            blocked = self._blocked()
            if blocked is not None:
                return blocked
            self._adapter.scroll_wheel_while_guarded(self._window_handle, 1)
            blocked, reading = self._settle_and_poll()
            if blocked is not None:
                return blocked
            if reading is None:
                return CameraAlignmentStatus.CAMERA_UNAVAILABLE
            zoom_delta = reading.zoom_distance - previous_zoom
            previous_zoom = reading.zoom_distance
            if zoom_delta <= self._config.zoom_delta_tolerance_units:
                stationary_zoom_steps += 1
                if stationary_zoom_steps >= ZOOM_HARD_STOP_CONFIRMATION_STEPS:
                    zoom_stopped = True
                    break
            else:
                stationary_zoom_steps = 0
        if not zoom_stopped:
            return CameraAlignmentStatus.NOT_CONVERGED

        for _step in range(self._config.maximum_pitch_steps):
            error = self._config.target_pitch_degrees - reading.pitch_degrees
            if abs(error) <= self._config.pitch_tolerance_degrees:
                return CameraAlignmentStatus.ALIGNED
            blocked = self._blocked()
            if blocked is not None:
                return blocked
            if error > 0.0:
                key = self._config.pitch_up_virtual_key
            else:
                key = self._config.pitch_down_virtual_key
            duration = self._pitch_pulse_duration(error)
            self._adapter.send_key_while_guarded(self._window_handle, key, duration)
            blocked, reading = self._settle_and_poll()
            if blocked is not None:
                return blocked
            if reading is None:
                return CameraAlignmentStatus.CAMERA_UNAVAILABLE
        return CameraAlignmentStatus.NOT_CONVERGED

    def _pitch_pulse_duration(self, error_degrees: float) -> float:
        """Return a bounded pulse that becomes gentler near the measured target."""

        absolute_error = abs(error_degrees)
        maximum_duration = (
            self._config.pitch_up_hold_seconds
            if error_degrees > 0.0
            else self._config.pitch_down_pulse_seconds
        )
        if absolute_error > PITCH_COARSE_ERROR_DEGREES:
            return maximum_duration
        if absolute_error > PITCH_MEDIUM_ERROR_DEGREES:
            return min(maximum_duration, PITCH_MEDIUM_PULSE_SECONDS)
        return min(maximum_duration, PITCH_FINE_PULSE_SECONDS)

    def _settle_and_poll(
        self,
    ) -> tuple[CameraAlignmentStatus | None, CameraState | None]:
        self._sleep(self._config.step_settle_seconds)
        blocked = self._blocked()
        return (blocked, None) if blocked is not None else (None, self._poll())

    def _poll(self) -> CameraState | None:
        reading = self._camera_source.poll(self._monotonic())
        return reading.state

    def _blocked(self) -> CameraAlignmentStatus | None:
        if self._adapter.is_aborted():
            return CameraAlignmentStatus.ABORTED
        if not self._adapter.is_foreground(self._window_handle):
            return CameraAlignmentStatus.FOCUS_LOST
        return None


def _camera_config_with_parameters(
    config: CameraAlignmentConfig, parameters: TacticalParameterSpace
) -> CameraAlignmentConfig:
    return replace(
        config,
        zoom_out_notches=round(parameters.camera_zoom_level),
        target_pitch_degrees=parameters.camera_pitch_degrees,
    )
