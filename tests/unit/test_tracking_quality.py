"""Tests for the tracking-quality state machine and the map writes it gates (US-035)."""

from __future__ import annotations

import pytest
from minimap_doubles import (
    CONFIDENT_RESPONSE,
    REFERENCE_ZOOM_SIGNATURE,
    MirrorOdometer,
    ScriptedOdometer,
)

from flyff_bot.features.automation.controllers import VIRTUAL_KEY_RIGHT, VIRTUAL_KEY_W
from flyff_bot.features.automation.models import Position, Viewport, WorldState
from flyff_bot.features.navigation.pathing import PathingConfig, PathingController
from flyff_bot.features.navigation.spatial import GridCell, SpatialMap, SpatialMapConfig
from flyff_bot.features.navigation.tracking import (
    MEASURED_TURN_DEGREES_PER_SECOND,
    MovementModel,
    MovementTracker,
    TrackingConfig,
    TrackingQuality,
)
from flyff_bot.features.vision.minimap import (
    ZOOM_SIGNATURE_TOLERANCE_FRACTION,
    MinimapDisplacement,
    MinimapReading,
)

GRACE_SECONDS = 1.0
CELL_SIZE_PIXELS = 10.0
MODEL = MovementModel(forward_speed_pixels_per_second=10.0, turn_degrees_per_second=90.0)
MAP_CONFIG = SpatialMapConfig(cell_size_pixels=CELL_SIZE_PIXELS, maximum_link_span_cells=8)
PATHING_CONFIG = PathingConfig(
    movement=MODEL, tracking=TrackingConfig(prediction_grace_seconds=GRACE_SECONDS)
)


def _reading(
    east: float = 0.0,
    north: float = 0.0,
    *,
    heading_degrees: float | None = 0.0,
    response: float = CONFIDENT_RESPONSE,
    zoom_signature: float = REFERENCE_ZOOM_SIGNATURE,
) -> MinimapReading:
    """Build one reading from the player motion it should describe."""

    return MinimapReading(
        displacement=MinimapDisplacement(x=-east, y=north, response=response),
        heading_degrees=heading_degrees,
        zoom_signature=zoom_signature,
    )


def _blind_reading(zoom_signature: float = REFERENCE_ZOOM_SIGNATURE) -> MinimapReading:
    """Build a reading whose correlation was rejected by the confidence gate."""

    return MinimapReading(displacement=None, heading_degrees=None, zoom_signature=zoom_signature)


def _state(seconds: float) -> WorldState:
    return WorldState(
        observed_at_seconds=seconds,
        position=Position(0, 0),
        nearby_mob_count=0,
        inventory=(),
        progress_marker=0,
        viewport=Viewport(800, 600),
    )


def _tracker() -> MovementTracker:
    return MovementTracker(MODEL, TrackingConfig(prediction_grace_seconds=GRACE_SECONDS))


def test_a_confident_reading_measures_the_position_and_the_heading() -> None:
    tracker = _tracker()

    tracker.observe(_reading(), 0.0)
    update = tracker.observe(_reading(3.0, 4.0, heading_degrees=37.0), 0.5)

    assert update.quality is TrackingQuality.MEASURED
    assert tracker.quality is TrackingQuality.MEASURED
    assert tracker.position.x == pytest.approx(3.0)
    assert tracker.position.y == pytest.approx(4.0)
    assert tracker.heading_degrees == pytest.approx(37.0)
    assert update.measured_speed_pixels_per_second == pytest.approx(10.0)


def test_the_measured_heading_replaces_the_predicted_one() -> None:
    tracker = _tracker()
    tracker.observe(_reading(heading_degrees=0.0), 0.0)

    tracker.apply(VIRTUAL_KEY_RIGHT, 1.0)
    assert tracker.heading_degrees == pytest.approx(90.0)

    tracker.observe(_reading(heading_degrees=12.0), 0.2)

    assert tracker.heading_degrees == pytest.approx(12.0)


