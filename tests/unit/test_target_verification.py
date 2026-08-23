"""Unit tests for target-bar extraction and verification."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from flyff_bot.constants import DEFAULT_TARGET_ANCHOR_PATH
from flyff_bot.features.vision import (
    AnchorOffsetRegion,
    CapturedFrame,
    ClientSize,
    OcrError,
    OcrErrorCode,
    TargetNameStatus,
    TargetRegion,
    TargetStatus,
    TargetVerificationConfig,
    TargetVerifier,
    TesseractTextRecognizer,
    extract_anchor_relative_region,
    extract_target_region,
    load_mob_anchor_templates,
    match_whitelisted_name,
    preprocess_target_name_region,
    resolve_mob_anchor_path,
)
from flyff_bot.features.vision.target_verification import (
    DEFAULT_ANCHOR_MATCH_THRESHOLD,
    DEFAULT_TARGET_REGION_HEIGHT,
    DEFAULT_TARGET_REGION_WIDTH,
    DEFAULT_TARGET_REGION_X,
    DEFAULT_TARGET_REGION_Y,
    compute_target_header_bounds,
)

HP_BAR_COLOR = (0, 0, 220)
NAME_TEXT_COLOR = (160, 255, 255)
HEADER_ANCHOR_TEMPLATE = np.array(
    [[[1, 2, 3], [4, 5, 6]], [[7, 8, 9], [10, 11, 12]]], dtype=np.uint8
)
WEAK_ANCHOR_PIXEL = (30, 31, 32)
TARGET_REGION = TargetRegion(x=0.25, y=0.0, width=0.5, height=0.5)
HP_OFFSET = AnchorOffsetRegion(dx=2, dy=6, width=10, height=2)
NAME_OFFSET = AnchorOffsetRegion(dx=3, dy=2, width=2, height=2)
WHITELISTED_NAMEPLATE = "Flame <Lvl 175>"
FOREIGN_NAMEPLATE = "MiniMushu <Lvl 12>"
REAL_FIXTURE_DIRECTORY = Path("data/assets/mobs/eden/flame")
# BUG-011 reproduction: the header anchor matches on both captures, but the shipped
# `models/target_flame.png` scored ~0.25 against the 2559x1439 nameplate because the
# arbitrary world scenery behind the glyphs dominates the correlation.
REAL_FLAME_FIXTURES = (
    "Screenshot 2026-08-15 204002.png",
    "Screenshot 2026-08-16 231337.png",
)
REAL_FOREIGN_FIXTURE = "Screenshot 2026-08-16 231312.png"
REAL_EMPTY_FIXTURE = "Screenshot 2026-08-15 203618.png"


def _tesseract_is_usable() -> bool:
    """Report whether a Tesseract install can actually recognize the configured languages.

    Locating the binary is not enough: an install without the English and German language
    data exits non-zero, which would fail the fixture tests instead of skipping. A binary
    that cannot be located at all surfaces here as `ENGINE_UNAVAILABLE`.
    """

    try:
        TesseractTextRecognizer().recognize(np.full((32, 64), 255, dtype=np.uint8))
    except OcrError as error:
        return error.code is not OcrErrorCode.ENGINE_UNAVAILABLE
    return True


TESSERACT_IS_USABLE = _tesseract_is_usable()


class _FakeRecognizer:
    """A deterministic OCR stand-in that counts how often it was invoked."""

    def __init__(
        self, lines: Sequence[str] = (WHITELISTED_NAMEPLATE,), error: Exception | None = None
    ) -> None:
        self.lines = tuple(lines)
        self.error = error
        self.calls = 0

    def recognize(self, image: npt.NDArray[np.uint8]) -> Iterable[str]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.lines


def _frame(
    *,
    include_hp: bool,
    include_name: bool = True,
    header_left: int = 0,
    header_top: int = 0,
) -> CapturedFrame:
    """Draw a synthetic target header at an arbitrary place inside the target region."""

    pixels = np.zeros((20, 40, 3), dtype=np.uint8)
    region = pixels[0:10, 10:30]
    if include_hp:
        region[header_top + 6 : header_top + 8, header_left + 2 : header_left + 12] = HP_BAR_COLOR
    if include_name:
        region[header_top + 2 : header_top + 4, header_left + 3 : header_left + 5] = NAME_TEXT_COLOR
    region[header_top : header_top + 2, header_left : header_left + 2] = HEADER_ANCHOR_TEMPLATE
    return CapturedFrame(pixels, ClientSize(40, 20))


def _verifier(
    recognizer: _FakeRecognizer | None = None,
    anchor_match_threshold: float = DEFAULT_ANCHOR_MATCH_THRESHOLD,
) -> tuple[TargetVerifier, _FakeRecognizer]:
    engine = recognizer or _FakeRecognizer()
    config = TargetVerificationConfig(
        region=TARGET_REGION,
        hp_offset=HP_OFFSET,
        name_offset=NAME_OFFSET,
        hp_color_lower_bound=(0, 0, 100),
        hp_color_upper_bound=(100, 100, 255),
        minimum_hp_pixel_count=10,
        anchor_match_threshold=anchor_match_threshold,
    )
    return TargetVerifier(("Flame",), HEADER_ANCHOR_TEMPLATE, engine, config), engine


def test_extract_target_region_uses_normalized_client_coordinates() -> None:
    extracted = extract_target_region(_frame(include_hp=True), TARGET_REGION)

    assert extracted.client_size == ClientSize(20, 10)
    assert extracted.pixels.flags.c_contiguous
    assert tuple(extracted.pixels[6, 2]) == HP_BAR_COLOR


def test_extract_anchor_relative_region_clips_to_the_frame_bounds() -> None:
    pixels = np.arange(6 * 8 * 3, dtype=np.uint8).reshape((6, 8, 3))

    clipped = extract_anchor_relative_region(
        pixels, 1, 1, AnchorOffsetRegion(dx=-3, dy=-3, width=6, height=6)
    )

    assert clipped.shape == (4, 4, 3)
    assert np.array_equal(clipped, pixels[0:4, 0:4])


def test_extract_anchor_relative_region_returns_empty_pixels_outside_the_frame() -> None:
    pixels = np.zeros((4, 4, 3), dtype=np.uint8)

    outside = extract_anchor_relative_region(
        pixels, 3, 3, AnchorOffsetRegion(dx=5, dy=5, width=2, height=2)
    )

    assert outside.size == 0


def test_anchor_offset_region_rejects_empty_dimensions() -> None:
    with pytest.raises(ValueError, match="dimensions must be positive"):
        AnchorOffsetRegion(dx=0, dy=0, width=0, height=4)


def test_default_anchor_threshold_is_a_robust_baseline() -> None:
    assert TargetVerificationConfig().anchor_match_threshold == DEFAULT_ANCHOR_MATCH_THRESHOLD
    assert DEFAULT_ANCHOR_MATCH_THRESHOLD == 0.75


def test_preprocess_target_name_region_keeps_glyphs_and_drops_the_background() -> None:
    pixels = np.zeros((4, 6, 3), dtype=np.uint8)
    pixels[:, :] = (40, 130, 90)
    pixels[1:3, 2:4] = NAME_TEXT_COLOR

    processed = preprocess_target_name_region(pixels, TargetVerificationConfig(name_ocr_upscale=1))

    assert processed.shape == (4, 6)
    assert np.array_equal(processed == 0, np.array(pixels == NAME_TEXT_COLOR).all(axis=2))


def test_preprocess_target_name_region_upscales_for_small_nameplate_glyphs() -> None:
    pixels = np.zeros((4, 6, 3), dtype=np.uint8)

    processed = preprocess_target_name_region(pixels, TargetVerificationConfig(name_ocr_upscale=3))

    assert processed.shape == (12, 18)


def test_preprocess_target_name_region_tolerates_an_empty_crop() -> None:
    empty = np.empty((0, 0, 3), dtype=np.uint8)

    assert preprocess_target_name_region(empty, TargetVerificationConfig()).size == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (WHITELISTED_NAMEPLATE, "Flame"),
        ("  flame   <lvl 175>  ", "Flame"),
        (FOREIGN_NAMEPLATE, None),
        ("", None),
    ],
)
def test_match_whitelisted_name_ignores_case_and_the_level_suffix(
    text: str, expected: str | None
) -> None:
    assert match_whitelisted_name(text, ("Flame",)) == expected


def test_verifier_accepts_a_whitelisted_nameplate_reading() -> None:
    verifier, recognizer = _verifier()

    result = verifier.verify(_frame(include_hp=True))

    assert result.status is TargetStatus.VALID_TARGET
    assert result.target_name == "Flame"
    assert result.is_alive
    assert result.hp_pixel_count == 20
    assert result.hp_percentage == pytest.approx(100.0)
    assert result.metrics.anchor_passed
    assert result.metrics.hp_passed
    assert result.metrics.name_passed
    assert result.metrics.name_status is TargetNameStatus.MATCHED
    assert result.metrics.name_candidate == "Flame"
    assert result.metrics.name_text == WHITELISTED_NAMEPLATE
    assert recognizer.calls == 1


def test_verifier_reuses_the_reading_while_the_nameplate_is_unchanged() -> None:
    """One OCR subprocess per target, not one per 100 ms tick on the Qt GUI thread."""

    verifier, recognizer = _verifier()
    frame = _frame(include_hp=True)

    first = verifier.verify(frame)
    repeated = verifier.verify(frame)

    assert recognizer.calls == 1
    assert repeated.status is first.status is TargetStatus.VALID_TARGET
    assert repeated.metrics.name_text == first.metrics.name_text


def test_verifier_re_reads_the_nameplate_once_it_changes() -> None:
    verifier, recognizer = _verifier(_FakeRecognizer((WHITELISTED_NAMEPLATE,)))
    changed = _frame(include_hp=True).pixels.copy()
    changed[2, 13] = (0, 0, 0)  # Erase one nameplate glyph pixel inside the name crop.

    verifier.verify(_frame(include_hp=True))
    recognizer.lines = (FOREIGN_NAMEPLATE,)
    result = verifier.verify(CapturedFrame(changed, ClientSize(40, 20)))

    assert recognizer.calls == 2
    assert result.status is TargetStatus.WRONG_TARGET
    assert result.metrics.name_text == FOREIGN_NAMEPLATE


def test_verifier_retries_ocr_after_a_failed_recognition() -> None:
    """A recoverable engine problem must not be latched by the nameplate cache."""

    recognizer = _FakeRecognizer(error=OcrError(OcrErrorCode.ENGINE_UNAVAILABLE))
    verifier, _ = _verifier(recognizer)
    frame = _frame(include_hp=True)

    verifier.verify(frame)
    recognizer.error = None
    recovered = verifier.verify(frame)

    assert recognizer.calls == 2
    assert recovered.status is TargetStatus.VALID_TARGET


def test_verifier_reports_the_canonical_whitelist_entry_rather_than_the_raw_reading() -> None:
    verifier, _ = _verifier(_FakeRecognizer(("fLaMe  <Lvl 3>",)))

    result = verifier.verify(_frame(include_hp=True))

    assert result.target_name == "Flame"
    assert result.metrics.name_candidate == "Flame"
    assert result.metrics.name_text == "fLaMe  <Lvl 3>"


def test_verifier_follows_the_header_anchor_when_it_moves_inside_the_region() -> None:
    verifier, _ = _verifier()

    anchored = verifier.verify(_frame(include_hp=True))
    shifted = verifier.verify(_frame(include_hp=True, header_left=6, header_top=2))

    assert shifted.status is anchored.status is TargetStatus.VALID_TARGET
    assert shifted.hp_pixel_count == anchored.hp_pixel_count
    assert shifted.hp_percentage == pytest.approx(anchored.hp_percentage)
    assert shifted.metrics.name_candidate == anchored.metrics.name_candidate


def test_verifier_rejects_a_target_outside_the_configured_whitelist() -> None:
    verifier, _ = _verifier(_FakeRecognizer((FOREIGN_NAMEPLATE,)))

    result = verifier.verify(_frame(include_hp=True))

    assert result.status is TargetStatus.WRONG_TARGET
    assert result.target_name is None
    assert result.is_alive
    assert result.metrics.anchor_passed
    assert result.metrics.hp_passed
    assert not result.metrics.name_passed
    assert result.metrics.name_status is TargetNameStatus.NO_MATCH
    assert result.metrics.name_candidate is None
    assert result.metrics.name_text == FOREIGN_NAMEPLATE


def test_verifier_reports_an_empty_reading_as_unreadable() -> None:
    verifier, _ = _verifier(_FakeRecognizer(("", "   ")))

    result = verifier.verify(_frame(include_hp=True))

    assert result.status is TargetStatus.WRONG_TARGET
    assert result.metrics.name_status is TargetNameStatus.UNREADABLE
    assert result.metrics.name_text == ""


def test_verifier_separates_a_missing_ocr_engine_from_a_failed_reading() -> None:
    unavailable, _ = _verifier(_FakeRecognizer(error=OcrError(OcrErrorCode.ENGINE_UNAVAILABLE)))
    failed, _ = _verifier(_FakeRecognizer(error=OcrError(OcrErrorCode.RECOGNITION_FAILED)))

    unavailable_result = unavailable.verify(_frame(include_hp=True))
    failed_result = failed.verify(_frame(include_hp=True))

    assert unavailable_result.metrics.name_status is TargetNameStatus.ENGINE_UNAVAILABLE
    assert failed_result.metrics.name_status is TargetNameStatus.OCR_FAILED
    assert unavailable_result.status is failed_result.status is TargetStatus.WRONG_TARGET


def test_verifier_reports_empty_target_bar_fixture_as_no_target() -> None:
    verifier, recognizer = _verifier()
    pixels = _frame(include_hp=False, include_name=False).pixels.copy()
    pixels[0:2, 10:12] = HP_BAR_COLOR

    result = verifier.verify(CapturedFrame(pixels, ClientSize(40, 20)))

    assert result.status is TargetStatus.NO_TARGET
    assert result.target_name is None
    assert not result.is_alive
    assert result.hp_percentage == 0.0
    assert not result.metrics.anchor_passed
    assert result.metrics.anchor_score < result.metrics.anchor_threshold
    assert result.metrics.anchor_threshold == DEFAULT_ANCHOR_MATCH_THRESHOLD
    assert not result.metrics.hp_passed
    assert not result.metrics.name_passed
    assert recognizer.calls == 0


def test_verifier_skips_the_ocr_subprocess_when_the_anchor_fails() -> None:
    verifier, recognizer = _verifier(anchor_match_threshold=0.95)
    pixels = _frame(include_hp=True).pixels.copy()
    pixels[1, 11] = WEAK_ANCHOR_PIXEL

    result = verifier.verify(CapturedFrame(pixels, ClientSize(40, 20)))

    assert recognizer.calls == 0
    assert result.metrics.name_status is TargetNameStatus.NOT_EVALUATED
    assert result.metrics.name_text == ""
    assert result.metrics.name_candidate is None


def test_verifier_measures_hp_metrics_even_when_the_anchor_fails() -> None:
    verifier, _ = _verifier(anchor_match_threshold=0.95)
    pixels = _frame(include_hp=True).pixels.copy()
    pixels[1, 11] = WEAK_ANCHOR_PIXEL

    result = verifier.verify(CapturedFrame(pixels, ClientSize(40, 20)))

    assert result.status is TargetStatus.NO_TARGET
    assert not result.metrics.anchor_passed
    assert result.hp_pixel_count == 0
    assert result.hp_percentage == 0.0
    assert result.metrics.hp_pixel_count == 20
    assert result.metrics.hp_percentage == pytest.approx(100.0)
    assert result.metrics.hp_passed


def test_verifier_measures_the_name_reading_even_when_the_hp_bar_is_depleted() -> None:
    verifier, _ = _verifier()
    pixels = _frame(include_hp=False).pixels.copy()
    pixels[6, 12:17] = HP_BAR_COLOR

    result = verifier.verify(CapturedFrame(pixels, ClientSize(40, 20)))

    assert result.status is TargetStatus.WRONG_TARGET
    assert result.target_name is None
    assert result.hp_pixel_count == 5
    assert result.hp_percentage == pytest.approx(50.0)
    assert result.metrics.anchor_passed
    assert not result.metrics.hp_passed
    assert result.metrics.minimum_hp_pixel_count == 10
    assert result.metrics.name_passed
    assert result.metrics.name_candidate == "Flame"


def test_update_anchor_threshold_applies_to_the_next_verification() -> None:
    verifier, _ = _verifier(anchor_match_threshold=0.95)
    pixels = _frame(include_hp=True).pixels.copy()
    pixels[1, 11] = WEAK_ANCHOR_PIXEL
    frame = CapturedFrame(pixels, ClientSize(40, 20))
    rejected = verifier.verify(frame)

    verifier.update_anchor_threshold(0.7)
    accepted = verifier.verify(frame)

    assert rejected.status is TargetStatus.NO_TARGET
    assert accepted.status is TargetStatus.VALID_TARGET
    assert accepted.target_name == "Flame"
    assert verifier.config.anchor_match_threshold == pytest.approx(0.7)
    assert accepted.metrics.anchor_threshold == pytest.approx(0.7)


def test_update_anchor_threshold_rejects_scores_outside_the_supported_range() -> None:
    verifier, _ = _verifier()

    with pytest.raises(ValueError, match="between zero and one"):
        verifier.update_anchor_threshold(1.5)


def test_verifier_requires_at_least_one_whitelisted_name() -> None:
    with pytest.raises(ValueError, match="At least one non-empty target name"):
        TargetVerifier((" ",), HEADER_ANCHOR_TEMPLATE, _FakeRecognizer())


def test_target_region_rejects_bounds_outside_frame() -> None:
    with pytest.raises(ValueError, match="inside the client frame"):
        TargetRegion(x=0.6, width=0.5)


def test_default_target_region_bounds_and_computation() -> None:
    region = TargetRegion()
    assert region.x == DEFAULT_TARGET_REGION_X == 0.40
    assert region.y == DEFAULT_TARGET_REGION_Y == 0.0
    assert region.width == DEFAULT_TARGET_REGION_WIDTH == 0.20
    assert region.height == DEFAULT_TARGET_REGION_HEIGHT == 0.12

    left, top, right, bottom = compute_target_header_bounds(1600, 900)
    assert left == round(1600 * 0.40)
    assert top == 0
    assert right == round(1600 * 0.60)
    assert bottom == round(900 * 0.12)


def test_verifier_ignores_sky_colours_outside_the_dedicated_hp_region() -> None:
    verifier, _ = _verifier()
    pixels = _frame(include_hp=True).pixels.copy()
    pixels[8:10, 22:30] = HP_BAR_COLOR

    result = verifier.verify(CapturedFrame(pixels, ClientSize(40, 20)))

    assert result.hp_pixel_count == 20


def test_verifier_rejects_real_sky_fixture_without_a_target() -> None:
    verifier = TargetVerifier(
        ("Flame",), _real_anchor_template(), _FakeRecognizer(), TargetVerificationConfig()
    )

    result = verifier.verify(_real_fixture(REAL_EMPTY_FIXTURE))

    assert result.status is TargetStatus.NO_TARGET
    assert result.target_name is None
    assert result.hp_pixel_count == 0
    assert not result.metrics.anchor_passed


def test_real_nameplate_preprocessing_isolates_the_same_glyphs_across_resolutions() -> None:
    """The mask must depend on the nameplate, not on the scenery drawn behind it."""

    glyph_counts = [
        int(np.count_nonzero(_real_preprocessed_nameplate(fixture) == 0))
        for fixture in REAL_FLAME_FIXTURES
    ]

    assert min(glyph_counts) > 0
    assert max(glyph_counts) - min(glyph_counts) <= 0.1 * min(glyph_counts)


@pytest.mark.skipif(
    not TESSERACT_IS_USABLE, reason="Tesseract OCR with English and German data is unavailable."
)
@pytest.mark.parametrize("fixture", REAL_FLAME_FIXTURES)
def test_verifier_accepts_real_flame_fixtures_through_tesseract(fixture: str) -> None:
    verifier = _real_verifier()

    result = verifier.verify(_real_fixture(fixture))

    assert result.metrics.name_status is TargetNameStatus.MATCHED, result.metrics.name_text
    assert result.status is TargetStatus.VALID_TARGET
    assert result.target_name == "Flame"
    assert result.metrics.anchor_passed
    assert result.metrics.hp_passed
    assert "flame" in result.metrics.name_text.casefold()


@pytest.mark.skipif(
    not TESSERACT_IS_USABLE, reason="Tesseract OCR with English and German data is unavailable."
)
def test_verifier_rejects_a_real_target_outside_the_active_whitelist() -> None:
    verifier = _real_verifier()

    result = verifier.verify(_real_fixture(REAL_FOREIGN_FIXTURE))

    assert result.status is TargetStatus.WRONG_TARGET
    assert result.target_name is None
    assert result.metrics.anchor_passed
    assert result.metrics.name_status is TargetNameStatus.NO_MATCH


def _real_verifier() -> TargetVerifier:
    """Build a verifier on the shipped anchor and the production default configuration."""

    return TargetVerifier(
        ("Flame",),
        _real_anchor_template(),
        TesseractTextRecognizer(),
        TargetVerificationConfig(),
    )


def _real_preprocessed_nameplate(fixture: str) -> npt.NDArray[np.uint8]:
    config = TargetVerificationConfig()
    frame = _real_fixture(fixture)
    region = extract_target_region(frame, config.region).pixels
    result = cv2.matchTemplate(region, _real_anchor_template(), cv2.TM_CCOEFF_NORMED)
    _minimum, score, _minimum_location, (anchor_x, anchor_y) = cv2.minMaxLoc(result)
    assert score >= config.anchor_match_threshold
    crop = extract_anchor_relative_region(region, anchor_x, anchor_y, config.name_offset)
    return preprocess_target_name_region(crop, config)


def _real_anchor_template() -> npt.NDArray[np.uint8]:
    template = cv2.imread(DEFAULT_TARGET_ANCHOR_PATH, cv2.IMREAD_COLOR)
    assert template is not None
    return cast("npt.NDArray[np.uint8]", template)


def _real_fixture(filename: str) -> CapturedFrame:
    pixels = cv2.imread(str(REAL_FIXTURE_DIRECTORY / filename))
    assert pixels is not None
    frame = cast("npt.NDArray[np.uint8]", np.ascontiguousarray(pixels))
    return CapturedFrame(frame, ClientSize(frame.shape[1], frame.shape[0]))


def test_resolve_mob_anchor_path_finds_anchors_for_eden_mobs() -> None:
    for mob_name in ("Flame", "LadyBlum", "MiniMush", "NightMist", "Oldrut", "Rapra"):
        anchor_path = resolve_mob_anchor_path(mob_name)
        assert anchor_path is not None
        assert anchor_path.is_file()


def test_load_mob_anchor_templates_loads_unique_templates() -> None:
    templates = load_mob_anchor_templates(("Flame", "Rapra", "Oldrut"))
    assert len(templates) >= 1
    for template in templates:
        assert template.ndim == 3
        assert template.dtype == np.uint8


def test_target_verifier_accepts_sequence_of_anchor_templates() -> None:
    template1 = np.ones((5, 5, 3), dtype=np.uint8)
    template2 = np.full((5, 5, 3), 2, dtype=np.uint8)
    verifier = TargetVerifier(
        ("Flame", "Rapra"),
        (template1, template2),
        _FakeRecognizer(),
        TargetVerificationConfig(),
    )
    assert verifier.allowed_names == ("Flame", "Rapra")


@pytest.mark.parametrize(
    ("text", "allowed", "expected"),
    [
        ("Rapra <Lvl 176>", ("Flame", "Rapra"), "Rapra"),
        ("Oldrut <Lvl 177>", ("Flame", "Oldrut", "Rapra"), "Oldrut"),
        ("LadyBlum <Lvl 174>", ("LadyBlum", "Rapra"), "LadyBlum"),
        ("MiniMush <Lvl 173>", ("Flame", "MiniMush"), "MiniMush"),
        ("NightMist <Lvl 175>", ("NightMist",), "NightMist"),
    ],
)
def test_match_whitelisted_name_matches_multiple_mobs(
    text: str, allowed: tuple[str, ...], expected: str
) -> None:
    assert match_whitelisted_name(text, allowed) == expected


def test_update_allowed_names_switches_the_whitelist_and_drops_the_cached_reading() -> None:
    verifier, recognizer = _verifier()
    frame = _frame(include_hp=True)

    assert verifier.verify(frame).status is TargetStatus.VALID_TARGET
    calls_before = recognizer.calls

    verifier.update_allowed_names(("Rapra",))
    result = verifier.verify(frame)

    assert verifier.allowed_names == ("Rapra",)
    assert result.status is TargetStatus.WRONG_TARGET
    assert result.metrics.name_status is TargetNameStatus.NO_MATCH
    # The cached reading resolved "Flame" against the previous whitelist, so it must be
    # re-read rather than reused for the new selection.
    assert recognizer.calls == calls_before + 1


def test_update_allowed_names_keeps_the_loaded_anchors_when_none_are_supplied() -> None:
    verifier, _ = _verifier()
    frame = _frame(include_hp=True)

    verifier.update_allowed_names(("Flame",))

    assert verifier.verify(frame).status is TargetStatus.VALID_TARGET


def test_update_allowed_names_applies_mob_specific_anchor_templates() -> None:
    verifier, _ = _verifier()
    # An anchor larger than the searched header region can never be located, which makes
    # the swap observable without depending on correlation scores of synthetic pixels.
    unmatchable_anchor = np.zeros((40, 80, 3), dtype=np.uint8)

    verifier.update_allowed_names(("Flame",), (unmatchable_anchor,))

    assert verifier.verify(_frame(include_hp=True)).status is TargetStatus.NO_TARGET


def test_update_allowed_names_rejects_an_empty_selection() -> None:
    verifier, _ = _verifier()

    with pytest.raises(ValueError, match="At least one non-empty target name"):
        verifier.update_allowed_names(())
