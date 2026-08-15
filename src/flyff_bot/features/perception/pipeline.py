"""Perception application service for building coherent world-state snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol

import cv2

from flyff_bot.features.automation.models import (
    RecentLoot,
    SelectedTarget,
    TargetState,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.vision.capture import FrameSource
from flyff_bot.features.vision.detection import Detection, DetectionError, Detector
from flyff_bot.features.vision.loot_ocr import LootEvent, LootOcrError
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.features.vision.target_verification import (
    TargetStatus,
    TargetVerificationResult,
)


class PerceptionFailure(StrEnum):
    """A non-fatal feed failure observed while processing a frame."""

    DETECTION = "detection"
    TARGET_VERIFICATION = "target_verification"
    LOOT_READING = "loot_reading"


class TargetVerificationFeed(Protocol):
    """A component that classifies the selected target from a captured frame."""

    def verify(self, frame: CapturedFrame) -> TargetVerificationResult:
        """Return the current target classification."""


class LootFeed(Protocol):
    """A component that reads pickup notifications from a captured frame."""

    def read(self, frame: CapturedFrame) -> tuple[LootEvent, ...]:
        """Return pickups visible in this frame."""


class PerceptionEventKind(StrEnum):
    """State transitions emitted by one perception tick."""

    TARGET_CHANGED = "target_changed"
    MOB_APPEARED = "mob_appeared"


@dataclass(frozen=True, slots=True)
class PerceptionEvent:
    """A material change between two world-state snapshots."""

    kind: PerceptionEventKind
    target: SelectedTarget | None = None
    mob: VisibleMob | None = None


@dataclass(frozen=True, slots=True)
class PerceptionTick:
    """The state and feed outcomes produced from one captured frame."""

    state: WorldState
    events: tuple[PerceptionEvent, ...]
    failures: frozenset[PerceptionFailure]


class PerceptionPipeline:
    """Capture once and independently aggregate all perception feeds."""

    def __init__(
        self,
        frame_source: FrameSource,
        detector: Detector,
        target_verifier: TargetVerificationFeed,
        loot_log_reader: LootFeed,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._frame_source = frame_source
        self._detector = detector
        self._target_verifier = target_verifier
        self._loot_log_reader = loot_log_reader
        self._clock = clock

    def tick(self, window_handle: int, previous_state: WorldState) -> PerceptionTick:
        """Build a new snapshot, retaining a feed's prior data if that feed fails."""

        frame = self._frame_source.capture(window_handle)
        failures: set[PerceptionFailure] = set()
        visible_mobs = previous_state.visible_mobs
        selected_target = previous_state.selected_target
        recent_loot = previous_state.recent_loot

        try:
            visible_mobs = tuple(
                _visible_mob(detection) for detection in self._detector.detect(frame)
            )
        except DetectionError, cv2.error:
            failures.add(PerceptionFailure.DETECTION)
        try:
            selected_target = _selected_target(self._target_verifier.verify(frame))
        except ValueError, cv2.error:
            failures.add(PerceptionFailure.TARGET_VERIFICATION)
        try:
            recent_loot = tuple(_recent_loot(event) for event in self._loot_log_reader.read(frame))
        except LootOcrError:
            failures.add(PerceptionFailure.LOOT_READING)

        state = WorldState(
            observed_at_seconds=self._clock(),
            position=previous_state.position,
            nearby_mob_count=len(visible_mobs),
            inventory=previous_state.inventory,
            progress_marker=previous_state.progress_marker,
            is_stuck=previous_state.is_stuck,
            selected_target=selected_target,
            visible_mobs=visible_mobs,
            recent_loot=recent_loot,
        )
        return PerceptionTick(state, _events(previous_state, state), frozenset(failures))


def _visible_mob(detection: Detection) -> VisibleMob:
    box = detection.bounding_box
    return VisibleMob(
        detection.class_id,
        detection.class_name,
        detection.confidence,
        box.x,
        box.y,
        box.width,
        box.height,
    )


def _selected_target(result: TargetVerificationResult) -> SelectedTarget:
    state_by_status = {
        TargetStatus.VALID_TARGET: TargetState.VALID,
        TargetStatus.WRONG_TARGET: TargetState.WRONG,
        TargetStatus.NO_TARGET: TargetState.NONE,
    }
    return SelectedTarget(state_by_status[result.status], result.target_name, result.hp_pixel_count)


def _recent_loot(event: LootEvent) -> RecentLoot:
    return RecentLoot(event.item_name, event.count, event.raw_text)


def _events(previous_state: WorldState, state: WorldState) -> tuple[PerceptionEvent, ...]:
    events: list[PerceptionEvent] = []
    if state.selected_target != previous_state.selected_target:
        events.append(
            PerceptionEvent(PerceptionEventKind.TARGET_CHANGED, target=state.selected_target)
        )
    previous_mobs = set(previous_state.visible_mobs)
    events.extend(
        PerceptionEvent(PerceptionEventKind.MOB_APPEARED, mob=mob)
        for mob in state.visible_mobs
        if mob not in previous_mobs
    )
    return tuple(events)