def test_prediction_covers_the_grace_period_and_then_degrades() -> None:
    tracker = _tracker()
    tracker.observe(_reading(), 0.0)
    tracker.observe(_reading(), 0.1)

    tracker.apply(VIRTUAL_KEY_W, 0.5)
    predicted = tracker.observe(_blind_reading(), 0.6)

    assert predicted.quality is TrackingQuality.PREDICTED
    assert tracker.position.y == pytest.approx(5.0)

    degraded = tracker.observe(_blind_reading(), 0.1 + GRACE_SECONDS + 0.01)

    assert degraded.quality is TrackingQuality.DEGRADED


def test_a_measurement_after_a_degraded_span_recovers_the_quality() -> None:
    tracker = _tracker()
    tracker.observe(_reading(), 0.0)
    tracker.observe(_blind_reading(), 5.0)
    assert tracker.quality is TrackingQuality.DEGRADED

    recovered = tracker.observe(_reading(1.0, 0.0), 5.1)

    assert recovered.quality is TrackingQuality.MEASURED


def test_a_missing_reading_is_treated_as_no_measurement() -> None:
    tracker = _tracker()
    tracker.observe(_reading(), 0.0)

    assert tracker.observe(None, 0.1).quality is TrackingQuality.PREDICTED
    assert tracker.observe(None, 10.0).quality is TrackingQuality.DEGRADED


def test_a_tick_slower_than_the_measured_bound_reports_predicted() -> None:
    """Two frames that far apart may have scrolled past the overlap the gate assumes."""

    beyond = MODEL.maximum_measurement_interval_seconds + 0.1
    tracker = MovementTracker(
        MODEL, TrackingConfig(prediction_grace_seconds=beyond + GRACE_SECONDS)
    )
    tracker.observe(_reading(), 0.0)

    update = tracker.observe(_reading(1.0, 0.0), beyond)

    assert update.quality is TrackingQuality.PREDICTED
    assert tracker.position.x == pytest.approx(0.0)


def test_a_changed_zoom_level_degrades_the_tracker_until_it_is_reanchored() -> None:
    """The corruption mode that would otherwise write silently rescaled cells."""

    tracker = _tracker()
    tracker.observe(_reading(), 0.0)
    assert tracker.zoom_signature_anchor == pytest.approx(REFERENCE_ZOOM_SIGNATURE)
    rescaled = REFERENCE_ZOOM_SIGNATURE * (1.0 + 2.0 * ZOOM_SIGNATURE_TOLERANCE_FRACTION)

    seconds = 0.0
    for _tick in range(TrackingConfig().zoom_change_confirmations):
        seconds += 0.1
        update = tracker.observe(_reading(1.0, 0.0, zoom_signature=rescaled), seconds)

    assert update.zoom_changed
    assert tracker.zoom_changed
    assert tracker.quality is TrackingQuality.DEGRADED

    # A confident reading at the new zoom must not silently resume measuring.
    seconds += 0.1
    assert (
        tracker.observe(_reading(1.0, 0.0, zoom_signature=rescaled), seconds).quality
        is TrackingQuality.DEGRADED
    )

    tracker.reanchor()
    seconds += 0.1
    tracker.observe(_reading(1.0, 0.0, zoom_signature=rescaled), seconds)
    seconds += 0.1

    assert (
        tracker.observe(_reading(1.0, 0.0, zoom_signature=rescaled), seconds).quality
        is TrackingQuality.MEASURED
    )


def test_one_deviating_signature_does_not_count_as_a_zoom_change() -> None:
    tracker = _tracker()
    tracker.observe(_reading(), 0.0)
    rescaled = REFERENCE_ZOOM_SIGNATURE * (1.0 + 2.0 * ZOOM_SIGNATURE_TOLERANCE_FRACTION)

    tracker.observe(_reading(1.0, 0.0, zoom_signature=rescaled), 0.1)
    tracker.observe(_reading(1.0, 0.0), 0.2)

    assert not tracker.zoom_changed
    assert tracker.quality is TrackingQuality.MEASURED


