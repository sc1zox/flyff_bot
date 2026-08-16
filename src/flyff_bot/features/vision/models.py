"""Typed contracts for image frames captured from a client area."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt


class PixelFormat(StrEnum):
    """Colour order of a captured frame."""

    BGR = "bgr"
    RGB = "rgb"


@dataclass(frozen=True, slots=True)
class ClientSize:
    """Dimensions of a window client area in pixels."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Client dimensions must be positive.")


@dataclass(frozen=True, slots=True)
class ClientPoint:
    """A pixel coordinate relative to the top-left client-area pixel."""

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """An OpenCV-compatible client-area frame with its exact coordinate system."""

    pixels: npt.NDArray[np.uint8]
    client_size: ClientSize
    pixel_format: PixelFormat = PixelFormat.BGR

    def __post_init__(self) -> None:
        expected_shape = (self.client_size.height, self.client_size.width, 3)
        if self.pixels.dtype != np.uint8 or self.pixels.shape != expected_shape:
            msg = f"Expected uint8 frame shape {expected_shape}, got {self.pixels.shape}."
            raise ValueError(msg)
        if not self.pixels.flags.c_contiguous:
            raise ValueError("Frame pixels must be C-contiguous.")

    def client_point_at(self, x: int, y: int) -> ClientPoint:
        """Map a frame pixel to the identical client-space coordinate."""

        if not (0 <= x < self.client_size.width and 0 <= y < self.client_size.height):
            raise ValueError("Frame pixel is outside the client area.")
        return ClientPoint(x=x, y=y)


class FrameCaptureErrorCode(StrEnum):
    """Known capture failures mapped to localized presentation text."""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    INVALID_WINDOW = "invalid_window"
    MINIMIZED = "minimized"
    OCCLUDED = "occluded"
    CAPTURE_FAILED = "capture_failed"


class FrameCaptureError(RuntimeError):
    """A known client-frame capture failure."""

    def __init__(self, code: FrameCaptureErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class TargetVerificationMetrics:
    """Per-criterion thresholds and pass/fail outcomes for one target verification.

    Every field is a raw measurement taken on the current frame, independent of whether
    an earlier criterion passed. `hp_pixel_count` and `hp_percentage` are therefore the
    diagnostic readings sampled at the best anchor match, while the same fields on
    `TargetVerificationResult` stay zero unless the header anchor itself was accepted.
    """

    anchor_score: float = 0.0
    anchor_threshold: float = 0.0
    anchor_passed: bool = False
    minimum_hp_pixel_count: int = 0
    hp_pixel_count: int = 0
    hp_percentage: float = 0.0
    hp_passed: bool = False
    name_candidate: str | None = None
    name_score: float = 0.0
    name_threshold: float = 0.0
    name_passed: bool = False


@dataclass(frozen=True, slots=True)
class PlayerVitals:
    """An observed snapshot of player vital percentages."""

    hp_percentage: float = 100.0
    mp_percentage: float = 100.0
    fp_percentage: float = 100.0

    def __post_init__(self) -> None:
        for name, value in (
            ("HP", self.hp_percentage),
            ("MP", self.mp_percentage),
            ("FP", self.fp_percentage),
        ):
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} percentage must be between 0.0 and 100.0, got {value}.")
