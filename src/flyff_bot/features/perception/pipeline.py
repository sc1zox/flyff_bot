"""Perception application service for building coherent world-state snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol

import cv2

from flyff_bot.features.automation.models import (
    InventoryEntry,
    PlayerVitals,
    RecentLoot,
    SelectedTarget,
    TargetState,
    Viewport,
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
from flyff_bot.features.vision.vitals import PlayerVitalsFeed, PlayerVitalsReader


class PerceptionFailure(StrEnum):
    """A non-fatal feed failure observed while processing a frame."""

    DETECTION = "detection"
    TARGET_VERIFICATION = "target_verification"
    LOOT_READING = "loot_reading"
    VITALS_READING = "vitals_reading"


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
    LOOT_COLLECTED = "loot_collected"
    VITALS_CHANGED = "vitals_changed"


@dataclass(frozen=True, slots=True)
class PerceptionEvent:
    """A material change between two world-state snapshots."""

    kind: PerceptionEventKind
    target: SelectedTarget | None = None
    mob: VisibleMob | None = None
    loot: RecentLoot | None = None
    vitals: PlayerVitals | None = None


@dataclass(frozen=True, slots=True)
class PerceptionTick:
    """The state and feed outcomes produced from one captured frame."""

    state: WorldState
    events: tuple[PerceptionEvent, ...]
    failures: frozenset[PerceptionFailure]
    frame: CapturedFrame | None = None


class PerceptionPipeline:
    """Capture once and independently aggregate all perception feeds."""

    def __init__(
        self,
        frame_source: FrameSource,
        detector: Detector,
        target_verifier: TargetVerificationFeed,
        loot_log_reader: LootFeed,
        clock: Callable[[], float] = monotonic,
        vitals_reader: PlayerVitalsFeed | None = None,
    ) -> None:
        self._frame_source = frame_source
        self._detector = detector
        self._target_verifier = target_verifier
        self._loot_log_reader = loot_log_reader
        self._clock = clock
        self._vitals_reader = vitals_reader or PlayerVitalsReader()
        self._visible_loot_fingerprints: frozenset[tuple[str, int, str]] = frozenset()

    def tick(self, window_handle: int, previous_state: WorldState) -> PerceptionTick:
        """Build a new snapshot, retaining a feed's prior data if that feed fails."""

        frame = self._frame_source.capture(window_handle)
        failures: set[PerceptionFailure] = set()
        visible_mobs = previous_state.visible_mobs
        selected_target = previous_state.selected_target
        recent_loot = previous_state.recent_loot
        player_vitals = previous_state.player_vitals
        confirmed_loot: tuple[LootEvent, ...] = ()

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
            observed_loot = self._loot_log_reader.read(frame)
            confirmed_loot = self._new_loot_events(observed_loot)
            recent_loot = tuple(_recent_loot(event) for event in confirmed_loot)
        except LootOcrError:
            failures.add(PerceptionFailure.LOOT_READING)
        try:
            player_vitals = self._vitals_reader.read(frame)
        except ValueError, cv2.error:
            failures.add(PerceptionFailure.VITALS_READING)

        inventory = _apply_loot(previous_state.inventory, confirmed_loot)

        state = WorldState(
            observed_at_seconds=self._clock(),
            position=previous_state.position,
            nearby_mob_count=len(visible_mobs),
            inventory=inventory,
            progress_marker=previous_state.progress_marker
            + sum(event.count for event in confirmed_loot),
            is_stuck=previous_state.is_stuck,
            selected_target=selected_target,
            visible_mobs=visible_mobs,
            recent_loot=recent_loot,
            viewport=Viewport(frame.client_size.width, frame.client_size.height),
            player_vitals=player_vitals,
        )
        return PerceptionTick(state, _events(previous_state, state), frozenset(failures), frame)

    def _new_loot_events(self, observed_loot: tuple[LootEvent, ...]) -> tuple[LootEvent, ...]:
        """Return notifications newly visible since the preceding successful OCR read."""

        fingerprints = frozenset(_loot_fingerprint(event) for event in observed_loot)
        new_events = tuple(
            event
            for event in observed_loot
            if _loot_fingerprint(event) not in self._visible_loot_fingerprints
        )
        self._visible_loot_fingerprints = fingerprints
        return new_events


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


def _loot_fingerprint(event: LootEvent) -> tuple[str, int, str]:
    return (event.item_name, event.count, event.raw_text)


def _apply_loot(
    inventory: tuple[InventoryEntry, ...], loot_events: tuple[LootEvent, ...]
) -> tuple[InventoryEntry, ...]:
    quantities = {entry.item: entry.quantity for entry in inventory}
    for event in loot_events:
        quantities[event.item_name] = quantities.get(event.item_name, 0) + event.count
    return tuple(InventoryEntry(item, quantity) for item, quantity in quantities.items())


def _events(previous_state: WorldState, state: WorldState) -> tuple[PerceptionEvent, ...]:
    events: list[PerceptionEvent] = []
    if state.selected_target != previous_state.selected_target:
        events.append(
            PerceptionEvent(PerceptionEventKind.TARGET_CHANGED, target=state.selected_target)
        )
    if state.player_vitals != previous_state.player_vitals:
        events.append(
            PerceptionEvent(PerceptionEventKind.VITALS_CHANGED, vitals=state.player_vitals)
        )
    previous_mobs = set(previous_state.visible_mobs)
    events.extend(
        PerceptionEvent(PerceptionEventKind.MOB_APPEARED, mob=mob)
        for mob in state.visible_mobs
        if mob not in previous_mobs
    )
    events.extend(
        PerceptionEvent(PerceptionEventKind.LOOT_COLLECTED, loot=loot)
        for loot in state.recent_loot
        if loot not in previous_state.recent_loot
    )
    return tuple(events)
