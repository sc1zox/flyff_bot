"""Tests for unrecoverable-stuck detection, teleporter reset, and persistence (US-051)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from flyff_bot.features.automation.emergency_persistence import (
    load_emergency_config,
    save_emergency_config,
)
from flyff_bot.features.automation.emergency_recovery import (
    DEFAULT_PROGRESS_DISTANCE_UNITS,
    DEFAULT_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    EmergencyRecoveryAction,
    EmergencyRecoveryConfig,
    EmergencyRecoveryMonitor,
)
from flyff_bot.features.navigation.teleporter_models import TeleporterDestination

TIMEOUT_SECONDS = 60.0
DESTINATION = TeleporterDestination(
    destination_id=7,
    name="Eden",
    search_text="Eden",
    world_id=2,
    anchor_x=100.0,
    anchor_z=200.0,
)
CONFIG = EmergencyRecoveryConfig(
    destination=DESTINATION,
    stuck_timeout_seconds=TIMEOUT_SECONDS,
    confirmation_timeout_seconds=2.0,
)


def test_the_stuck_timer_accumulates_only_across_the_ticks_it_is_stepped() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)

    monitor.observe(0.0, position_x=0.0, position_z=0.0)
    monitor.observe(10.0, position_x=0.0, position_z=0.0)
    monitor.observe(25.0, position_x=0.0, position_z=0.0)

    assert monitor.stuck_seconds == pytest.approx(25.0)


def test_a_halted_span_never_counts_towards_the_timeout() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_z=0.0)
    monitor.observe(5.0, position_x=0.0, position_z=0.0)

    monitor.halt()
    decision = monitor.observe(3600.0, position_x=0.0, position_z=0.0)

    assert monitor.stuck_seconds == pytest.approx(5.0)
    assert decision.action is EmergencyRecoveryAction.NONE


def test_verified_displacement_cancels_the_accumulated_stuck_span() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_z=0.0)
    monitor.observe(30.0, position_x=0.0, position_z=0.0)
    assert monitor.stuck_seconds == pytest.approx(30.0)

    monitor.observe(31.0, position_x=40.0, position_z=0.0)

    assert monitor.stuck_seconds == pytest.approx(0.0)


def test_jitter_below_the_progress_distance_is_not_treated_as_progress() -> None:
    monitor = EmergencyRecoveryMonitor(replace(CONFIG, progress_distance_units=10.0))
    monitor.observe(0.0, position_x=0.0, position_z=0.0)

    monitor.observe(20.0, position_x=3.0, position_z=2.0)

    assert monitor.stuck_seconds == pytest.approx(20.0)


def test_an_engaged_target_cancels_the_accumulated_stuck_span() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_z=0.0)
    monitor.observe(45.0, position_x=0.0, position_z=0.0)

    monitor.observe(46.0, position_x=0.0, position_z=0.0, engaged=True)

    assert monitor.stuck_seconds == pytest.approx(0.0)


def test_an_unknown_position_neither_advances_nor_cancels_the_reference() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_z=0.0)

    monitor.observe(10.0)
    monitor.observe(20.0, position_x=0.0, position_z=0.0)

    assert monitor.stuck_seconds == pytest.approx(20.0)


def test_the_expired_timer_asks_for_the_selected_client_destination() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_z=0.0)

    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_z=0.0)

    assert decision.action is EmergencyRecoveryAction.TELEPORT
    assert decision.destination is DESTINATION


def test_an_unselected_destination_reports_the_recovery_as_unavailable() -> None:
    monitor = EmergencyRecoveryMonitor(
        EmergencyRecoveryConfig(destination=None, stuck_timeout_seconds=TIMEOUT_SECONDS)
    )
    monitor.observe(0.0, position_x=0.0, position_z=0.0)

    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_z=0.0)

    assert decision.action is EmergencyRecoveryAction.UNAVAILABLE
    assert decision.destination is None


@pytest.mark.parametrize(
    "timeout_seconds",
    [9.9, 300.1],
)
def test_a_timeout_outside_the_supported_range_is_refused(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="Unrecoverable stuck timeout"):
        EmergencyRecoveryConfig(stuck_timeout_seconds=timeout_seconds)


def test_the_emergency_settings_survive_a_restart_with_a_selected_destination(
    tmp_path: Path,
) -> None:
    path = tmp_path / "emergency.json"
    stored = replace(CONFIG, stuck_timeout_seconds=125.0)

    save_emergency_config(stored, path, destinations=(DESTINATION,))

    assert load_emergency_config(path, destinations=(DESTINATION,)) == stored
    absent = load_emergency_config(tmp_path / "absent.json", destinations=(DESTINATION,))
    assert absent.destination is None
    assert absent.stuck_timeout_seconds == pytest.approx(
        DEFAULT_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS
    )


def test_an_unreadable_emergency_config_falls_back_to_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "emergency.json"
    path.write_text("{not json}", encoding="utf-8")

    assert load_emergency_config(path) == EmergencyRecoveryConfig()


def test_progress_is_measured_in_client_world_units() -> None:
    # Regression for BUG-020: the threshold was calibrated in minimap pixels while the
    # session feeds live GPS world coordinates into it.
    monitor = EmergencyRecoveryMonitor(CONFIG)
    jitter = DEFAULT_PROGRESS_DISTANCE_UNITS / 2.0
    walked = DEFAULT_PROGRESS_DISTANCE_UNITS * 2.0

    monitor.observe(0.0, position_x=100.0, position_z=100.0)
    monitor.observe(10.0, position_x=100.0 + jitter, position_z=100.0)
    assert monitor.stuck_seconds == pytest.approx(10.0)

    monitor.observe(20.0, position_x=100.0 + walked, position_z=100.0)
    assert monitor.stuck_seconds == pytest.approx(0.0)
