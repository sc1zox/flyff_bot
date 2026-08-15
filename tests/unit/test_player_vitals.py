"""Unit tests for player vitals perception using pure pixel analysis."""

from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest

from flyff_bot.features.automation.models import PlayerVitals
from flyff_bot.features.vision.models import CapturedFrame, ClientSize, PixelFormat
from flyff_bot.features.vision.vitals import (
    DEFAULT_FP_BAR_BOTTOM,
    DEFAULT_FP_BAR_LEFT,
    DEFAULT_FP_BAR_RIGHT,
    DEFAULT_FP_BAR_TOP,
    DEFAULT_HP_BAR_BOTTOM,
    DEFAULT_HP_BAR_LEFT,
    DEFAULT_HP_BAR_RIGHT,
    DEFAULT_HP_BAR_TOP,
    DEFAULT_MP_BAR_BOTTOM,
    DEFAULT_MP_BAR_LEFT,
    DEFAULT_MP_BAR_RIGHT,
    DEFAULT_MP_BAR_TOP,
    GaugeRegion,
    PlayerVitalsConfig,
    PlayerVitalsReader,
)


def _make_hud_image(hp_fill: float, mp_fill: float, fp_fill: float) -> np.ndarray:
    """Create a synthetic 260x113 Flyff HUD image with specified fill percentages (0.0 - 1.0)."""

    img = np.zeros((113, 260, 3), dtype=np.uint8)

    # HP bar: x in [108..246], y in [30..36]
    hp_x1, hp_x2 = int(260 * DEFAULT_HP_BAR_LEFT), int(260 * DEFAULT_HP_BAR_RIGHT)
    hp_y1, hp_y2 = int(113 * DEFAULT_HP_BAR_TOP), int(113 * DEFAULT_HP_BAR_BOTTOM)
    hp_fill_x = hp_x1 + int((hp_x2 - hp_x1) * hp_fill)
    if hp_fill_x > hp_x1:
        # BGR: Red bar [143, 143, 240]
        img[hp_y1:hp_y2, hp_x1:hp_fill_x] = [143, 143, 240]

    # MP bar: x in [108..246], y in [47..53]
    mp_x1, mp_x2 = int(260 * DEFAULT_MP_BAR_LEFT), int(260 * DEFAULT_MP_BAR_RIGHT)
    mp_y1, mp_y2 = int(113 * DEFAULT_MP_BAR_TOP), int(113 * DEFAULT_MP_BAR_BOTTOM)
    mp_fill_x = mp_x1 + int((mp_x2 - mp_x1) * mp_fill)
    if mp_fill_x > mp_x1:
        # BGR: Blue bar [240, 143, 143]
        img[mp_y1:mp_y2, mp_x1:mp_fill_x] = [240, 143, 143]

    # FP bar: x in [108..246], y in [64..70]
    fp_x1, fp_x2 = int(260 * DEFAULT_FP_BAR_LEFT), int(260 * DEFAULT_FP_BAR_RIGHT)
    fp_y1, fp_y2 = int(113 * DEFAULT_FP_BAR_TOP), int(113 * DEFAULT_FP_BAR_BOTTOM)
    fp_fill_x = fp_x1 + int((fp_x2 - fp_x1) * fp_fill)
    if fp_fill_x > fp_x1:
        # BGR: Green bar [143, 240, 143]
        img[fp_y1:fp_y2, fp_x1:fp_fill_x] = [143, 240, 143]

    return img


def test_player_vitals_model_validation() -> None:
    vitals = PlayerVitals(hp_percentage=85.0, mp_percentage=50.0, fp_percentage=20.0)
    assert vitals.hp_percentage == 85.0
    assert vitals.mp_percentage == 50.0
    assert vitals.fp_percentage == 20.0

    with pytest.raises(ValueError, match="HP percentage"):
        PlayerVitals(hp_percentage=-1.0)
    with pytest.raises(ValueError, match="MP percentage"):
        PlayerVitals(mp_percentage=105.0)
    with pytest.raises(ValueError, match="FP percentage"):
        PlayerVitals(fp_percentage=-0.1)


def test_player_vitals_config_validation() -> None:
    config = PlayerVitalsConfig()
    assert config.min_channel_value == 130
    assert config.min_channel_diff == 25

    with pytest.raises(ValueError, match="HUD bounds"):
        PlayerVitalsConfig(hud_left=0.5, hud_right=0.2)
    with pytest.raises(ValueError, match="Minimum channel value"):
        PlayerVitalsConfig(min_channel_value=300)
    with pytest.raises(ValueError, match="GaugeRegion coordinates"):
        GaugeRegion(left=0.8, top=0.1, right=0.2, bottom=0.5)


