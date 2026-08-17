"""Target-bar inspection for safe target selection verification."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.loot_ocr import LootOcrError, LootOcrErrorCode, TextRecognizer
from flyff_bot.features.vision.models import (
    CapturedFrame,
    ClientSize,
    TargetNameStatus,
    TargetVerificationMetrics,
)

DEFAULT_TARGET_REGION_X = 0.38
DEFAULT_TARGET_REGION_Y = 0.0
DEFAULT_TARGET_REGION_WIDTH = 0.24
DEFAULT_TARGET_REGION_HEIGHT = 0.10
DEFAULT_HP_COLOR_LOWER_BOUND = (100, 100, 220)
DEFAULT_HP_COLOR_UPPER_BOUND = (140, 180, 255)
DEFAULT_MINIMUM_HP_PIXEL_COUNT = 10
DEFAULT_ANCHOR_MATCH_THRESHOLD = 0.75
MINIMUM_MATCH_THRESHOLD = 0.3
MAXIMUM_MATCH_THRESHOLD = 1.0
# Flyff renders the target name in one fixed pale-yellow fill (BGR ~160/255/255) on every
# client resolution, so isolating that colour leaves the glyphs and drops the arbitrary
# world background the nameplate is drawn over.
DEFAULT_NAME_TEXT_COLOR_LOWER_BOUND = (110, 215, 215)
DEFAULT_NAME_TEXT_COLOR_UPPER_BOUND = (210, 255, 255)
DEFAULT_NAME_OCR_UPSCALE = 2

# One nameplate reading: the canonical whitelist entry, the raw OCR text, and its status.
type _NameReading = tuple[str | None, str, TargetNameStatus]


class TargetStatus(StrEnum):
    """The safety-relevant state of the currently selected target."""

    VALID_TARGET = "valid_target"
    WRONG_TARGET = "wrong_target"
    NO_TARGET = "no_target"


@dataclass(frozen=True, slots=True)
class TargetRegion:
    """A normalized rectangle within a client frame."""

    x: float = DEFAULT_TARGET_REGION_X
    y: float = DEFAULT_TARGET_REGION_Y
    width: float = DEFAULT_TARGET_REGION_WIDTH
    height: float = DEFAULT_TARGET_REGION_HEIGHT

    def __post_init__(self) -> None:
        if min(self.x, self.y, self.width, self.height) < 0.0:
            raise ValueError("Target region values must not be negative.")
        if self.width == 0.0 or self.height == 0.0:
            raise ValueError("Target region dimensions must be positive.")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("Target region must be inside the client frame.")


@dataclass(frozen=True, slots=True)
class AnchorOffsetRegion:
    """A pixel rectangle placed relative to a matched header anchor's top-left corner.

    The Flyff target header is drawn at a fixed pixel size regardless of client
    resolution, so offsetting from the anchor match keeps the HP bar and name crops
    aligned wherever the header appears inside the searched region.
    """

    dx: int
    dy: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Anchor-relative region dimensions must be positive.")


DEFAULT_HP_OFFSET = AnchorOffsetRegion(dx=5, dy=27, width=150, height=12)
DEFAULT_NAME_OFFSET = AnchorOffsetRegion(dx=40, dy=-4, width=125, height=35)


@dataclass(frozen=True, slots=True)
class TargetVerificationConfig:
    """Configurable visual characteristics of a Flyff target header."""

    region: TargetRegion = field(default_factory=TargetRegion)
    hp_offset: AnchorOffsetRegion = DEFAULT_HP_OFFSET
    name_offset: AnchorOffsetRegion = DEFAULT_NAME_OFFSET
    hp_color_lower_bound: tuple[int, int, int] = DEFAULT_HP_COLOR_LOWER_BOUND
    hp_color_upper_bound: tuple[int, int, int] = DEFAULT_HP_COLOR_UPPER_BOUND
    minimum_hp_pixel_count: int = DEFAULT_MINIMUM_HP_PIXEL_COUNT
    anchor_match_threshold: float = DEFAULT_ANCHOR_MATCH_THRESHOLD
    name_text_color_lower_bound: tuple[int, int, int] = DEFAULT_NAME_TEXT_COLOR_LOWER_BOUND
    name_text_color_upper_bound: tuple[int, int, int] = DEFAULT_NAME_TEXT_COLOR_UPPER_BOUND
    name_ocr_upscale: int = DEFAULT_NAME_OCR_UPSCALE

    def __post_init__(self) -> None:
        if self.minimum_hp_pixel_count <= 0:
            raise ValueError("Minimum HP pixel count must be positive.")
        if not 0.0 <= self.anchor_match_threshold <= 1.0:
            raise ValueError("Target match thresholds must be between zero and one.")
        if self.name_ocr_upscale < 1:
            raise ValueError("Target name OCR upscale must be at least one.")
        for lower_bound, upper_bound in (
            (self.hp_color_lower_bound, self.hp_color_upper_bound),
            (self.name_text_color_lower_bound, self.name_text_color_upper_bound),
        ):
            for lower, upper in zip(lower_bound, upper_bound, strict=True):
                if not 0 <= lower <= upper <= 255:
                    raise ValueError("Target colour bounds must be ordered byte values.")


@dataclass(frozen=True, slots=True)
class TargetVerificationResult:
    """The selected target's safety status and observed visual evidence."""

    status: TargetStatus
    target_name: str | None
    hp_pixel_count: int
    hp_percentage: float = 0.0
    metrics: TargetVerificationMetrics = field(default_factory=TargetVerificationMetrics)

    @property
    def is_alive(self) -> bool:
        """Whether the target header contains the configured HP-bar color."""

        return self.hp_pixel_count > 0


