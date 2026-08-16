"""OCR-based extraction of monster kill count from the Flyff session stats HUD."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.loot_ocr import TextRecognizer
from flyff_bot.features.vision.models import CapturedFrame, PixelFormat

# Normalized ROI bounds for the monster stats HUD window.
# Calibrated against 1600×900 reference: stats at approx x=235..410, y=30..120.
DEFAULT_MONSTER_STATS_ROI_LEFT = 0.147
DEFAULT_MONSTER_STATS_ROI_TOP = 0.033
DEFAULT_MONSTER_STATS_ROI_RIGHT = 0.256
DEFAULT_MONSTER_STATS_ROI_BOTTOM = 0.133

# Preprocessing constants for adaptive thresholding.
DEFAULT_MONSTER_STATS_THRESHOLD_BLOCK_SIZE = 21
DEFAULT_MONSTER_STATS_THRESHOLD_OFFSET = 5
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID_SIZE = (4, 4)

# Pattern to match "Monster Kills: <int>" in OCR output.
_KILL_COUNT_PATTERN = re.compile(r"Monster\s*Kills?\s*[:;]\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MonsterStatsConfig:
    """Configurable ROI and preprocessing for the monster stats HUD region."""

    roi_left: float = DEFAULT_MONSTER_STATS_ROI_LEFT
    roi_top: float = DEFAULT_MONSTER_STATS_ROI_TOP
    roi_right: float = DEFAULT_MONSTER_STATS_ROI_RIGHT
    roi_bottom: float = DEFAULT_MONSTER_STATS_ROI_BOTTOM
    threshold_block_size: int = DEFAULT_MONSTER_STATS_THRESHOLD_BLOCK_SIZE
    threshold_offset: int = DEFAULT_MONSTER_STATS_THRESHOLD_OFFSET

    def __post_init__(self) -> None:
        if not 0.0 <= self.roi_left < self.roi_right <= 1.0:
            raise ValueError("Monster stats ROI left/right must be ordered within [0.0, 1.0].")
        if not 0.0 <= self.roi_top < self.roi_bottom <= 1.0:
            raise ValueError("Monster stats ROI top/bottom must be ordered within [0.0, 1.0].")
        if self.threshold_block_size < 3 or not self.threshold_block_size % 2:
            raise ValueError(
                "Threshold block size must be an odd integer of at least three."
            )


class MonsterStatsFeed(Protocol):
    """A component that reads the monster kill count from a captured frame."""

    def read(self, frame: CapturedFrame) -> int | None:
        """Return the Monster Kills count, or None if unreadable."""


class MonsterStatsReader:
    """OCR-based extractor for the Monster Kills counter in the HUD stats window."""

    def __init__(
        self,
        recognizer: TextRecognizer,
        config: MonsterStatsConfig | None = None,
    ) -> None:
        self._recognizer = recognizer
        self._config = config or MonsterStatsConfig()

    def read(self, frame: CapturedFrame) -> int | None:
        """Extract the Monster Kills integer from the stats HUD ROI."""

        pixels = frame.pixels
        if frame.pixel_format is PixelFormat.RGB:
            pixels = cast("npt.NDArray[np.uint8]", cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR))

        roi = self._extract_roi(pixels)
        if roi.size == 0 or roi.shape[0] == 0 or roi.shape[1] == 0:
            return None

        preprocessed = self._preprocess(roi)
        try:
            lines = self._recognizer.recognize(preprocessed)
        except Exception:  # noqa: BLE001 — OCR failures are non-fatal
            return None

        for line in lines:
            match = _KILL_COUNT_PATTERN.search(line)
            if match:
                return int(match.group(1))
        return None

    def _extract_roi(self, pixels: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Crop the monster stats region using normalized bounds."""

        height, width = pixels.shape[:2]
        left, top, right, bottom = compute_monster_stats_roi(
            width, height, self._config
        )
        if right <= left or bottom <= top:
            return np.empty((0, 0, 3), dtype=np.uint8)
        return pixels[top:bottom, left:right]

    def _preprocess(self, roi: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Convert to grayscale, enhance contrast, and threshold for OCR."""

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(
            clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID_SIZE
        )
        enhanced = clahe.apply(gray)
        return cast(
            "npt.NDArray[np.uint8]",
            cv2.adaptiveThreshold(
                enhanced,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                self._config.threshold_block_size,
                self._config.threshold_offset,
            ),
        )


def compute_monster_stats_roi(
    client_width: int,
    client_height: int,
    config: MonsterStatsConfig | None = None,
) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) pixel coordinates for the stats ROI."""

    cfg = config or MonsterStatsConfig()
    left = int(client_width * cfg.roi_left)
    top = int(client_height * cfg.roi_top)
    right = int(client_width * cfg.roi_right)
    bottom = int(client_height * cfg.roi_bottom)
    return left, top, right, bottom