def test_vitals_reader_full_gauges_synthetic() -> None:
    reader = PlayerVitalsReader()
    hud_pixels = _make_hud_image(hp_fill=1.0, mp_fill=1.0, fp_fill=1.0)
    frame = CapturedFrame(
        pixels=hud_pixels,
        client_size=ClientSize(260, 113),
        pixel_format=PixelFormat.BGR,
    )

    vitals = reader.read(frame)
    assert vitals.hp_percentage == 100.0
    assert vitals.mp_percentage == 100.0
    assert vitals.fp_percentage == 100.0


def test_vitals_reader_empty_gauges_synthetic() -> None:
    reader = PlayerVitalsReader()
    hud_pixels = _make_hud_image(hp_fill=0.0, mp_fill=0.0, fp_fill=0.0)
    frame = CapturedFrame(
        pixels=hud_pixels,
        client_size=ClientSize(260, 113),
        pixel_format=PixelFormat.BGR,
    )

    vitals = reader.read(frame)
    assert vitals.hp_percentage == 0.0
    assert vitals.mp_percentage == 0.0
    assert vitals.fp_percentage == 0.0


def test_vitals_reader_half_gauges_synthetic() -> None:
    reader = PlayerVitalsReader()
    hud_pixels = _make_hud_image(hp_fill=0.5, mp_fill=0.25, fp_fill=0.75)
    frame = CapturedFrame(
        pixels=hud_pixels,
        client_size=ClientSize(260, 113),
        pixel_format=PixelFormat.BGR,
    )

    vitals = reader.read(frame)
    assert 48.0 <= vitals.hp_percentage <= 52.0
    assert 23.0 <= vitals.mp_percentage <= 27.0
    assert 73.0 <= vitals.fp_percentage <= 77.0


def test_vitals_reader_with_text_occlusions() -> None:
    """Simulate black text digits drawn on top of the bars."""

    reader = PlayerVitalsReader()
    hud_pixels = _make_hud_image(hp_fill=0.8, mp_fill=0.6, fp_fill=0.4)

    # Draw black lines simulating numbers "1234/1234" in the middle of HP and MP bars
    hp_y1, hp_y2 = int(113 * DEFAULT_HP_BAR_TOP), int(113 * DEFAULT_HP_BAR_BOTTOM)
    hud_pixels[hp_y1:hp_y2, 130:135] = [0, 0, 0]
    hud_pixels[hp_y1:hp_y2, 150:155] = [255, 255, 255]

    frame = CapturedFrame(
        pixels=hud_pixels,
        client_size=ClientSize(260, 113),
        pixel_format=PixelFormat.BGR,
    )

    vitals = reader.read(frame)
    # The furthest colored pixel is still at 80%
    assert 78.0 <= vitals.hp_percentage <= 82.0


def test_vitals_reader_real_fixture() -> None:
    fixture_path = Path("data/player_vitals_left_top_corner.png")
    if not fixture_path.is_file():
        pytest.skip("Fixture image not found")

    image = cv2.imread(str(fixture_path), cv2.IMREAD_COLOR)
    assert image is not None

    reader = PlayerVitalsReader()
    frame = CapturedFrame(
        pixels=cast("np.ndarray", image),
        client_size=ClientSize(image.shape[1], image.shape[0]),
        pixel_format=PixelFormat.BGR,
    )

    vitals = reader.read(frame)
    assert vitals.hp_percentage == 100.0
    assert vitals.mp_percentage == 100.0
    assert 90.0 <= vitals.fp_percentage <= 95.0


def test_vitals_reader_rgb_format() -> None:
    reader = PlayerVitalsReader()
    bgr_pixels = _make_hud_image(hp_fill=1.0, mp_fill=0.5, fp_fill=0.0)
    rgb_pixels = cv2.cvtColor(bgr_pixels, cv2.COLOR_BGR2RGB)

    frame = CapturedFrame(
        pixels=cast("np.ndarray", rgb_pixels),
        client_size=ClientSize(260, 113),
        pixel_format=PixelFormat.RGB,
    )

    vitals = reader.read(frame)
    assert vitals.hp_percentage == 100.0
    assert 48.0 <= vitals.mp_percentage <= 52.0
    assert vitals.fp_percentage == 0.0


def test_vitals_reader_embedded_in_full_frame() -> None:
    """Test when the HUD is at the top-left of a 1024x768 frame."""

    full_frame_pixels = np.zeros((768, 1024, 3), dtype=np.uint8)
    hud_pixels = _make_hud_image(hp_fill=1.0, mp_fill=1.0, fp_fill=1.0)
    # Paste HUD into top-left
    full_frame_pixels[0:113, 0:260] = hud_pixels

    reader = PlayerVitalsReader(
        PlayerVitalsConfig(hud_left=0.0, hud_top=0.0, hud_right=260 / 1024, hud_bottom=113 / 768)
    )
    frame = CapturedFrame(
        pixels=full_frame_pixels,
        client_size=ClientSize(1024, 768),
        pixel_format=PixelFormat.BGR,
    )

    vitals = reader.read(frame)
    assert vitals.hp_percentage == 100.0
    assert vitals.mp_percentage == 100.0
    assert vitals.fp_percentage == 100.0
