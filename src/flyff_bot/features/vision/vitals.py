"""Pure pixel-color perception of player vital gauges from top-left HUD."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.models import CapturedFrame, PixelFormat, PlayerVitals

# The Flyff HUD vitals orb is anchored at the client's fixed top-left pixel origin and does not
# scale with window resolution (BUG-006): a normalized fraction of window size samples 3D game
# scenery on any resolution above the reference size, causing false 0% gauge drops.
DEFAULT_HUD_WIDTH_PX = 260
DEFAULT_HUD_HEIGHT_PX = 113

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

    hud_width_px: int = DEFAULT_HUD_WIDTH_PX
    hud_height_px: int = DEFAULT_HUD_HEIGHT_PX
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
        if self.hud_width_px <= 0 or self.hud_height_px <= 0:
            raise ValueError("HUD pixel dimensions must be positive.")
        if not 0 <= self.min_channel_value <= 255:
            raise ValueError("Minimum channel value must be between 0 and 255.")
        if not 0 <= self.min_channel_diff <= 255:
            raise ValueError("Minimum channel difference must be between 0 and 255.")


class PlayerVitalsFeed(Protocol):
    """Protocol for components reading player vitals from captured frames."""

    def read(self, frame: CapturedFrame) -> PlayerVitals:
        """Extract HP, MP, and FP percentages from the frame."""


@dataclass(frozen=True, slots=True)
class VitalsLayout:
    """Client-pixel rectangles for the HUD box and each gauge, as (left, top, right, bottom)."""

    hud: tuple[int, int, int, int]
    hp: tuple[int, int, int, int]
    mp: tuple[int, int, int, int]
    fp: tuple[int, int, int, int]


def compute_vitals_layout(config: PlayerVitalsConfig | None = None) -> VitalsLayout:
    """Return the fixed top-left HUD box and gauge rects in client pixel coordinates."""

    cfg = config or PlayerVitalsConfig()
    hud_width, hud_height = cfg.hud_width_px, cfg.hud_height_px

    def _rect(region: GaugeRegion) -> tuple[int, int, int, int]:
        left = int(hud_width * region.left)
        right = int(hud_width * region.right)
        top = int(hud_height * region.top)
        bottom = int(hud_height * region.bottom)
        return left, top, right, bottom

    return VitalsLayout(
        hud=(0, 0, hud_width, hud_height),
        hp=_rect(cfg.hp_region),
        mp=_rect(cfg.mp_region),
        fp=_rect(cfg.fp_region),
    )


class PlayerVitalsReader:
    """Pure pixel-color extractor for player HP, MP, and FP gauges."""

    def __init__(self, config: PlayerVitalsConfig | None = None) -> None:
        self._config = config or PlayerVitalsConfig()
        self._layout = compute_vitals_layout(self._config)

    def read(self, frame: CapturedFrame) -> PlayerVitals:
        """Extract HP, MP, and FP fill percentages from client-space frame."""

        pixels = frame.pixels
        if frame.pixel_format is PixelFormat.RGB:
            pixels = cast("npt.NDArray[np.uint8]", cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR))

        hud_crop = self._clip(pixels, self._layout.hud)
        hp_crop = self._clip(hud_crop, self._layout.hp)
        mp_crop = self._clip(hud_crop, self._layout.mp)
        fp_crop = self._clip(hud_crop, self._layout.fp)

        # In BGR: Red channel is index 2, Blue is index 0, Green is index 1
        hp_pct = self._measure_gauge(hp_crop, channel_index=2)
        mp_pct = self._measure_gauge(mp_crop, channel_index=0)
        fp_pct = self._measure_gauge(fp_crop, channel_index=1)

        return PlayerVitals(
            hp_percentage=hp_pct,
            mp_percentage=mp_pct,
            fp_percentage=fp_pct,
        )

    def _clip(
        self, source: npt.NDArray[np.uint8], rect: tuple[int, int, int, int]
    ) -> npt.NDArray[np.uint8]:
        source_height, source_width = source.shape[:2]
        left, top, right, bottom = rect
        right = min(right, source_width)
        bottom = min(bottom, source_height)
        if right <= left or bottom <= top:
            return np.empty((0, 0, 3), dtype=np.uint8)
        return source[top:bottom, left:right]

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
