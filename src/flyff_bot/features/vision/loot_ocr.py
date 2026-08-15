"""OCR-based extraction of central Flyff loot notifications."""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.models import CapturedFrame, ClientSize, PixelFormat

DEFAULT_LOOT_REGION_X = 0.30
DEFAULT_LOOT_REGION_Y = 0.60
DEFAULT_LOOT_REGION_WIDTH = 0.40
DEFAULT_LOOT_REGION_HEIGHT = 0.18
DEFAULT_ADAPTIVE_THRESHOLD_BLOCK_SIZE = 31
DEFAULT_ADAPTIVE_THRESHOLD_OFFSET = 5
TESSERACT_EXECUTABLE = "tesseract"
TESSERACT_LANGUAGE = "eng+deu"
TESSERACT_PAGE_SEGMENTATION_MODE = 6
TESSERACT_TIMEOUT_SECONDS = 10.0
_TESSERACT_INPUT_FILENAME = "loot-roi.png"
_TESSERACT_CONFIG_ARGUMENT = "--psm"
_TESSERACT_OUTPUT_FORMAT = "stdout"
_DEFAULT_LOOT_COUNT = 1
_PENYA_NAME = "penya"
_PICKUP_PATTERNS = (
    re.compile(
        r"^You received(?: (?P<count>\d+)(?:\s*[xX])?)? (?P<item>.+?)\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:Du hast )?(?:(?P<count>\d+)(?:\s*[xX])? )?(?P<item>.+?) erhalten\.?$",
        re.IGNORECASE,
    ),
)


class LootOcrErrorCode(StrEnum):
    """Known OCR failures that presentation code can localize."""

    ENGINE_UNAVAILABLE = "engine_unavailable"
    RECOGNITION_FAILED = "recognition_failed"


class LootOcrError(RuntimeError):
    """A failure while turning a preprocessed loot region into text."""

    def __init__(self, code: LootOcrErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class LootLogRegion:
    """A normalized rectangle containing the central notification log."""

    x: float = DEFAULT_LOOT_REGION_X
    y: float = DEFAULT_LOOT_REGION_Y
    width: float = DEFAULT_LOOT_REGION_WIDTH
    height: float = DEFAULT_LOOT_REGION_HEIGHT

    def __post_init__(self) -> None:
        if min(self.x, self.y, self.width, self.height) < 0.0:
            raise ValueError("Loot log region values must not be negative.")
        if self.width == 0.0 or self.height == 0.0:
            raise ValueError("Loot log region dimensions must be positive.")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("Loot log region must be inside the client frame.")


@dataclass(frozen=True, slots=True)
class LootOcrConfig:
    """Configurable visual characteristics of the central notification log."""

    region: LootLogRegion = field(default_factory=LootLogRegion)
    adaptive_threshold_block_size: int = DEFAULT_ADAPTIVE_THRESHOLD_BLOCK_SIZE
    adaptive_threshold_offset: int = DEFAULT_ADAPTIVE_THRESHOLD_OFFSET

    def __post_init__(self) -> None:
        if self.adaptive_threshold_block_size < 3 or not self.adaptive_threshold_block_size % 2:
            raise ValueError(
                "Adaptive threshold block size must be an odd integer of at least three."
            )


@dataclass(frozen=True, slots=True)
class LootEvent:
    """One item pickup observed in the client notification log."""

    timestamp: datetime
    item_name: str
    count: int
    raw_text: str


class TextRecognizer(Protocol):
    """An OCR engine capable of reading preprocessed notification text."""

    def recognize(self, image: npt.NDArray[np.uint8]) -> Iterable[str]:
        """Return recognized notification lines from a monochrome image."""


class TesseractTextRecognizer:
    """Production OCR adapter for a locally installed Tesseract executable."""

    def __init__(self, executable: str = TESSERACT_EXECUTABLE) -> None:
        self._executable = executable

    def recognize(self, image: npt.NDArray[np.uint8]) -> tuple[str, ...]:
        success, encoded_image = cv2.imencode(".png", image)
        if not success:
            raise LootOcrError(LootOcrErrorCode.RECOGNITION_FAILED)
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory, _TESSERACT_INPUT_FILENAME)
            image_path.write_bytes(encoded_image.tobytes())
            try:
                result = subprocess.run(
                    [
                        self._executable,
                        str(image_path),
                        _TESSERACT_OUTPUT_FORMAT,
                        "-l",
                        TESSERACT_LANGUAGE,
                        _TESSERACT_CONFIG_ARGUMENT,
                        str(TESSERACT_PAGE_SEGMENTATION_MODE),
                    ],
                    capture_output=True,
                    check=True,
                    text=True,
                    timeout=TESSERACT_TIMEOUT_SECONDS,
                )
            except FileNotFoundError as error:
                raise LootOcrError(LootOcrErrorCode.ENGINE_UNAVAILABLE) from error
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                raise LootOcrError(LootOcrErrorCode.RECOGNITION_FAILED) from error
        return tuple(line for line in result.stdout.splitlines() if line.strip())


