"""Deterministic viewport initialization for the mob distance model (US-042, US-043).

The inverse-perspective spawn distance relation of US-037/US-041,
``distance = a / bounding_box_height + b``, is only valid while the camera keeps the exact
zoom and pitch it was calibrated at, and the minimap odometry of US-035 only reports the
calibrated pixel scale while the minimap keeps the zoom level it was measured at. All three
are restored here without inspecting game memory:

* the minimap zoom-out button is clicked past its own range, so the widget ends on the
  engine's maximum zoom-out hard stop in every session,
* the wheel is scrolled forwards past Flyff's physical zoom limit, which the engine
  hard-clamps to the same focal length in every session, and
* the pitch is driven into its vertical limit and then pulled back by one calibrated
  downward pulse, which lands on the standardized ~45 degree elevation that keeps distant
  spawns on the horizon visible.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from flyff_bot.features.automation.controllers import VIRTUAL_KEY_DOWN, VIRTUAL_KEY_UP
from flyff_bot.features.vision.capture import FrameSource
from flyff_bot.features.vision.minimap import MinimapGeometry, locate_minimap
from flyff_bot.features.vision.models import FrameCaptureError

# In Entropia Flyff (neuz.exe), the engine pulls the camera away to its zoom-out hard stop
# on a forward wheel rotation (+WHEEL_DELTA), and twenty notches outrun the zoom range
# from a fully zoomed-in start, so the camera always settles on the engine's clamped maximum.
ZOOM_OUT_WHEEL_NOTCHES = 20
PITCH_UP_HOLD_SECONDS = 0.8
PITCH_DOWN_PULSE_SECONDS = 0.70
# The minimap HUD carries its zoom buttons on a circle just outside the ring stroke. The
# zoom-out button's pale disk spans x 1442-1451 and y 146-156 in both client-area stills
# shipped under `data/assets/fixtures/minimap/`, whose ring `locate_minimap` places at
# (1513.0, 105.5); these are the displacements from that located centre to its middle.
MINIMAP_ZOOM_OUT_BUTTON_OFFSET_X_PIXELS = -66.5
MINIMAP_ZOOM_OUT_BUTTON_OFFSET_Y_PIXELS = 45.5
# The widget offers fewer steps than this from any starting level, so the run always ends on
# the hard stop rather than a relative offset, exactly like the camera wheel above.
MINIMAP_ZOOM_OUT_CLICKS = 10
# The widget redraws the map surface per step, and a click that lands during the redraw is
# swallowed.
MINIMAP_CLICK_SETTLE_SECONDS = 0.12
# The client interpolates the camera, so each step needs to finish before the next one is
# measured against it.
STEP_SETTLE_SECONDS = 0.2
# A farming session that starts from an arbitrary camera state would read distances off a
# perspective the model was never fitted for, so the pre-flight is on unless disabled.
DEFAULT_AUTO_ALIGN_CAMERA = True


class CameraAlignmentStatus(StrEnum):
    """Outcome of one alignment attempt."""

    ALIGNED = "aligned"
    ABORTED = "aborted"
    FOCUS_LOST = "focus_lost"
    MINIMAP_NOT_FOUND = "minimap_not_found"


# Returns the located minimap ring geometry, or ``None`` when the widget is not visible.
type MinimapLocator = Callable[[], MinimapGeometry | None]


@dataclass(frozen=True, slots=True)
class CameraAlignmentConfig:
    """Zoom, pitch, and settle timings of the standardized alignment sequence."""

    zoom_out_notches: int = ZOOM_OUT_WHEEL_NOTCHES
    pitch_up_virtual_key: int = VIRTUAL_KEY_UP
    pitch_up_hold_seconds: float = PITCH_UP_HOLD_SECONDS
    pitch_down_virtual_key: int = VIRTUAL_KEY_DOWN
    pitch_down_pulse_seconds: float = PITCH_DOWN_PULSE_SECONDS
    step_settle_seconds: float = STEP_SETTLE_SECONDS
    minimap_zoom_out_clicks: int = MINIMAP_ZOOM_OUT_CLICKS
    minimap_click_settle_seconds: float = MINIMAP_CLICK_SETTLE_SECONDS

    def __post_init__(self) -> None:
        if self.zoom_out_notches <= 0:
            raise ValueError("Camera zoom-out notch count must be positive.")
        if self.pitch_up_hold_seconds <= 0.0 or self.pitch_down_pulse_seconds <= 0.0:
            raise ValueError("Camera pitch durations must be positive.")
        if self.step_settle_seconds < 0.0:
            raise ValueError("Camera settle delay must not be negative.")
        if self.minimap_zoom_out_clicks <= 0:
            raise ValueError("Minimap zoom-out must dispatch at least one click.")
        if self.minimap_click_settle_seconds < 0.0:
            raise ValueError("Minimap click settle delay must not be negative.")


def minimap_zoom_out_button(geometry: MinimapGeometry) -> tuple[int, int]:
    """Return the client-area coordinates of the minimap's zoom-out button."""

    return (
        round(geometry.centre_x + MINIMAP_ZOOM_OUT_BUTTON_OFFSET_X_PIXELS),
        round(geometry.centre_y + MINIMAP_ZOOM_OUT_BUTTON_OFFSET_Y_PIXELS),
    )


