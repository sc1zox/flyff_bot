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
# Calibrated against 1600x900 reference: stats at approx x=235..410, y=30..120.
DEFAULT_MONSTER_STATS_ROI_LEFT = 0.147
DEFAULT_MONSTER_STATS_ROI_TOP = 0.033
DEFAULT_MONSTER_STATS_ROI_RIGHT = 0.256
DEFAULT_MONSTER_STATS_ROI_BOTTOM = 0.133

# Preprocessing constants for adaptive thresholding.
DEFAULT_MONSTER_STATS_THRESHOLD_BLOCK_SIZE = 21
DEFAULT_MONSTER_STATS_THRESHOLD_OFFSET = 5
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID_SIZE = (4, 4)

# When a header-anchor template is configured, the "Monster Kills:" text line is cropped at this
# fixed pixel offset from the anchor's matched top-left corner, following the stats window's own
# static layout (the anchor covers the "Time:" label directly above it).
DEFAULT_ANCHOR_MATCH_THRESHOLD = 0.85
DEFAULT_KILLS_TEXT_OFFSET_X = 0
DEFAULT_KILLS_TEXT_OFFSET_Y = 16
DEFAULT_KILLS_TEXT_WIDTH = 145
DEFAULT_KILLS_TEXT_HEIGHT = 20

# Pattern to match "Monster Kills: <int>" in OCR output.
_KILL_COUNT_PATTERN = re.compile(r"Monster\s*Kills?\s*[:;]\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MonsterStatsConfig:
    """Configurable ROI, anchor matching, and preprocessing for the monster stats HUD region."""

    roi_left: float = DEFAULT_MONSTER_STATS_ROI_LEFT
    roi_top: float = DEFAULT_MONSTER_STATS_ROI_TOP
    roi_right: float = DEFAULT_MONSTER_STATS_ROI_RIGHT
    roi_bottom: float = DEFAULT_MONSTER_STATS_ROI_BOTTOM
    threshold_block_size: int = DEFAULT_MONSTER_STATS_THRESHOLD_BLOCK_SIZE
    threshold_offset: int = DEFAULT_MONSTER_STATS_THRESHOLD_OFFSET
    anchor_match_threshold: float = DEFAULT_ANCHOR_MATCH_THRESHOLD
    kills_text_offset_x: int = DEFAULT_KILLS_TEXT_OFFSET_X
    kills_text_offset_y: int = DEFAULT_KILLS_TEXT_OFFSET_Y
    kills_text_width: int = DEFAULT_KILLS_TEXT_WIDTH
    kills_text_height: int = DEFAULT_KILLS_TEXT_HEIGHT

    def __post_init__(self) -> None:
        if not 0.0 <= self.roi_left < self.roi_right <= 1.0:
            raise ValueError("Monster stats ROI left/right must be ordered within [0.0, 1.0].")
        if not 0.0 <= self.roi_top < self.roi_bottom <= 1.0:
            raise ValueError("Monster stats ROI top/bottom must be ordered within [0.0, 1.0].")
        if self.threshold_block_size < 3 or not self.threshold_block_size % 2:
            raise ValueError("Threshold block size must be an odd integer of at least three.")
        if not 0.0 <= self.anchor_match_threshold <= 1.0:
            raise ValueError("Anchor match threshold must be between zero and one.")
        if self.kills_text_width <= 0 or self.kills_text_height <= 0:
            raise ValueError("Kills text region dimensions must be positive.")


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
        header_anchor_template: npt.NDArray[np.uint8] | None = None,
    ) -> None:
        self._recognizer = recognizer
        self._config = config or MonsterStatsConfig()
        if header_anchor_template is not None and (
            header_anchor_template.dtype != np.uint8 or header_anchor_template.ndim != 3
        ):
            raise ValueError("Monster stats header anchor template must be a uint8 colour image.")
        self._header_anchor_template = header_anchor_template

    def read(self, frame: CapturedFrame) -> int | None:
        """Extract the Monster Kills integer from the stats HUD ROI."""

        pixels = frame.pixels
        if frame.pixel_format is PixelFormat.RGB:
            pixels = cast("npt.NDArray[np.uint8]", cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR))

        roi = (
            self._extract_anchored_roi(pixels, self._header_anchor_template)
            if self._header_anchor_template is not None
            else self._extract_roi(pixels)
        )
        if roi.size == 0 or roi.shape[0] == 0 or roi.shape[1] == 0:
            return None

        preprocessed = self._preprocess(roi)
        try:
            lines = self._recognizer.recognize(preprocessed)
        except Exception:  # OCR failures are non-fatal
            return None

        for line in lines:
            match = _KILL_COUNT_PATTERN.search(line)
            if match:
                return int(match.group(1))
        return None

    def _extract_roi(self, pixels: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Crop the monster stats region using normalized bounds."""

        height, width = pixels.shape[:2]
        left, top, right, bottom = compute_monster_stats_roi(width, height, self._config)
        if right <= left or bottom <= top:
            return np.empty((0, 0, 3), dtype=np.uint8)
        return pixels[top:bottom, left:right]

    def _extract_anchored_roi(
        self, pixels: npt.NDArray[np.uint8], template: npt.NDArray[np.uint8]
    ) -> npt.NDArray[np.uint8]:
        """Locate the stats window via template match, wherever it is placed on screen."""

        height, width = pixels.shape[:2]
        template_height, template_width = template.shape[:2]
        if template_height > height or template_width > width:
            return np.empty((0, 0, 3), dtype=np.uint8)

        result = cv2.matchTemplate(pixels, template, cv2.TM_CCOEFF_NORMED)
        _min_val, score, _min_loc, max_loc = cv2.minMaxLoc(result)
        if score < self._config.anchor_match_threshold:
            return np.empty((0, 0, 3), dtype=np.uint8)

        anchor_x, anchor_y = max_loc
        left = max(0, anchor_x + self._config.kills_text_offset_x)
        top = max(0, anchor_y + self._config.kills_text_offset_y)
        right = min(width, left + self._config.kills_text_width)
        bottom = min(height, top + self._config.kills_text_height)
        if right <= left or bottom <= top:
            return np.empty((0, 0, 3), dtype=np.uint8)
        return pixels[top:bottom, left:right]

    def _preprocess(self, roi: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Convert to grayscale, enhance contrast, and threshold for OCR."""

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID_SIZE)
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
