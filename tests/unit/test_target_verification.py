"""Unit tests for target-bar extraction and verification."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from flyff_bot.features.vision import (
    CapturedFrame,
    ClientSize,
    TargetRegion,
    TargetStatus,
    TargetVerificationConfig,
    TargetVerifier,
    extract_target_region,
)

HP_BAR_COLOR = (0, 0, 220)
HEADER_ANCHOR_TEMPLATE = np.array(
    [[[1, 2, 3], [4, 5, 6]], [[7, 8, 9], [10, 11, 12]]], dtype=np.uint8
)
NAME_TEMPLATE = np.array(
    [[[255, 255, 255], [20, 40, 60]], [[60, 40, 20], [255, 255, 255]]], dtype=np.uint8
)
TARGET_REGION = TargetRegion(x=0.25, y=0.0, width=0.5, height=0.5)
REAL_FIXTURE_DIRECTORY = Path("data/eden/flame")
REAL_FIXTURE_CROP = (slice(20, 90), slice(520, 750))
REAL_ANCHOR_CROP = (slice(12, 38), slice(15, 45))
REAL_NAME_CROP = (slice(10, 40), slice(60, 175))
REAL_HP_REGION = TargetRegion(x=20 / 230, y=39 / 70, width=150 / 230, height=12 / 70)
REAL_NAME_REGION = TargetRegion(x=55 / 230, y=8 / 70, width=125 / 230, height=35 / 70)


def _frame(*, include_hp: bool, name_template: np.ndarray | None = NAME_TEMPLATE) -> CapturedFrame:
    pixels = np.zeros((20, 40, 3), dtype=np.uint8)
    region = pixels[0:10, 10:30]
    if include_hp:
        region[6:8, 2:12] = HP_BAR_COLOR
    if name_template is not None:
        region[2:4, 3:5] = name_template
    region[0:2, 0:2] = HEADER_ANCHOR_TEMPLATE
    return CapturedFrame(pixels, ClientSize(40, 20))


def _verifier() -> TargetVerifier:
    return TargetVerifier(
        {"Aibatt": NAME_TEMPLATE},
        HEADER_ANCHOR_TEMPLATE,
        TargetVerificationConfig(
            region=TARGET_REGION,
            hp_region=TargetRegion(x=0.0, y=0.6, width=1.0, height=0.4),
            name_region=TargetRegion(x=0.0, y=0.0, width=1.0, height=0.6),
            hp_color_lower_bound=(0, 0, 100),
            hp_color_upper_bound=(100, 100, 255),
            minimum_hp_pixel_count=10,
        ),
    )


def test_extract_target_region_uses_normalized_client_coordinates() -> None:
    extracted = extract_target_region(_frame(include_hp=True), TARGET_REGION)

    assert extracted.client_size == ClientSize(20, 10)
    assert extracted.pixels.flags.c_contiguous
    assert tuple(extracted.pixels[6, 2]) == HP_BAR_COLOR


def test_verifier_accepts_live_whitelisted_target_fixture() -> None:
    result = _verifier().verify(_frame(include_hp=True))

    assert result.status is TargetStatus.VALID_TARGET
    assert result.target_name == "Aibatt"
    assert result.is_alive
    assert result.hp_pixel_count == 20


def test_verifier_rejects_live_target_with_unrecognized_name_fixture() -> None:
    other_name = np.flip(NAME_TEMPLATE, axis=0).copy()

    result = _verifier().verify(_frame(include_hp=True, name_template=other_name))

    assert result.status is TargetStatus.WRONG_TARGET
    assert result.target_name is None
    assert result.is_alive


def test_verifier_reports_empty_target_bar_fixture_as_no_target() -> None:
    pixels = _frame(include_hp=False, name_template=None).pixels.copy()
    pixels[0:2, 10:12] = HP_BAR_COLOR
    pixels[0:2, 0:2] = 0
    result = _verifier().verify(CapturedFrame(pixels, ClientSize(40, 20)))

    assert result.status is TargetStatus.NO_TARGET
    assert result.target_name is None
    assert not result.is_alive


def test_verifier_rejects_depleted_hp_bar() -> None:
    pixels = _frame(include_hp=False).pixels.copy()
    pixels[6, 12:17] = HP_BAR_COLOR

    result = _verifier().verify(CapturedFrame(pixels, ClientSize(40, 20)))

    assert result.status is TargetStatus.WRONG_TARGET
    assert result.target_name is None
    assert result.hp_pixel_count == 5


def test_target_region_rejects_bounds_outside_frame() -> None:
    with pytest.raises(ValueError, match="inside the client frame"):
        TargetRegion(x=0.6, width=0.5)


def test_verifier_ignores_sky_colours_outside_the_dedicated_hp_region() -> None:
    pixels = _frame(include_hp=True).pixels.copy()
    pixels[0:5, 0:5] = HP_BAR_COLOR

    result = _verifier().verify(CapturedFrame(pixels, ClientSize(40, 20)))

    assert result.hp_pixel_count == 20


def test_verifier_rejects_real_sky_fixture_without_a_target() -> None:
    verifier = _real_verifier({"Flame": _real_name_template()})

    result = verifier.verify(_real_fixture("Screenshot 2026-08-15 203618.png"))

    assert result.status is TargetStatus.NO_TARGET
    assert result.target_name is None
    assert result.hp_pixel_count == 0


def test_verifier_accepts_real_flame_target_fixture_with_hp_percentage() -> None:
    verifier = _real_verifier({"Flame": _real_name_template()})

    result = verifier.verify(_real_fixture("Screenshot 2026-08-15 204002.png"))

    assert result.status is TargetStatus.VALID_TARGET
    assert result.target_name == "Flame"
    assert 0.0 < result.hp_percentage <= 100.0


def test_verifier_rejects_real_target_outside_the_active_whitelist() -> None:
    flame_name = _real_name_template()
    verifier = _real_verifier({"Aibatt": np.flip(flame_name, axis=1).copy()})

    result = verifier.verify(_real_fixture("Screenshot 2026-08-15 204002.png"))

    assert result.status is TargetStatus.WRONG_TARGET
    assert result.target_name is None


def _real_verifier(name_templates: dict[str, np.ndarray]) -> TargetVerifier:
    target = _real_fixture("Screenshot 2026-08-15 204002.png")
    return TargetVerifier(
        name_templates,
        target.pixels[REAL_ANCHOR_CROP].copy(),
        TargetVerificationConfig(
            region=TargetRegion(x=0.0, y=0.0, width=1.0, height=1.0),
            hp_region=REAL_HP_REGION,
            name_region=REAL_NAME_REGION,
            hp_color_lower_bound=(100, 100, 220),
            hp_color_upper_bound=(140, 180, 255),
            minimum_hp_pixel_count=10,
            name_match_threshold=0.95,
            anchor_match_threshold=0.95,
        ),
    )


def _real_name_template() -> np.ndarray:
    return _real_fixture("Screenshot 2026-08-15 204002.png").pixels[REAL_NAME_CROP].copy()


def _real_fixture(filename: str) -> CapturedFrame:
    pixels = cv2.imread(str(REAL_FIXTURE_DIRECTORY / filename))
    assert pixels is not None
    crop = cast(npt.NDArray[np.uint8], np.ascontiguousarray(pixels[REAL_FIXTURE_CROP]))
    return CapturedFrame(crop, ClientSize(crop.shape[1], crop.shape[0]))
