"""Unit tests for monster-kills HUD OCR extraction and ROI resolution scaling."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from flyff_bot.constants import DEFAULT_MONSTER_STATS_PANEL_PATH
from flyff_bot.features.vision.loot_ocr import (
    TESSERACT_LANGUAGE_ENGLISH,
    LootOcrError,
    LootOcrErrorCode,
    TesseractTextRecognizer,
    resolve_tesseract_executable,
)
from flyff_bot.features.vision.models import (
    CapturedFrame,
    ClientSize,
    MonsterStatsSource,
    MonsterStatsStatus,
)
from flyff_bot.features.vision.monster_stats import (
    HEADER_ANCHOR_TEMPLATE_BOTTOM,
    HEADER_ANCHOR_TEMPLATE_LEFT,
    HEADER_ANCHOR_TEMPLATE_RIGHT,
    HEADER_ANCHOR_TEMPLATE_TOP,
    MonsterStatsConfig,
    MonsterStatsReader,
    compute_monster_stats_roi,
    extract_hud_text_mask,
    load_header_anchor_template,
)

# The constant colour the client renders every stats-HUD glyph in, in BGR order.
HUD_TEXT_COLOUR = (255, 209, 249)

PANEL_FIXTURE_PATH = Path(DEFAULT_MONSTER_STATS_PANEL_PATH)
FULL_FRAME_FIXTURE_PATH = Path(
    "data/assets/fixtures/full_screen_view_with_monster_stats_1600_900_Res.png"
)
# The reference screenshot includes the window title bar above the client area.
FULL_FRAME_TITLE_BAR_HEIGHT = 31


class FixtureRecognizer:
    """Predictable OCR output used to keep reader tests engine-independent."""

    def __init__(self, lines: Iterable[str]) -> None:
        self._lines = tuple(lines)
        self.received: npt.NDArray[np.uint8] | None = None

    def recognize(self, image: npt.NDArray[np.uint8]) -> tuple[str, ...]:
        self.received = image
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


def _read_bgr(path: Path) -> npt.NDArray[np.uint8]:
    """Load a fixture screenshot as the uint8 BGR array the vision code expects."""

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None
    return np.asarray(image, dtype=np.uint8)


def _reference_client_frame() -> CapturedFrame:
    """The reference screenshot with its window title bar removed, as a client frame."""

    client = np.ascontiguousarray(_read_bgr(FULL_FRAME_FIXTURE_PATH)[FULL_FRAME_TITLE_BAR_HEIGHT:])
    return CapturedFrame(client, ClientSize(client.shape[1], client.shape[0]))


def _english_ocr_available() -> bool:
    """Report whether a Tesseract install with English training data can be invoked."""

    if shutil.which("tesseract") is None:
        return False
    listing = subprocess.run(
        [resolve_tesseract_executable(), "--list-langs"],
        capture_output=True,
        text=True,
        check=False,
    )
    return TESSERACT_LANGUAGE_ENGLISH in listing.stdout.split()


def test_roi_remains_fixed_docked_pixel_region_across_resolutions() -> None:
    for width, height in ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440)):
        left, top, right, bottom = compute_monster_stats_roi(width, height)
        assert (left, top, right, bottom) == (260, 0, 410, 120)


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
    assert metrics.source is MonsterStatsSource.FIXED_REGION
    left, top, right, bottom = compute_monster_stats_roi(1600, 900)
    assert (metrics.roi_width, metrics.roi_height) == (right - left, bottom - top)


def test_config_rejects_inverted_roi_bounds() -> None:
    with pytest.raises(ValueError):
        MonsterStatsConfig(roi_left=500, roi_right=200)
    with pytest.raises(ValueError):
        MonsterStatsConfig(roi_top=500, roi_bottom=200)
    with pytest.raises(ValueError):
        MonsterStatsConfig(roi_left=-10)


def test_config_rejects_out_of_range_anchor_threshold_or_negative_inset() -> None:
    with pytest.raises(ValueError):
        MonsterStatsConfig(anchor_match_threshold=1.5)
    with pytest.raises(ValueError):
        MonsterStatsConfig(anchor_match_threshold=-0.1)
    with pytest.raises(ValueError):
        MonsterStatsConfig(anchor_inset_x=-1)
    with pytest.raises(ValueError):
        MonsterStatsConfig(anchor_inset_y=-1)


def test_reader_rejects_non_uint8_or_non_colour_anchor_template() -> None:
    grayscale_template: npt.NDArray[np.uint8] = np.zeros((10, 10), dtype=np.uint8)

    with pytest.raises(ValueError, match="header anchor template"):
        MonsterStatsReader(FixtureRecognizer(()), header_anchor_template=grayscale_template)


def _hud_panel(background: tuple[int, int, int]) -> npt.NDArray[np.uint8]:
    """A synthetic stats window: HUD-coloured glyph strokes over an arbitrary background."""

    panel: npt.NDArray[np.uint8] = np.full((40, 150, 3), background, dtype=np.uint8)
    # A striped glyph pattern (rather than a flat block) so TM_CCOEFF_NORMED cannot
    # spuriously score a perfect match against a uniform region.
    panel[HEADER_ANCHOR_TEMPLATE_TOP:HEADER_ANCHOR_TEMPLATE_BOTTOM:3, 3:50] = HUD_TEXT_COLOUR
    panel[HEADER_ANCHOR_TEMPLATE_TOP:HEADER_ANCHOR_TEMPLATE_BOTTOM, 3:50:2] = HUD_TEXT_COLOUR
    return panel


def test_hud_text_mask_isolates_the_same_glyphs_over_different_backgrounds() -> None:
    """The panel is transparent, so only a colour key survives a changing game world."""

    over_dark = extract_hud_text_mask(_hud_panel((10, 20, 15)))
    over_bright = extract_hud_text_mask(_hud_panel((250, 250, 250)))
    over_orange = extract_hud_text_mask(_hud_panel((30, 120, 240)))

    assert over_dark.any()
    assert np.array_equal(over_dark, over_bright)
    assert np.array_equal(over_dark, over_orange)


def test_hud_text_mask_isolates_real_hud_text_over_two_different_backgrounds() -> None:
    """Both shipped screenshots show the same window over unrelated scenery."""

    if not PANEL_FIXTURE_PATH.is_file() or not FULL_FRAME_FIXTURE_PATH.is_file():
        pytest.skip("Fixture image not found")

    frame = _reference_client_frame()
    left, top, right, bottom = compute_monster_stats_roi(
        frame.client_size.width, frame.client_size.height
    )

    panel_mask = extract_hud_text_mask(_read_bgr(PANEL_FIXTURE_PATH))
    region_mask = extract_hud_text_mask(frame.pixels[top:bottom, left:right])

    # Only glyphs may key; a background leaking in would fill a large part of the region.
    for mask in (panel_mask, region_mask):
        keyed_ratio = float(np.count_nonzero(mask)) / mask.size
        assert 0.02 < keyed_ratio < 0.20


def test_reader_locates_relocated_window_via_anchor_template() -> None:
    """The window can be dragged anywhere on screen; the anchor must still find it."""

    panel = _hud_panel((10, 20, 15))
    anchor = np.ascontiguousarray(
        panel[
            HEADER_ANCHOR_TEMPLATE_TOP:HEADER_ANCHOR_TEMPLATE_BOTTOM,
            HEADER_ANCHOR_TEMPLATE_LEFT:HEADER_ANCHOR_TEMPLATE_RIGHT,
        ]
    )
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
    assert metrics.source is MonsterStatsSource.ANCHORED


def test_reader_matches_an_anchor_captured_over_a_different_background() -> None:
    """Matching runs on glyph masks, so the template's own scenery must not matter."""

    template_panel = _hud_panel((10, 20, 15))
    anchor = np.ascontiguousarray(
        template_panel[
            HEADER_ANCHOR_TEMPLATE_TOP:HEADER_ANCHOR_TEMPLATE_BOTTOM,
            HEADER_ANCHOR_TEMPLATE_LEFT:HEADER_ANCHOR_TEMPLATE_RIGHT,
        ]
    )
    live_panel = _hud_panel((250, 250, 250))
    frame_pixels = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame_pixels[300 : 300 + live_panel.shape[0], 700 : 700 + live_panel.shape[1]] = live_panel
    frame = CapturedFrame(frame_pixels, ClientSize(1920, 1080))

    metrics = MonsterStatsReader(
        FixtureRecognizer(("Monster Kills: 9",)), header_anchor_template=anchor
    ).read(frame)

    assert metrics.anchor_passed
    assert metrics.source is MonsterStatsSource.ANCHORED
    assert metrics.parsed_count == 9


