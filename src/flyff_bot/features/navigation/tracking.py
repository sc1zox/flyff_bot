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
    VIRTUAL_KEY_S,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.navigation.spatial import WorldPoint
from flyff_bot.features.vision.models import CapturedFrame

DEFAULT_FORWARD_SPEED_UNITS_PER_SECOND = 60.0
DEFAULT_BACKWARD_SPEED_UNITS_PER_SECOND = 45.0
DEFAULT_TURN_DEGREES_PER_SECOND = 90.0
DEFAULT_MOTION_THRESHOLD = 1.5
DEFAULT_STALL_TIMEOUT_SECONDS = 5.0
DEFAULT_MOVEMENT_GRACE_SECONDS = 2.0
DEFAULT_MOTION_SAMPLE_STRIDE = 8
# The player model is drawn in the middle of the third-person viewport, so its running animation
# keeps producing pixel differences while the world stands still. These fractions are the share of
# the frame that is excluded around that centre. They are estimates, not values calibrated against
# measured client frames.
DEFAULT_CENTER_MASK_WIDTH_FRACTION = 0.34
DEFAULT_CENTER_MASK_HEIGHT_FRACTION = 0.5
# One delayed or dropped capture must not be able to satisfy the whole stall timeout by itself.
MAXIMUM_STALL_SAMPLE_SECONDS = 1.0
FULL_TURN_DEGREES = 360.0
HALF_TURN_DEGREES = 180.0

# Flyff's default controls turn the character with `A`/`D` exactly as the arrow keys do, so all
# four keys rotate the estimated heading instead of translating the estimated position.
ROTATION_VIRTUAL_KEYS = frozenset(
    {VIRTUAL_KEY_LEFT, VIRTUAL_KEY_RIGHT, VIRTUAL_KEY_A, VIRTUAL_KEY_D}
)
CLOCKWISE_VIRTUAL_KEYS = frozenset({VIRTUAL_KEY_RIGHT, VIRTUAL_KEY_D})


@dataclass(frozen=True, slots=True)
class MovementModel:
    """Estimated client movement rates used for dead-reckoning navigation."""

    forward_speed_units_per_second: float = DEFAULT_FORWARD_SPEED_UNITS_PER_SECOND
    backward_speed_units_per_second: float = DEFAULT_BACKWARD_SPEED_UNITS_PER_SECOND
    turn_degrees_per_second: float = DEFAULT_TURN_DEGREES_PER_SECOND

    def __post_init__(self) -> None:
        if self.forward_speed_units_per_second <= 0.0:
            raise ValueError("Forward speed estimate must be positive.")
        if self.backward_speed_units_per_second <= 0.0:
            raise ValueError("Backward speed estimate must be positive.")
        if self.turn_degrees_per_second <= 0.0:
            raise ValueError("Turn rate estimate must be positive.")


