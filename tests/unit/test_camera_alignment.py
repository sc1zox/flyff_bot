"""Tests for the standardized viewport alignment routine (US-042, US-043)."""

from __future__ import annotations

import minimap_fixtures as fixtures
import pytest

from flyff_bot.features.automation.camera_alignment import (
    MINIMAP_CLICK_SETTLE_SECONDS,
    MINIMAP_ZOOM_OUT_CLICKS,
    PITCH_DOWN_PULSE_SECONDS,
    PITCH_UP_HOLD_SECONDS,
    ZOOM_OUT_WHEEL_NOTCHES,
    CameraAligner,
    CameraAlignmentConfig,
    CameraAlignmentStatus,
    MinimapLocator,
    frame_minimap_locator,
    minimap_zoom_out_button,
)
from flyff_bot.features.automation.controllers import VIRTUAL_KEY_DOWN, VIRTUAL_KEY_UP
from flyff_bot.features.vision.minimap import MinimapGeometry, locate_minimap
from flyff_bot.features.vision.models import (
    CapturedFrame,
    FrameCaptureError,
    FrameCaptureErrorCode,
)

VIRTUAL_KEY_PAGE_UP = 0x21
VIRTUAL_KEY_PAGE_DOWN = 0x22

WINDOW_HANDLE = 7
MINIMAP_CENTRE = MinimapGeometry(centre_x=1512.0, centre_y=106.5)


class _CameraAdapter:
    """Record the dispatched sequence and fail the guards after a chosen step."""

    def __init__(
        self, *, abort_after: int | None = None, focus_loss_after: int | None = None
    ) -> None:
        self.abort_after = abort_after
        self.focus_loss_after = focus_loss_after
        self.actions: list[tuple[str, int, float]] = []
        self.clicks: list[tuple[int, int]] = []
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
        assert window_handle == WINDOW_HANDLE
        self.clicks.append((x_coordinate, y_coordinate))
        self.actions.append(("click", window_handle, 0.0))