def test_reader_falls_back_to_the_fixed_region_when_the_anchor_is_missed() -> None:
    """A closed stats window must not stop the reading; the source names the crop used."""

    panel = _hud_panel((10, 20, 15))
    anchor = np.ascontiguousarray(
        panel[
            HEADER_ANCHOR_TEMPLATE_TOP:HEADER_ANCHOR_TEMPLATE_BOTTOM,
            HEADER_ANCHOR_TEMPLATE_LEFT:HEADER_ANCHOR_TEMPLATE_RIGHT,
        ]
    )
    reader = MonsterStatsReader(
        FixtureRecognizer(("Monster Kills: 42",)), header_anchor_template=anchor
    )

    metrics = reader.read(_frame(width=1920, height=1080))

    assert not metrics.anchor_passed
    assert metrics.anchor_configured
    assert metrics.source is MonsterStatsSource.FIXED_REGION
    assert metrics.anchor_threshold == MonsterStatsConfig().anchor_match_threshold


def test_reader_falls_back_to_the_fixed_region_for_a_frame_smaller_than_the_anchor() -> None:
    panel = _hud_panel((10, 20, 15))
    anchor = np.ascontiguousarray(
        panel[
            HEADER_ANCHOR_TEMPLATE_TOP:HEADER_ANCHOR_TEMPLATE_BOTTOM,
            HEADER_ANCHOR_TEMPLATE_LEFT:HEADER_ANCHOR_TEMPLATE_RIGHT,
        ]
    )
    reader = MonsterStatsReader(
        FixtureRecognizer(("Monster Kills: 42",)), header_anchor_template=anchor
    )

    metrics = reader.read(_frame(width=10, height=10))

    assert metrics.source is MonsterStatsSource.FIXED_REGION
    assert metrics.status is MonsterStatsStatus.ROI_UNAVAILABLE


