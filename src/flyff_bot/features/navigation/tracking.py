"""Stall detection for authoritative 3D closed-loop navigation."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.vision.models import CapturedFrame

DEFAULT_LIVE_MOTION_THRESHOLD_UNITS_PER_SECOND = 0.5
DEFAULT_LIVE_STALL_TIMEOUT_SECONDS = 2.0
DEFAULT_MOTION_THRESHOLD = 1.5
DEFAULT_STALL_TIMEOUT_SECONDS = 5.0
DEFAULT_MOVEMENT_GRACE_SECONDS = 2.0
DEFAULT_MOTION_SAMPLE_STRIDE = 8
DEFAULT_CENTER_MASK_WIDTH_FRACTION = 0.34
DEFAULT_CENTER_MASK_HEIGHT_FRACTION = 0.5
MAXIMUM_STALL_SAMPLE_SECONDS = 1.0


class StallConfig:
    """Configuration for stall and collision detection."""

    def __init__(
        self,
        *,
        live_motion_threshold_units_per_second: float = (
            DEFAULT_LIVE_MOTION_THRESHOLD_UNITS_PER_SECOND
        ),
        live_stall_timeout_seconds: float = DEFAULT_LIVE_STALL_TIMEOUT_SECONDS,
        motion_threshold: float = DEFAULT_MOTION_THRESHOLD,
        stall_timeout_seconds: float = DEFAULT_STALL_TIMEOUT_SECONDS,
        movement_grace_seconds: float = DEFAULT_MOVEMENT_GRACE_SECONDS,
        sample_stride: int = DEFAULT_MOTION_SAMPLE_STRIDE,
        center_mask_width_fraction: float = DEFAULT_CENTER_MASK_WIDTH_FRACTION,
        center_mask_height_fraction: float = DEFAULT_CENTER_MASK_HEIGHT_FRACTION,
    ) -> None:
        if live_motion_threshold_units_per_second <= 0.0:
            raise ValueError("Live stall motion threshold must be positive.")
        if live_stall_timeout_seconds <= 0.0:
            raise ValueError("Live stall timeout must be positive.")
        if motion_threshold <= 0.0:
            raise ValueError("Stall motion threshold must be positive.")
        if stall_timeout_seconds <= 0.0:
            raise ValueError("Stall timeout must be positive.")
        if movement_grace_seconds < 0.0:
            raise ValueError("Stall movement grace must not be negative.")
        if sample_stride <= 0:
            raise ValueError("Stall sample stride must be positive.")
        for fraction in (center_mask_width_fraction, center_mask_height_fraction):
            if not 0.0 <= fraction < 1.0:
                raise ValueError("Stall centre mask fractions must be within [0.0, 1.0).")
        self.live_motion_threshold_units_per_second = live_motion_threshold_units_per_second
        self.live_stall_timeout_seconds = live_stall_timeout_seconds
        self.motion_threshold = motion_threshold
        self.stall_timeout_seconds = stall_timeout_seconds
        self.movement_grace_seconds = movement_grace_seconds
        self.sample_stride = sample_stride
        self.center_mask_width_fraction = center_mask_width_fraction
        self.center_mask_height_fraction = center_mask_height_fraction


class StallDetector:
    """Report a stall when commanded movement produces no position displacement."""

    def __init__(self, config: StallConfig | None = None) -> None:
        self._config = config or StallConfig()
        self._signature: npt.NDArray[np.float32] | None = None
        self._peripheral_mask: npt.NDArray[np.bool_] | None = None
        self._stalled_seconds = 0.0
        self._sampled_at_seconds: float | None = None
        self._commanded_at_seconds: float | None = None
        self._live_position: WorldPosition | None = None
        self._live_at_seconds: float | None = None
        self._using_live_position = False

    @property
    def is_stalled(self) -> bool:
        """Return whether motionless state persisted for the configured stall timeout."""

        timeout = (
            self._config.live_stall_timeout_seconds
            if self._using_live_position
            else self._config.stall_timeout_seconds
        )
        return self._stalled_seconds >= timeout

    @property
    def stalled_seconds(self) -> float:
        """Return how long commanded movement has produced no movement."""

        return self._stalled_seconds

    def reset(self) -> None:
        """Forget the previous position and clear the accumulated stall time."""

        self._signature = None
        self._stalled_seconds = 0.0
        self._sampled_at_seconds = None
        self._commanded_at_seconds = None
        self._live_position = None
        self._live_at_seconds = None
        self._using_live_position = False

    def observe(
        self,
        frame: CapturedFrame | None = None,
        *,
        movement_commanded: bool = True,
        at_seconds: float,
        live_position: WorldPosition | None = None,
        live_sampled_at_seconds: float | None = None,
    ) -> bool:
        """Return the current stall verdict for one tick."""

        if live_position is not None:
            return self._observe_live(
                live_position,
                movement_commanded=movement_commanded,
                at_seconds=(
                    at_seconds if live_sampled_at_seconds is None else live_sampled_at_seconds
                ),
            )
        self._live_position = None
        self._live_at_seconds = None
        self._using_live_position = False
        return self._observe_frame(
            frame, movement_commanded=movement_commanded, at_seconds=at_seconds
        )

    def _observe_live(
        self,
        position: WorldPosition,
        *,
        movement_commanded: bool,
        at_seconds: float,
    ) -> bool:
        previous = self._live_position
        previous_at_seconds = self._live_at_seconds
        self._live_position = position
        self._live_at_seconds = at_seconds
        self._using_live_position = True
        self._signature = None
        self._sampled_at_seconds = at_seconds
        verdict = self._gate(movement_commanded, at_seconds)
        if verdict is not None:
            return verdict
        if previous is None or previous_at_seconds is None:
            self._stalled_seconds = 0.0
            return self.is_stalled
        elapsed = min(max(0.0, at_seconds - previous_at_seconds), MAXIMUM_STALL_SAMPLE_SECONDS)
        if elapsed <= 0.0:
            return self.is_stalled
        speed = position.distance_to(previous) / elapsed
        if speed < self._config.live_motion_threshold_units_per_second:
            self._stalled_seconds += elapsed
        else:
            self._stalled_seconds = 0.0
        return self.is_stalled

    def _observe_frame(
        self, frame: CapturedFrame | None, *, movement_commanded: bool, at_seconds: float
    ) -> bool:
        if frame is None:
            return self.is_stalled
        signature = self._frame_signature(frame)
        previous = self._signature
        previous_at_seconds = self._sampled_at_seconds
        self._signature = signature
        self._sampled_at_seconds = at_seconds
        verdict = self._gate(movement_commanded, at_seconds)
        if verdict is not None:
            return verdict
        if previous is None or previous.shape != signature.shape or previous_at_seconds is None:
            return self.is_stalled
        elapsed = min(max(0.0, at_seconds - previous_at_seconds), MAXIMUM_STALL_SAMPLE_SECONDS)
        if self._motion(signature, previous) < self._config.motion_threshold:
            self._stalled_seconds += elapsed
        else:
            self._stalled_seconds = 0.0
        return self.is_stalled

    def _gate(self, movement_commanded: bool, at_seconds: float) -> bool | None:
        """Return a final verdict for ticks that carry no stall evidence, else ``None``."""

        if movement_commanded:
            self._commanded_at_seconds = at_seconds
            return None
        if self._within_movement_grace(at_seconds):
            return self.is_stalled
        self._stalled_seconds = 0.0
        return False

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
