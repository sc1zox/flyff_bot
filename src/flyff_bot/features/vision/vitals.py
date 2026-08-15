"""Pure pixel-color perception of player vital gauges from top-left HUD."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.automation.models import PlayerVitals
from flyff_bot.features.vision.models import CapturedFrame, PixelFormat

# Default HUD box in client frame (normalized: top-left corner)
DEFAULT_HUD_LEFT = 0.0
DEFAULT_HUD_TOP = 0.0
DEFAULT_HUD_RIGHT = 0.25
DEFAULT_HUD_BOTTOM = 0.20

# Standard normalized bounds within the HUD box for HP, MP, FP bars
# Calibrated against Flyff HUD reference dimensions (260x113)
DEFAULT_HP_BAR_LEFT = 0.415
DEFAULT_HP_BAR_RIGHT = 0.946
DEFAULT_HP_BAR_TOP = 0.265
DEFAULT_HP_BAR_BOTTOM = 0.327

DEFAULT_MP_BAR_LEFT = 0.415
DEFAULT_MP_BAR_RIGHT = 0.946
DEFAULT_MP_BAR_TOP = 0.416
DEFAULT_MP_BAR_BOTTOM = 0.478

DEFAULT_FP_BAR_LEFT = 0.415
DEFAULT_FP_BAR_RIGHT = 0.946
DEFAULT_FP_BAR_TOP = 0.566
DEFAULT_FP_BAR_BOTTOM = 0.628

DEFAULT_MIN_VITAL_CHANNEL_VALUE = 130
DEFAULT_MIN_VITAL_CHANNEL_DIFF = 25


class VitalGaugeType(StrEnum):
    """The supported player vital gauges."""

    HP = "hp"
    MP = "mp"
    FP = "fp"


@dataclass(frozen=True, slots=True)
class GaugeRegion:
    """Normalized relative bounding box for one gauge bar within the HUD region."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.left < self.right <= 1.0 or not 0.0 <= self.top < self.bottom <= 1.0:
            raise ValueError("GaugeRegion coordinates must be ordered within [0.0, 1.0].")


@dataclass(frozen=True, slots=True)
class PlayerVitalsConfig:
    """Configurable visual boundaries and color thresholds for player vitals."""

    hud_left: float = DEFAULT_HUD_LEFT
    hud_top: float = DEFAULT_HUD_TOP
    hud_right: float = DEFAULT_HUD_RIGHT
    hud_bottom: float = DEFAULT_HUD_BOTTOM
    hp_region: GaugeRegion = field(
        default_factory=lambda: GaugeRegion(
            DEFAULT_HP_BAR_LEFT, DEFAULT_HP_BAR_TOP, DEFAULT_HP_BAR_RIGHT, DEFAULT_HP_BAR_BOTTOM
        )
    )
    mp_region: GaugeRegion = field(
        default_factory=lambda: GaugeRegion(
            DEFAULT_MP_BAR_LEFT, DEFAULT_MP_BAR_TOP, DEFAULT_MP_BAR_RIGHT, DEFAULT_MP_BAR_BOTTOM
        )
    )
    fp_region: GaugeRegion = field(
        default_factory=lambda: GaugeRegion(
            DEFAULT_FP_BAR_LEFT, DEFAULT_FP_BAR_TOP, DEFAULT_FP_BAR_RIGHT, DEFAULT_FP_BAR_BOTTOM
        )
    )
    min_channel_value: int = DEFAULT_MIN_VITAL_CHANNEL_VALUE
    min_channel_diff: int = DEFAULT_MIN_VITAL_CHANNEL_DIFF

    def __post_init__(self) -> None:
        if (
            not 0.0 <= self.hud_left < self.hud_right <= 1.0
            or not 0.0 <= self.hud_top < self.hud_bottom <= 1.0
        ):
            raise ValueError("HUD bounds must be ordered normalized coordinates.")
        if not 0 <= self.min_channel_value <= 255:
            raise ValueError("Minimum channel value must be between 0 and 255.")
        if not 0 <= self.min_channel_diff <= 255:
            raise ValueError("Minimum channel difference must be between 0 and 255.")


class PlayerVitalsFeed(Protocol):
    """Protocol for components reading player vitals from captured frames."""

    def read(self, frame: CapturedFrame) -> PlayerVitals:
        """Extract HP, MP, and FP percentages from the frame."""


class PlayerVitalsReader:
    """Pure pixel-color extractor for player HP, MP, and FP gauges."""

    def __init__(self, config: PlayerVitalsConfig | None = None) -> None:
        self._config = config or PlayerVitalsConfig()

    def read(self, frame: CapturedFrame) -> PlayerVitals:
        """Extract HP, MP, and FP fill percentages from client-space frame."""

        pixels = frame.pixels
        if frame.pixel_format is PixelFormat.RGB:
            pixels = cast("npt.NDArray[np.uint8]", cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR))

        hud_crop = self._extract_hud_region(pixels)
        hp_crop = self._extract_gauge_crop(hud_crop, self._config.hp_region)
        mp_crop = self._extract_gauge_crop(hud_crop, self._config.mp_region)
        fp_crop = self._extract_gauge_crop(hud_crop, self._config.fp_region)

        # In BGR: Red channel is index 2, Blue is index 0, Green is index 1
        hp_pct = self._measure_gauge(hp_crop, channel_index=2)
        mp_pct = self._measure_gauge(mp_crop, channel_index=0)
        fp_pct = self._measure_gauge(fp_crop, channel_index=1)

        return PlayerVitals(
            hp_percentage=hp_pct,
            mp_percentage=mp_pct,
            fp_percentage=fp_pct,
        )

    def _extract_hud_region(self, pixels: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        height, width = pixels.shape[:2]
        # If the frame is already a small cropped HUD region (e.g. <=300x150),
        # use the full crop directly.
        if width <= 300 and height <= 150:
            return pixels

        left = int(width * self._config.hud_left)
        right = int(width * self._config.hud_right)
        top = int(height * self._config.hud_top)
        bottom = int(height * self._config.hud_bottom)
        if right <= left or bottom <= top:
            return pixels
        return pixels[top:bottom, left:right]

    def _extract_gauge_crop(
        self, hud: npt.NDArray[np.uint8], region: GaugeRegion
    ) -> npt.NDArray[np.uint8]:
        hud_height, hud_width = hud.shape[:2]
        left = int(hud_width * region.left)
        right = int(hud_width * region.right)
        top = int(hud_height * region.top)
        bottom = int(hud_height * region.bottom)
        if right <= left or bottom <= top:
            return np.empty((0, 0, 3), dtype=np.uint8)
        return hud[top:bottom, left:right]

    def _measure_gauge(self, crop: npt.NDArray[np.uint8], channel_index: int) -> float:
        if crop.size == 0 or crop.shape[1] == 0:
            return 0.0

        other_channels = [c for c in (0, 1, 2) if c != channel_index]
        target_ch = crop[:, :, channel_index]
        other_max = np.maximum(crop[:, :, other_channels[0]], crop[:, :, other_channels[1]])

        is_colored = (target_ch >= self._config.min_channel_value) & (
            target_ch.astype(int) - other_max.astype(int) >= self._config.min_channel_diff
        )

        col_has_color = np.any(is_colored, axis=0)
        colored_indices = np.where(col_has_color)[0]
        total_cols = crop.shape[1]

        if len(colored_indices) == 0:
            return 0.0

        last_colored_index = int(colored_indices[-1])
        percentage = (last_colored_index + 1) / total_cols * 100.0
        return float(min(100.0, max(0.0, round(percentage, 1))))