@dataclass(frozen=True, slots=True)
class StallConfig:
    """How little the client view may change before movement counts as stalled."""

    motion_threshold: float = DEFAULT_MOTION_THRESHOLD
    stall_timeout_seconds: float = DEFAULT_STALL_TIMEOUT_SECONDS
    movement_grace_seconds: float = DEFAULT_MOVEMENT_GRACE_SECONDS
    sample_stride: int = DEFAULT_MOTION_SAMPLE_STRIDE
    center_mask_width_fraction: float = DEFAULT_CENTER_MASK_WIDTH_FRACTION
    center_mask_height_fraction: float = DEFAULT_CENTER_MASK_HEIGHT_FRACTION

    def __post_init__(self) -> None:
        if self.motion_threshold <= 0.0:
            raise ValueError("Stall motion threshold must be positive.")
        if self.stall_timeout_seconds <= 0.0:
            raise ValueError("Stall timeout must be positive.")
        if self.movement_grace_seconds < 0.0:
            raise ValueError("Stall movement grace must not be negative.")
        if self.sample_stride <= 0:
            raise ValueError("Stall sample stride must be positive.")
        for fraction in (self.center_mask_width_fraction, self.center_mask_height_fraction):
            if not 0.0 <= fraction < 1.0:
                raise ValueError("Stall centre mask fractions must be within [0.0, 1.0).")


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
        if virtual_key in ROTATION_VIRTUAL_KEYS:
            direction = 1.0 if virtual_key in CLOCKWISE_VIRTUAL_KEYS else -1.0
            turned = direction * self._model.turn_degrees_per_second * duration_seconds
            self._heading_degrees = (self._heading_degrees + turned) % FULL_TURN_DEGREES
            return
        if virtual_key == VIRTUAL_KEY_W:
            self._translate(
                self._forward_vector(), self._model.forward_speed_units_per_second, duration_seconds
            )
            return
        if virtual_key == VIRTUAL_KEY_S:
            forward_x, forward_y = self._forward_vector()
            self._translate(
                (-forward_x, -forward_y),
                self._model.backward_speed_units_per_second,
                duration_seconds,
            )

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
    """Report a stall when commanded forward movement leaves the surrounding scenery unchanged."""

    def __init__(self, config: StallConfig | None = None) -> None:
        self._config = config or StallConfig()
        self._signature: npt.NDArray[np.float32] | None = None
        self._peripheral_mask: npt.NDArray[np.bool_] | None = None
        self._stalled_seconds = 0.0
        self._sampled_at_seconds: float | None = None
        self._commanded_at_seconds: float | None = None

    @property
    def is_stalled(self) -> bool:
        """Return whether motionless scenery persisted for the configured stall timeout."""

        return self._stalled_seconds >= self._config.stall_timeout_seconds

    @property
    def stalled_seconds(self) -> float:
        """Return how long commanded forward movement has produced no scene parallax."""

        return self._stalled_seconds

    def reset(self) -> None:
        """Forget the previous frame and clear the accumulated stall time."""

        self._signature = None
        self._stalled_seconds = 0.0
        self._sampled_at_seconds = None
        self._commanded_at_seconds = None

    def observe(
        self, frame: CapturedFrame | None, *, movement_commanded: bool, at_seconds: float
    ) -> bool:
        """Compare this frame with the previous one and return the current stall verdict."""

        if frame is None:
            return self.is_stalled
        signature = self._frame_signature(frame)
        previous = self._signature
        previous_at_seconds = self._sampled_at_seconds
        self._signature = signature
        self._sampled_at_seconds = at_seconds
        if movement_commanded:
            self._commanded_at_seconds = at_seconds
        elif self._within_movement_grace(at_seconds):
            # A tick without a movement command in an ongoing travel phase carries no evidence
            # either way, so the accumulated stall time is held rather than extended or cleared.
            return self.is_stalled
        else:
            self._stalled_seconds = 0.0
            return False
        if previous is None or previous.shape != signature.shape or previous_at_seconds is None:
            return self.is_stalled
        elapsed = min(max(0.0, at_seconds - previous_at_seconds), MAXIMUM_STALL_SAMPLE_SECONDS)
        if self._motion(signature, previous) < self._config.motion_threshold:
            self._stalled_seconds += elapsed
        else:
            self._stalled_seconds = 0.0
        return self.is_stalled

    def _within_movement_grace(self, at_seconds: float) -> bool:
        if self._commanded_at_seconds is None:
            return False
        return at_seconds - self._commanded_at_seconds <= self._config.movement_grace_seconds

    def _motion(
        self, signature: npt.NDArray[np.float32], previous: npt.NDArray[np.float32]
    ) -> float:
        difference = np.abs(signature - previous)
        return float(difference[self._mask_for(difference.shape)].mean())

    def _mask_for(self, shape: tuple[int, ...]) -> npt.NDArray[np.bool_]:
        """Return the sample mask that excludes the centred player-character region."""

        cached = self._peripheral_mask
        if cached is not None and cached.shape == shape:
            return cached
        height, width = shape
        mask = np.ones(shape, dtype=np.bool_)
        half_height = int(height * self._config.center_mask_height_fraction / 2.0)
        half_width = int(width * self._config.center_mask_width_fraction / 2.0)
        if half_height > 0 and half_width > 0:
            center_y = height // 2
            center_x = width // 2
            mask[
                center_y - half_height : center_y + half_height,
                center_x - half_width : center_x + half_width,
            ] = False
        self._peripheral_mask = mask
        return mask

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
