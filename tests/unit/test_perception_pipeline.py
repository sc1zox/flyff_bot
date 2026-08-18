"""Tests for aggregation of independent vision feeds into world-state snapshots."""

from __future__ import annotations

import numpy as np
import pytest

from flyff_bot.features.automation.models import (
    InventoryEntry,
    MonsterStatsMetrics,
    MonsterStatsStatus,
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
    TargetNameStatus,
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

    tick = PerceptionPipeline(
        frame_source, detector, verifier, clock=lambda: OBSERVED_AT_SECONDS
    ).tick(WINDOW_HANDLE, _previous_state())

    assert tick.state is not _previous_state()
    assert tick.state.observed_at_seconds == OBSERVED_AT_SECONDS
    assert tick.state.position == Position(3, 4)
    assert tick.state.inventory == (InventoryEntry("potion", 2),)
    assert tick.state.progress_marker == 9
    assert tick.state.nearby_mob_count == 1
    assert tick.state.visible_mobs[0].class_name == "Aibatt"
    assert tick.state.selected_target == SelectedTarget(TargetState.VALID, "Aibatt", 20)
    assert tick.frame is FRAME
    assert frame_source.handles == [WINDOW_HANDLE]
    assert detector.frames == verifier.frames == [FRAME]


def test_tick_emits_target_transition_and_new_mob_events() -> None:
    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([_mob()]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.VALID_TARGET, "Aibatt", 20)),
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
        name_text="Aibatt <Lvl 12>",
        name_status=TargetNameStatus.MATCHED,
        name_passed=True,
    )
    result = TargetVerificationResult(TargetStatus.VALID_TARGET, "Aibatt", 20, 100.0, metrics)

    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(result),
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
            TargetVerificationMetrics(anchor_score=0.91, name_candidate="Aibatt"),
        )
    )
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        verifier,
        clock=lambda: OBSERVED_AT_SECONDS,
    )
    first = pipeline.tick(WINDOW_HANDLE, _previous_state())

    verifier.result = TargetVerificationResult(
        TargetStatus.VALID_TARGET,
        "Aibatt",
        20,
        100.0,
        TargetVerificationMetrics(anchor_score=0.99, name_candidate="Aibatt"),
    )
    second = pipeline.tick(WINDOW_HANDLE, first.state)

    assert first.state.selected_target.metrics != second.state.selected_target.metrics
    assert all(event.kind is not PerceptionEventKind.TARGET_CHANGED for event in second.events)


def test_tick_isolates_detector_failure() -> None:
    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector(DetectionError(DetectionErrorCode.INFERENCE_FAILED)),
        _TargetVerifier(TargetVerificationResult(TargetStatus.VALID_TARGET, "Aibatt", 20)),
        clock=lambda: OBSERVED_AT_SECONDS,
    ).tick(WINDOW_HANDLE, _previous_state())

    assert tick.failures == frozenset({PerceptionFailure.DETECTION})
    assert tick.state.nearby_mob_count == 0
    assert tick.state.selected_target == SelectedTarget(TargetState.VALID, "Aibatt", 20)


def test_tick_isolates_target_verification_failure() -> None:
    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(ValueError("invalid target region")),
        clock=lambda: OBSERVED_AT_SECONDS,
    ).tick(WINDOW_HANDLE, _previous_state())

    assert tick.failures == frozenset({PerceptionFailure.TARGET_VERIFICATION})
    assert tick.state.selected_target == SelectedTarget(TargetState.NONE, None, 0)


class _MonsterStatsReader:
    def __init__(self, result: MonsterStatsMetrics) -> None:
        self.result = result
        self.frames: list[CapturedFrame] = []

    def read(self, frame: CapturedFrame) -> MonsterStatsMetrics:
        self.frames.append(frame)
        return self.result


def test_tick_forwards_monster_stats_metrics_and_the_parsed_kill_count() -> None:
    metrics = MonsterStatsMetrics(
        anchor_configured=True,
        anchor_score=0.93,
        anchor_threshold=0.85,
        anchor_passed=True,
        roi_width=145,
        roi_height=20,
        raw_text="Monster Kills: 12",
        parsed_count=12,
        status=MonsterStatsStatus.OK,
    )

    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        clock=lambda: OBSERVED_AT_SECONDS,
        monster_stats_reader=_MonsterStatsReader(metrics),
    ).tick(WINDOW_HANDLE, _previous_state())

    assert tick.state.monster_stats == metrics
    assert tick.state.monster_kill_count == 12


def test_monster_stats_are_sampled_on_their_own_interval() -> None:
    """OCR is far slower than a tick, so it must not run on every captured frame."""

    reader = _MonsterStatsReader(MonsterStatsMetrics(status=MonsterStatsStatus.OK, parsed_count=3))
    now = 100.0
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        clock=lambda: now,
        monster_stats_reader=reader,
        monster_stats_interval_seconds=0.5,
    )

    state = _previous_state()
    for elapsed in (0.0, 0.1, 0.2, 0.4):
        now = 100.0 + elapsed
        state = pipeline.tick(WINDOW_HANDLE, state).state
    assert len(reader.frames) == 1

    # CombatController takes its kill baseline only from an OK reading, so a skipped tick must
    # carry the last one forward unchanged rather than reverting to the IDLE default.
    assert state.monster_stats.status is MonsterStatsStatus.OK
    assert state.monster_kill_count == 3

    now = 100.5
    pipeline.tick(WINDOW_HANDLE, state)

    assert len(reader.frames) == 2


def test_pipeline_rejects_a_negative_monster_stats_interval() -> None:
    with pytest.raises(ValueError, match="interval"):
        PerceptionPipeline(
            _FrameSource(),
            _Detector([]),
            _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
            monster_stats_interval_seconds=-1.0,
        )


def test_tick_retains_the_previous_kill_count_when_the_reading_fails() -> None:
    """A zero written here would look like the HUD counter had been reset."""

    previous = WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=0,
        inventory=(),
        progress_marker=0,
        monster_kill_count=17,
    )
    metrics = MonsterStatsMetrics(anchor_configured=True, status=MonsterStatsStatus.NO_MATCH)

    tick = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        clock=lambda: OBSERVED_AT_SECONDS,
        monster_stats_reader=_MonsterStatsReader(metrics),
    ).tick(WINDOW_HANDLE, previous)

    assert tick.state.monster_kill_count == 17
    assert tick.state.monster_stats.status is MonsterStatsStatus.NO_MATCH


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
        vitals_reader=vitals_feed,
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    tick = pipeline.tick(WINDOW_HANDLE, previous)
    assert PerceptionFailure.VITALS_READING in tick.failures
    assert tick.state.player_vitals == previous.player_vitals
