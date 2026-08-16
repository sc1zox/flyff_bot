"""Tests for aggregation of independent vision feeds into world-state snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from flyff_bot.features.automation.models import (
    InventoryEntry,
    PlayerVitals,
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
    TargetVerificationMetrics,
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
        player_vitals=PlayerVitals(0.0, 0.0, 0.0),
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
    assert tick.state.inventory == (InventoryEntry("potion", 2), InventoryEntry("Sword", 1))
    assert tick.state.progress_marker == 10
    assert tick.state.nearby_mob_count == 1
    assert tick.state.visible_mobs[0].class_name == "Aibatt"
    assert tick.state.selected_target == SelectedTarget(TargetState.VALID, "Aibatt", 20)
    assert tick.state.recent_loot[0].item_name == "Sword"
    assert tick.frame is FRAME
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


def test_tick_forwards_full_target_verification_metrics_into_selected_target() -> None:
    metrics = TargetVerificationMetrics(
        anchor_score=0.95,
        anchor_threshold=0.9,
        anchor_passed=True,
        minimum_hp_pixel_count=10,
        hp_passed=True,
        name_candidate="Aibatt",
        name_score=0.92,
        name_threshold=0.9,
        name_passed=True,
    )
    result = TargetVerificationResult(TargetStatus.VALID_TARGET, "Aibatt", 20, 100.0, metrics)

    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(result),
        _LootLogReader(()),
        clock=lambda: OBSERVED_AT_SECONDS,
    ).tick(WINDOW_HANDLE, _previous_state())

    selected = tick.state.selected_target
    assert selected.state is TargetState.VALID
    assert selected.name == "Aibatt"
    assert selected.hp_pixel_count == 20
    assert selected.hp_percentage == 100.0
    assert selected.metrics == metrics


def test_tick_does_not_emit_target_changed_for_metrics_only_jitter() -> None:
    verifier = _TargetVerifier(
        TargetVerificationResult(
            TargetStatus.VALID_TARGET,
            "Aibatt",
            20,
            100.0,
            TargetVerificationMetrics(anchor_score=0.91, name_candidate="Aibatt", name_score=0.91),
        )
    )
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        verifier,
        _LootLogReader(()),
        clock=lambda: OBSERVED_AT_SECONDS,
    )
    first = pipeline.tick(WINDOW_HANDLE, _previous_state())

    verifier.result = TargetVerificationResult(
        TargetStatus.VALID_TARGET,
        "Aibatt",
        20,
        100.0,
        TargetVerificationMetrics(anchor_score=0.99, name_candidate="Aibatt", name_score=0.99),
    )
    second = pipeline.tick(WINDOW_HANDLE, first.state)

    assert first.state.selected_target.metrics != second.state.selected_target.metrics
    assert all(event.kind is not PerceptionEventKind.TARGET_CHANGED for event in second.events)


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


def test_tick_counts_new_loot_only_once_until_the_notification_clears() -> None:
    reader = _LootLogReader(
        (LootEvent(datetime(2026, 8, 15, tzinfo=UTC), "Sword", 2, "You received 2 Sword."),)
    )
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        reader,
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    first = pipeline.tick(WINDOW_HANDLE, _previous_state())
    repeated = pipeline.tick(WINDOW_HANDLE, first.state)
    reader.result = ()
    cleared = pipeline.tick(WINDOW_HANDLE, repeated.state)
    reader.result = (
        LootEvent(datetime(2026, 8, 15, tzinfo=UTC), "Sword", 2, "You received 2 Sword."),
    )
    after_clear = pipeline.tick(WINDOW_HANDLE, cleared.state)

    assert first.state.inventory == (InventoryEntry("potion", 2), InventoryEntry("Sword", 2))
    assert first.state.progress_marker == 11
    assert repeated.state.inventory == first.state.inventory
    assert repeated.state.progress_marker == first.state.progress_marker
    assert cleared.state.recent_loot == ()
    assert after_clear.state.inventory == (InventoryEntry("potion", 2), InventoryEntry("Sword", 4))
    assert after_clear.state.progress_marker == 13


def test_loot_read_failure_retains_prior_inventory_and_progress() -> None:
    previous = WorldState(
        observed_at_seconds=1.0,
        position=Position(3, 4),
        nearby_mob_count=0,
        inventory=(InventoryEntry("Sword", 3),),
        progress_marker=3,
    )

    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        _LootLogReader(LootOcrError(LootOcrErrorCode.RECOGNITION_FAILED)),
        clock=lambda: OBSERVED_AT_SECONDS,
    ).tick(WINDOW_HANDLE, previous)

    assert tick.state.inventory == previous.inventory
    assert tick.state.progress_marker == previous.progress_marker


class _VitalsReader:
    def __init__(self, result: PlayerVitals | Exception) -> None:
        self.result = result
        self.frames: list[CapturedFrame] = []

    def read(self, frame: CapturedFrame) -> PlayerVitals:
        self.frames.append(frame)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_tick_reads_player_vitals_and_emits_event() -> None:
    vitals = PlayerVitals(hp_percentage=60.0, mp_percentage=40.0, fp_percentage=80.0)
    vitals_feed = _VitalsReader(vitals)
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        _LootLogReader(()),
        vitals_reader=vitals_feed,
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    tick = pipeline.tick(WINDOW_HANDLE, _previous_state())
    assert tick.state.player_vitals == PlayerVitals(60.0, 40.0, 80.0)
    assert any(event.kind is PerceptionEventKind.VITALS_CHANGED for event in tick.events)


def test_tick_isolates_vitals_reading_failure() -> None:
    vitals_feed = _VitalsReader(ValueError("vitals parse failed"))
    previous = _previous_state()
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        _LootLogReader(()),
        vitals_reader=vitals_feed,
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    tick = pipeline.tick(WINDOW_HANDLE, previous)
    assert PerceptionFailure.VITALS_READING in tick.failures
    assert tick.state.player_vitals == previous.player_vitals
