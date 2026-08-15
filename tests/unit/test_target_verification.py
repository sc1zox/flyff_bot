"""Unit tests for target-bar extraction and verification."""

from __future__ import annotations

import numpy as np
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
NAME_TEMPLATE = np.array(
    [[[255, 255, 255], [20, 40, 60]], [[60, 40, 20], [255, 255, 255]]], dtype=np.uint8
)
TARGET_REGION = TargetRegion(x=0.25, y=0.0, width=0.5, height=0.5)


def _frame(*, include_hp: bool, name_template: np.ndarray | None = NAME_TEMPLATE) -> CapturedFrame:
    pixels = np.zeros((20, 40, 3), dtype=np.uint8)
    region = pixels[0:10, 10:30]
    if include_hp:
        region[6:8, 2:12] = HP_BAR_COLOR
    if name_template is not None:
        region[2:4, 3:5] = name_template
    return CapturedFrame(pixels, ClientSize(40, 20))


def _verifier() -> TargetVerifier:
    return TargetVerifier(
        {"Aibatt": NAME_TEMPLATE},
        TargetVerificationConfig(region=TARGET_REGION, minimum_hp_pixel_count=10),
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
    result = _verifier().verify(_frame(include_hp=False, name_template=None))

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
