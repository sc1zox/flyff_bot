"""OCR-based extraction of monster kill count from the Flyff session stats HUD."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.models import (
    CapturedFrame,
    MonsterStatsMetrics,
    MonsterStatsSource,
    MonsterStatsStatus,
    PixelFormat,
)
from flyff_bot.features.vision.ocr import OcrError, OcrErrorCode, TextRecognizer

# Fixed top-left client-pixel bounds for the monster stats HUD window docked to Player Vitals.
# The player vitals orb occupies (0, 0, 260, 113) px; stats HUD attaches directly at
# x=260..410, y=0..120.
DEFAULT_MONSTER_STATS_ROI_LEFT_PX = 260
DEFAULT_MONSTER_STATS_ROI_TOP_PX = 0
DEFAULT_MONSTER_STATS_ROI_RIGHT_PX = 410
DEFAULT_MONSTER_STATS_ROI_BOTTOM_PX = 120

# The stats HUD has no opaque backing, so its text is drawn straight over the moving game
# world. Contrast-based binarization therefore keeps whatever happens to be behind the panel.
# The client renders every stats glyph in one constant colour instead, BGR (255, 209, 249),
# which is HSV (146, 46, 255); keying that colour isolates the text from any background.
# The bounds below span the antialiasing spread measured around that centre.
HUD_TEXT_HUE_MINIMUM = 130
HUD_TEXT_HUE_MAXIMUM = 165
HUD_TEXT_SATURATION_MINIMUM = 15
HUD_TEXT_SATURATION_MAXIMUM = 95
HUD_TEXT_VALUE_MINIMUM = 215
HUD_TEXT_VALUE_MAXIMUM = 255

# Where the shipped header anchor template sits inside the stats window it was cropped from.
# Subtracting this inset from a match turns the anchor position back into the panel origin.
DEFAULT_ANCHOR_MATCH_THRESHOLD = 0.85
DEFAULT_ANCHOR_INSET_X = 3
DEFAULT_ANCHOR_INSET_Y = 4

# Bounds of the "Time:" header line inside `data/assets/stats/monster_stats.png`,
# used as the anchor template.
HEADER_ANCHOR_TEMPLATE_LEFT = 3
HEADER_ANCHOR_TEMPLATE_TOP = 4
HEADER_ANCHOR_TEMPLATE_RIGHT = 50
HEADER_ANCHOR_TEMPLATE_BOTTOM = 19

# Pattern to match "Monster Kills: <int>" in OCR output.
_KILL_COUNT_PATTERN = re.compile(r"Monster\s*Kills?\s*[:;]\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MonsterStatsConfig:
    """Configurable ROI and anchor matching for the monster stats HUD region."""

    roi_left: int = DEFAULT_MONSTER_STATS_ROI_LEFT_PX
    roi_top: int = DEFAULT_MONSTER_STATS_ROI_TOP_PX
    roi_right: int = DEFAULT_MONSTER_STATS_ROI_RIGHT_PX
    roi_bottom: int = DEFAULT_MONSTER_STATS_ROI_BOTTOM_PX
    anchor_match_threshold: float = DEFAULT_ANCHOR_MATCH_THRESHOLD
    anchor_inset_x: int = DEFAULT_ANCHOR_INSET_X
    anchor_inset_y: int = DEFAULT_ANCHOR_INSET_Y

    def __post_init__(self) -> None:
        if not 0 <= self.roi_left < self.roi_right:
            raise ValueError("Monster stats ROI left/right must be positive and ordered.")
        if not 0 <= self.roi_top < self.roi_bottom:
            raise ValueError("Monster stats ROI top/bottom must be positive and ordered.")
        if not 0.0 <= self.anchor_match_threshold <= 1.0:
            raise ValueError("Anchor match threshold must be between zero and one.")
        if self.anchor_inset_x < 0 or self.anchor_inset_y < 0:
            raise ValueError("Anchor inset must not be negative.")

    @property
    def panel_width(self) -> int:
        """Width of the stats window, applied to both the fixed and the anchored crop."""

        return self.roi_right - self.roi_left

    @property
    def panel_height(self) -> int:
        """Height of the stats window, applied to both the fixed and the anchored crop."""

        return self.roi_bottom - self.roi_top


class MonsterStatsFeed(Protocol):
    """A component that reads the monster kill count from a captured frame."""

    def read(self, frame: CapturedFrame) -> MonsterStatsMetrics:
        """Return the reading and the diagnostic evidence measured for it."""


def extract_hud_text_mask(pixels: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """Return a mask that is 255 on stats-HUD glyph pixels and 0 on everything else.

    Keying the client's constant glyph colour rather than thresholding contrast is what
    makes the reading independent of the game world drawn behind the transparent panel.
    """

    hsv = cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV)
    return cast(
        "npt.NDArray[np.uint8]",
        cv2.inRange(
            hsv,
            (HUD_TEXT_HUE_MINIMUM, HUD_TEXT_SATURATION_MINIMUM, HUD_TEXT_VALUE_MINIMUM),
            (HUD_TEXT_HUE_MAXIMUM, HUD_TEXT_SATURATION_MAXIMUM, HUD_TEXT_VALUE_MAXIMUM),
        ),
    )


def load_header_anchor_template(path: Path) -> npt.NDArray[np.uint8] | None:
    """Crop the "Time:" header line out of a stats window screenshot.

    Returns `None` when the image cannot be read or is smaller than the header bounds, so a
    missing or truncated asset degrades to the fixed region instead of raising at startup.
    """

    panel = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if panel is None:
        return None
    if (
        panel.shape[0] < HEADER_ANCHOR_TEMPLATE_BOTTOM
        or panel.shape[1] < HEADER_ANCHOR_TEMPLATE_RIGHT
    ):
        return None
    return cast(
        "npt.NDArray[np.uint8]",
        np.ascontiguousarray(
            panel[
                HEADER_ANCHOR_TEMPLATE_TOP:HEADER_ANCHOR_TEMPLATE_BOTTOM,
                HEADER_ANCHOR_TEMPLATE_LEFT:HEADER_ANCHOR_TEMPLATE_RIGHT,
            ]
        ),
    )


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
        self._anchor_mask = (
            None
            if header_anchor_template is None
            else extract_hud_text_mask(header_anchor_template)
        )

    def read(self, frame: CapturedFrame) -> MonsterStatsMetrics:
        """Measure the stats HUD ROI and report the reading with its diagnostic evidence."""

        pixels = frame.pixels
        if frame.pixel_format is PixelFormat.RGB:
            pixels = cast("npt.NDArray[np.uint8]", cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR))

        # The glyph mask is built once and drives both anchor matching and OCR, so the anchor
        # is compared background-free against a background-free frame.
        mask = extract_hud_text_mask(pixels)
        threshold = self._config.anchor_match_threshold
        anchor_configured = self._anchor_mask is not None
        anchor_score = 0.0
        source = MonsterStatsSource.FIXED_REGION
        roi: npt.NDArray[np.uint8] | None = None

        if self._anchor_mask is not None:
            anchored, anchor_score = self._extract_anchored_roi(mask, self._anchor_mask)
            if anchored is not None:
                roi, source = anchored, MonsterStatsSource.ANCHORED
        anchor_passed = anchor_configured and anchor_score >= threshold
        # A missed anchor falls back to the documented fixed placement rather than reporting
        # nothing; `source` tells the operator which crop the number actually came from.
        if roi is None:
            roi = self._extract_fixed_roi(mask)

        def measured(
            status: MonsterStatsStatus, raw_text: str = "", parsed_count: int | None = None
        ) -> MonsterStatsMetrics:
            return MonsterStatsMetrics(
                anchor_configured=anchor_configured,
                anchor_score=anchor_score,
                anchor_threshold=threshold,
                anchor_passed=anchor_passed,
                roi_width=roi.shape[1] if roi is not None else 0,
                roi_height=roi.shape[0] if roi is not None else 0,
                raw_text=raw_text,
                parsed_count=parsed_count,
                status=status,
                source=source,
            )

        if roi.size == 0:
            return measured(MonsterStatsStatus.ROI_UNAVAILABLE)

        try:
            # Tesseract reads dark text on a light ground, so the glyph mask is inverted.
            lines = self._recognizer.recognize(cast("npt.NDArray[np.uint8]", cv2.bitwise_not(roi)))
        except OcrError as error:
            # A missing engine install is the operator's to fix and is named separately from a
            # recognition that ran and failed, which is not actionable.
            return measured(
                MonsterStatsStatus.ENGINE_UNAVAILABLE
                if error.code is OcrErrorCode.ENGINE_UNAVAILABLE
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

    def _extract_fixed_roi(self, mask: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Crop the stats region from its documented fixed client position."""

        height, width = mask.shape[:2]
        left, top, right, bottom = compute_monster_stats_roi(width, height, self._config)
        if right <= left or bottom <= top:
            return np.empty((0, 0), dtype=np.uint8)
        return mask[top:bottom, left:right]

    def _extract_anchored_roi(
        self, mask: npt.NDArray[np.uint8], anchor: npt.NDArray[np.uint8]
    ) -> tuple[npt.NDArray[np.uint8] | None, float]:
        """Locate the stats window via its header line, wherever it is placed on screen.

        The best match score is always reported, including when it stays below the
        configured threshold, so diagnostics can show how close the match came.
        """

        height, width = mask.shape[:2]
        anchor_height, anchor_width = anchor.shape[:2]
        if anchor_height > height or anchor_width > width:
            return None, 0.0

        result = cv2.matchTemplate(mask, anchor, cv2.TM_CCOEFF_NORMED)
        _min_val, score, _min_loc, max_loc = cv2.minMaxLoc(result)
        if score < self._config.anchor_match_threshold:
            return None, float(score)

        anchor_x, anchor_y = max_loc
        left = max(0, anchor_x - self._config.anchor_inset_x)
        top = max(0, anchor_y - self._config.anchor_inset_y)
        right = min(width, left + self._config.panel_width)
        bottom = min(height, top + self._config.panel_height)
        if right <= left or bottom <= top:
            return None, float(score)
        return mask[top:bottom, left:right], float(score)


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
