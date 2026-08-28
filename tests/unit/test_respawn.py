"""Bounded-ROI revive-menu perception and its foreground-guarded dispatch (US-086)."""

from __future__ import annotations

from typing import cast

import numpy as np
import numpy.typing as npt
import pytest

from flyff_bot.features.automation.models import Position
from flyff_bot.features.automation.quest_execution_models import CombatInputAdapterLike
from flyff_bot.features.automation.respawn import (
    RESPAWN_ROI_LEFT_FRACTION,
    RESPAWN_ROI_TOP_FRACTION,
    RespawnInputDispatcher,
    RespawnMenuPerceiver,
    RespawnObservation,
)
from flyff_bot.features.vision.models import CapturedFrame, ClientSize
from flyff_bot.features.vision.ocr import (
    BoundedTextRecognizer,
    OcrError,
    OcrErrorCode,
    RecognizedTextLine,
)

WINDOW_HANDLE = 7
CLIENT_WIDTH = 800
CLIENT_HEIGHT = 600
LODESTAR_LINE = RecognizedTextLine("Lodestar", 20, 30, 100, 20)


class _Recognizer:
    """Return scripted lines and record the exact region it was handed."""

    def __init__(self, *lines: RecognizedTextLine, error: OcrErrorCode | None = None) -> None:
        self._lines = lines
        self._error = error
        self.regions: list[tuple[int, int]] = []

    def recognize_lines(self, image: npt.NDArray[np.uint8]) -> tuple[RecognizedTextLine, ...]:
        self.regions.append((image.shape[1], image.shape[0]))
        if self._error is not None:
            raise OcrError(self._error)
        return self._lines


class _Adapter:
    def __init__(self, *, foreground: bool = True, aborted: bool = False) -> None:
        self.foreground = foreground
        self.aborted = aborted
        self.clicks: list[tuple[int, int, int]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key_while_guarded(
        self, _window_handle: int, _virtual_key: int, _duration_seconds: float
    ) -> None:
        raise AssertionError("The revive menu is clicked, never keyed blindly.")


def _frame() -> CapturedFrame:
    return CapturedFrame(
        np.zeros((CLIENT_HEIGHT, CLIENT_WIDTH, 3), dtype=np.uint8),
        ClientSize(width=CLIENT_WIDTH, height=CLIENT_HEIGHT),
    )


def _perceiver(recognizer: _Recognizer) -> RespawnMenuPerceiver:
    return RespawnMenuPerceiver(cast("BoundedTextRecognizer", recognizer))


def test_the_revive_option_is_read_from_a_bounded_region_and_reported_in_client_pixels() -> None:
    recognizer = _Recognizer(RecognizedTextLine("Restart", 20, 5, 60, 20), LODESTAR_LINE)

    observation = _perceiver(recognizer).observe(_frame())

    # OCR never sees the whole frame, so a chat or HUD line cannot be mistaken for a menu row.
    assert recognizer.regions[0] < (CLIENT_WIDTH, CLIENT_HEIGHT)
    left = round(CLIENT_WIDTH * RESPAWN_ROI_LEFT_FRACTION)
    top = round(CLIENT_HEIGHT * RESPAWN_ROI_TOP_FRACTION)
    assert observation.position == Position(
        left + LODESTAR_LINE.centre[0], top + LODESTAR_LINE.centre[1]
    )
    assert observation.detail == "lodestar"


def test_a_line_below_the_match_threshold_yields_no_clickable_position() -> None:
    recognizer = _Recognizer(RecognizedTextLine("Sell all items", 20, 30, 100, 20))

    observation = _perceiver(recognizer).observe(_frame())

    assert observation.position is None
    assert observation.detail == "respawn_option_not_found"


def test_an_ocr_failure_is_reported_instead_of_guessed_around() -> None:
    recognizer = _Recognizer(error=OcrErrorCode.ENGINE_UNAVAILABLE)

    observation = _perceiver(recognizer).observe(_frame())

    assert observation.position is None
    assert observation.detail == "ocr_engine_unavailable"


def test_a_missing_frame_is_reported_rather_than_treated_as_an_empty_menu() -> None:
    assert _perceiver(_Recognizer()).observe(None).detail == "frame_unavailable"


@pytest.mark.parametrize("phrases", [(), ("  ",)])
def test_respawn_phrases_must_be_non_empty(phrases: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        RespawnMenuPerceiver(cast("BoundedTextRecognizer", _Recognizer()), phrases=phrases)


@pytest.mark.parametrize("threshold", [0.0, 1.5])
def test_the_respawn_match_threshold_must_be_a_proportion(threshold: float) -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        RespawnMenuPerceiver(
            cast("BoundedTextRecognizer", _Recognizer()), match_threshold=threshold
        )


def test_only_an_ocr_proven_option_is_clicked() -> None:
    adapter = _Adapter()
    dispatcher = RespawnInputDispatcher(cast("CombatInputAdapterLike", adapter), WINDOW_HANDLE)

    assert dispatcher.dispatch(RespawnObservation(Position(120, 90), "lodestar", 1.0))
    assert adapter.clicks == [(WINDOW_HANDLE, 120, 90)]
    assert not dispatcher.dispatch(RespawnObservation())
    assert adapter.clicks == [(WINDOW_HANDLE, 120, 90)]


@pytest.mark.parametrize(
    "adapter", [_Adapter(foreground=False), _Adapter(aborted=True)], ids=["background", "aborted"]
)
def test_a_background_or_emergency_stopped_client_is_never_clicked(adapter: _Adapter) -> None:
    dispatcher = RespawnInputDispatcher(cast("CombatInputAdapterLike", adapter), WINDOW_HANDLE)

    assert not dispatcher.dispatch(RespawnObservation(Position(120, 90), "lodestar", 1.0))
    assert adapter.clicks == []