def test_reset_drops_the_zoom_anchor_and_the_estimate() -> None:
    tracker = _tracker()
    tracker.observe(_reading(5.0, 5.0), 0.0)

    tracker.reset()

    assert tracker.zoom_signature_anchor is None
    assert tracker.quality is TrackingQuality.DEGRADED
    assert tracker.position.x == pytest.approx(0.0)


def test_invalid_tracking_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        TrackingConfig(prediction_grace_seconds=-1.0)
    with pytest.raises(ValueError):
        TrackingConfig(zoom_change_confirmations=0)


def test_the_map_stays_read_only_while_tracking_is_degraded() -> None:
    spatial_map = SpatialMap(MAP_CONFIG)
    odometer = ScriptedOdometer([_reading(), _blind_reading(), _blind_reading()])
    controller = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)

    controller.observe(_state(0.0))
    learned = len(spatial_map.known_cells())
    assert learned == 1

    controller.observe(_state(0.5))
    controller.observe(_state(10.0))

    assert controller.tracking_quality is TrackingQuality.DEGRADED
    assert len(spatial_map.known_cells()) == learned


def test_recovery_after_a_degraded_span_creates_no_edge_across_the_gap() -> None:
    spatial_map = SpatialMap(MAP_CONFIG)
    odometer = ScriptedOdometer(
        [
            _reading(),
            _blind_reading(),
            _reading(4.0 * CELL_SIZE_PIXELS, 0.0),
        ]
    )
    controller = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)

    controller.observe(_state(0.0))
    controller.observe(_state(10.0))
    controller.observe(_state(10.1))

    assert controller.tracking_quality is TrackingQuality.MEASURED
    assert spatial_map.cell_of(controller.position) == GridCell(4, 0)
    assert spatial_map.neighbors(GridCell(0, 0)) == ()
    assert spatial_map.neighbors(GridCell(4, 0)) == ()


def test_motion_the_controller_never_commanded_still_moves_the_estimate() -> None:
    """Combat auto-run, knockback, and manual movement all reach the estimate this way."""

    odometer = MirrorOdometer(MODEL)
    controller = PathingController(SpatialMap(MAP_CONFIG), config=PATHING_CONFIG, odometer=odometer)
    controller.observe(_state(0.0))

    odometer.displace(7.0, -3.0)
    controller.observe(_state(0.2))

    assert controller.position.x == pytest.approx(7.0)
    assert controller.position.y == pytest.approx(-3.0)


def test_tracking_only_ticks_follow_motion_without_learning_anything() -> None:
    """The standby path: the operator moves the character while the session is paused."""

    spatial_map = SpatialMap(MAP_CONFIG)
    odometer = MirrorOdometer(MODEL)
    controller = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)

    odometer.displace(5.0 * CELL_SIZE_PIXELS, 0.0)
    quality = controller.track(_state(0.1))

    assert quality is TrackingQuality.MEASURED
    assert controller.position.x == pytest.approx(5.0 * CELL_SIZE_PIXELS)
    assert spatial_map.known_cells() == ()


def test_the_snapshot_carries_the_zoom_level_the_positions_are_expressed_in() -> None:
    odometer = MirrorOdometer(MODEL, zoom_signature=123.5)
    controller = PathingController(SpatialMap(MAP_CONFIG), config=PATHING_CONFIG, odometer=odometer)

    assert controller.snapshot().zoom_signature_anchor is None

    controller.observe(_state(0.0))

    assert controller.snapshot().zoom_signature_anchor == pytest.approx(123.5)


def test_the_default_turn_pulse_stays_inside_the_heading_tolerance() -> None:
    """A pulse longer than the tolerance would oscillate around the target bearing."""

    config = PathingConfig()
    turned = MEASURED_TURN_DEGREES_PER_SECOND * config.turn_duration_seconds

    assert turned < config.heading_tolerance_degrees
