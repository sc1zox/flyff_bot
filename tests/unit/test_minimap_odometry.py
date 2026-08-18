"""Tests for the read-only minimap sensor against recorded client frames.

Every assertion here replays frames shipped in `data/assets/fixtures/minimap/`, whose
measurement is written up in `docs/sources/2026-08-18-minimap-odometry-calibration.md`.
"""

from __future__ import annotations

import math

import cv2
import minimap_fixtures as fixtures
import numpy as np
import numpy.typing as npt
import pytest

from flyff_bot.features.navigation.tracking import (
    MEASURED_FORWARD_SPEED_PIXELS_PER_SECOND,
    MEASURED_TURN_DEGREES_PER_SECOND,
)
from flyff_bot.features.vision.minimap import (
    MAXIMUM_INTER_FRAME_DISPLACEMENT_PIXELS,
    MINIMAP_CENTRE_RIGHT_OFFSET_PIXELS,
    MINIMAP_CENTRE_TOP_OFFSET_PIXELS,
    MINIMUM_CORRELATION_RESPONSE,
    ZOOM_SIGNATURE_TOLERANCE_FRACTION,
    MinimapGeometry,
    MinimapOdometer,
    locate_minimap,
    measure_translation,
    read_minimap,
)
from flyff_bot.features.vision.models import CapturedFrame, ClientSize

# The recorded bursts were captured at a 1600x1200 client, where the ring centre sits three
# pixels left of and one pixel above the nominal anchor.
CENTRE_TOLERANCE_PIXELS = 5.0
# Integrating many short measured steps under-reads a traverse by about 3 % (see the
# calibration source), so the fitted constants are pinned with a margin above that.
FITTED_CONSTANT_TOLERANCE = 0.10
# The heading of the marker read from the walk burst and the bearing of the motion measured
# from the same frames agreed to 3.3 deg.
HEADING_AGREEMENT_TOLERANCE_DEGREES = 6.0
# Half a revolution at the fitted turn rate: two samples further apart than this cannot be
# unwrapped into a rotation direction at all.
UNAMBIGUOUS_TURN_GAP_SECONDS = 180.0 / MEASURED_TURN_DEGREES_PER_SECOND


