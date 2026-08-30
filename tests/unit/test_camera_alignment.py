"""Tests for closed-loop live-memory camera alignment."""

from __future__ import annotations

import math

import pytest

from flyff_bot.features.automation.camera_alignment import (
    CameraAligner,
    CameraAlignmentConfig,
    CameraAlignmentStatus,
)
from flyff_bot.features.navigation.live_camera import CameraReading, CameraState

WINDOW_HANDLE = 7


class _CameraAdapter:
    def __init__(
        self, *, abort_after: int | None = None, focus_loss_after: int | None = None
    ) -> None:
        self.abort_after = abort_after
        self.focus_loss_after = focus_loss_after
        self.actions: list[tuple[str, float]] = []

    def is_aborted(self) -> bool:
        return self.abort_after is not None and len(self.actions) >= self.abort_after

    def is_foreground(self, window_handle: int) -> bool:
        assert window_handle == WINDOW_HANDLE
        return not (
            self.focus_loss_after is not None and len(self.actions) >= self.focus_loss_after
        )

    def scroll_wheel_while_guarded(self, window_handle: int, notches: int) -> None:
        assert window_handle == WINDOW_HANDLE
        self.actions.append(("scroll", float(notches)))

    def send_key_while_guarded(
        self, window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        assert window_handle == WINDOW_HANDLE
        self.actions.append((f"key:{virtual_key:#04x}", duration_seconds))


class _CameraSource:
    def __init__(self, states: list[CameraState | None]) -> None:
        self.states = states
        self.polls = 0

    def poll(self, at_seconds: float) -> CameraReading:
        assert at_seconds >= 0.0
        self.polls += 1
        state = self.states.pop(0)
        return CameraReading(state=state, sampled_at_seconds=at_seconds)


def _state(zoom: float, pitch: float) -> CameraState:
    return CameraState(zoom_distance=zoom, pitch_radians=math.radians(pitch))


def test_alignment_waits_for_confirmed_zoom_hard_stop_then_pitch_target() -> None:
    adapter = _CameraAdapter()
    source = _CameraSource(
        [
            _state(10.0, 20.0),
            _state(11.0, 20.0),
            _state(11.0, 20.0),
            _state(11.0, 20.0),
            _state(11.0, 30.0),
        ]
    )

    status = CameraAligner(adapter, WINDOW_HANDLE, source, sleep=lambda _delay: None).align()

    assert status is CameraAlignmentStatus.ALIGNED
    assert [name for name, _value in adapter.actions] == [
        "scroll",
        "scroll",
        "scroll",
        "key:0x26",
    ]
    assert source.polls == 5


def test_alignment_uses_damped_pitch_pulses_to_converge_on_the_ergonomic_default() -> None:
    """BUG-042: small remaining errors must not repeat the coarse 80-ms pulse."""

    adapter = _CameraAdapter()
    source = _CameraSource(
        [
            _state(10.0, 20.0),
            _state(11.0, 20.0),
            _state(11.0, 20.0),
            _state(11.0, 20.0),
            _state(11.0, 26.0),
            _state(11.0, 29.0),
        ]
    )

    status = CameraAligner(adapter, WINDOW_HANDLE, source, sleep=lambda _delay: None).align()

    assert status is CameraAlignmentStatus.ALIGNED
    assert CameraAlignmentConfig().target_pitch_degrees == pytest.approx(30.0)
    assert CameraAlignmentConfig().pitch_tolerance_degrees == pytest.approx(2.5)
    assert adapter.actions[-2:] == [("key:0x26", 0.05), ("key:0x26", 0.025)]


def test_damped_pitch_pulses_never_exceed_the_configured_directional_cap() -> None:
    config = CameraAlignmentConfig(pitch_up_hold_seconds=0.04, pitch_down_pulse_seconds=0.02)
    aligner = CameraAligner(_CameraAdapter(), WINDOW_HANDLE, _CameraSource([]), config=config)

    assert aligner._pitch_pulse_duration(7.0) == pytest.approx(0.04)
    assert aligner._pitch_pulse_duration(-4.0) == pytest.approx(0.02)


def test_damped_pitch_pulses_use_direction_and_exact_error_bands() -> None:
    aligner = CameraAligner(_CameraAdapter(), WINDOW_HANDLE, _CameraSource([]))

    assert aligner._pitch_pulse_duration(11.0) == pytest.approx(0.08)
    assert aligner._pitch_pulse_duration(-10.0) == pytest.approx(0.05)
    assert aligner._pitch_pulse_duration(5.0) == pytest.approx(0.025)


def test_alignment_does_not_treat_one_delayed_zoom_measurement_as_a_hard_stop() -> None:
    adapter = _CameraAdapter()
    source = _CameraSource(
        [
            _state(10.0, 30.0),
            _state(10.0, 30.0),
            _state(11.0, 30.0),
            _state(11.0, 30.0),
            _state(11.0, 30.0),
        ]
    )

    status = CameraAligner(adapter, WINDOW_HANDLE, source, sleep=lambda _delay: None).align()

    assert status is CameraAlignmentStatus.ALIGNED
    assert [name for name, _value in adapter.actions] == ["scroll", "scroll", "scroll", "scroll"]


def test_missing_memory_state_fails_without_input() -> None:
    adapter = _CameraAdapter()
    source = _CameraSource([None])

    status = CameraAligner(adapter, WINDOW_HANDLE, source).align()

    assert status is CameraAlignmentStatus.CAMERA_UNAVAILABLE
    assert adapter.actions == []


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (_CameraAdapter(abort_after=0), CameraAlignmentStatus.ABORTED),
        (_CameraAdapter(focus_loss_after=0), CameraAlignmentStatus.FOCUS_LOST),
    ],
)
def test_initial_guard_refuses_all_input(
    adapter: _CameraAdapter, expected: CameraAlignmentStatus
) -> None:
    source = _CameraSource([_state(10.0, 45.0)])

    assert CameraAligner(adapter, WINDOW_HANDLE, source).align() is expected
    assert adapter.actions == []
    assert source.polls == 0


def test_focus_loss_between_actions_halts_the_loop() -> None:
    adapter = _CameraAdapter(focus_loss_after=1)
    source = _CameraSource([_state(10.0, 45.0)])

    status = CameraAligner(adapter, WINDOW_HANDLE, source, sleep=lambda _delay: None).align()

    assert status is CameraAlignmentStatus.FOCUS_LOST
    assert len(adapter.actions) == 1


def test_bounded_zoom_without_a_measured_hard_stop_reports_non_convergence() -> None:
    adapter = _CameraAdapter()
    source = _CameraSource([_state(1.0, 45.0), _state(2.0, 45.0), _state(3.0, 45.0)])
    config = CameraAlignmentConfig(zoom_out_notches=2, step_settle_seconds=0.0)

    status = CameraAligner(adapter, WINDOW_HANDLE, source, config=config).align()

    assert status is CameraAlignmentStatus.NOT_CONVERGED
    assert len(adapter.actions) == 2


def test_alignment_config_rejects_invalid_budgets_and_tolerances() -> None:
    with pytest.raises(ValueError):
        CameraAlignmentConfig(zoom_out_notches=0)
    with pytest.raises(ValueError):
        CameraAlignmentConfig(maximum_pitch_steps=0)
    with pytest.raises(ValueError):
        CameraAlignmentConfig(pitch_tolerance_degrees=0.0)
