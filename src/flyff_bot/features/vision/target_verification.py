"""Target-bar inspection for safe target selection verification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.models import CapturedFrame, ClientSize, TargetVerificationMetrics

DEFAULT_TARGET_REGION_X = 0.25
DEFAULT_TARGET_REGION_Y = 0.0
DEFAULT_TARGET_REGION_WIDTH = 0.5
DEFAULT_TARGET_REGION_HEIGHT = 0.15
DEFAULT_HP_COLOR_LOWER_BOUND = (100, 100, 220)
DEFAULT_HP_COLOR_UPPER_BOUND = (140, 180, 255)
DEFAULT_MINIMUM_HP_PIXEL_COUNT = 10
DEFAULT_NAME_MATCH_THRESHOLD = 0.9
DEFAULT_ANCHOR_MATCH_THRESHOLD = 0.9


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
class TargetVerificationConfig:
    """Configurable visual characteristics of a Flyff target header."""

    region: TargetRegion = field(default_factory=TargetRegion)
    hp_region: TargetRegion = field(
        default_factory=lambda: TargetRegion(x=0.34, y=0.5, width=0.32, height=0.12)
    )
    name_region: TargetRegion = field(
        default_factory=lambda: TargetRegion(x=0.4, y=0.2, width=0.3, height=0.25)
    )
    hp_color_lower_bound: tuple[int, int, int] = DEFAULT_HP_COLOR_LOWER_BOUND
    hp_color_upper_bound: tuple[int, int, int] = DEFAULT_HP_COLOR_UPPER_BOUND
    minimum_hp_pixel_count: int = DEFAULT_MINIMUM_HP_PIXEL_COUNT
    name_match_threshold: float = DEFAULT_NAME_MATCH_THRESHOLD
    anchor_match_threshold: float = DEFAULT_ANCHOR_MATCH_THRESHOLD

    def __post_init__(self) -> None:
        if self.minimum_hp_pixel_count <= 0:
            raise ValueError("Minimum HP pixel count must be positive.")
        for threshold in (self.name_match_threshold, self.anchor_match_threshold):
            if not 0.0 <= threshold <= 1.0:
                raise ValueError("Target match thresholds must be between zero and one.")
        for lower, upper in zip(self.hp_color_lower_bound, self.hp_color_upper_bound, strict=True):
            if not 0 <= lower <= upper <= 255:
                raise ValueError("HP color bounds must be ordered byte values.")


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


class TargetVerifier:
    """Verify a live, whitelisted target from its target-bar appearance."""

    def __init__(
        self,
        name_templates: Mapping[str, npt.NDArray[np.uint8]],
        header_anchor_template: npt.NDArray[np.uint8],
        config: TargetVerificationConfig | None = None,
    ) -> None:
        self._name_templates = dict(name_templates)
        self._config = config or TargetVerificationConfig()
        if not self._name_templates or any(not name.strip() for name in self._name_templates):
            raise ValueError("At least one non-empty target name template is required.")
        if any(
            template.dtype != np.uint8 or template.ndim != 3
            for template in self._name_templates.values()
        ):
            raise ValueError("Target name templates must be uint8 colour images.")
        if header_anchor_template.dtype != np.uint8 or header_anchor_template.ndim != 3:
            raise ValueError("Target header anchor template must be a uint8 colour image.")
        self._header_anchor_template = header_anchor_template

    def verify(self, frame: CapturedFrame) -> TargetVerificationResult:
        """Classify the selected target from its header region in a captured frame."""

        anchor_threshold = self._config.anchor_match_threshold
        minimum_hp_pixel_count = self._config.minimum_hp_pixel_count
        name_threshold = self._config.name_match_threshold

        target_region = extract_target_region(frame, self._config.region)
        anchor_score = self._anchor_score(target_region.pixels)
        anchor_passed = anchor_score >= anchor_threshold
        if not anchor_passed:
            return TargetVerificationResult(
                TargetStatus.NO_TARGET,
                None,
                0,
                metrics=TargetVerificationMetrics(
                    anchor_score=anchor_score,
                    anchor_threshold=anchor_threshold,
                    anchor_passed=False,
                    minimum_hp_pixel_count=minimum_hp_pixel_count,
                    name_threshold=name_threshold,
                ),
            )

        hp_pixels = extract_target_region(target_region, self._config.hp_region).pixels
        hp_pixel_count = self._hp_pixel_count(hp_pixels)
        hp_passed = hp_pixel_count >= minimum_hp_pixel_count
        if not hp_passed:
            return TargetVerificationResult(
                TargetStatus.WRONG_TARGET,
                None,
                hp_pixel_count,
                self._hp_percentage(hp_pixels),
                metrics=TargetVerificationMetrics(
                    anchor_score=anchor_score,
                    anchor_threshold=anchor_threshold,
                    anchor_passed=True,
                    minimum_hp_pixel_count=minimum_hp_pixel_count,
                    hp_passed=False,
                    name_threshold=name_threshold,
                ),
            )

        name_candidate, name_score = self._best_name_match(
            extract_target_region(target_region, self._config.name_region).pixels
        )
        name_passed = name_score >= name_threshold
        status = TargetStatus.VALID_TARGET if name_passed else TargetStatus.WRONG_TARGET
        return TargetVerificationResult(
            status,
            name_candidate if name_passed else None,
            hp_pixel_count,
            self._hp_percentage(hp_pixels),
            metrics=TargetVerificationMetrics(
                anchor_score=anchor_score,
                anchor_threshold=anchor_threshold,
                anchor_passed=True,
                minimum_hp_pixel_count=minimum_hp_pixel_count,
                hp_passed=True,
                name_candidate=name_candidate,
                name_score=name_score,
                name_threshold=name_threshold,
                name_passed=name_passed,
            ),
        )

    def _anchor_score(self, pixels: npt.NDArray[np.uint8]) -> float:
        template = self._header_anchor_template
        if template.shape[0] > pixels.shape[0] or template.shape[1] > pixels.shape[1]:
            return 0.0
        return float(cv2.minMaxLoc(cv2.matchTemplate(pixels, template, cv2.TM_CCOEFF_NORMED))[1])

    def _hp_pixel_count(self, pixels: npt.NDArray[np.uint8]) -> int:
        lower = np.array(self._config.hp_color_lower_bound, dtype=np.uint8)
        upper = np.array(self._config.hp_color_upper_bound, dtype=np.uint8)
        return int(np.count_nonzero(np.all((pixels >= lower) & (pixels <= upper), axis=2)))

    def _best_name_match(self, pixels: npt.NDArray[np.uint8]) -> tuple[str | None, float]:
        best_name: str | None = None
        best_score = 0.0
        for name, template in self._name_templates.items():
            if template.shape[0] > pixels.shape[0] or template.shape[1] > pixels.shape[1]:
                continue
            score = float(
                cv2.minMaxLoc(cv2.matchTemplate(pixels, template, cv2.TM_CCOEFF_NORMED))[1]
            )
            if best_name is None or score > best_score:
                best_name = name
                best_score = score
        return best_name, best_score

    def _hp_percentage(self, pixels: npt.NDArray[np.uint8]) -> float:
        lower = np.array(self._config.hp_color_lower_bound, dtype=np.uint8)
        upper = np.array(self._config.hp_color_upper_bound, dtype=np.uint8)
        mask = np.all((pixels >= lower) & (pixels <= upper), axis=2)
        filled_columns = int(np.count_nonzero(np.any(mask, axis=0)))
        return float(100.0 * filled_columns / pixels.shape[1])


def _region_bounds(size: ClientSize, region: TargetRegion) -> tuple[int, int, int, int]:
    left = round(size.width * region.x)
    top = round(size.height * region.y)
    right = round(size.width * (region.x + region.width))
    bottom = round(size.height * (region.y + region.height))
    if right <= left or bottom <= top:
        raise ValueError("Target region rounds to an empty area for this client size.")
    return left, top, right, bottom
