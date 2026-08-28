"""Observed, foreground-guarded player respawn through the client revive menu."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from flyff_bot.features.automation.models import Position
from flyff_bot.features.automation.quest_execution_models import CombatInputAdapterLike
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.features.vision.ocr import BoundedTextRecognizer, OcrError

# Entropia's bundled English help/FAQ identifies ``Lodestar`` as the revive-menu
# option that returns a dead character to the nearest town.  The ROI remains broad
# enough for supported client resolutions but excludes chat, inventory, and HUD text.
RESPAWN_ROI_LEFT_FRACTION = 0.25
RESPAWN_ROI_TOP_FRACTION = 0.20
RESPAWN_ROI_RIGHT_FRACTION = 0.75
RESPAWN_ROI_BOTTOM_FRACTION = 0.85
DEFAULT_RESPAWN_MATCH_THRESHOLD = 0.80
DEFAULT_RESPAWN_PHRASES = ("lodestar", "loadstar")


@dataclass(frozen=True, slots=True)
class RespawnObservation:
    """Read-only evidence for one exact revive-menu option."""

    position: Position | None = None
    detail: str = "respawn_option_not_found"
    score: float = 0.0


class RespawnMenuPerceiver:
    """Find the client-declared Lodestar row inside a bounded centre ROI."""

    def __init__(
        self,
        recognizer: BoundedTextRecognizer,
        *,
        phrases: tuple[str, ...] = DEFAULT_RESPAWN_PHRASES,
        match_threshold: float = DEFAULT_RESPAWN_MATCH_THRESHOLD,
    ) -> None:
        if not phrases or any(not phrase.strip() for phrase in phrases):
            raise ValueError("Respawn phrases must be non-empty.")
        if not 0.0 < match_threshold <= 1.0:
            raise ValueError("Respawn match threshold must be between zero and one.")
        self._recognizer = recognizer
        self._phrases = tuple(phrase.casefold() for phrase in phrases)
        self._match_threshold = match_threshold

    def observe(self, frame: CapturedFrame | None) -> RespawnObservation:
        if frame is None:
            return RespawnObservation(detail="frame_unavailable")
        width = frame.client_size.width
        height = frame.client_size.height
        left = round(width * RESPAWN_ROI_LEFT_FRACTION)
        top = round(height * RESPAWN_ROI_TOP_FRACTION)
        right = round(width * RESPAWN_ROI_RIGHT_FRACTION)
        bottom = round(height * RESPAWN_ROI_BOTTOM_FRACTION)
        roi = frame.pixels[top:bottom, left:right]
        try:
            lines = self._recognizer.recognize_lines(roi)
        except OcrError as error:
            return RespawnObservation(detail=f"ocr_{error.code.value}")
        best_line = None
        best_score = 0.0
        for line in lines:
            normalized = line.text.casefold().strip()
            score = max(
                SequenceMatcher(None, normalized, phrase).ratio() for phrase in self._phrases
            )
            if score > best_score:
                best_line = line
                best_score = score
        if best_line is None or best_score < self._match_threshold:
            return RespawnObservation(score=best_score)
        x, y = best_line.centre
        return RespawnObservation(Position(left + x, top + y), "lodestar", best_score)


class RespawnInputDispatcher:
    """Click only an OCR-proven option while foreground and F12-safe."""

    def __init__(self, adapter: CombatInputAdapterLike, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, observation: RespawnObservation) -> bool:
        if (
            observation.position is None
            or self._adapter.is_aborted()
            or not self._adapter.is_foreground(self._window_handle)
        ):
            return False
        self._adapter.click_client(
            self._window_handle, observation.position.x, observation.position.y
        )
        return True