def _aligner(
    adapter: _CameraAdapter,
    sleeps: list[float],
    *,
    locate_minimap_geometry: MinimapLocator | None = None,
) -> CameraAligner:
    return CameraAligner(
        adapter,
        WINDOW_HANDLE,
        locate_minimap_geometry=locate_minimap_geometry,
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
    # Each step settles before the next one is measured against it.
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
    """Flyff zooms out on a forward wheel and pitches on Up/Down."""

    config = CameraAlignmentConfig()

    assert config.zoom_out_notches > 0
    # The zoom range is shorter than the dispatched run, so a fully zoomed-in camera still
    # ends on the engine's clamped maximum.
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


# --------------------------------------------------------------------------------------
# Minimap zoom-out hard stop (US-043)
# --------------------------------------------------------------------------------------


def test_the_zoom_out_button_sits_where_the_shipped_minimap_still_draws_it() -> None:
    """The offsets are measured evidence, so they are checked against the recorded HUD."""

    still = fixtures.still("zoom_default")
    geometry = locate_minimap(still)
    assert geometry is not None

    button_x, button_y = minimap_zoom_out_button(geometry)

    # The button's pale disk spans x 1442-1451 and y 146-156 in the still, below the
    # zoom-in button and outside the ring stroke, so the click lands well inside it.
    assert 1442 <= button_x <= 1451
    assert 146 <= button_y <= 156
    assert (button_x, button_y) == (1446, 151)


def test_the_button_coordinates_follow_the_located_ring_centre() -> None:
    shifted = MinimapGeometry(
        centre_x=MINIMAP_CENTRE.centre_x - 10.0, centre_y=MINIMAP_CENTRE.centre_y + 4.0
    )

    anchored = minimap_zoom_out_button(MINIMAP_CENTRE)
    moved = minimap_zoom_out_button(shifted)

    assert (moved[0] - anchored[0], moved[1] - anchored[1]) == (-10, 4)


def test_alignment_clicks_the_minimap_to_its_hard_stop_before_touching_the_camera() -> None:
    adapter = _CameraAdapter()
    sleeps: list[float] = []

    status = _aligner(adapter, sleeps, locate_minimap_geometry=lambda: MINIMAP_CENTRE).align()

    assert status is CameraAlignmentStatus.ALIGNED
    assert adapter.clicks == [minimap_zoom_out_button(MINIMAP_CENTRE)] * MINIMAP_ZOOM_OUT_CLICKS
    dispatched = [action for action, _handle, _value in adapter.actions]
    assert dispatched == ["click"] * MINIMAP_ZOOM_OUT_CLICKS + [
        "scroll",
        f"key:{VIRTUAL_KEY_UP:#04x}",
        f"key:{VIRTUAL_KEY_DOWN:#04x}",
    ]
    assert sleeps[:MINIMAP_ZOOM_OUT_CLICKS] == [MINIMAP_CLICK_SETTLE_SECONDS] * (
        MINIMAP_ZOOM_OUT_CLICKS
    )


def test_alignment_refuses_the_run_when_the_minimap_widget_is_not_visible() -> None:
    adapter = _CameraAdapter()

    status = _aligner(adapter, [], locate_minimap_geometry=lambda: None).align()

    assert status is CameraAlignmentStatus.MINIMAP_NOT_FOUND
    assert adapter.actions == []


def test_alignment_stops_clicking_the_minimap_when_the_client_loses_focus() -> None:
    adapter = _CameraAdapter(focus_loss_after=3)

    status = _aligner(adapter, [], locate_minimap_geometry=lambda: MINIMAP_CENTRE).align()

    assert status is CameraAlignmentStatus.FOCUS_LOST
    assert len(adapter.clicks) == 3


def test_alignment_stops_clicking_the_minimap_when_the_emergency_stop_is_pressed() -> None:
    adapter = _CameraAdapter(abort_after=4)

    status = _aligner(adapter, [], locate_minimap_geometry=lambda: MINIMAP_CENTRE).align()

    assert status is CameraAlignmentStatus.ABORTED
    assert len(adapter.clicks) == 4


def test_alignment_without_a_locator_leaves_the_minimap_untouched() -> None:
    adapter = _CameraAdapter()

    status = _aligner(adapter, []).align()

    assert status is CameraAlignmentStatus.ALIGNED
    assert adapter.clicks == []


def test_the_minimap_click_run_outruns_the_widgets_own_zoom_range() -> None:
    config = CameraAlignmentConfig()

    assert config.minimap_zoom_out_clicks == MINIMAP_ZOOM_OUT_CLICKS
    assert config.minimap_zoom_out_clicks >= 10


def test_alignment_config_rejects_an_empty_click_run_and_a_negative_settle_delay() -> None:
    with pytest.raises(ValueError):
        CameraAlignmentConfig(minimap_zoom_out_clicks=0)
    with pytest.raises(ValueError):
        CameraAlignmentConfig(minimap_click_settle_seconds=-0.01)


class _FrameSource:
    """Frame source double that either replays a still or fails the way capture does."""

    def __init__(self, frame: CapturedFrame | None) -> None:
        self._frame = frame

    def capture(self, window_handle: int) -> CapturedFrame:
        assert window_handle == WINDOW_HANDLE
        if self._frame is None:
            raise FrameCaptureError(FrameCaptureErrorCode.OCCLUDED)
        return self._frame


def test_the_frame_locator_finds_the_ring_in_a_captured_client_frame() -> None:
    locate = frame_minimap_locator(_FrameSource(fixtures.still("zoom_default")), WINDOW_HANDLE)

    geometry = locate()

    assert geometry is not None
    assert geometry.centre_x == pytest.approx(MINIMAP_CENTRE.centre_x, abs=5.0)
    assert geometry.centre_y == pytest.approx(MINIMAP_CENTRE.centre_y, abs=5.0)


def test_a_frame_that_cannot_be_captured_reports_no_minimap_instead_of_raising() -> None:
    locate = frame_minimap_locator(_FrameSource(None), WINDOW_HANDLE)

    assert locate() is None
