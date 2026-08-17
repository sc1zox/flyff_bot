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


class TargetNameStatus(StrEnum):
    """Outcome of reading and whitelisting the target header's monster name."""

    NOT_EVALUATED = "not_evaluated"
    MATCHED = "matched"
    NO_MATCH = "no_match"
    UNREADABLE = "unreadable"
    OCR_FAILED = "ocr_failed"
    ENGINE_UNAVAILABLE = "engine_unavailable"


@dataclass(frozen=True, slots=True)
class TargetVerificationMetrics:
    """Per-criterion thresholds and pass/fail outcomes for one target verification.

    The anchor and HP fields are raw measurements taken on the current frame,
    independent of whether an earlier criterion passed: `hp_pixel_count` and
    `hp_percentage` are the diagnostic readings sampled at the best anchor match, while
    the same fields on `TargetVerificationResult` stay zero unless the header anchor
    itself was accepted. Name recognition is the one criterion that is skipped when the
    anchor fails, because it runs an OCR subprocess; it then reports `NOT_EVALUATED`
    rather than a fabricated negative result. `name_text` is the raw OCR output and
    `name_candidate` is the canonical whitelist entry it matched.
    """

    anchor_score: float = 0.0
    anchor_threshold: float = 0.0
    anchor_passed: bool = False
    minimum_hp_pixel_count: int = 0
    hp_pixel_count: int = 0
    hp_percentage: float = 0.0
    hp_passed: bool = False
    name_candidate: str | None = None
    name_text: str = ""
    name_status: TargetNameStatus = TargetNameStatus.NOT_EVALUATED
    name_passed: bool = False


class MonsterStatsStatus(StrEnum):
    """Health of one monster-kills HUD reading, as shown by the diagnostics panel."""

    IDLE = "idle"
    OK = "ok"
    ANCHOR_NOT_FOUND = "anchor_not_found"
    ROI_UNAVAILABLE = "roi_unavailable"
    OCR_FAILED = "ocr_failed"
    NO_MATCH = "no_match"


@dataclass(frozen=True, slots=True)
class MonsterStatsMetrics:
    """Raw diagnostic evidence behind one monster-kills HUD OCR attempt.

    Every field is measured on the current frame regardless of whether the reading
    succeeded, so the debug panel can show why a failing read failed. `parsed_count`
    is `None` for every status other than `OK`; callers must keep their previous kill
    count in that case rather than treating it as zero.
    """

    anchor_configured: bool = False
    anchor_score: float = 0.0
    anchor_threshold: float = 0.0
    anchor_passed: bool = False
    roi_width: int = 0
    roi_height: int = 0
    raw_text: str = ""
    parsed_count: int | None = None
    status: MonsterStatsStatus = MonsterStatsStatus.IDLE


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
