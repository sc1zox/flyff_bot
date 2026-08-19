"""Perception application service for building coherent world-state snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol

import cv2

from flyff_bot.features.automation.models import (
    PlayerVitals,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.vision.capture import FrameSource
from flyff_bot.features.vision.detection import Detection, DetectionError, Detector
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.features.vision.monster_stats import MonsterStatsFeed
from flyff_bot.features.vision.target_verification import (
    TargetStatus,
    TargetVerificationResult,
)
from flyff_bot.features.vision.vitals import PlayerVitalsFeed, PlayerVitalsReader

# The HUD kill counter changes at most once per kill, so sampling it twice a second is ample
# while keeping the far more expensive OCR subprocess off the majority of perception ticks.
DEFAULT_MONSTER_STATS_INTERVAL_SECONDS = 0.5
# Named so the handlers below stay single-name `except` clauses. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
DETECTION_ERRORS = (DetectionError, cv2.error)
FRAME_READ_ERRORS = (ValueError, cv2.error)


class PerceptionFailure(StrEnum):
    """A non-fatal feed failure observed while processing a frame."""

    DETECTION = "detection"
    TARGET_VERIFICATION = "target_verification"
    VITALS_READING = "vitals_reading"
    MONSTER_STATS = "monster_stats"


class TargetVerificationFeed(Protocol):
    """A component that classifies the selected target from a captured frame."""

    def verify(self, frame: CapturedFrame) -> TargetVerificationResult:
        """Return the current target classification."""


class PerceptionEventKind(StrEnum):
    """State transitions emitted by one perception tick."""

    TARGET_CHANGED = "target_changed"
    MOB_APPEARED = "mob_appeared"
    VITALS_CHANGED = "vitals_changed"


@dataclass(frozen=True, slots=True)
class PerceptionEvent:
    """A material change between two world-state snapshots."""

    kind: PerceptionEventKind
    target: SelectedTarget | None = None
    mob: VisibleMob | None = None
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
        clock: Callable[[], float] = monotonic,
        vitals_reader: PlayerVitalsFeed | None = None,
        monster_stats_reader: MonsterStatsFeed | None = None,
        monster_stats_interval_seconds: float = DEFAULT_MONSTER_STATS_INTERVAL_SECONDS,
    ) -> None:
        if monster_stats_interval_seconds < 0.0:
            raise ValueError("Monster stats read interval must not be negative.")
        self._frame_source = frame_source
        self._detector = detector
        self._target_verifier = target_verifier
        self._clock = clock
        self._vitals_reader = vitals_reader or PlayerVitalsReader()
        self._monster_stats_reader = monster_stats_reader
        self._monster_stats_interval_seconds = monster_stats_interval_seconds
        self._next_monster_stats_read_at_seconds = 0.0

    def tick(self, window_handle: int, previous_state: WorldState) -> PerceptionTick:
        """Build a new snapshot, retaining a feed's prior data if that feed fails."""

        frame = self._frame_source.capture(window_handle)
        failures: set[PerceptionFailure] = set()
        visible_mobs = previous_state.visible_mobs
        selected_target = previous_state.selected_target
        player_vitals = previous_state.player_vitals
        monster_kill_count = previous_state.monster_kill_count
        monster_stats = previous_state.monster_stats

        try:
            visible_mobs = tuple(
                _visible_mob(detection) for detection in self._detector.detect(frame)
            )
        except DETECTION_ERRORS:
            failures.add(PerceptionFailure.DETECTION)
        try:
            selected_target = _selected_target(self._target_verifier.verify(frame))
        except FRAME_READ_ERRORS:
            failures.add(PerceptionFailure.TARGET_VERIFICATION)
        try:
            player_vitals = self._vitals_reader.read(frame)
        except FRAME_READ_ERRORS:
            failures.add(PerceptionFailure.VITALS_READING)
        observed_at_seconds = self._clock()
        # Each reading spawns an OCR subprocess, which is far slower than one perception tick,
        # so the HUD counter is sampled on its own interval instead of on every frame.
        if (
            self._monster_stats_reader is not None
            and observed_at_seconds >= self._next_monster_stats_read_at_seconds
        ):
            self._next_monster_stats_read_at_seconds = (
                observed_at_seconds + self._monster_stats_interval_seconds
            )
            try:
                monster_stats = self._monster_stats_reader.read(frame)
                # A failed reading keeps the previous count rather than reporting zero, which
                # would look like the counter had been reset.
                if monster_stats.parsed_count is not None:
                    monster_kill_count = monster_stats.parsed_count
            except Exception:  # OCR failures are non-fatal
                failures.add(PerceptionFailure.MONSTER_STATS)

        state = WorldState(
            observed_at_seconds=observed_at_seconds,
            position=previous_state.position,
            nearby_mob_count=len(visible_mobs),
            inventory=previous_state.inventory,
            progress_marker=previous_state.progress_marker,
            is_stuck=previous_state.is_stuck,
            selected_target=selected_target,
            visible_mobs=visible_mobs,
            viewport=Viewport(frame.client_size.width, frame.client_size.height),
            player_vitals=player_vitals,
            monster_kill_count=monster_kill_count,
            monster_stats=monster_stats,
        )
        return PerceptionTick(state, _events(previous_state, state), frozenset(failures), frame)


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
    return SelectedTarget(
        state_by_status[result.status],
        result.target_name,
        result.hp_pixel_count,
        result.hp_percentage,
        result.metrics,
    )


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
    return tuple(events)
