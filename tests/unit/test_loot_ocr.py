"""Unit tests for central loot-log OCR preprocessing and parsing."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision import (
    CapturedFrame,
    ClientSize,
    LootLogReader,
    LootLogRegion,
    LootOcrConfig,
    extract_loot_region,
    parse_loot_lines,
    preprocess_loot_region,
)

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
LOOT_REGION = LootLogRegion(x=0.25, y=0.5, width=0.5, height=0.25)


class FixtureRecognizer:
    """Predictable OCR output used to keep pipeline tests engine-independent."""

    def __init__(self, lines: Iterable[str]) -> None:
        self._lines = tuple(lines)
        self.images: list[npt.NDArray[np.uint8]] = []

    def recognize(self, image: npt.NDArray[np.uint8]) -> tuple[str, ...]:
        self.images.append(image)
        return self._lines


def _frame() -> CapturedFrame:
    pixels = np.zeros((40, 80, 3), dtype=np.uint8)
    pixels[22:28, 25:55] = (255, 255, 255)
    return CapturedFrame(pixels, ClientSize(80, 40))


def test_extract_and_preprocess_loot_region_from_synthetic_notification_crop() -> None:
    config = LootOcrConfig(region=LOOT_REGION)

    extracted = extract_loot_region(_frame(), LOOT_REGION)
    preprocessed = preprocess_loot_region(_frame(), config)

    assert extracted.client_size == ClientSize(40, 10)
    assert extracted.pixels.flags.c_contiguous
    assert preprocessed.shape == (10, 40)
    assert preprocessed.dtype == np.uint8
    assert set(np.unique(preprocessed)).issubset({0, 255})


def test_reader_emits_structured_english_and_german_loot_events() -> None:
    recognizer = FixtureRecognizer(
        ("You received 3 Mysterious Rose of Eden.", "Du hast 2x Mondstein erhalten.")
    )
    reader = LootLogReader(recognizer, LootOcrConfig(region=LOOT_REGION))

    events = reader.read(_frame(), CAPTURED_AT)

    assert [(event.item_name, event.count) for event in events] == [
        ("Mysterious Rose of Eden", 3),
        ("Mondstein", 2),
    ]
    assert all(event.timestamp == CAPTURED_AT for event in events)
    assert recognizer.images[0].shape == (10, 40)


def test_parser_uses_default_count_and_ignores_currency_and_unknown_notifications() -> None:
    events = parse_loot_lines(
        (
            "You received Mysterious Rose of Eden.",
            "You received 3,440,250 (Bonus: 1,960,942) Penya. (Total: 113,322,073)",
            "A monster has appeared.",
        ),
        CAPTURED_AT,
    )

    assert len(events) == 1
    assert events[0].item_name == "Mysterious Rose of Eden"
    assert events[0].count == 1
    assert events[0].raw_text == "You received Mysterious Rose of Eden."


def test_loot_region_rejects_bounds_outside_frame() -> None:
    try:
        LootLogRegion(x=0.7, width=0.4)
    except ValueError as error:
        assert "inside the client frame" in str(error)
    else:
        raise AssertionError("LootLogRegion accepted bounds outside the client frame.")
