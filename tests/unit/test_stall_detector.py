"""Tests for obstacle stall detection from live GPS coordinates and frames."""

from __future__ import annotations

import numpy as np
import pytest

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.tracking import (
    MAXIMUM_STALL_SAMPLE_SECONDS,
    StallConfig,
    StallDetector,
)
from flyff_bot.features.vision.models import CapturedFrame, ClientSize

FRAME_WIDTH = 160
FRAME_HEIGHT = 120
BACKGROUND_VALUE = 40
CHARACTER_TOP = 40
CHARACTER_BOTTOM = 72
CHARACTER_LEFT = 60
CHARACTER_RIGHT = 100

STALL_TIMEOUT_SECONDS = 5.0
SAMPLE_INTERVAL_SECONDS = 0.5
STALL_CONFIG = StallConfig(
    motion_threshold=1.0,
    stall_timeout_seconds=STALL_TIMEOUT_SECONDS,
)


def _frame(
    *, background: int = BACKGROUND_VALUE, character: int = BACKGROUND_VALUE
) -> CapturedFrame:
    pixels = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), background, dtype=np.uint8)
    pixels[CHARACTER_TOP:CHARACTER_BOTTOM, CHARACTER_LEFT:CHARACTER_RIGHT] = character
    return CapturedFrame(
        np.ascontiguousarray(pixels), ClientSize(width=FRAME_WIDTH, height=FRAME_HEIGHT)
    )


def _animation_frame(step: int) -> CapturedFrame:
    """Return a frame whose scenery is frozen and whose centred character keeps animating."""

    return _frame(character=0 if step % 2 == 0 else 255)


def test_center_character_animation_over_frozen_scenery_reports_a_stall() -> None:
    """Walking into an obstacle keeps the run animation, but the world stops moving."""

    detector = StallDetector(STALL_CONFIG)
    seconds = 0.0

    detector.observe(
        _animation_frame(0),
        movement_commanded=True,
        at_seconds=seconds,
    )
    for step in range(1, int(STALL_TIMEOUT_SECONDS / SAMPLE_INTERVAL_SECONDS)):
        seconds += SAMPLE_INTERVAL_SECONDS
        assert not detector.observe(
            _animation_frame(step),
            movement_commanded=True,
            at_seconds=seconds,
        )

    seconds += SAMPLE_INTERVAL_SECONDS
    assert detector.observe(
        _animation_frame(0),
        movement_commanded=True,
        at_seconds=seconds,
    )
    assert detector.is_stalled
    assert detector.stalled_seconds == pytest.approx(STALL_TIMEOUT_SECONDS)


def test_without_the_center_mask_the_same_animation_hides_the_stall() -> None:
    """The centre mask is what makes the frozen-scenery verdict possible."""

    detector = StallDetector(
        StallConfig(
            motion_threshold=1.0,
            stall_timeout_seconds=STALL_TIMEOUT_SECONDS,
            center_mask_width_fraction=0.0,
            center_mask_height_fraction=0.0,
        )
    )

    for step in range(20):
        detector.observe(
            _animation_frame(step),
            movement_commanded=True,
            at_seconds=step * SAMPLE_INTERVAL_SECONDS,
        )

    assert not detector.is_stalled
    assert detector.stalled_seconds == pytest.approx(0.0)


def test_moving_scenery_never_accumulates_stall_time() -> None:
    detector = StallDetector(STALL_CONFIG)

    for step in range(20):
        detector.observe(
            _frame(background=BACKGROUND_VALUE + step * 5),
            movement_commanded=True,
            at_seconds=step * SAMPLE_INTERVAL_SECONDS,
        )

    assert not detector.is_stalled
    assert detector.stalled_seconds == pytest.approx(0.0)


def test_non_commanded_ticks_hold_the_stall_streak_within_the_movement_grace() -> None:
    """A turn tick between forward steps must not discard the accumulated streak."""

    detector = StallDetector(STALL_CONFIG)
    seconds = 0.0
    for step in range(10):
        detector.observe(
            _animation_frame(step),
            movement_commanded=True,
            at_seconds=seconds,
        )
        seconds += SAMPLE_INTERVAL_SECONDS

    held = detector.stalled_seconds
    assert held == pytest.approx(STALL_TIMEOUT_SECONDS - SAMPLE_INTERVAL_SECONDS)

    detector.observe(
        _animation_frame(10),
        movement_commanded=False,
        at_seconds=seconds,
    )
    assert detector.stalled_seconds == pytest.approx(held)
    assert not detector.is_stalled

    seconds += SAMPLE_INTERVAL_SECONDS
    assert detector.observe(
        _animation_frame(11),
        movement_commanded=True,
        at_seconds=seconds,
    )


def test_a_movement_pause_beyond_the_grace_clears_the_stall_streak() -> None:
    detector = StallDetector(STALL_CONFIG)
    seconds = 0.0
    for step in range(6):
        detector.observe(
            _animation_frame(step),
            movement_commanded=True,
            at_seconds=seconds,
        )
        seconds += SAMPLE_INTERVAL_SECONDS

    assert detector.stalled_seconds > 0.0

    seconds += STALL_CONFIG.movement_grace_seconds + SAMPLE_INTERVAL_SECONDS
    assert not detector.observe(
        _animation_frame(6),
        movement_commanded=False,
        at_seconds=seconds,
    )
    assert detector.stalled_seconds == pytest.approx(0.0)


