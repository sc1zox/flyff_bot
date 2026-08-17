"""Unit tests for monster-kills HUD OCR extraction and ROI resolution scaling."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from flyff_bot.features.vision.loot_ocr import LootOcrError, LootOcrErrorCode
from flyff_bot.features.vision.models import (
    CapturedFrame,
    ClientSize,
    MonsterStatsStatus,
)
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


class _FailingOcrRecognizer:
    """An OCR backend that reports one known engine failure code."""

    def __init__(self, code: LootOcrErrorCode) -> None:
        self._code = code

    def recognize(self, image: npt.NDArray[np.uint8]) -> tuple[str, ...]:
        raise LootOcrError(self._code)


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

    metrics = reader.read(_frame())

    assert metrics.parsed_count == 7
    assert metrics.status is MonsterStatsStatus.OK


def test_reader_parses_semicolon_and_case_insensitive_variants() -> None:
    reader = MonsterStatsReader(FixtureRecognizer(("monster kills; 128",)))

    assert reader.read(_frame()).parsed_count == 128


def test_reader_reports_no_match_with_the_raw_text_it_recognized() -> None:
    reader = MonsterStatsReader(FixtureRecognizer(("Level 42", "Deaths: 0")))

    metrics = reader.read(_frame())

    assert metrics.parsed_count is None
    assert metrics.status is MonsterStatsStatus.NO_MATCH
    assert metrics.raw_text == "Level 42 Deaths: 0"


def test_reader_reports_ocr_failure_without_raising() -> None:
    reader = MonsterStatsReader(_RaisingRecognizer())

    metrics = reader.read(_frame())

    assert metrics.parsed_count is None
    assert metrics.status is MonsterStatsStatus.OCR_FAILED


def test_reader_reports_a_missing_engine_distinctly_from_a_recognition_failure() -> None:
    """A missing Tesseract install is actionable; a failed recognition is not the same fault."""

    unavailable = MonsterStatsReader(
        _FailingOcrRecognizer(LootOcrErrorCode.ENGINE_UNAVAILABLE)
    ).read(_frame())
    failed = MonsterStatsReader(_FailingOcrRecognizer(LootOcrErrorCode.RECOGNITION_FAILED)).read(
        _frame()
    )

    assert unavailable.status is MonsterStatsStatus.ENGINE_UNAVAILABLE
    assert unavailable.parsed_count is None
    assert failed.status is MonsterStatsStatus.OCR_FAILED
    assert failed.parsed_count is None


def test_reader_reports_an_unavailable_region_for_a_frame_smaller_than_the_roi() -> None:
    reader = MonsterStatsReader(FixtureRecognizer(("Monster Kills: 1",)))

    metrics = reader.read(_frame(width=4, height=4))

    assert metrics.parsed_count is None
    assert metrics.status is MonsterStatsStatus.ROI_UNAVAILABLE


def test_reader_reports_the_measured_region_and_an_unconfigured_anchor() -> None:
    """Without a template the fixed region is read, so no anchor badge can be shown."""

    reader = MonsterStatsReader(FixtureRecognizer(("Monster Kills: 3",)))

    metrics = reader.read(_frame())

    assert not metrics.anchor_configured
    assert metrics.anchor_score == 0.0
    left, top, right, bottom = compute_monster_stats_roi(1600, 900)
    assert (metrics.roi_width, metrics.roi_height) == (right - left, bottom - top)


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


def test_config_rejects_out_of_range_anchor_threshold_or_text_region() -> None:
    with pytest.raises(ValueError):
        MonsterStatsConfig(anchor_match_threshold=1.5)
    with pytest.raises(ValueError):
        MonsterStatsConfig(anchor_match_threshold=-0.1)
    with pytest.raises(ValueError):
        MonsterStatsConfig(kills_text_width=0)
    with pytest.raises(ValueError):
        MonsterStatsConfig(kills_text_height=-1)


def test_reader_rejects_non_uint8_or_non_colour_anchor_template() -> None:
    grayscale_template: npt.NDArray[np.uint8] = np.zeros((10, 10), dtype=np.uint8)

    with pytest.raises(ValueError, match="header anchor template"):
        MonsterStatsReader(FixtureRecognizer(()), header_anchor_template=grayscale_template)


def _panel_with_anchor() -> tuple[np.ndarray, np.ndarray]:
    """A synthetic stats panel with a distinctive, textured header anchor block at (3, 4)."""

    panel = np.zeros((40, 150, 3), dtype=np.uint8)
    anchor = np.zeros((15, 47, 3), dtype=np.uint8)
    # A striped pattern (rather than a flat block) so TM_CCOEFF_NORMED cannot spuriously
    # score a perfect match against a uniform (e.g. all-black) background.
    anchor[:, ::2] = 200
    anchor[::3, :] = 90
    panel[4 : 4 + 15, 3 : 3 + 47] = anchor
    return panel, anchor


def test_reader_locates_relocated_window_via_anchor_template() -> None:
    """The window can be dragged anywhere on screen; the anchor must still find it."""

    panel, anchor = _panel_with_anchor()
    frame_pixels = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame_pixels[300 : 300 + panel.shape[0], 700 : 700 + panel.shape[1]] = panel
    frame = CapturedFrame(frame_pixels, ClientSize(1920, 1080))

    reader = MonsterStatsReader(
        FixtureRecognizer(("Monster Kills: 42",)), header_anchor_template=anchor
    )

    metrics = reader.read(frame)

    assert metrics.parsed_count == 42
    assert metrics.anchor_configured
    assert metrics.anchor_passed
    assert metrics.anchor_score >= metrics.anchor_threshold


def test_reader_reports_a_missing_anchor_with_its_measured_score() -> None:
    """A closed or absent stats window must not raise; its score is still diagnostic."""

    _panel, anchor = _panel_with_anchor()
    reader = MonsterStatsReader(
        FixtureRecognizer(("Monster Kills: 42",)), header_anchor_template=anchor
    )

    metrics = reader.read(_frame(width=1920, height=1080))

    assert metrics.parsed_count is None
    assert metrics.status is MonsterStatsStatus.ANCHOR_NOT_FOUND
    assert not metrics.anchor_passed
    assert metrics.anchor_threshold == MonsterStatsConfig().anchor_match_threshold


def test_reader_anchor_search_reports_a_missing_anchor_for_an_undersized_frame() -> None:
    _panel, anchor = _panel_with_anchor()
    reader = MonsterStatsReader(
        FixtureRecognizer(("Monster Kills: 42",)), header_anchor_template=anchor
    )

    assert reader.read(_frame(width=10, height=10)).status is MonsterStatsStatus.ANCHOR_NOT_FOUND


def test_reader_anchors_and_extracts_relative_to_real_panel_fixture() -> None:
    fixture_path = Path("data/monster_stats.png")
    if not fixture_path.is_file():
        pytest.skip("Fixture image not found")

    panel = cv2.imread(str(fixture_path))
    assert panel is not None
    anchor: npt.NDArray[np.uint8] = np.asarray(panel[4:19, 3:50], dtype=np.uint8)

    frame_pixels = np.zeros((900, 1600, 3), dtype=np.uint8)
    frame_pixels[100 : 100 + panel.shape[0], 500 : 500 + panel.shape[1]] = panel
    frame = CapturedFrame(frame_pixels, ClientSize(1600, 900))

    reader = MonsterStatsReader(
        FixtureRecognizer(("Monster Kills: 1",)), header_anchor_template=anchor
    )

    assert reader.read(frame).parsed_count == 1
