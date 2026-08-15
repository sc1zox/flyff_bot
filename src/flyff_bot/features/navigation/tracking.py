"""Relative position estimation and visual stall detection for pathing."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_A,
    VIRTUAL_KEY_D,
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.navigation.spatial import WorldPoint
from flyff_bot.features.vision.models import CapturedFrame

DEFAULT_FORWARD_SPEED_UNITS_PER_SECOND = 60.0
DEFAULT_STRAFE_SPEED_UNITS_PER_SECOND = 45.0
DEFAULT_TURN_DEGREES_PER_SECOND = 90.0
DEFAULT_MOTION_THRESHOLD = 1.5
DEFAULT_STALL_SAMPLE_COUNT = 2
DEFAULT_MOTION_SAMPLE_STRIDE = 8
FULL_TURN_DEGREES = 360.0
HALF_TURN_DEGREES = 180.0


@dataclass(frozen=True, slots=True)
class MovementModel:
    """Estimated client movement rates used for dead-reckoning navigation."""

    forward_speed_units_per_second: float = DEFAULT_FORWARD_SPEED_UNITS_PER_SECOND
    strafe_speed_units_per_second: float = DEFAULT_STRAFE_SPEED_UNITS_PER_SECOND
    turn_degrees_per_second: float = DEFAULT_TURN_DEGREES_PER_SECOND

    def __post_init__(self) -> None:
        if self.forward_speed_units_per_second <= 0.0:
            raise ValueError("Forward speed estimate must be positive.")
        if self.strafe_speed_units_per_second <= 0.0:
            raise ValueError("Strafe speed estimate must be positive.")
        if self.turn_degrees_per_second <= 0.0:
            raise ValueError("Turn rate estimate must be positive.")


@dataclass(frozen=True, slots=True)
class StallConfig:
    """How little the client view may change before movement counts as stalled."""

    motion_threshold: float = DEFAULT_MOTION_THRESHOLD
    consecutive_samples: int = DEFAULT_STALL_SAMPLE_COUNT
    sample_stride: int = DEFAULT_MOTION_SAMPLE_STRIDE

    def __post_init__(self) -> None:
        if self.motion_threshold <= 0.0:
            raise ValueError("Stall motion threshold must be positive.")
        if self.consecutive_samples <= 0:
            raise ValueError("Stall sample count must be positive.")
        if self.sample_stride <= 0:
            raise ValueError("Stall sample stride must be positive.")


class MovementTracker:
    """Estimate a session-relative position and heading from dispatched movement keys."""

    def __init__(self, model: MovementModel | None = None) -> None:
        self._model = model or MovementModel()
        self._position = WorldPoint(0.0, 0.0)
        self._heading_degrees = 0.0

    @property
    def position(self) -> WorldPoint:
        """Return the estimated position relative to the session start point."""

        return self._position

    @property
    def heading_degrees(self) -> float:
        """Return the estimated facing as a clockwise compass bearing."""

        return self._heading_degrees

    def reset(self) -> None:
        """Return the estimate to the session origin and its initial facing."""

        self._position = WorldPoint(0.0, 0.0)
        self._heading_degrees = 0.0

    def apply(self, virtual_key: int, duration_seconds: float) -> None:
        """Integrate one dispatched movement or camera-rotation pulse."""

        if duration_seconds <= 0.0:
            return
        if virtual_key in {VIRTUAL_KEY_LEFT, VIRTUAL_KEY_RIGHT}:
            direction = 1.0 if virtual_key == VIRTUAL_KEY_RIGHT else -1.0
            turned = direction * self._model.turn_degrees_per_second * duration_seconds
            self._heading_degrees = (self._heading_degrees + turned) % FULL_TURN_DEGREES
            return
        if virtual_key == VIRTUAL_KEY_W:
            self._translate(
                self._forward_vector(), self._model.forward_speed_units_per_second, duration_seconds
            )
            return
        if virtual_key in {VIRTUAL_KEY_A, VIRTUAL_KEY_D}:
            forward_x, forward_y = self._forward_vector()
            strafe = (
                (forward_y, -forward_x) if virtual_key == VIRTUAL_KEY_D else (-forward_y, forward_x)
            )
            self._translate(strafe, self._model.strafe_speed_units_per_second, duration_seconds)

    def _forward_vector(self) -> tuple[float, float]:
        radians = math.radians(self._heading_degrees)
        return (math.sin(radians), math.cos(radians))

    def _translate(
        self, direction: tuple[float, float], speed: float, duration_seconds: float
    ) -> None:
        distance = speed * duration_seconds
        self._position = WorldPoint(
            self._position.x + direction[0] * distance,
            self._position.y + direction[1] * distance,
        )


class StallDetector:
    """Report a stall when commanded forward movement leaves the client view unchanged."""

    def __init__(self, config: StallConfig | None = None) -> None:
        self._config = config or StallConfig()
        self._signature: npt.NDArray[np.float32] | None = None
        self._consecutive = 0

    @property
    def is_stalled(self) -> bool:
        """Return whether enough consecutive motionless movement samples were seen."""

        return self._consecutive >= self._config.consecutive_samples

    def reset(self) -> None:
        """Forget the previous frame and clear the stall streak."""

        self._signature = None
        self._consecutive = 0

    def observe(self, frame: CapturedFrame | None, *, movement_commanded: bool) -> bool:
        """Compare this frame with the previous one and return the current stall verdict."""

        if frame is None:
            return self.is_stalled
        signature = self._frame_signature(frame)
        previous = self._signature
        self._signature = signature
        if not movement_commanded:
            self._consecutive = 0
            return False
        if previous is None or previous.shape != signature.shape:
            return self.is_stalled
        motion = float(np.abs(signature - previous).mean())
        if motion < self._config.motion_threshold:
            self._consecutive += 1
        else:
            self._consecutive = 0
        return self.is_stalled

    def _frame_signature(self, frame: CapturedFrame) -> npt.NDArray[np.float32]:
        stride = self._config.sample_stride
        sampled = frame.pixels[::stride, ::stride]
        return sampled.astype(np.float32).mean(axis=2)


def bearing_degrees(origin: WorldPoint, target: WorldPoint) -> float:
    """Return the clockwise compass bearing from one estimated point to another."""

    return math.degrees(math.atan2(target.x - origin.x, target.y - origin.y)) % FULL_TURN_DEGREES


def heading_error_degrees(heading_degrees: float, bearing: float) -> float:
    """Return the shortest signed turn from a heading to a bearing."""

    return (bearing - heading_degrees + HALF_TURN_DEGREES) % FULL_TURN_DEGREES - HALF_TURN_DEGREES


def distance_units(origin: WorldPoint, target: WorldPoint) -> float:
    """Return the straight-line distance between two estimated points."""

    return math.hypot(target.x - origin.x, target.y - origin.y)
