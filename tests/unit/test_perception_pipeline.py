"""Tests for aggregation of independent vision feeds into world-state snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from flyff_bot.features.automation.models import (
    InventoryEntry,
    Position,
    SelectedTarget,
    TargetState,
    WorldState,
)
from flyff_bot.features.perception import (
    PerceptionEventKind,
    PerceptionFailure,
    PerceptionPipeline,
)
from flyff_bot.features.vision import (
    BoundingBox,
    CapturedFrame,
    ClientSize,
    Detection,
    DetectionError,
    DetectionErrorCode,
    LootEvent,
    LootOcrError,
    LootOcrErrorCode,
    TargetStatus,
    TargetVerificationResult,
)

WINDOW_HANDLE = 42
OBSERVED_AT_SECONDS = 12.5
FRAME = CapturedFrame(np.zeros((4, 4, 3), dtype=np.uint8), ClientSize(4, 4))


class _FrameSource:
    def __init__(self) -> None:
        self.handles: list[int] = []

    def capture(self, window_handle: int) -> CapturedFrame:
        self.handles.append(window_handle)
        return FRAME


class _Detector:
    def __init__(self, result: list[Detection] | Exception) -> None:
        self.result = result
        self.frames: list[CapturedFrame] = []

    def detect(self, frame: CapturedFrame) -> list[Detection]:
        self.frames.append(frame)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _TargetVerifier:
    def __init__(self, result: TargetVerificationResult | Exception) -> None:
        self.result = result
        self.frames: list[CapturedFrame] = []

    def verify(self, frame: CapturedFrame) -> TargetVerificationResult:
        self.frames.append(frame)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _LootLogReader:
    def __init__(self, result: tuple[LootEvent, ...] | Exception) -> None:
        self.result = result
        self.frames: list[CapturedFrame] = []

    def read(self, frame: CapturedFrame) -> tuple[LootEvent, ...]:
        self.frames.append(frame)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _previous_state() -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(3, 4),
        nearby_mob_count=0,
        inventory=(InventoryEntry("potion", 2),),
        progress_marker=9,
    )


def _mob() -> Detection:
    return Detection(BoundingBox(1, 2, 3, 4), 0.9, 7, "Aibatt")


def test_tick_aggregates_one_shared_frame_into_a_new_world_state() -> None:
    frame_source = _FrameSource()
    detector = _Detector([_mob()])
    verifier = _TargetVerifier(TargetVerificationResult(TargetStatus.VALID_TARGET, "Aibatt", 20))
    loot_reader = _LootLogReader(
        (LootEvent(datetime(2026, 8, 15, tzinfo=UTC), "Sword", 1, "You received Sword."),)
    )

    tick = PerceptionPipeline(
        frame_source, detector, verifier, loot_reader, clock=lambda: OBSERVED_AT_SECONDS
    ).tick(WINDOW_HANDLE, _previous_state())

    assert tick.state is not _previous_state()
    assert tick.state.observed_at_seconds == OBSERVED_AT_SECONDS
    assert tick.state.position == Position(3, 4)
    assert tick.state.inventory == (InventoryEntry("potion", 2),)
    assert tick.state.nearby_mob_count == 1
    assert tick.state.visible_mobs[0].class_name == "Aibatt"
    assert tick.state.selected_target == SelectedTarget(TargetState.VALID, "Aibatt", 20)
    assert tick.state.recent_loot[0].item_name == "Sword"
    assert frame_source.handles == [WINDOW_HANDLE]
    assert detector.frames == verifier.frames == loot_reader.frames == [FRAME]


def test_tick_emits_target_transition_and_new_mob_events() -> None:
    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([_mob()]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.VALID_TARGET, "Aibatt", 20)),
        _LootLogReader(()),
        clock=lambda: OBSERVED_AT_SECONDS,
    ).tick(WINDOW_HANDLE, _previous_state())

    assert [event.kind for event in tick.events] == [
        PerceptionEventKind.TARGET_CHANGED,
        PerceptionEventKind.MOB_APPEARED,
    ]


def test_tick_isolates_detector_and_loot_failures() -> None:
    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector(DetectionError(DetectionErrorCode.INFERENCE_FAILED)),
        _TargetVerifier(TargetVerificationResult(TargetStatus.VALID_TARGET, "Aibatt", 20)),
        _LootLogReader(LootOcrError(LootOcrErrorCode.RECOGNITION_FAILED)),
        clock=lambda: OBSERVED_AT_SECONDS,
    ).tick(WINDOW_HANDLE, _previous_state())

    assert tick.failures == frozenset({PerceptionFailure.DETECTION, PerceptionFailure.LOOT_READING})
    assert tick.state.nearby_mob_count == 0
    assert tick.state.selected_target == SelectedTarget(TargetState.VALID, "Aibatt", 20)


def test_tick_isolates_target_verification_failure() -> None:
    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(ValueError("invalid target region")),
        _LootLogReader(()),
        clock=lambda: OBSERVED_AT_SECONDS,
    ).tick(WINDOW_HANDLE, _previous_state())

    assert tick.failures == frozenset({PerceptionFailure.TARGET_VERIFICATION})
    assert tick.state.selected_target == SelectedTarget(TargetState.NONE, None, 0)