def extract_target_region(frame: CapturedFrame, region: TargetRegion) -> CapturedFrame:
    """Extract the configured target-header area while preserving client-frame metadata."""

    size = frame.client_size
    left, top, right, bottom = _region_bounds(size, region)
    pixels = np.ascontiguousarray(frame.pixels[top:bottom, left:right])
    return CapturedFrame(
        pixels=pixels,
        client_size=ClientSize(width=right - left, height=bottom - top),
        pixel_format=frame.pixel_format,
    )


def extract_anchor_relative_region(
    pixels: npt.NDArray[np.uint8], anchor_x: int, anchor_y: int, offset: AnchorOffsetRegion
) -> npt.NDArray[np.uint8]:
    """Crop the offset rectangle around a matched anchor, clipped to the frame bounds."""

    left = max(anchor_x + offset.dx, 0)
    top = max(anchor_y + offset.dy, 0)
    right = min(anchor_x + offset.dx + offset.width, pixels.shape[1])
    bottom = min(anchor_y + offset.dy + offset.height, pixels.shape[0])
    if right <= left or bottom <= top:
        return np.empty((0, 0, pixels.shape[2]), dtype=np.uint8)
    return np.ascontiguousarray(pixels[top:bottom, left:right])


def preprocess_target_name_region(
    pixels: npt.NDArray[np.uint8], config: TargetVerificationConfig
) -> npt.NDArray[np.uint8]:
    """Isolate the nameplate glyphs as dark text on white for OCR.

    Thresholding on the fixed nameplate fill colour rather than on brightness is what
    makes the reading independent of the arbitrary world scenery behind the header.
    """

    if pixels.size == 0:
        return np.empty((0, 0), dtype=np.uint8)
    mask = cv2.inRange(
        pixels,
        np.array(config.name_text_color_lower_bound, dtype=np.uint8),
        np.array(config.name_text_color_upper_bound, dtype=np.uint8),
    )
    text = cv2.bitwise_not(mask)
    if config.name_ocr_upscale > 1:
        text = cv2.resize(
            text,
            None,
            fx=config.name_ocr_upscale,
            fy=config.name_ocr_upscale,
            interpolation=cv2.INTER_CUBIC,
        )
    return cast("npt.NDArray[np.uint8]", text)


def match_whitelisted_name(text: str, allowed_names: Iterable[str]) -> str | None:
    """Return the canonical whitelist entry contained in recognized nameplate text.

    Flyff appends a level suffix such as `<Lvl 175>` to the monster name, so the
    comparison is a case-insensitive containment test rather than an equality test.
    """

    normalized = " ".join(text.split()).casefold()
    if not normalized:
        return None
    for name in allowed_names:
        if " ".join(name.split()).casefold() in normalized:
            return name
    return None


