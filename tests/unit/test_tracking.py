"""Tests for the command-model prediction inside the measured movement tracker."""

from __future__ import annotations

import pytest

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_A,
    VIRTUAL_KEY_D,
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.navigation.spatial import WorldPoint
from flyff_bot.features.navigation.tracking import (
    MovementModel,
    MovementTracker,
    bearing_degrees,
    distance_pixels,
    heading_error_degrees,
)


def _tracker() -> MovementTracker:
    return MovementTracker(
        MovementModel(
            forward_speed_pixels_per_second=10.0,
            turn_degrees_per_second=90.0,
        )
    )


def test_movement_pulses_estimate_a_relative_position_and_heading() -> None:
    tracker = _tracker()

    tracker.apply(VIRTUAL_KEY_W, 1.0)

    assert tracker.position.x == pytest.approx(0.0, abs=1e-9)
    assert tracker.position.y == pytest.approx(10.0)

    tracker.apply(VIRTUAL_KEY_RIGHT, 1.0)
    tracker.apply(VIRTUAL_KEY_W, 1.0)

    assert tracker.heading_degrees == pytest.approx(90.0)
    assert tracker.position.x == pytest.approx(10.0)
    assert tracker.position.y == pytest.approx(10.0)

    tracker.apply(VIRTUAL_KEY_LEFT, 1.0)

    assert tracker.heading_degrees == pytest.approx(0.0)


def test_turn_keys_rotate_the_heading_instead_of_strafing_the_position() -> None:
    """BUG-009: `A`/`D` turn the character in Flyff, they do not translate it sideways."""

    tracker = _tracker()

    tracker.apply(VIRTUAL_KEY_D, 1.0)

    assert tracker.heading_degrees == pytest.approx(90.0)
    assert tracker.position == WorldPoint(0.0, 0.0)

    tracker.apply(VIRTUAL_KEY_A, 2.0)

    assert tracker.heading_degrees == pytest.approx(270.0)
    assert tracker.position == WorldPoint(0.0, 0.0)


def test_turn_keys_match_the_arrow_keys_they_share_a_rotation_direction_with() -> None:
    """BUG-009: `D` and Right turn clockwise, `A` and Left turn counter-clockwise."""

    turn_keys = _tracker()
    arrow_keys = _tracker()

    turn_keys.apply(VIRTUAL_KEY_D, 0.5)
    arrow_keys.apply(VIRTUAL_KEY_RIGHT, 0.5)

    assert turn_keys.heading_degrees == pytest.approx(arrow_keys.heading_degrees)

    turn_keys.apply(VIRTUAL_KEY_A, 1.5)
    arrow_keys.apply(VIRTUAL_KEY_LEFT, 1.5)

    assert turn_keys.heading_degrees == pytest.approx(arrow_keys.heading_degrees)


def test_a_turn_and_walk_sequence_predicts_a_square_back_to_the_origin() -> None:
    tracker = _tracker()

    for _side in range(4):
        tracker.apply(VIRTUAL_KEY_W, 1.0)
        tracker.apply(VIRTUAL_KEY_D, 1.0)

    assert tracker.heading_degrees == pytest.approx(0.0)
    assert distance_pixels(tracker.position, WorldPoint(0.0, 0.0)) == pytest.approx(0.0, abs=1e-9)


def test_zero_duration_pulses_and_unknown_keys_leave_the_estimate_untouched() -> None:
    tracker = _tracker()

    tracker.apply(VIRTUAL_KEY_W, 0.0)
    tracker.apply(0x00, 1.0)

    assert tracker.position == WorldPoint(0.0, 0.0)
    assert tracker.heading_degrees == pytest.approx(0.0)


def test_reset_returns_the_estimate_to_the_session_origin() -> None:
    tracker = _tracker()
    tracker.apply(VIRTUAL_KEY_W, 1.0)
    tracker.apply(VIRTUAL_KEY_D, 1.0)

    tracker.reset()

    assert tracker.position == WorldPoint(0.0, 0.0)
    assert tracker.heading_degrees == pytest.approx(0.0)


def test_invalid_movement_models_are_rejected() -> None:
    with pytest.raises(ValueError):
        MovementModel(forward_speed_pixels_per_second=0.0)
    with pytest.raises(ValueError):
        MovementModel(turn_degrees_per_second=0.0)


def test_bearing_and_heading_error_use_shortest_signed_turns() -> None:
    assert bearing_degrees(WorldPoint(0.0, 0.0), WorldPoint(0.0, 5.0)) == pytest.approx(0.0)
    assert bearing_degrees(WorldPoint(0.0, 0.0), WorldPoint(5.0, 0.0)) == pytest.approx(90.0)
    assert heading_error_degrees(350.0, 10.0) == pytest.approx(20.0)
    assert heading_error_degrees(10.0, 350.0) == pytest.approx(-20.0)