def test_a_single_delayed_sample_cannot_satisfy_the_stall_timeout() -> None:
    detector = StallDetector(STALL_CONFIG)

    detector.observe(
        _animation_frame(0),
        movement_commanded=True,
        at_seconds=0.0,
    )
    detector.observe(
        _animation_frame(1),
        movement_commanded=True,
        at_seconds=STALL_TIMEOUT_SECONDS * 10.0,
    )

    assert detector.stalled_seconds == pytest.approx(MAXIMUM_STALL_SAMPLE_SECONDS)
    assert not detector.is_stalled


def test_missing_frames_keep_the_verdict_and_reset_clears_it() -> None:
    detector = StallDetector(STALL_CONFIG)
    seconds = 0.0
    for step in range(11):
        detector.observe(
            _animation_frame(step),
            movement_commanded=True,
            at_seconds=seconds,
        )
        seconds += SAMPLE_INTERVAL_SECONDS

    assert detector.is_stalled
    assert detector.observe(None, movement_commanded=True, at_seconds=seconds)

    detector.reset()

    assert not detector.is_stalled
    assert detector.stalled_seconds == pytest.approx(0.0)


def test_invalid_stall_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        StallConfig(motion_threshold=0.0)
    with pytest.raises(ValueError):
        StallConfig(stall_timeout_seconds=0.0)
    with pytest.raises(ValueError):
        StallConfig(movement_grace_seconds=-1.0)
    with pytest.raises(ValueError):
        StallConfig(sample_stride=0)
    with pytest.raises(ValueError):
        StallConfig(center_mask_width_fraction=1.0)
    with pytest.raises(ValueError):
        StallConfig(center_mask_height_fraction=-0.1)
    with pytest.raises(ValueError):
        StallConfig(live_motion_threshold_units_per_second=0.0)
    with pytest.raises(ValueError):
        StallConfig(live_stall_timeout_seconds=0.0)


def test_live_world_position_is_the_primary_two_second_stall_signal() -> None:
    detector = StallDetector()
    stationary = WorldPosition(100.0, 20.0, 300.0)

    assert not detector.observe(
        None,
        movement_commanded=True,
        at_seconds=0.0,
        live_position=stationary,
    )
    for sample in (0.5, 1.0, 1.5):
        assert not detector.observe(
            None,
            movement_commanded=True,
            at_seconds=sample,
            live_position=stationary,
        )
    assert detector.observe(
        None,
        movement_commanded=True,
        at_seconds=2.0,
        live_position=stationary,
    )


def test_live_speed_at_the_threshold_is_not_a_stall_and_resets_the_streak() -> None:
    detector = StallDetector()
    start = WorldPosition(0.0, 0.0, 0.0)
    detector.observe(
        None,
        movement_commanded=True,
        at_seconds=0.0,
        live_position=start,
    )
    detector.observe(
        None,
        movement_commanded=True,
        at_seconds=0.5,
        live_position=start,
    )

    assert not detector.observe(
        None,
        movement_commanded=True,
        at_seconds=1.0,
        live_position=WorldPosition(0.25, 0.0, 0.0),
    )
    assert detector.stalled_seconds == pytest.approx(0.0)


def test_throttled_duplicate_live_samples_do_not_accumulate_stall_time() -> None:
    detector = StallDetector()
    position = WorldPosition(0.0, 0.0, 0.0)

    for tick in (0.0, 0.02, 0.04, 0.06, 0.08):
        assert not detector.observe(
            None,
            movement_commanded=True,
            at_seconds=tick,
            live_position=position,
            live_sampled_at_seconds=0.0,
        )

    assert detector.stalled_seconds == pytest.approx(0.0)


def test_client_driven_combat_approach_is_sampled_and_stalls_before_the_engagement_timeout() -> (
    None
):
    """The approach is walked by the game client, so the session samples it itself."""

    engagement_timeout_seconds = 10.0
    tick_interval_seconds = 0.1
    detector = StallDetector(STALL_CONFIG)
    seconds = 0.0
    stalled_at_seconds: float | None = None

    for step in range(int(engagement_timeout_seconds / tick_interval_seconds)):
        stalled = detector.observe(
            _animation_frame(step),
            movement_commanded=True,
            at_seconds=seconds,
        )
        if stalled:
            stalled_at_seconds = seconds
            break
        seconds += tick_interval_seconds

    assert stalled_at_seconds is not None
    assert stalled_at_seconds < engagement_timeout_seconds


def test_a_measured_approach_that_keeps_covering_ground_never_stalls() -> None:
    """A reachable mob is walked to, so the live displacement clears the streak."""

    detector = StallDetector(STALL_CONFIG)

    for step in range(int(STALL_TIMEOUT_SECONDS / SAMPLE_INTERVAL_SECONDS) * 3):
        assert not detector.observe(
            None,
            live_position=WorldPosition(float(step) * 5.0, 0.0, 0.0),
            movement_commanded=True,
            at_seconds=step * SAMPLE_INTERVAL_SECONDS,
        )

    assert detector.stalled_seconds == pytest.approx(0.0)