class TargetVerifier:
    """Verify a live, whitelisted target from its target-bar appearance."""

    def __init__(
        self,
        allowed_names: Iterable[str],
        header_anchor_template: npt.NDArray[np.uint8],
        recognizer: TextRecognizer,
        config: TargetVerificationConfig | None = None,
    ) -> None:
        self._allowed_names = tuple(allowed_names)
        self._recognizer = recognizer
        self._config = config or TargetVerificationConfig()
        if not self._allowed_names or any(not name.strip() for name in self._allowed_names):
            raise ValueError("At least one non-empty target name is required.")
        if header_anchor_template.dtype != np.uint8 or header_anchor_template.ndim != 3:
            raise ValueError("Target header anchor template must be a uint8 colour image.")
        self._header_anchor_template = header_anchor_template
        self._last_name_mask: npt.NDArray[np.uint8] | None = None
        self._last_name_reading: _NameReading = (None, "", TargetNameStatus.NOT_EVALUATED)

    @property
    def config(self) -> TargetVerificationConfig:
        """Return the configuration currently applied to every verification."""

        return self._config

    @property
    def allowed_names(self) -> tuple[str, ...]:
        """Return the monster names accepted as a valid target."""

        return self._allowed_names

    def update_anchor_threshold(self, anchor_match_threshold: float) -> None:
        """Apply the operator-selected anchor match threshold without rebuilding state."""

        self._config = replace(self._config, anchor_match_threshold=anchor_match_threshold)

    def verify(self, frame: CapturedFrame) -> TargetVerificationResult:
        """Classify the selected target from its header region in a captured frame.

        The anchor and HP criteria are measured on every frame so the debug metrics stay
        complete. Name recognition runs an OCR subprocess and is therefore evaluated only
        once the header anchor is accepted, which is also the only case in which a target
        exists to name.
        """

        config = self._config
        target_region = extract_target_region(frame, config.region).pixels
        anchor_score, anchor_x, anchor_y = self._match_anchor(target_region)
        anchor_passed = anchor_score >= config.anchor_match_threshold

        hp_pixels = extract_anchor_relative_region(
            target_region, anchor_x, anchor_y, config.hp_offset
        )
        hp_pixel_count = self._hp_pixel_count(hp_pixels)
        hp_percentage = self._hp_percentage(hp_pixels, config.hp_offset.width)
        hp_passed = hp_pixel_count >= config.minimum_hp_pixel_count

        name_candidate, name_text, name_status = (
            self._read_name(
                extract_anchor_relative_region(
                    target_region, anchor_x, anchor_y, config.name_offset
                )
            )
            if anchor_passed
            else (None, "", TargetNameStatus.NOT_EVALUATED)
        )
        name_passed = name_status is TargetNameStatus.MATCHED

        status = _target_status(anchor_passed, hp_passed, name_passed)
        return TargetVerificationResult(
            status,
            name_candidate if status is TargetStatus.VALID_TARGET else None,
            hp_pixel_count if anchor_passed else 0,
            hp_percentage if anchor_passed else 0.0,
            metrics=TargetVerificationMetrics(
                anchor_score=anchor_score,
                anchor_threshold=config.anchor_match_threshold,
                anchor_passed=anchor_passed,
                minimum_hp_pixel_count=config.minimum_hp_pixel_count,
                hp_pixel_count=hp_pixel_count,
                hp_percentage=hp_percentage,
                hp_passed=hp_passed,
                name_candidate=name_candidate,
                name_text=name_text,
                name_status=name_status,
                name_passed=name_passed,
            ),
        )

    def _read_name(self, pixels: npt.NDArray[np.uint8]) -> _NameReading:
        """Read the nameplate and resolve it to a canonical whitelist entry.

        Only the canonical entry is returned as the candidate; the raw OCR string stays
        diagnostic, because it flickers between ticks and `SelectedTarget.name` takes
        part in the equality that raises a target-changed event.

        Because the mask keeps only the fixed nameplate fill colour, it is byte-identical
        on every tick a target stays selected, so the previous reading is reused instead
        of spending another ~75 ms OCR subprocess per tick on the same glyphs. A failed
        recognition is not remembered, so a recoverable engine problem is retried.
        """

        image = preprocess_target_name_region(pixels, self._config)
        if image.size == 0:
            return None, "", TargetNameStatus.UNREADABLE
        if self._last_name_mask is not None and np.array_equal(image, self._last_name_mask):
            return self._last_name_reading
        try:
            lines = self._recognizer.recognize(image)
        except LootOcrError as error:
            unavailable = error.code is LootOcrErrorCode.ENGINE_UNAVAILABLE
            return (
                None,
                "",
                TargetNameStatus.ENGINE_UNAVAILABLE if unavailable else TargetNameStatus.OCR_FAILED,
            )
        reading = self._resolve_reading(lines)
        self._last_name_mask = image
        self._last_name_reading = reading
        return reading

    def _resolve_reading(self, lines: Iterable[str]) -> _NameReading:
        raw_text = " ".join(line.strip() for line in lines if line.strip())
        if not raw_text:
            return None, "", TargetNameStatus.UNREADABLE
        candidate = match_whitelisted_name(raw_text, self._allowed_names)
        if candidate is None:
            return None, raw_text, TargetNameStatus.NO_MATCH
        return candidate, raw_text, TargetNameStatus.MATCHED

    def _match_anchor(self, pixels: npt.NDArray[np.uint8]) -> tuple[float, int, int]:
        """Return the best anchor score and its top-left location inside the region."""

        template = self._header_anchor_template
        if template.shape[0] > pixels.shape[0] or template.shape[1] > pixels.shape[1]:
            return 0.0, 0, 0
        _, score, _, location = cv2.minMaxLoc(
            cv2.matchTemplate(pixels, template, cv2.TM_CCOEFF_NORMED)
        )
        return float(score), int(location[0]), int(location[1])

    def _hp_pixel_count(self, pixels: npt.NDArray[np.uint8]) -> int:
        lower = np.array(self._config.hp_color_lower_bound, dtype=np.uint8)
        upper = np.array(self._config.hp_color_upper_bound, dtype=np.uint8)
        return int(np.count_nonzero(np.all((pixels >= lower) & (pixels <= upper), axis=2)))

    def _hp_percentage(self, pixels: npt.NDArray[np.uint8], gauge_width: int) -> float:
        """Measure the filled share of the gauge against its configured full width.

        A crop clipped by the frame edge keeps the nominal denominator, so a partially
        visible header cannot report a falsely full HP bar.
        """

        if pixels.size == 0:
            return 0.0
        lower = np.array(self._config.hp_color_lower_bound, dtype=np.uint8)
        upper = np.array(self._config.hp_color_upper_bound, dtype=np.uint8)
        mask = np.all((pixels >= lower) & (pixels <= upper), axis=2)
        filled_columns = int(np.count_nonzero(np.any(mask, axis=0)))
        return float(100.0 * filled_columns / gauge_width)


def _target_status(anchor_passed: bool, hp_passed: bool, name_passed: bool) -> TargetStatus:
    """Collapse the three measured criteria into one safety-relevant status."""

    if not anchor_passed:
        return TargetStatus.NO_TARGET
    if hp_passed and name_passed:
        return TargetStatus.VALID_TARGET
    return TargetStatus.WRONG_TARGET


def compute_target_header_bounds(
    client_width: int, client_height: int, region: TargetRegion | None = None
) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) pixel bounds for the target header region."""

    return _region_bounds(ClientSize(client_width, client_height), region or TargetRegion())


def _region_bounds(size: ClientSize, region: TargetRegion) -> tuple[int, int, int, int]:
    left = round(size.width * region.x)
    top = round(size.height * region.y)
    right = round(size.width * (region.x + region.width))
    bottom = round(size.height * (region.y + region.height))
    if right <= left or bottom <= top:
        raise ValueError("Target region rounds to an empty area for this client size.")
    return left, top, right, bottom
