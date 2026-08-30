"""Template-anchored discovery of the client's built-in teleporter dialog."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from flyff_bot.features.navigation.teleporter_dispatch import (
    ClientPoint,
    TeleporterDialogGeometry,
)
from flyff_bot.features.vision.capture import FrameSource
from flyff_bot.features.vision.models import FrameCaptureError

TELEPORT_BUTTON_ASSET_RELATIVE_PATH = Path("Lang/English/Theme/Default/ButtTeleport.tga")
BUTTON_STATE_COUNT = 3
BUTTON_MATCH_THRESHOLD = 0.92
MINIMUM_DIALOG_WIDTH_PIXELS = 250
MINIMUM_DIALOG_HEIGHT_PIXELS = 180
SEARCH_FIELD_X_RATIO = 0.50
SEARCH_FIELD_Y_RATIO = 0.25
FIRST_RESULT_X_RATIO = 0.50
FIRST_RESULT_Y_RATIO = 0.35


class TemplateTeleporterDialogLocator:
    """Find the client-owned teleport button and its enclosing dialog rectangle.

    The loose TGA is loaded from the operator's client installation at runtime. Missing,
    ambiguous, or geometrically incoherent evidence returns ``None`` and therefore causes
    dispatch to fail closed without a click.
    """

    def __init__(
        self,
        frame_source: FrameSource,
        client_data_root: Path,
        *,
        match_threshold: float = BUTTON_MATCH_THRESHOLD,
    ) -> None:
        self._frame_source = frame_source
        self._asset_path = client_data_root / TELEPORT_BUTTON_ASSET_RELATIVE_PATH
        self._match_threshold = match_threshold

    def locate(self, window_handle: int) -> TeleporterDialogGeometry | None:
        if not self._asset_path.is_file():
            return None
        template = cv2.imread(str(self._asset_path), cv2.IMREAD_COLOR)
        if template is None or template.shape[1] % BUTTON_STATE_COUNT != 0:
            return None
        try:
            frame = self._frame_source.capture(window_handle)
        except FrameCaptureError:
            return None
        pixels = frame.pixels
        if pixels.ndim != 3 or pixels.shape[2] != 3:
            return None
        state_width = template.shape[1] // BUTTON_STATE_COUNT
        button = template[:, :state_width]
        if pixels.shape[0] < button.shape[0] or pixels.shape[1] < button.shape[1]:
            return None
        result = cv2.matchTemplate(pixels, button, cv2.TM_CCOEFF_NORMED)
        locations = np.argwhere(result >= self._match_threshold)
        if locations.size == 0:
            return None
        best_y, best_x = np.unravel_index(int(np.argmax(result)), result.shape)
        # More than one spatially distinct match is ambiguous; adjacent pixels around one
        # correlation peak are intentionally treated as the same detection.
        distinct = [
            (int(y), int(x))
            for y, x in locations
            if abs(int(y) - best_y) > button.shape[0] or abs(int(x) - best_x) > button.shape[1]
        ]
        if distinct:
            return None
        button_center = ClientPoint(
            best_x + button.shape[1] // 2,
            best_y + button.shape[0] // 2,
        )
        dialog = self._enclosing_dialog(pixels, button_center)
        if dialog is None:
            return None
        x, y, width, height = dialog
        return TeleporterDialogGeometry(
            search_field=ClientPoint(
                x + round(width * SEARCH_FIELD_X_RATIO),
                y + round(height * SEARCH_FIELD_Y_RATIO),
            ),
            first_result=ClientPoint(
                x + round(width * FIRST_RESULT_X_RATIO),
                y + round(height * FIRST_RESULT_Y_RATIO),
            ),
            teleport_button=button_center,
        )

    @staticmethod
    def _enclosing_dialog(
        pixels: np.ndarray,
        button_center: ClientPoint,
    ) -> tuple[int, int, int, int] | None:
        grayscale = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(grayscale, 50, 150)
        contours, _hierarchy = cv2.findContours(
            edges,
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        candidates: list[tuple[int, int, int, int]] = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if width < MINIMUM_DIALOG_WIDTH_PIXELS or height < MINIMUM_DIALOG_HEIGHT_PIXELS:
                continue
            if x <= button_center.x <= x + width and y <= button_center.y <= y + height:
                candidates.append((x, y, width, height))
        if not candidates:
            return None
        return min(candidates, key=lambda rectangle: rectangle[2] * rectangle[3])
