"""Regression coverage for client stats replacing player-vitals OCR."""

from __future__ import annotations

from test_perception_pipeline import (
    OBSERVED_AT_SECONDS,
    WINDOW_HANDLE,
    _Detector,
    _FrameSource,
    _previous_state,
    _TargetVerifier,
)

from flyff_bot.features.automation.models import Position, WorldState
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.player_stats.models import (
    ClientPlayerStatsSnapshot,
    PlayerStatField,
    PlayerStatsReadError,
    PlayerStatsReadErrorCode,
    PlayerStatsSource,
)
from flyff_bot.features.vision.models import PlayerVitals
from flyff_bot.features.vision.target_verification import (
    TargetStatus,
    TargetVerificationResult,
)


class _StatsReader:
    def __init__(self, snapshot: ClientPlayerStatsSnapshot) -> None:
        self.snapshot = snapshot
        self.poll_calls = 0
        self.close_calls = 0

    def poll(self, at_seconds: float) -> ClientPlayerStatsSnapshot:
        self.poll_calls += 1
        return self.snapshot

    def close(self) -> None:
        self.close_calls += 1


def test_client_stats_replace_vitals_ocr_when_complete() -> None:
    stats = ClientPlayerStatsSnapshot(
        PlayerStatsSource.CLIENT_MEMORY,
        sampled_at_seconds=1.0,
        client_sha256="a" * 64,
        fields=(
            PlayerStatField("hp", 61.5, False),
            PlayerStatField("mp", 43.0, False),
            PlayerStatField("fp", 82.25, False),
        ),
    )
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        player_stats_reader=_StatsReader(stats),
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    tick = pipeline.tick(WINDOW_HANDLE, _previous_state())

    assert tick.state.player_stats_snapshot == stats
    assert tick.state.player_vitals == PlayerVitals(61.5, 43.0, 82.25)


def test_client_stats_sets_monster_kill_count() -> None:
    stats = ClientPlayerStatsSnapshot(
        PlayerStatsSource.CLIENT_MEMORY,
        sampled_at_seconds=1.0,
        client_sha256="a" * 64,
        fields=(
            PlayerStatField("hp", 100.0, False),
            PlayerStatField("mp", 100.0, False),
            PlayerStatField("fp", 100.0, False),
            PlayerStatField("monster_kills", 42.0, False),
        ),
    )
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        player_stats_reader=_StatsReader(stats),
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    tick = pipeline.tick(WINDOW_HANDLE, _previous_state())

    assert tick.state.monster_kill_count == 42


def test_partial_client_stats_keep_previous_vitals_without_ocr_fallback() -> None:
    stats = ClientPlayerStatsSnapshot(
        PlayerStatsSource.CLIENT_MEMORY,
        sampled_at_seconds=1.0,
        client_sha256="a" * 64,
        fields=(PlayerStatField("hp", 61.5, False),),
    )
    previous = _previous_state()
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        player_stats_reader=_StatsReader(stats),
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    tick = pipeline.tick(WINDOW_HANDLE, previous)

    assert tick.state.player_stats_snapshot == stats
    assert tick.state.player_vitals == previous.player_vitals


def test_unavailable_client_stats_do_not_request_ocr() -> None:
    stats = ClientPlayerStatsSnapshot(
        PlayerStatsSource.UNAVAILABLE,
        error=PlayerStatsReadError(PlayerStatsReadErrorCode.NO_PROFILE),
    )
    previous = WorldState(
        observed_at_seconds=0.0,
        position=Position(0, 0),
        nearby_mob_count=0,
        progress_marker=0,
    )
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        player_stats_reader=_StatsReader(stats),
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    tick = pipeline.tick(WINDOW_HANDLE, previous)

    assert tick.failures == frozenset()
    assert tick.state.player_stats_snapshot is not None
    assert tick.state.player_stats_snapshot.source is PlayerStatsSource.UNAVAILABLE
    assert tick.state.player_vitals == previous.player_vitals


def test_capture_only_tick_and_close_do_not_reopen_player_stats_provider() -> None:
    stats = ClientPlayerStatsSnapshot(
        PlayerStatsSource.UNAVAILABLE,
        error=PlayerStatsReadError(PlayerStatsReadErrorCode.HANDLE_LOST),
    )
    reader = _StatsReader(stats)
    previous = _previous_state()
    pipeline = PerceptionPipeline(
        _FrameSource(),
        _Detector([]),
        _TargetVerifier(TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)),
        player_stats_reader=reader,
        clock=lambda: OBSERVED_AT_SECONDS,
    )

    tick = pipeline.tick(WINDOW_HANDLE, previous, poll_live_providers=False)
    pipeline.close()
    pipeline.close()

    assert tick.frame is not None
    assert reader.poll_calls == 0
    assert reader.close_calls == 2
