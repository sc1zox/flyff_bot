"""Pure minimap radar-dot detection for staged search navigation."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from flyff_bot.features.automation.models import Position
from flyff_bot.features.vision.models import CapturedFrame, PixelFormat

DEFAULT_MINIMAP_LEFT = 0.75
DEFAULT_MINIMAP_TOP = 0.0
DEFAULT_MINIMAP_RIGHT = 1.0
DEFAULT_MINIMAP_BOTTOM = 0.30
DEFAULT_MINIMUM_RED_PIXELS = 4
MINIMUM_RED_CHANNEL = 150
MAXIMUM_NON_RED_CHANNEL = 120


@dataclass(frozen=True, slots=True)
class MinimapRadarConfig:
    """Normalized top-right minimap bounds and conservative red-dot threshold."""

    left: float = DEFAULT_MINIMAP_LEFT
    top: float = DEFAULT_MINIMAP_TOP
    right: float = DEFAULT_MINIMAP_RIGHT
    bottom: float = DEFAULT_MINIMAP_BOTTOM
    minimum_red_pixels: int = DEFAULT_MINIMUM_RED_PIXELS

    def __post_init__(self) -> None:
        if not 0.0 <= self.left < self.right <= 1.0 or not 0.0 <= self.top < self.bottom <= 1.0:
            raise ValueError("Minimap bounds must be ordered normalized coordinates.")
        if self.minimum_red_pixels <= 0:
            raise ValueError("Minimum radar-dot pixels must be positive.")


class MinimapRadar:
    """Find the nearest qualifying red connected component in a client minimap ROI."""

    def __init__(self, config: MinimapRadarConfig | None = None) -> None:
        self._config = config or MinimapRadarConfig()

    def nearest_dot(self, frame: CapturedFrame | None) -> Position | None:
        """Return a client-relative red-dot centre, or ``None`` when no dot qualifies."""

        if frame is None or frame.pixel_format is not PixelFormat.BGR:
            return None
        height, width = frame.pixels.shape[:2]
        left, right = int(width * self._config.left), int(width * self._config.right)
        top, bottom = int(height * self._config.top), int(height * self._config.bottom)
        region = frame.pixels[top:bottom, left:right]
        blue, green, red = cv2.split(region)
        mask = np.where(
            (red >= MINIMUM_RED_CHANNEL)
            & (green <= MAXIMUM_NON_RED_CHANNEL)
            & (blue <= MAXIMUM_NON_RED_CHANNEL),
            255,
            0,
        ).astype(np.uint8)
        component_count, _labels, statistics, centroids = cv2.connectedComponentsWithStats(mask)
        candidates = [
            (statistics[index], centroids[index])
            for index in range(1, component_count)
            if statistics[index, cv2.CC_STAT_AREA] >= self._config.minimum_red_pixels
        ]
        if not candidates:
            return None
        centre_x, centre_y = region.shape[1] / 2, region.shape[0] / 2
        _statistics, centroid = min(
            candidates,
            key=lambda candidate: (
                (candidate[1][0] - centre_x) ** 2 + (candidate[1][1] - centre_y) ** 2
            ),
        )
        return Position(left + int(centroid[0]), top + int(centroid[1]))