def _scroll(frame: CapturedFrame, matrix: npt.NDArray[np.float32]) -> CapturedFrame:
    """Return the frame with its whole content translated by an affine matrix."""

    scrolled = cv2.warpAffine(
        frame.pixels,
        matrix,
        (frame.client_size.width, frame.client_size.height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )
    return CapturedFrame(np.ascontiguousarray(scrolled, dtype=np.uint8), frame.client_size)


def _nominal_centre(frame: CapturedFrame) -> tuple[float, float]:
    return (
        frame.client_size.width - MINIMAP_CENTRE_RIGHT_OFFSET_PIXELS,
        MINIMAP_CENTRE_TOP_OFFSET_PIXELS,
    )


def test_the_locator_anchors_the_ring_to_the_client_edges_in_client_area_coordinates() -> None:
    for name in ("zoom_default", "zoom_maximum_out"):
        frame = fixtures.still(name)
        geometry = locate_minimap(frame)

        assert geometry is not None, name
        nominal_x, nominal_y = _nominal_centre(frame)
        assert abs(geometry.centre_x - nominal_x) <= CENTRE_TOLERANCE_PIXELS
        assert abs(geometry.centre_y - nominal_y) <= CENTRE_TOLERANCE_PIXELS


def test_the_ring_geometry_is_identical_at_both_recorded_zoom_levels() -> None:
    """The `+` / `-` buttons rescale the content, not the widget."""

    default = locate_minimap(fixtures.still("zoom_default"))
    zoomed_out = locate_minimap(fixtures.still("zoom_maximum_out"))

    assert default == zoomed_out


def test_a_client_too_small_for_the_widget_reports_not_found() -> None:
    tiny = CapturedFrame(np.zeros((80, 120, 3), dtype=np.uint8), ClientSize(120, 80))

    assert locate_minimap(tiny) is None


def test_a_collapsed_minimap_reports_not_found_instead_of_an_out_of_bounds_region() -> None:
    """The operator can close the widget with its ring buttons; scenery is left behind."""

    frame = fixtures.still("zoom_default")
    pixels = frame.pixels.copy()
    centre_x, centre_y = (round(value) for value in _nominal_centre(frame))
    # Tile the scenery that sits beside the widget over the widget itself, which is what
    # closing it leaves behind.
    beside = pixels[0:20, centre_x - 90 : centre_x - 70]
    top = max(0, centre_y - 90)
    patch = np.tile(beside, (10, 10, 1))[
        0 : centre_y + 90 - top, 0 : frame.client_size.width - centre_x + 90
    ]
    pixels[top : centre_y + 90, centre_x - 90 :] = patch
    collapsed = CapturedFrame(np.ascontiguousarray(pixels), frame.client_size)

    assert locate_minimap(collapsed) is None


def test_the_heading_is_read_from_the_colour_keyed_marker_not_from_the_ring_centre() -> None:
    frame = fixtures.still("zoom_default")
    geometry = locate_minimap(frame)
    assert geometry is not None

    sample = read_minimap(frame, geometry)

    assert sample.heading_degrees is not None
    assert 0.0 <= sample.heading_degrees < 360.0


def test_the_marker_nose_points_along_the_measured_direction_of_travel() -> None:
    """The 180 deg sign convention, validated against motion the client really performed."""

    walk = fixtures.sequence("walk")
    odometer = MinimapOdometer()
    east = north = 0.0
    heading: float | None = None
    for record in walk.frames:
        reading = odometer.observe(record.frame)
        assert reading is not None
        if record.seconds > walk.key_up_seconds:
            break
        east += reading.player_dx
        north += reading.player_dy
        heading = heading if heading is not None else reading.heading_degrees

    travel_bearing = math.degrees(math.atan2(east, north)) % 360.0

    assert heading is not None
    assert abs(heading - travel_bearing) < HEADING_AGREEMENT_TOLERANCE_DEGREES


def test_phase_correlation_recovers_a_known_synthetic_scroll() -> None:
    frame = fixtures.still("zoom_default")
    geometry = locate_minimap(frame)
    assert geometry is not None
    reference = read_minimap(frame, geometry)

    for shift_x, shift_y in ((1, 0), (3, 2), (6, -4), (12, 9), (16, -10)):
        matrix = np.array([[1.0, 0.0, shift_x], [0.0, 1.0, shift_y]], dtype=np.float32)
        scrolled = _scroll(frame, matrix)
        sample = read_minimap(scrolled, geometry)

        measured = measure_translation(reference, sample)

        assert measured is not None, (shift_x, shift_y)
        assert measured.x == pytest.approx(float(shift_x), abs=0.5)
        assert measured.y == pytest.approx(float(shift_y), abs=0.5)


def test_unrelated_minimap_content_falls_below_the_confidence_gate() -> None:
    """A zoom step and a different zone both fail the gate rather than reporting a jump."""

    default = fixtures.still("zoom_default")
    geometry = locate_minimap(default)
    assert geometry is not None
    reference = read_minimap(default, geometry)
    rescaled = read_minimap(fixtures.still("zoom_maximum_out"), geometry)

    assert measure_translation(reference, rescaled) is None


def test_a_displacement_beyond_the_measured_bound_is_rejected() -> None:
    frame = fixtures.still("zoom_default")
    geometry = locate_minimap(frame)
    assert geometry is not None
    reference = read_minimap(frame, geometry)
    jump = round(MAXIMUM_INTER_FRAME_DISPLACEMENT_PIXELS) + 10
    matrix = np.array([[1.0, 0.0, jump], [0.0, 1.0, 0.0]], dtype=np.float32)
    sample = read_minimap(_scroll(frame, matrix), geometry)

    assert measure_translation(reference, sample) is None


def test_the_zoom_signature_separates_the_two_recorded_zoom_levels() -> None:
    default = fixtures.still("zoom_default")
    geometry = locate_minimap(default)
    assert geometry is not None

    at_default = read_minimap(default, geometry).zoom_signature
    at_maximum_out = read_minimap(fixtures.still("zoom_maximum_out"), geometry).zoom_signature

    deviation = abs(at_maximum_out - at_default) / at_default
    assert deviation > ZOOM_SIGNATURE_TOLERANCE_FRACTION


def test_the_zoom_signature_is_stable_while_the_map_scrolls_at_one_zoom_level() -> None:
    walk = fixtures.sequence("walk")
    geometry = locate_minimap(walk.frames[0].frame)
    assert geometry is not None

    signatures = [read_minimap(record.frame, geometry).zoom_signature for record in walk.frames]

    anchor = signatures[0]
    assert max(abs(value - anchor) / anchor for value in signatures) < (
        ZOOM_SIGNATURE_TOLERANCE_FRACTION
    )


def test_the_odometer_reports_confident_readings_across_the_recorded_walk() -> None:
    walk = fixtures.sequence("walk")
    odometer = MinimapOdometer()

    responses = []
    for record in walk.frames:
        reading = odometer.observe(record.frame)
        assert reading is not None
        if reading.displacement is not None:
            responses.append(reading.displacement.response)

    assert len(responses) == len(walk.frames) - 1
    assert min(responses) >= MINIMUM_CORRELATION_RESPONSE


def test_the_fitted_forward_speed_reproduces_the_recorded_walk() -> None:
    """Regression pin for `MEASURED_FORWARD_SPEED_PIXELS_PER_SECOND`."""

    walk = fixtures.sequence("walk")
    odometer = MinimapOdometer()
    east = north = 0.0
    elapsed = 0.0
    for record in walk.frames:
        reading = odometer.observe(record.frame)
        assert reading is not None
        if record.seconds > walk.key_up_seconds:
            break
        east += reading.player_dx
        north += reading.player_dy
        elapsed = record.seconds

    measured_speed = math.hypot(east, north) / elapsed

    assert measured_speed == pytest.approx(
        MEASURED_FORWARD_SPEED_PIXELS_PER_SECOND, rel=FITTED_CONSTANT_TOLERANCE
    )


def test_the_fitted_turn_rate_reproduces_the_recorded_turn() -> None:
    """Regression pin for `MEASURED_TURN_DEGREES_PER_SECOND`."""

    turn = fixtures.sequence("turn")
    geometry = locate_minimap(turn.frames[0].frame)
    assert geometry is not None

    previous: float | None = None
    previous_seconds = 0.0
    rotated = 0.0
    elapsed = 0.0
    for record in turn.frames:
        # Two frames further apart than half a revolution cannot be unwrapped at all, so the
        # regression stops at the first such gap rather than guessing across it.
        if (
            previous is not None
            and record.seconds - previous_seconds > UNAMBIGUOUS_TURN_GAP_SECONDS
        ):
            break
        heading = read_minimap(record.frame, geometry).heading_degrees
        assert heading is not None
        if previous is not None:
            rotated += (heading - previous + 180.0) % 360.0 - 180.0
            elapsed = record.seconds
        previous = heading
        previous_seconds = record.seconds

    assert elapsed > 1.0
    assert rotated / elapsed == pytest.approx(
        MEASURED_TURN_DEGREES_PER_SECOND, rel=FITTED_CONSTANT_TOLERANCE
    )


def test_a_pure_rotation_produces_no_measured_translation() -> None:
    """Turning in place must not move the estimate: the minimap is player-centred."""

    turn = fixtures.sequence("turn")
    odometer = MinimapOdometer()
    east = north = 0.0
    for record in turn.frames:
        reading = odometer.observe(record.frame)
        assert reading is not None
        east += reading.player_dx
        north += reading.player_dy

    assert math.hypot(east, north) < 1.0


def test_an_absent_frame_clears_the_measurement_chain() -> None:
    walk = fixtures.sequence("walk")
    odometer = MinimapOdometer()
    odometer.observe(walk.frames[0].frame)

    assert odometer.observe(None) is None

    resumed = odometer.observe(walk.frames[1].frame)
    assert resumed is not None
    assert resumed.displacement is None


def test_an_invalid_geometry_is_rejected() -> None:
    with pytest.raises(ValueError):
        MinimapGeometry(centre_x=10.0, centre_y=10.0, surface_radius=0)
