"""Tests for the standardized camera viewport alignment routine."""

from __future__ import annotations

import pytest

from flyff_bot.features.automation.camera_alignment import (
    PITCH_DOWN_PULSE_SECONDS,
    PITCH_UP_HOLD_SECONDS,
    ZOOM_OUT_WHEEL_NOTCHES,
    CameraAligner,
    CameraAlignmentConfig,
    CameraAlignmentStatus,
)
from flyff_bot.features.automation.controllers import VIRTUAL_KEY_DOWN, VIRTUAL_KEY_UP

VIRTUAL_KEY_PAGE_UP = 0x21
VIRTUAL_KEY_PAGE_DOWN = 0x22

WINDOW_HANDLE = 7


class _CameraAdapter:
    """Record the dispatched sequence and fail the guards after a chosen step."""

    def __init__(
        self, *, abort_after: int | None = None, focus_loss_after: int | None = None
    ) -> None:
        self.abort_after = abort_after
        self.focus_loss_after = focus_loss_after
        self.actions: list[tuple[str, int, float]] = []
        self.guard_checks = 0

    def is_aborted(self) -> bool:
        self.guard_checks += 1
        return self.abort_after is not None and len(self.actions) >= self.abort_after

    def is_foreground(self, window_handle: int) -> bool:
        assert window_handle == WINDOW_HANDLE
        return not (
            self.focus_loss_after is not None and len(self.actions) >= self.focus_loss_after
        )

    def scroll_wheel_while_guarded(self, window_handle: int, notches: int) -> None:
        self.actions.append(("scroll", window_handle, float(notches)))

    def send_key_while_guarded(
        self, window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.actions.append((f"key:{virtual_key:#04x}", window_handle, duration_seconds))

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        pass


def _aligner(
    adapter: _CameraAdapter,
    sleeps: list[float],
) -> CameraAligner:
    return CameraAligner(
        adapter,
        WINDOW_HANDLE,
        sleep=sleeps.append,
    )


def test_align_runs_the_zoom_hard_stop_then_pitch_ceiling_then_calibrated_pulse() -> None:
    adapter = _CameraAdapter()
    sleeps: list[float] = []

    status = _aligner(adapter, sleeps).align()

    assert status is CameraAlignmentStatus.ALIGNED
    assert adapter.actions == [
        ("scroll", WINDOW_HANDLE, float(ZOOM_OUT_WHEEL_NOTCHES)),
        (f"key:{VIRTUAL_KEY_UP:#04x}", WINDOW_HANDLE, PITCH_UP_HOLD_SECONDS),
        (f"key:{VIRTUAL_KEY_DOWN:#04x}", WINDOW_HANDLE, PITCH_DOWN_PULSE_SECONDS),
    ]
    assert len(sleeps) == len(adapter.actions)


def test_align_refuses_to_dispatch_anything_while_the_client_is_not_foregrounded() -> None:
    adapter = _CameraAdapter(focus_loss_after=0)

    status = _aligner(adapter, []).align()

    assert status is CameraAlignmentStatus.FOCUS_LOST
    assert adapter.actions == []


def test_align_refuses_to_dispatch_anything_while_the_emergency_stop_is_held() -> None:
    adapter = _CameraAdapter(abort_after=0)

    status = _aligner(adapter, []).align()

    assert status is CameraAlignmentStatus.ABORTED
    assert adapter.actions == []


def test_align_halts_before_the_remaining_steps_when_focus_is_lost_mid_sequence() -> None:
    adapter = _CameraAdapter(focus_loss_after=1)

    status = _aligner(adapter, []).align()

    assert status is CameraAlignmentStatus.FOCUS_LOST
    assert [action for action, _handle, _value in adapter.actions] == ["scroll"]


def test_align_halts_before_the_remaining_steps_when_the_emergency_stop_is_pressed() -> None:
    adapter = _CameraAdapter(abort_after=2)

    status = _aligner(adapter, []).align()

    assert status is CameraAlignmentStatus.ABORTED
    assert len(adapter.actions) == 2


def test_align_reports_focus_loss_that_happens_during_the_final_pitch_pulse() -> None:
    adapter = _CameraAdapter(focus_loss_after=3)

    status = _aligner(adapter, []).align()

    assert status is CameraAlignmentStatus.FOCUS_LOST
    assert len(adapter.actions) == 3


def test_alignment_zooms_out_forwards_past_the_hard_stop_with_the_arrow_pitch_keys() -> None:
    config = CameraAlignmentConfig()

    assert config.zoom_out_notches > 0
    assert config.zoom_out_notches >= 20
    assert config.pitch_up_virtual_key == VIRTUAL_KEY_UP
    assert config.pitch_down_virtual_key == VIRTUAL_KEY_DOWN


def test_alignment_config_rejects_a_backwards_zoom_and_non_positive_durations() -> None:
    with pytest.raises(ValueError):
        CameraAlignmentConfig(zoom_out_notches=-15)
    with pytest.raises(ValueError):
        CameraAlignmentConfig(zoom_out_notches=0)
    with pytest.raises(ValueError):
        CameraAlignmentConfig(pitch_up_hold_seconds=0.0)
    with pytest.raises(ValueError):
        CameraAlignmentConfig(pitch_down_pulse_seconds=-0.1)
    with pytest.raises(ValueError):
        CameraAlignmentConfig(step_settle_seconds=-0.1)


def test_align_honors_a_custom_configuration() -> None:
    adapter = _CameraAdapter()
    sleeps: list[float] = []
    config = CameraAlignmentConfig(
        zoom_out_notches=4,
        pitch_up_virtual_key=VIRTUAL_KEY_PAGE_UP,
        pitch_up_hold_seconds=0.5,
        pitch_down_virtual_key=VIRTUAL_KEY_PAGE_DOWN,
        pitch_down_pulse_seconds=0.25,
        step_settle_seconds=0.0,
    )

    status = CameraAligner(adapter, WINDOW_HANDLE, config=config, sleep=sleeps.append).align()

    assert status is CameraAlignmentStatus.ALIGNED
    assert adapter.actions == [
        ("scroll", WINDOW_HANDLE, 4.0),
        (f"key:{VIRTUAL_KEY_PAGE_UP:#04x}", WINDOW_HANDLE, 0.5),
        (f"key:{VIRTUAL_KEY_PAGE_DOWN:#04x}", WINDOW_HANDLE, 0.25),
    ]
    assert sleeps == [0.0, 0.0, 0.0]
