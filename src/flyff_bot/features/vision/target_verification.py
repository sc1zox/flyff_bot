"""Target-bar inspection for safe target selection verification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.models import CapturedFrame, ClientSize

DEFAULT_TARGET_REGION_X = 0.25
DEFAULT_TARGET_REGION_Y = 0.0
DEFAULT_TARGET_REGION_WIDTH = 0.5
DEFAULT_TARGET_REGION_HEIGHT = 0.15
DEFAULT_HP_COLOR_LOWER_BOUND = (0, 0, 100)
DEFAULT_HP_COLOR_UPPER_BOUND = (100, 100, 255)
DEFAULT_MINIMUM_HP_PIXEL_COUNT = 10
DEFAULT_NAME_MATCH_THRESHOLD = 0.9


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
    hp_color_lower_bound: tuple[int, int, int] = DEFAULT_HP_COLOR_LOWER_BOUND
    hp_color_upper_bound: tuple[int, int, int] = DEFAULT_HP_COLOR_UPPER_BOUND
    minimum_hp_pixel_count: int = DEFAULT_MINIMUM_HP_PIXEL_COUNT
    name_match_threshold: float = DEFAULT_NAME_MATCH_THRESHOLD

    def __post_init__(self) -> None:
        if self.minimum_hp_pixel_count <= 0:
            raise ValueError("Minimum HP pixel count must be positive.")
        if not 0.0 <= self.name_match_threshold <= 1.0:
            raise ValueError("Name match threshold must be between zero and one.")
        for lower, upper in zip(self.hp_color_lower_bound, self.hp_color_upper_bound, strict=True):
            if not 0 <= lower <= upper <= 255:
                raise ValueError("HP color bounds must be ordered byte values.")


@dataclass(frozen=True, slots=True)
class TargetVerificationResult:
    """The selected target's safety status and observed visual evidence."""

    status: TargetStatus
    target_name: str | None
    hp_pixel_count: int

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

    def verify(self, frame: CapturedFrame) -> TargetVerificationResult:
        """Classify the selected target from its header region in a captured frame."""

        target_region = extract_target_region(frame, self._config.region)
        hp_pixel_count = self._hp_pixel_count(target_region.pixels)
        if hp_pixel_count < self._config.minimum_hp_pixel_count:
            status = TargetStatus.NO_TARGET if hp_pixel_count == 0 else TargetStatus.WRONG_TARGET
            return TargetVerificationResult(status, None, hp_pixel_count)
        target_name = self._matching_target_name(target_region.pixels)
        status = TargetStatus.VALID_TARGET if target_name is not None else TargetStatus.WRONG_TARGET
        return TargetVerificationResult(status, target_name, hp_pixel_count)

    def _hp_pixel_count(self, pixels: npt.NDArray[np.uint8]) -> int:
        lower = np.array(self._config.hp_color_lower_bound, dtype=np.uint8)
        upper = np.array(self._config.hp_color_upper_bound, dtype=np.uint8)
        return int(np.count_nonzero(np.all((pixels >= lower) & (pixels <= upper), axis=2)))

    def _matching_target_name(self, pixels: npt.NDArray[np.uint8]) -> str | None:
        for name, template in self._name_templates.items():
            if template.shape[0] > pixels.shape[0] or template.shape[1] > pixels.shape[1]:
                continue
            score = float(
                cv2.minMaxLoc(cv2.matchTemplate(pixels, template, cv2.TM_CCOEFF_NORMED))[1]
            )
            if score >= self._config.name_match_threshold:
                return name
        return None


def _region_bounds(size: ClientSize, region: TargetRegion) -> tuple[int, int, int, int]:
    left = round(size.width * region.x)
    top = round(size.height * region.y)
    right = round(size.width * (region.x + region.width))
    bottom = round(size.height * (region.y + region.height))
    if right <= left or bottom <= top:
        raise ValueError("Target region rounds to an empty area for this client size.")
    return left, top, right, bottom
