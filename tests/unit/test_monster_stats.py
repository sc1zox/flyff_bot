"""Unit tests for monster-kills HUD OCR extraction and ROI resolution scaling."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import numpy.typing as npt
import pytest

from flyff_bot.features.vision.models import CapturedFrame, ClientSize
from flyff_bot.features.vision.monster_stats import (
    MonsterStatsConfig,
    MonsterStatsReader,
    compute_monster_stats_roi,
)


class FixtureRecognizer:
    """Predictable OCR output used to keep reader tests engine-independent."""

    def __init__(self, lines: Iterable[str]) -> None:
        self._lines = tuple(lines)

    def recognize(self, image: npt.NDArray[np.uint8]) -> tuple[str, ...]:
        return self._lines


class _RaisingRecognizer:
    """An OCR backend that always fails, exercising the non-fatal error path."""

    def recognize(self, image: npt.NDArray[np.uint8]) -> tuple[str, ...]:
        raise RuntimeError("ocr backend unavailable")


def _frame(width: int = 1600, height: int = 900) -> CapturedFrame:
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    return CapturedFrame(pixels, ClientSize(width, height))


def test_roi_scales_proportionally_across_client_resolutions() -> None:
    reference = compute_monster_stats_roi(1600, 900)
    scaled = compute_monster_stats_roi(3200, 1800)

    # Integer pixel truncation means doubling is only exact within a one-pixel tolerance.
    for reference_value, scaled_value in zip(reference, scaled, strict=True):
        assert abs(scaled_value - reference_value * 2) <= 1


@pytest.mark.parametrize("width,height", [(800, 600), (2560, 1080), (1280, 720), (1600, 900)])
def test_roi_stays_within_frame_bounds_across_resolutions(width: int, height: int) -> None:
    left, top, right, bottom = compute_monster_stats_roi(width, height)

    assert 0 <= left < right <= width
    assert 0 <= top < bottom <= height


def test_reader_extracts_kill_count_from_matching_line() -> None:
    reader = MonsterStatsReader(FixtureRecognizer(("Level 42", "Monster Kills: 7", "Deaths: 0")))

    assert reader.read(_frame()) == 7


def test_reader_parses_semicolon_and_case_insensitive_variants() -> None:
    reader = MonsterStatsReader(FixtureRecognizer(("monster kills; 128",)))

    assert reader.read(_frame()) == 128


def test_reader_returns_none_when_no_matching_line_present() -> None:
    reader = MonsterStatsReader(FixtureRecognizer(("Level 42", "Deaths: 0")))

    assert reader.read(_frame()) is None


def test_reader_returns_none_on_ocr_failure() -> None:
    reader = MonsterStatsReader(_RaisingRecognizer())

    assert reader.read(_frame()) is None


def test_reader_returns_none_for_a_frame_too_small_for_the_configured_roi() -> None:
    reader = MonsterStatsReader(FixtureRecognizer(("Monster Kills: 1",)))

    assert reader.read(_frame(width=4, height=4)) is None


def test_config_rejects_inverted_roi_bounds() -> None:
    with pytest.raises(ValueError):
        MonsterStatsConfig(roi_left=0.5, roi_right=0.2)
    with pytest.raises(ValueError):
        MonsterStatsConfig(roi_top=0.5, roi_bottom=0.2)


def test_config_rejects_even_or_undersized_threshold_block_size() -> None:
    with pytest.raises(ValueError):
        MonsterStatsConfig(threshold_block_size=4)
    with pytest.raises(ValueError):
        MonsterStatsConfig(threshold_block_size=1)
