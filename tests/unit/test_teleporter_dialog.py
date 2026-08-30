"""Tests for client-asset anchored teleporter dialog geometry."""

from pathlib import Path

import cv2
import numpy as np

from flyff_bot.features.navigation.teleporter_dialog import (
    TELEPORT_BUTTON_ASSET_RELATIVE_PATH,
    TemplateTeleporterDialogLocator,
)
from flyff_bot.features.vision.models import CapturedFrame, ClientSize


class _FrameSource:
    def __init__(self, pixels: np.ndarray) -> None:
        self._frame = CapturedFrame(
            pixels,
            ClientSize(width=pixels.shape[1], height=pixels.shape[0]),
        )

    def capture(self, _window_handle: int) -> CapturedFrame:
        return self._frame


def test_locator_derives_clicks_from_the_detected_dialog_and_client_button(tmp_path: Path) -> None:
    random = np.random.default_rng(92)
    button = random.integers(0, 256, size=(20, 96, 3), dtype=np.uint8)
    asset = np.concatenate((button, button, button), axis=1)
    asset_path = tmp_path / TELEPORT_BUTTON_ASSET_RELATIVE_PATH
    asset_path.parent.mkdir(parents=True)
    encoded, payload = cv2.imencode(".png", asset)
    assert encoded
    asset_path.write_bytes(payload.tobytes())

    pixels = np.zeros((500, 700, 3), dtype=np.uint8)
    cv2.rectangle(pixels, (150, 80), (550, 430), (255, 255, 255), 2)
    pixels[380:400, 300:396] = button
    locator = TemplateTeleporterDialogLocator(_FrameSource(pixels), tmp_path)

    geometry = locator.locate(42)

    assert geometry is not None
    assert geometry.teleport_button.x == 348
    assert geometry.teleport_button.y == 390
    assert 150 < geometry.search_field.x < 550
    assert 80 < geometry.search_field.y < 430


def test_missing_client_button_asset_returns_no_geometry(tmp_path: Path) -> None:
    pixels = np.zeros((100, 100, 3), dtype=np.uint8)

    assert TemplateTeleporterDialogLocator(_FrameSource(pixels), tmp_path).locate(42) is None
