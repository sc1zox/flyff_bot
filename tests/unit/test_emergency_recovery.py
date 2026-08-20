"""Tests for unrecoverable-stuck detection, emergency teleport, and persistence (US-040, US-059)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from flyff_bot.features.automation.emergency_persistence import (
    load_emergency_config,
    save_emergency_config,
)
from flyff_bot.features.automation.emergency_recovery import (
    DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY,
    DEFAULT_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    EmergencyRecoveryAction,
    EmergencyRecoveryConfig,
    EmergencyRecoveryMonitor,
    EmergencyTeleportDispatcher,
    EmergencyTeleportInputAdapter,
)

WINDOW_HANDLE = 42
TIMEOUT_SECONDS = 60.0
CONFIG = EmergencyRecoveryConfig(stuck_timeout_seconds=TIMEOUT_SECONDS, settle_delay_seconds=2.0)


class _Adapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.keys: list[tuple[int, float]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))


def test_the_stuck_timer_accumulates_only_across_the_ticks_it_is_stepped() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)

    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    monitor.observe(10.0, position_x=0.0, position_y=0.0)
    monitor.observe(25.0, position_x=0.0, position_y=0.0)

    assert monitor.stuck_seconds == pytest.approx(25.0)


def test_a_halted_span_never_counts_towards_the_timeout() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    monitor.observe(5.0, position_x=0.0, position_y=0.0)

    monitor.halt()
    decision = monitor.observe(3600.0, position_x=0.0, position_y=0.0)

    assert monitor.stuck_seconds == pytest.approx(5.0)
    assert decision.action is EmergencyRecoveryAction.NONE


def test_verified_displacement_cancels_the_accumulated_stuck_span() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    monitor.observe(30.0, position_x=0.0, position_y=0.0)
    assert monitor.stuck_seconds == pytest.approx(30.0)

    monitor.observe(31.0, position_x=40.0, position_y=0.0)

    assert monitor.stuck_seconds == pytest.approx(0.0)


def test_jitter_below_the_progress_distance_is_not_treated_as_progress() -> None:
    monitor = EmergencyRecoveryMonitor(replace(CONFIG, progress_distance_pixels=10.0))
    monitor.observe(0.0, position_x=0.0, position_y=0.0)

    monitor.observe(20.0, position_x=3.0, position_y=2.0)

    assert monitor.stuck_seconds == pytest.approx(20.0)


def test_an_engaged_target_cancels_the_accumulated_stuck_span() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    monitor.observe(45.0, position_x=0.0, position_y=0.0)

    monitor.observe(46.0, position_x=0.0, position_y=0.0, engaged=True)

    assert monitor.stuck_seconds == pytest.approx(0.0)


def test_an_unknown_position_neither_advances_nor_cancels_the_reference() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)

    monitor.observe(10.0)
    monitor.observe(20.0, position_x=0.0, position_y=0.0)

    assert monitor.stuck_seconds == pytest.approx(20.0)


def test_the_expired_timer_asks_for_the_configured_teleport_hotkey() -> None:
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)

    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_y=0.0)

    assert decision.action is EmergencyRecoveryAction.TELEPORT
    assert decision.virtual_key == DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY


def test_an_unassigned_hotkey_reports_the_recovery_as_unavailable() -> None:
    monitor = EmergencyRecoveryMonitor(
        EmergencyRecoveryConfig(teleport_virtual_key=None, stuck_timeout_seconds=TIMEOUT_SECONDS)
    )
    monitor.observe(0.0, position_x=0.0, position_y=0.0)

    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_y=0.0)

    assert decision.action is EmergencyRecoveryAction.UNAVAILABLE
    assert decision.virtual_key is None


@pytest.mark.parametrize(
    "timeout_seconds",
    [9.9, 300.1],
)
def test_a_timeout_outside_the_supported_range_is_refused(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="Unrecoverable stuck timeout"):
        EmergencyRecoveryConfig(stuck_timeout_seconds=timeout_seconds)


@pytest.mark.parametrize(
    "adapter",
    [_Adapter(aborted=True), _Adapter(foreground=False)],
)
def test_a_lost_foreground_or_engaged_emergency_stop_aborts_the_teleport(
    adapter: _Adapter,
) -> None:
    dispatcher = EmergencyTeleportDispatcher(
        cast(EmergencyTeleportInputAdapter, adapter), WINDOW_HANDLE
    )
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_y=0.0)

    assert not dispatcher.dispatch(decision)
    assert adapter.keys == []


def test_the_guarded_dispatcher_sends_the_hotkey_while_the_client_is_safe() -> None:
    adapter = _Adapter()
    dispatcher = EmergencyTeleportDispatcher(
        cast(EmergencyTeleportInputAdapter, adapter), WINDOW_HANDLE
    )
    monitor = EmergencyRecoveryMonitor(CONFIG)
    monitor.observe(0.0, position_x=0.0, position_y=0.0)
    decision = monitor.observe(TIMEOUT_SECONDS, position_x=0.0, position_y=0.0)

    assert dispatcher.dispatch(decision)
    assert adapter.keys == [
        (DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY, CONFIG.key_press_duration_seconds)
    ]


def test_the_emergency_settings_survive_a_restart_including_an_unassigned_hotkey(
    tmp_path: Path,
) -> None:
    path = tmp_path / "emergency.json"
    stored = EmergencyRecoveryConfig(teleport_virtual_key=None, stuck_timeout_seconds=125.0)

    save_emergency_config(stored, path)

    assert load_emergency_config(path) == stored
    assert load_emergency_config(tmp_path / "absent.json").stuck_timeout_seconds == pytest.approx(
        DEFAULT_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS
    )


def test_an_unreadable_emergency_config_falls_back_to_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "emergency.json"
    path.write_text("{not json}", encoding="utf-8")

    assert load_emergency_config(path) == EmergencyRecoveryConfig()
