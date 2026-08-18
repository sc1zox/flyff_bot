"""Measured position estimation, tracking quality, and stall detection for pathing.

Position and heading are measured from the client's minimap
(`flyff_bot.features.vision.minimap`) rather than extrapolated from dispatched key presses.
The command model below is only a short-term predictor for the ticks between two usable
measurements, and every constant in it is fitted from the recordings documented in
`docs/sources/2026-08-18-minimap-odometry-calibration.md`.

The canonical unit is the **minimap pixel at the calibrated zoom level** (US-035): the
client does not display a run speed, so no world-unit conversion can be measured and none
is introduced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_A,
    VIRTUAL_KEY_D,
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.navigation.spatial import WorldPoint
from flyff_bot.features.vision.minimap import (
    FULL_TURN_DEGREES,
    MAXIMUM_INTER_FRAME_DISPLACEMENT_PIXELS,
    MinimapReading,
    zoom_signature_matches,
)
from flyff_bot.features.vision.models import CapturedFrame

# Fitted from the `walk-1` burst: 346 minimap crops recorded at 91 frames/s while `W` was
# held for 3.0 s. Correlating 40 different start frames against the frame at key release
# gives 9.41 +- 0.12 minimap px/s, and the measured travel bearing of 136.3 deg agrees with
# the marker heading of 139.6 deg read from the same frames.
MEASURED_FORWARD_SPEED_PIXELS_PER_SECOND = 9.4
# Fitted from the `turn-1` burst: 61 full frames recorded at 9 frames/s while `RIGHT` was
# held for 6.0 s, yielding 1430.9 deg of marker rotation. A least-squares fit over the held
# span gives 239.96 deg/s with a residual standard deviation of 4.3 deg.
MEASURED_TURN_DEGREES_PER_SECOND = 240.0

# The client's own acceleration and deceleration are folded into the two constants above.
# The recorded coast tails bound their contribution: 0.85-0.97 px of travel after `W` was
# released (3.4 % of the 27.6 px traverse) and 2.5 deg of rotation after `RIGHT` was
# released (0.2 % of 1430.9 deg), all of it inside the first sample after release.
FORWARD_COAST_PIXELS = 1.0
TURN_COAST_DEGREES = 2.5

# Prediction is only trustworthy while its worst-case error stays inside one grid cell. At
# the fitted forward speed a fully wrong prediction accumulates 9.4 px/s, so 1.5 s stays
# below the 15 px default cell size.
DEFAULT_PREDICTION_GRACE_SECONDS = 1.5
# One deviating zoom signature can also be a transient redraw, so a change is only accepted
# after this many consecutive readings disagree with the anchored value.
DEFAULT_ZOOM_CHANGE_CONFIRMATIONS = 5

# Standing still measured 0.02 px/s sustained and never more than 1.8 px/s instantaneous,
# against 9.4 px/s while running, so this threshold separates the two with a wide margin.
DEFAULT_MEASURED_MOTION_THRESHOLD_PIXELS_PER_SECOND = 3.0
DEFAULT_MOTION_THRESHOLD = 1.5
DEFAULT_STALL_TIMEOUT_SECONDS = 5.0
DEFAULT_MOVEMENT_GRACE_SECONDS = 2.0
DEFAULT_MOTION_SAMPLE_STRIDE = 8
# The player model is drawn in the middle of the third-person viewport, so its running
# animation keeps producing pixel differences while the world stands still. These fractions
# are the share of the frame that is excluded around that centre. They are estimates, not
# values calibrated against measured client frames, and they are only reached on the
# fallback path that runs when the minimap measurement is unavailable.
DEFAULT_CENTER_MASK_WIDTH_FRACTION = 0.34
DEFAULT_CENTER_MASK_HEIGHT_FRACTION = 0.5
# One delayed or dropped capture must not be able to satisfy the whole stall timeout by itself.
MAXIMUM_STALL_SAMPLE_SECONDS = 1.0
HALF_TURN_DEGREES = 180.0

# Flyff's default controls turn the character with `A`/`D` exactly as the arrow keys do, so all
# four keys rotate the estimated heading instead of translating the estimated position.
ROTATION_VIRTUAL_KEYS = frozenset(
    {VIRTUAL_KEY_LEFT, VIRTUAL_KEY_RIGHT, VIRTUAL_KEY_A, VIRTUAL_KEY_D}
)
CLOCKWISE_VIRTUAL_KEYS = frozenset({VIRTUAL_KEY_RIGHT, VIRTUAL_KEY_D})


class TrackingQuality(StrEnum):
    """How the current position estimate was obtained."""

    MEASURED = "measured"
    PREDICTED = "predicted"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class MovementModel:
    """Fitted client movement rates used to predict between minimap measurements."""

    forward_speed_pixels_per_second: float = MEASURED_FORWARD_SPEED_PIXELS_PER_SECOND
    turn_degrees_per_second: float = MEASURED_TURN_DEGREES_PER_SECOND

    def __post_init__(self) -> None:
        if self.forward_speed_pixels_per_second <= 0.0:
            raise ValueError("Forward speed must be positive.")
        if self.turn_degrees_per_second <= 0.0:
            raise ValueError("Turn rate must be positive.")

    @property
    def maximum_measurement_interval_seconds(self) -> float:
        """Return how long two correlated frames may be apart before overlap is too small."""

        return MAXIMUM_INTER_FRAME_DISPLACEMENT_PIXELS / self.forward_speed_pixels_per_second


@dataclass(frozen=True, slots=True)
class TrackingConfig:
    """How long prediction may substitute for measurement, and when zoom counts as changed."""

    prediction_grace_seconds: float = DEFAULT_PREDICTION_GRACE_SECONDS
    zoom_change_confirmations: int = DEFAULT_ZOOM_CHANGE_CONFIRMATIONS

    def __post_init__(self) -> None:
        if self.prediction_grace_seconds < 0.0:
            raise ValueError("Prediction grace must not be negative.")
        if self.zoom_change_confirmations <= 0:
            raise ValueError("Zoom change confirmation count must be positive.")


@dataclass(frozen=True, slots=True)
class StallConfig:
    """How little movement the client may show before it counts as stalled."""

    measured_motion_threshold_pixels_per_second: float = (
        DEFAULT_MEASURED_MOTION_THRESHOLD_PIXELS_PER_SECOND
    )
    motion_threshold: float = DEFAULT_MOTION_THRESHOLD
    stall_timeout_seconds: float = DEFAULT_STALL_TIMEOUT_SECONDS
    movement_grace_seconds: float = DEFAULT_MOVEMENT_GRACE_SECONDS
    sample_stride: int = DEFAULT_MOTION_SAMPLE_STRIDE
    center_mask_width_fraction: float = DEFAULT_CENTER_MASK_WIDTH_FRACTION
    center_mask_height_fraction: float = DEFAULT_CENTER_MASK_HEIGHT_FRACTION

    def __post_init__(self) -> None:
        if self.measured_motion_threshold_pixels_per_second <= 0.0:
            raise ValueError("Measured stall motion threshold must be positive.")
        if self.motion_threshold <= 0.0:
            raise ValueError("Stall motion threshold must be positive.")
        if self.stall_timeout_seconds <= 0.0:
            raise ValueError("Stall timeout must be positive.")
        if self.movement_grace_seconds < 0.0:
            raise ValueError("Stall movement grace must not be negative.")
        if self.sample_stride <= 0:
            raise ValueError("Stall sample stride must be positive.")
        for fraction in (self.center_mask_width_fraction, self.center_mask_height_fraction):
            if not 0.0 <= fraction < 1.0:
                raise ValueError("Stall centre mask fractions must be within [0.0, 1.0).")


@dataclass(frozen=True, slots=True)
class TrackingUpdate:
    """The outcome of folding one minimap reading into the position estimate."""

    quality: TrackingQuality
    measured_speed_pixels_per_second: float | None
    zoom_changed: bool


class MovementTracker:
    """Estimate a session-relative position from the minimap, predicting between readings.

    The estimate is anchored on the last confident measurement. Dispatched key presses only
    move a separate prediction offset, which the next measurement discards, so a wrong
    command model can never accumulate into the anchor.
    """

    def __init__(
        self, model: MovementModel | None = None, config: TrackingConfig | None = None
    ) -> None:
        self._model = model or MovementModel()
        self._config = config or TrackingConfig()
        self._anchor = WorldPoint(0.0, 0.0)
        self._anchor_heading_degrees = 0.0
        self._predicted_offset = WorldPoint(0.0, 0.0)
        self._predicted_turn_degrees = 0.0
        self._quality = TrackingQuality.DEGRADED
        self._measured_at_seconds: float | None = None
        self._observed_at_seconds: float | None = None
        self._zoom_signature_anchor: float | None = None
        self._zoom_deviations = 0
        self._zoom_changed = False

    @property
    def position(self) -> WorldPoint:
        """Return the estimated position relative to the session start point."""

        return WorldPoint(
            self._anchor.x + self._predicted_offset.x, self._anchor.y + self._predicted_offset.y
        )

    @property
    def heading_degrees(self) -> float:
        """Return the estimated facing as a clockwise compass bearing."""

        return (self._anchor_heading_degrees + self._predicted_turn_degrees) % FULL_TURN_DEGREES

    @property
    def quality(self) -> TrackingQuality:
        """Return how the current estimate was obtained."""

        return self._quality

    @property
    def zoom_changed(self) -> bool:
        """Return whether the minimap zoom left the level the tracker was anchored to."""

        return self._zoom_changed

    @property
    def zoom_signature_anchor(self) -> float | None:
        """Return the zoom signature every position of this session is expressed in."""

        return self._zoom_signature_anchor

    def reset(self) -> None:
        """Return the estimate to the session origin and drop the zoom anchor."""

        self._anchor = WorldPoint(0.0, 0.0)
        self._anchor_heading_degrees = 0.0
        self._predicted_offset = WorldPoint(0.0, 0.0)
        self._predicted_turn_degrees = 0.0
        self._quality = TrackingQuality.DEGRADED
        self._measured_at_seconds = None
        self._observed_at_seconds = None
        self._zoom_signature_anchor = None
        self._zoom_deviations = 0
        self._zoom_changed = False

    def relocate(self, position: WorldPoint) -> None:
        """Re-express the estimate in a loaded profile's coordinate frame (US-036).

        Only the translational origin moves. Heading is measured from the north-up minimap
        and is therefore already absolute (US-035), and the zoom anchor is left untouched
        because the caller has just verified that the live scale matches the stored one.
        """

        self._anchor = position
        self._predicted_offset = WorldPoint(0.0, 0.0)

    def reanchor(self) -> None:
        """Accept the current minimap zoom as the level this session is measured in."""

        self._zoom_signature_anchor = None
        self._zoom_deviations = 0
        self._zoom_changed = False

    def apply(self, virtual_key: int, duration_seconds: float) -> None:
        """Predict one dispatched movement or rotation pulse until the next measurement."""

        if duration_seconds <= 0.0:
            return
        if virtual_key in ROTATION_VIRTUAL_KEYS:
            direction = 1.0 if virtual_key in CLOCKWISE_VIRTUAL_KEYS else -1.0
            self._predicted_turn_degrees += (
                direction * self._model.turn_degrees_per_second * duration_seconds
            )
            return
        if virtual_key == VIRTUAL_KEY_W:
            radians = math.radians(self.heading_degrees)
            distance = self._model.forward_speed_pixels_per_second * duration_seconds
            self._predicted_offset = WorldPoint(
                self._predicted_offset.x + math.sin(radians) * distance,
                self._predicted_offset.y + math.cos(radians) * distance,
            )

    def observe(self, reading: MinimapReading | None, at_seconds: float) -> TrackingUpdate:
        """Fold one minimap reading into the estimate and return the resulting quality."""

        elapsed = (
            None
            if self._observed_at_seconds is None
            else max(0.0, at_seconds - self._observed_at_seconds)
        )
        self._observed_at_seconds = at_seconds
        if reading is None:
            return self._without_measurement(at_seconds)
        self._track_zoom(reading.zoom_signature)
        if self._zoom_changed:
            # A rescaled measurement is worse than no measurement: it looks confident and
            # writes silently rescaled cells into the learned map.
            self._quality = TrackingQuality.DEGRADED
            self._measured_at_seconds = None
            return TrackingUpdate(self._quality, None, zoom_changed=True)
        if reading.displacement is None:
            return self._without_measurement(at_seconds)
        if elapsed is not None and elapsed > self._model.maximum_measurement_interval_seconds:
            # Two frames that far apart can have scrolled further than the aperture overlap
            # the correlation needs, so the response is no longer evidence of anything.
            return self._without_measurement(at_seconds)

        self._anchor = WorldPoint(
            self._anchor.x + reading.player_dx, self._anchor.y + reading.player_dy
        )
        self._predicted_offset = WorldPoint(0.0, 0.0)
        if reading.heading_degrees is not None:
            self._anchor_heading_degrees = reading.heading_degrees
            self._predicted_turn_degrees = 0.0
        else:
            self._anchor_heading_degrees = self.heading_degrees
            self._predicted_turn_degrees = 0.0
        self._quality = TrackingQuality.MEASURED
        self._measured_at_seconds = at_seconds
        speed = (
            reading.displacement.magnitude / elapsed
            if elapsed is not None and elapsed > 0.0
            else None
        )
        return TrackingUpdate(self._quality, speed, zoom_changed=False)

    def _without_measurement(self, at_seconds: float) -> TrackingUpdate:
        measured_at = self._measured_at_seconds
        within_grace = (
            measured_at is not None
            and at_seconds - measured_at <= self._config.prediction_grace_seconds
        )
        self._quality = TrackingQuality.PREDICTED if within_grace else TrackingQuality.DEGRADED
        return TrackingUpdate(self._quality, None, zoom_changed=self._zoom_changed)

    def _track_zoom(self, signature: float) -> None:
        anchor = self._zoom_signature_anchor
        if anchor is None:
            self._zoom_signature_anchor = signature
            self._zoom_deviations = 0
            return
        if not zoom_signature_matches(anchor, signature):
            self._zoom_deviations += 1
            if self._zoom_deviations >= self._config.zoom_change_confirmations:
                self._zoom_changed = True
            return
        self._zoom_deviations = 0


class StallDetector:
    """Report a stall when commanded forward movement produces no measured displacement.

    While the minimap measurement is unavailable the detector falls back to the peripheral
    pixel-difference signature, which is the only signal left at that point. The two paths
    are mutually exclusive: the expensive frame signature is never computed while a measured
    displacement is available.
    """

    def __init__(self, config: StallConfig | None = None) -> None:
        self._config = config or StallConfig()
        self._signature: npt.NDArray[np.float32] | None = None
        self._peripheral_mask: npt.NDArray[np.bool_] | None = None
        self._stalled_seconds = 0.0
        self._sampled_at_seconds: float | None = None
        self._commanded_at_seconds: float | None = None

    @property
    def is_stalled(self) -> bool:
        """Return whether motionless scenery persisted for the configured stall timeout."""

        return self._stalled_seconds >= self._config.stall_timeout_seconds

    @property
    def stalled_seconds(self) -> float:
        """Return how long commanded forward movement has produced no movement."""

        return self._stalled_seconds

    def reset(self) -> None:
        """Forget the previous frame and clear the accumulated stall time."""

        self._signature = None
        self._stalled_seconds = 0.0
        self._sampled_at_seconds = None
        self._commanded_at_seconds = None

    def observe(
        self,
        frame: CapturedFrame | None,
        *,
        measured_speed_pixels_per_second: float | None,
        movement_commanded: bool,
        at_seconds: float,
    ) -> bool:
        """Return the current stall verdict for one tick."""

        if measured_speed_pixels_per_second is not None:
            return self._observe_measured(
                measured_speed_pixels_per_second,
                movement_commanded=movement_commanded,
                at_seconds=at_seconds,
            )
        return self._observe_frame(
            frame, movement_commanded=movement_commanded, at_seconds=at_seconds
        )

    def _observe_measured(
        self, speed: float, *, movement_commanded: bool, at_seconds: float
    ) -> bool:
        previous_at_seconds = self._sampled_at_seconds
        self._signature = None
        self._sampled_at_seconds = at_seconds
        verdict = self._gate(movement_commanded, at_seconds)
        if verdict is not None:
            return verdict
        if previous_at_seconds is None:
            return self.is_stalled
        elapsed = min(max(0.0, at_seconds - previous_at_seconds), MAXIMUM_STALL_SAMPLE_SECONDS)
        if speed < self._config.measured_motion_threshold_pixels_per_second:
            self._stalled_seconds += elapsed
        else:
            self._stalled_seconds = 0.0
        return self.is_stalled

    def _observe_frame(
        self, frame: CapturedFrame | None, *, movement_commanded: bool, at_seconds: float
    ) -> bool:
        if frame is None:
            return self.is_stalled
        signature = self._frame_signature(frame)
        previous = self._signature
        previous_at_seconds = self._sampled_at_seconds
        self._signature = signature
        self._sampled_at_seconds = at_seconds
        verdict = self._gate(movement_commanded, at_seconds)
        if verdict is not None:
            return verdict
        if previous is None or previous.shape != signature.shape or previous_at_seconds is None:
            return self.is_stalled
        elapsed = min(max(0.0, at_seconds - previous_at_seconds), MAXIMUM_STALL_SAMPLE_SECONDS)
        if self._motion(signature, previous) < self._config.motion_threshold:
            self._stalled_seconds += elapsed
        else:
            self._stalled_seconds = 0.0
        return self.is_stalled

    def _gate(self, movement_commanded: bool, at_seconds: float) -> bool | None:
        """Return a final verdict for ticks that carry no stall evidence, else ``None``."""

        if movement_commanded:
            self._commanded_at_seconds = at_seconds
            return None
        if self._within_movement_grace(at_seconds):
            # A tick without a movement command in an ongoing travel phase carries no
            # evidence either way, so the accumulated stall time is held.
            return self.is_stalled
        self._stalled_seconds = 0.0
        return False

    def _within_movement_grace(self, at_seconds: float) -> bool:
        if self._commanded_at_seconds is None:
            return False
        return at_seconds - self._commanded_at_seconds <= self._config.movement_grace_seconds

    def _motion(
        self, signature: npt.NDArray[np.float32], previous: npt.NDArray[np.float32]
    ) -> float:
        difference = np.abs(signature - previous)
        return float(difference[self._mask_for(difference.shape)].mean())

    def _mask_for(self, shape: tuple[int, ...]) -> npt.NDArray[np.bool_]:
        """Return the sample mask that excludes the centred player-character region."""

        cached = self._peripheral_mask
        if cached is not None and cached.shape == shape:
            return cached
        height, width = shape
        mask = np.ones(shape, dtype=np.bool_)
        half_height = int(height * self._config.center_mask_height_fraction / 2.0)
        half_width = int(width * self._config.center_mask_width_fraction / 2.0)
        if half_height > 0 and half_width > 0:
            center_y = height // 2
            center_x = width // 2
            mask[
                center_y - half_height : center_y + half_height,
                center_x - half_width : center_x + half_width,
            ] = False
        self._peripheral_mask = mask
        return mask

    def _frame_signature(self, frame: CapturedFrame) -> npt.NDArray[np.float32]:
        stride = self._config.sample_stride
        sampled = frame.pixels[::stride, ::stride]
        return sampled.astype(np.float32).mean(axis=2)


def bearing_degrees(origin: WorldPoint, target: WorldPoint) -> float:
    """Return the clockwise compass bearing from one estimated point to another."""

    return math.degrees(math.atan2(target.x - origin.x, target.y - origin.y)) % FULL_TURN_DEGREES


def heading_error_degrees(heading_degrees: float, bearing: float) -> float:
    """Return the shortest signed turn from a heading to a bearing."""

    return (bearing - heading_degrees + HALF_TURN_DEGREES) % FULL_TURN_DEGREES - HALF_TURN_DEGREES


def distance_pixels(origin: WorldPoint, target: WorldPoint) -> float:
    """Return the straight-line distance between two estimated points, in minimap pixels."""

    return math.hypot(target.x - origin.x, target.y - origin.y)