def frame_minimap_locator(frame_source: FrameSource, window_handle: int) -> MinimapLocator:
    """Bind a frame source to one window so the aligner can find the live minimap.

    A frame that cannot be captured is reported as "no minimap", because the alignment has
    no way to place a click without one.
    """

    def locate() -> MinimapGeometry | None:
        try:
            frame = frame_source.capture(window_handle)
        except FrameCaptureError:
            return None
        return locate_minimap(frame)

    return locate


class CameraInputAdapter(Protocol):
    """Guarded platform operations needed to move the camera."""

    def is_aborted(self) -> bool: ...

    def is_foreground(self, window_handle: int) -> bool: ...

    def scroll_wheel_while_guarded(self, window_handle: int, notches: int) -> None: ...

    def send_key_while_guarded(
        self, window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None: ...

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None: ...


class CameraAligner:
    """Drive one client's camera to the calibrated zoom hard-stop and ~45 degree pitch."""

    def __init__(
        self,
        adapter: CameraInputAdapter,
        window_handle: int,
        *,
        config: CameraAlignmentConfig | None = None,
        locate_minimap_geometry: MinimapLocator | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._adapter = adapter
        self._window_handle = window_handle
        self._config = config or CameraAlignmentConfig()
        self._locate_minimap_geometry = locate_minimap_geometry
        self._sleep = sleep

    def align(self) -> CameraAlignmentStatus:
        """Run the standardized sequence, halting before any step that is no longer safe."""

        blocked = self._blocked()
        if blocked is not None:
            return blocked

        # The minimap runs first so the pointer ends over the client centre, which is where
        # the wheel notches of the camera zoom have to land.
        blocked = self._zoom_minimap_out()
        if blocked is not None:
            return blocked

        self._adapter.scroll_wheel_while_guarded(self._window_handle, self._config.zoom_out_notches)
        blocked = self._settle_then_check()
        if blocked is not None:
            return blocked

        self._adapter.send_key_while_guarded(
            self._window_handle,
            self._config.pitch_up_virtual_key,
            self._config.pitch_up_hold_seconds,
        )
        blocked = self._settle_then_check()
        if blocked is not None:
            return blocked

        self._adapter.send_key_while_guarded(
            self._window_handle,
            self._config.pitch_down_virtual_key,
            self._config.pitch_down_pulse_seconds,
        )
        blocked = self._settle_then_check()
        if blocked is not None:
            return blocked
        return CameraAlignmentStatus.ALIGNED

    def _zoom_minimap_out(self) -> CameraAlignmentStatus | None:
        """Click the minimap into its zoom-out hard stop, or report why it could not.

        Without a locator the caller has no frame source to find the widget with, so the
        camera part of the sequence runs on its own rather than failing.
        """

        if self._locate_minimap_geometry is None:
            return None
        geometry = self._locate_minimap_geometry()
        if geometry is None:
            return CameraAlignmentStatus.MINIMAP_NOT_FOUND
        button_x, button_y = minimap_zoom_out_button(geometry)
        for _ in range(self._config.minimap_zoom_out_clicks):
            blocked = self._blocked()
            if blocked is not None:
                return blocked
            self._adapter.click_client(self._window_handle, button_x, button_y)
            self._sleep(self._config.minimap_click_settle_seconds)
        return self._blocked()

    def _settle_then_check(self) -> CameraAlignmentStatus | None:
        self._sleep(self._config.step_settle_seconds)
        return self._blocked()

    def _blocked(self) -> CameraAlignmentStatus | None:
        """Report why the sequence must not continue, or None while it stays safe."""

        if self._adapter.is_aborted():
            return CameraAlignmentStatus.ABORTED
        if not self._adapter.is_foreground(self._window_handle):
            return CameraAlignmentStatus.FOCUS_LOST
        return None
