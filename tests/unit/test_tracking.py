"""Tests for live GPS and visual stall detection (US-040, US-059)."""

from __future__ import annotations

import numpy as np

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.tracking import StallConfig, StallDetector
from flyff_bot.features.vision.models import CapturedFrame, ClientSize


def _live_pos(x: float, y: float, z: float) -> WorldPosition:
    return WorldPosition(x=x, y=y, z=z)


def _frame(fill_value: int) -> CapturedFrame:
    image = np.full((100, 100, 3), fill_value, dtype=np.uint8)
    return CapturedFrame(image, ClientSize(width=100, height=100))


def test_stall_detector_reports_no_stall_when_moving_via_gps() -> None:
    detector = StallDetector(
        StallConfig(live_motion_threshold_units_per_second=1.0, live_stall_timeout_seconds=2.0)
    )

    # Steps with movement
    assert not detector.observe(live_position=_live_pos(100.0, 10.0, 200.0), at_seconds=0.0)
    assert not detector.observe(live_position=_live_pos(105.0, 10.0, 200.0), at_seconds=1.0)
    assert not detector.observe(live_position=_live_pos(110.0, 10.0, 200.0), at_seconds=2.0)
    assert detector.stalled_seconds == 0.0
    assert not detector.is_stalled


def test_stall_detector_accumulates_stalls_when_gps_position_is_constant() -> None:
    detector = StallDetector(
        StallConfig(live_motion_threshold_units_per_second=1.0, live_stall_timeout_seconds=2.0)
    )
    pos = _live_pos(100.0, 10.0, 200.0)

    assert not detector.observe(live_position=pos, at_seconds=0.0)
    assert not detector.observe(live_position=pos, at_seconds=1.0)
    assert detector.stalled_seconds == 1.0
    # Reaching 2.0s marks stalled
    assert detector.observe(live_position=pos, at_seconds=2.0)
    assert detector.is_stalled


def test_stall_detector_resets_counter_on_movement() -> None:
    detector = StallDetector(
        StallConfig(live_motion_threshold_units_per_second=1.0, live_stall_timeout_seconds=2.0)
    )
    pos = _live_pos(100.0, 10.0, 200.0)

    detector.observe(live_position=pos, at_seconds=0.0)
    detector.observe(live_position=pos, at_seconds=1.0)
    assert detector.stalled_seconds == 1.0

    # Moving resets stall accumulation
    detector.observe(live_position=_live_pos(120.0, 10.0, 200.0), at_seconds=2.0)
    assert detector.stalled_seconds == 0.0
    assert not detector.is_stalled


def test_stall_detector_frame_diff_fallback_when_gps_unavailable() -> None:
    detector = StallDetector(StallConfig(motion_threshold=5.0, stall_timeout_seconds=1.5))

    frame = _frame(100)

    assert not detector.observe(frame=frame, at_seconds=0.0)
    assert not detector.observe(frame=frame, at_seconds=1.0)
    assert detector.stalled_seconds == 1.0
    # Over 1.5s stall timeout
    assert detector.observe(frame=frame, at_seconds=2.0)
    assert detector.is_stalled