def extract_loot_region(frame: CapturedFrame, region: LootLogRegion) -> CapturedFrame:
    """Extract the configured notification rectangle from a captured client frame."""

    left, top, right, bottom = _region_bounds(frame.client_size, region)
    pixels = np.ascontiguousarray(frame.pixels[top:bottom, left:right])
    return CapturedFrame(
        pixels=pixels,
        client_size=ClientSize(width=right - left, height=bottom - top),
        pixel_format=frame.pixel_format,
    )


def preprocess_loot_region(frame: CapturedFrame, config: LootOcrConfig) -> npt.NDArray[np.uint8]:
    """Enhance central notification text for OCR without changing the source frame."""

    pixels = extract_loot_region(frame, config.region).pixels
    conversion = cv2.COLOR_BGR2GRAY if frame.pixel_format is PixelFormat.BGR else cv2.COLOR_RGB2GRAY
    grayscale = cv2.cvtColor(pixels, conversion)
    contrast_enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(grayscale)
    return cast(
        "npt.NDArray[np.uint8]",
        cv2.adaptiveThreshold(
            contrast_enhanced,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            config.adaptive_threshold_block_size,
            config.adaptive_threshold_offset,
        ),
    )


def parse_loot_lines(lines: Iterable[str], timestamp: datetime) -> tuple[LootEvent, ...]:
    """Parse supported German and English item pickup notification lines."""

    events: list[LootEvent] = []
    for line in lines:
        raw_text = " ".join(line.split())
        for pattern in _PICKUP_PATTERNS:
            match = pattern.fullmatch(raw_text)
            if match is None:
                continue
            item_name = match["item"].strip().rstrip(".")
            if not item_name or _PENYA_NAME in item_name.casefold():
                break
            count = int(match["count"]) if match["count"] is not None else _DEFAULT_LOOT_COUNT
            if count > 0:
                events.append(LootEvent(timestamp, item_name, count, raw_text))
            break
    return tuple(events)


class LootLogReader:
    """Read and parse loot notifications from an independently captured game frame."""

    def __init__(
        self,
        recognizer: TextRecognizer,
        config: LootOcrConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._recognizer = recognizer
        self._config = config or LootOcrConfig()
        self._clock = clock or (lambda: datetime.now(UTC))

    def read(
        self, frame: CapturedFrame, captured_at: datetime | None = None
    ) -> tuple[LootEvent, ...]:
        """Return item pickups recognized in this frame's central notification region."""

        timestamp = captured_at or self._clock()
        return parse_loot_lines(
            self._recognizer.recognize(preprocess_loot_region(frame, self._config)), timestamp
        )


def _region_bounds(size: ClientSize, region: LootLogRegion) -> tuple[int, int, int, int]:
    left = round(size.width * region.x)
    top = round(size.height * region.y)
    right = round(size.width * (region.x + region.width))
    bottom = round(size.height * (region.y + region.height))
    if right <= left or bottom <= top:
        raise ValueError("Loot log region rounds to an empty area for this client size.")
    return left, top, right, bottom
