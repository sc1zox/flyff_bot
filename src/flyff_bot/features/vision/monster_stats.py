"""OCR-based extraction of monster kill count from the Flyff session stats HUD."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.loot_ocr import LootOcrError, LootOcrErrorCode, TextRecognizer
from flyff_bot.features.vision.models import (
    CapturedFrame,
    MonsterStatsMetrics,
    MonsterStatsStatus,
    PixelFormat,
)

# Fixed top-left client-pixel bounds for the monster stats HUD window docked to Player Vitals.
# The player vitals orb occupies (0, 0, 260, 113) px; stats HUD attaches directly at
# x=260..410, y=0..120.
DEFAULT_MONSTER_STATS_ROI_LEFT_PX = 260
DEFAULT_MONSTER_STATS_ROI_TOP_PX = 0
DEFAULT_MONSTER_STATS_ROI_RIGHT_PX = 410
DEFAULT_MONSTER_STATS_ROI_BOTTOM_PX = 120

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

    roi_left: int = DEFAULT_MONSTER_STATS_ROI_LEFT_PX
    roi_top: int = DEFAULT_MONSTER_STATS_ROI_TOP_PX
    roi_right: int = DEFAULT_MONSTER_STATS_ROI_RIGHT_PX
    roi_bottom: int = DEFAULT_MONSTER_STATS_ROI_BOTTOM_PX
    threshold_block_size: int = DEFAULT_MONSTER_STATS_THRESHOLD_BLOCK_SIZE
    threshold_offset: int = DEFAULT_MONSTER_STATS_THRESHOLD_OFFSET
    anchor_match_threshold: float = DEFAULT_ANCHOR_MATCH_THRESHOLD
    kills_text_offset_x: int = DEFAULT_KILLS_TEXT_OFFSET_X
    kills_text_offset_y: int = DEFAULT_KILLS_TEXT_OFFSET_Y
    kills_text_width: int = DEFAULT_KILLS_TEXT_WIDTH
    kills_text_height: int = DEFAULT_KILLS_TEXT_HEIGHT

    def __post_init__(self) -> None:
        if not 0 <= self.roi_left < self.roi_right:
            raise ValueError("Monster stats ROI left/right must be positive and ordered.")
        if not 0 <= self.roi_top < self.roi_bottom:
            raise ValueError("Monster stats ROI top/bottom must be positive and ordered.")
        if self.threshold_block_size < 3 or not self.threshold_block_size % 2:
            raise ValueError("Threshold block size must be an odd integer of at least three.")
        if not 0.0 <= self.anchor_match_threshold <= 1.0:
            raise ValueError("Anchor match threshold must be between zero and one.")
        if self.kills_text_width <= 0 or self.kills_text_height <= 0:
            raise ValueError("Kills text region dimensions must be positive.")


class MonsterStatsFeed(Protocol):
    """A component that reads the monster kill count from a captured frame."""

    def read(self, frame: CapturedFrame) -> MonsterStatsMetrics:
        """Return the reading and the diagnostic evidence measured for it."""


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

    def read(self, frame: CapturedFrame) -> MonsterStatsMetrics:
        """Measure the stats HUD ROI and report the reading with its diagnostic evidence."""

        pixels = frame.pixels
        if frame.pixel_format is PixelFormat.RGB:
            pixels = cast("npt.NDArray[np.uint8]", cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR))

        threshold = self._config.anchor_match_threshold
        anchor_configured = self._header_anchor_template is not None
        if self._header_anchor_template is None:
            roi, anchor_score = self._extract_roi(pixels), 0.0
        else:
            roi, anchor_score = self._extract_anchored_roi(pixels, self._header_anchor_template)
        anchor_passed = anchor_configured and anchor_score >= threshold

        def measured(
            status: MonsterStatsStatus, raw_text: str = "", parsed_count: int | None = None
        ) -> MonsterStatsMetrics:
            return MonsterStatsMetrics(
                anchor_configured=anchor_configured,
                anchor_score=anchor_score,
                anchor_threshold=threshold,
                anchor_passed=anchor_passed,
                roi_width=roi.shape[1],
                roi_height=roi.shape[0],
                raw_text=raw_text,
                parsed_count=parsed_count,
                status=status,
            )

        if roi.size == 0 or roi.shape[0] == 0 or roi.shape[1] == 0:
            return measured(
                MonsterStatsStatus.ANCHOR_NOT_FOUND
                if anchor_configured and not anchor_passed
                else MonsterStatsStatus.ROI_UNAVAILABLE
            )

        preprocessed = self._preprocess(roi)
        try:
            lines = self._recognizer.recognize(preprocessed)
        except LootOcrError as error:
            # A missing engine install is the operator's to fix and is named separately from a
            # recognition that ran and failed, which is not actionable.
            return measured(
                MonsterStatsStatus.ENGINE_UNAVAILABLE
                if error.code is LootOcrErrorCode.ENGINE_UNAVAILABLE
                else MonsterStatsStatus.OCR_FAILED
            )
        except Exception:  # any other injected recognizer failure is non-fatal
            return measured(MonsterStatsStatus.OCR_FAILED)

        raw_text = " ".join(line.strip() for line in lines if line.strip())
        for line in lines:
            match = _KILL_COUNT_PATTERN.search(line)
            if match:
                return measured(MonsterStatsStatus.OK, raw_text, int(match.group(1)))
        return measured(MonsterStatsStatus.NO_MATCH, raw_text)

    def _extract_roi(self, pixels: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Crop the monster stats region using normalized bounds."""

        height, width = pixels.shape[:2]
        left, top, right, bottom = compute_monster_stats_roi(width, height, self._config)
        if right <= left or bottom <= top:
            return np.empty((0, 0, 3), dtype=np.uint8)
        return pixels[top:bottom, left:right]

    def _extract_anchored_roi(
        self, pixels: npt.NDArray[np.uint8], template: npt.NDArray[np.uint8]
    ) -> tuple[npt.NDArray[np.uint8], float]:
        """Locate the stats window via template match, wherever it is placed on screen.

        The best match score is always reported, including when it stays below the
        configured threshold, so diagnostics can show how close the match came.
        """

        empty: npt.NDArray[np.uint8] = np.empty((0, 0, 3), dtype=np.uint8)
        height, width = pixels.shape[:2]
        template_height, template_width = template.shape[:2]
        if template_height > height or template_width > width:
            return empty, 0.0

        result = cv2.matchTemplate(pixels, template, cv2.TM_CCOEFF_NORMED)
        _min_val, score, _min_loc, max_loc = cv2.minMaxLoc(result)
        if score < self._config.anchor_match_threshold:
            return empty, float(score)

        anchor_x, anchor_y = max_loc
        left = max(0, anchor_x + self._config.kills_text_offset_x)
        top = max(0, anchor_y + self._config.kills_text_offset_y)
        right = min(width, left + self._config.kills_text_width)
        bottom = min(height, top + self._config.kills_text_height)
        if right <= left or bottom <= top:
            return empty, float(score)
        return pixels[top:bottom, left:right], float(score)

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
    left = cfg.roi_left
    top = cfg.roi_top
    right = min(client_width, cfg.roi_right)
    bottom = min(client_height, cfg.roi_bottom)
    if right <= left or bottom <= top:
        return 0, 0, 0, 0
    return left, top, right, bottom