def test_header_anchor_template_loads_from_the_shipped_panel_screenshot() -> None:
    if not PANEL_FIXTURE_PATH.is_file():
        pytest.skip("Fixture image not found")

    template = load_header_anchor_template(PANEL_FIXTURE_PATH)

    assert template is not None
    assert template.shape == (
        HEADER_ANCHOR_TEMPLATE_BOTTOM - HEADER_ANCHOR_TEMPLATE_TOP,
        HEADER_ANCHOR_TEMPLATE_RIGHT - HEADER_ANCHOR_TEMPLATE_LEFT,
        3,
    )
    assert extract_hud_text_mask(template).any()


def test_header_anchor_template_returns_none_for_a_missing_file(tmp_path: Path) -> None:
    """A missing asset must degrade to the fixed region instead of failing startup."""

    assert load_header_anchor_template(tmp_path / "absent.png") is None


def test_shipped_anchor_locates_the_stats_window_in_the_reference_screenshot() -> None:
    """The shipped template and the live frame come from different scenes and sessions."""

    if not PANEL_FIXTURE_PATH.is_file() or not FULL_FRAME_FIXTURE_PATH.is_file():
        pytest.skip("Fixture image not found")

    template = load_header_anchor_template(PANEL_FIXTURE_PATH)
    assert template is not None
    frame = _reference_client_frame()

    recognizer = FixtureRecognizer(("Monster Kills: 13",))
    metrics = MonsterStatsReader(recognizer, header_anchor_template=template).read(frame)

    assert metrics.anchor_passed
    assert metrics.source is MonsterStatsSource.ANCHORED
    assert metrics.parsed_count == 13
    # The anchored crop must resolve to the documented fixed placement for this frame.
    left, top, right, bottom = compute_monster_stats_roi(
        frame.client_size.width, frame.client_size.height
    )
    assert (metrics.roi_width, metrics.roi_height) == (right - left, bottom - top)


def test_real_ocr_reads_the_kill_count_from_the_reference_screenshot() -> None:
    """End-to-end proof that the preprocessing survives a real game background."""

    if not PANEL_FIXTURE_PATH.is_file() or not FULL_FRAME_FIXTURE_PATH.is_file():
        pytest.skip("Fixture image not found")
    if not _english_ocr_available():
        pytest.skip("Tesseract with English training data is not installed")

    template = load_header_anchor_template(PANEL_FIXTURE_PATH)
    assert template is not None
    frame = _reference_client_frame()

    reader = MonsterStatsReader(
        TesseractTextRecognizer(language=TESSERACT_LANGUAGE_ENGLISH),
        header_anchor_template=template,
    )

    metrics = reader.read(frame)

    assert metrics.status is MonsterStatsStatus.OK
    assert metrics.parsed_count == 13
