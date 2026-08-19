"""Tests for multi-target monster selection, kill quotas, and their persistence."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from flyff_bot.features.automation.kill_goals import (
    UNLIMITED_KILL_QUOTA,
    KillGoalConfig,
    KillGoalTracker,
    MobKillProgress,
    MobKillQuota,
)
from flyff_bot.features.automation.kill_persistence import SqliteKillLog
from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import (
    FarmingMode,
    FarmingOrchestrator,
)
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.ui.dashboard import BotStatus, DashboardFeed, DashboardUpdate

WINDOW_HANDLE = 42
FLAME = VisibleMob(0, "Flame", 0.9, 20, 20, 20, 20)
# Far enough from Flame that the dead-target lockout around the corpse cannot swallow it.
RAPRA = VisibleMob(1, "Rapra", 0.9, 300, 300, 20, 20)
FIXED_TIMESTAMP = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


class _Pipeline:
    def __init__(self, states: list[WorldState]) -> None:
        self._states = iter(states)

    def tick(self, _window_handle: int, _previous: WorldState) -> PerceptionTick:
        return PerceptionTick(next(self._states), (), frozenset())


class _InputAdapter:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int, int]] = []
        self.keys: list[tuple[int, float]] = []
        self.closed_windows: list[int] = []

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, _window_handle: int) -> bool:
        return True

    def close_window(self, window_handle: int) -> bool:
        self.closed_windows.append(window_handle)
        return True

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.keys.append((virtual_key, duration_seconds))


def _state(
    time: float,
    *,
    target: SelectedTarget | None = None,
    mobs: tuple[VisibleMob, ...] = (),
) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        selected_target=target or SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=Viewport(400, 400),
    )


def _kill_states(start_seconds: float, name: str, mobs: tuple[VisibleMob, ...]) -> list[WorldState]:
    """Return the four snapshots one verified engagement walks through."""

    return [
        _state(start_seconds, mobs=mobs),
        _state(start_seconds + 1.0, target=SelectedTarget(TargetState.VALID, name, 100)),
        _state(start_seconds + 2.0, target=SelectedTarget(TargetState.VALID, name, 50)),
        _state(start_seconds + 3.0, target=SelectedTarget(TargetState.NONE, None, 0)),
    ]


def _orchestrator(
    states: list[WorldState],
    adapter: _InputAdapter,
    tracker: KillGoalTracker,
    *,
    dashboard_feed: DashboardFeed | None = None,
    observer_log: list[frozenset[str]] | None = None,
) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
        dashboard_feed=dashboard_feed,
        kill_goals=tracker,
        on_target_classes_changed=None if observer_log is None else observer_log.append,
    )


def test_quota_rejects_an_empty_class_name_and_a_negative_target() -> None:
    with pytest.raises(ValueError):
        MobKillQuota(" ", 1)
    with pytest.raises(ValueError):
        MobKillQuota("Flame", -1)


def test_configuration_rejects_a_repeated_monster_class() -> None:
    with pytest.raises(ValueError):
        KillGoalConfig((MobKillQuota("Flame", 1), MobKillQuota("Flame", 2)))


def test_tracker_counts_kills_per_class_and_reports_progress() -> None:
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 2), MobKillQuota("Rapra", 3))))

    assert tracker.record_kill("Flame")
    assert tracker.record_kill("Rapra")
    assert tracker.record_kill("Flame")

    assert tracker.progress == (
        MobKillProgress("Flame", 2, 2),
        MobKillProgress("Rapra", 1, 3),
    )
    assert tracker.kills_for("Flame") == 2


def test_tracker_ignores_a_kill_it_cannot_attribute() -> None:
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 1),)))

    assert not tracker.record_kill(None)

    assert tracker.progress == (MobKillProgress("Flame", 0, 1),)
    assert not tracker.is_completed


def test_completed_quota_leaves_the_active_targeting_whitelist() -> None:
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 1), MobKillQuota("Rapra", 2))))
    assert tracker.active_class_names == frozenset({"Flame", "Rapra"})

    tracker.record_kill("Flame")

    assert tracker.active_class_names == frozenset({"Rapra"})
    assert not tracker.is_completed


def test_session_completes_only_once_every_bounded_quota_is_reached() -> None:
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 1), MobKillQuota("Rapra", 1))))

    tracker.record_kill("Flame")
    assert not tracker.is_completed

    tracker.record_kill("Rapra")
    assert tracker.is_completed


def test_an_unlimited_quota_never_completes_the_session() -> None:
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", UNLIMITED_KILL_QUOTA),)))

    tracker.record_kill("Flame")

    assert tracker.active_class_names == frozenset({"Flame"})
    assert not tracker.is_completed


def test_an_empty_selection_restricts_nothing_and_never_completes() -> None:
    tracker = KillGoalTracker()

    assert not tracker.has_quotas
    assert tracker.active_class_names == frozenset()
    assert not tracker.is_completed


def test_editing_a_quota_keeps_the_kills_already_counted() -> None:
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 1),)))
    tracker.record_kill("Flame")
    assert tracker.is_completed

    tracker.update_config(KillGoalConfig((MobKillQuota("Flame", 3),)))

    assert tracker.progress == (MobKillProgress("Flame", 1, 3),)
    assert not tracker.is_completed


def test_kill_events_are_persisted_with_their_class_session_and_timestamp(
    tmp_path: Path,
) -> None:
    log = SqliteKillLog(tmp_path / "kills.sqlite3")
    tracker = KillGoalTracker(
        KillGoalConfig((MobKillQuota("Flame", 2),)),
        session_id="session-a",
        recorder=log,
        clock=lambda: FIXED_TIMESTAMP,
    )

    tracker.record_kill("Flame")

    assert log.kill_counts("session-a") == {"Flame": 1}
    assert log.quotas("session-a") == (MobKillQuota("Flame", 2),)
    with closing(sqlite3.connect(log.path)) as connection:
        rows = connection.execute(
            "SELECT session_id, class_name, recorded_at FROM kill_events"
        ).fetchall()
    assert rows == [("session-a", "Flame", FIXED_TIMESTAMP.isoformat())]


def test_a_second_session_does_not_inherit_another_sessions_kills(tmp_path: Path) -> None:
    log = SqliteKillLog(tmp_path / "kills.sqlite3")
    KillGoalTracker(
        KillGoalConfig((MobKillQuota("Flame", 5),)), session_id="session-a", recorder=log
    ).record_kill("Flame")

    other = KillGoalTracker(
        KillGoalConfig((MobKillQuota("Flame", 5),)), session_id="session-b", recorder=log
    )

    assert other.progress == (MobKillProgress("Flame", 0, 5),)


def test_a_resumed_session_restores_the_progress_it_persisted(tmp_path: Path) -> None:
    log = SqliteKillLog(tmp_path / "kills.sqlite3")
    config = KillGoalConfig((MobKillQuota("Flame", 2),))
    first = KillGoalTracker(config, session_id="session-a", recorder=log)
    first.record_kill("Flame")

    resumed = KillGoalTracker(config, session_id="session-a", recorder=log)

    assert resumed.progress == (MobKillProgress("Flame", 1, 2),)
    resumed.record_kill("Flame")
    assert resumed.is_completed
    assert log.kill_counts("session-a") == {"Flame": 2}


def test_stored_quotas_are_replaced_rather_than_accumulated(tmp_path: Path) -> None:
    log = SqliteKillLog(tmp_path / "kills.sqlite3")
    tracker = KillGoalTracker(
        KillGoalConfig((MobKillQuota("Flame", 1), MobKillQuota("Rapra", 1))),
        session_id="session-a",
        recorder=log,
    )

    tracker.update_config(KillGoalConfig((MobKillQuota("Rapra", 4),)))

    assert log.quotas("session-a") == (MobKillQuota("Rapra", 4),)


def test_a_verified_kill_is_attributed_to_the_engaged_monster_class() -> None:
    adapter = _InputAdapter()
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 2), MobKillQuota("Rapra", 1))))
    orchestrator = _orchestrator(_kill_states(1.0, "Flame", (FLAME,)), adapter, tracker)
    orchestrator.start()

    for _ in range(4):
        result = orchestrator.tick()

    assert result.mode is FarmingMode.RECONCILING
    assert tracker.progress == (
        MobKillProgress("Flame", 1, 2),
        MobKillProgress("Rapra", 0, 1),
    )


def test_a_finished_quota_is_dropped_from_targeting_and_perception_mid_session() -> None:
    adapter = _InputAdapter()
    observed: list[frozenset[str]] = []
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 2), MobKillQuota("Rapra", 1))))
    orchestrator = _orchestrator(
        [
            *_kill_states(1.0, "Rapra", (FLAME, RAPRA)),
            _state(5.0, mobs=(FLAME, RAPRA)),
            _state(6.0, mobs=(FLAME, RAPRA)),
            _state(7.0, mobs=(FLAME, RAPRA)),
        ],
        adapter,
        tracker,
        observer_log=observed,
    )
    orchestrator.configure_kill_goals(tracker.config)
    orchestrator.start()

    for _ in range(4):
        orchestrator.tick()

    # Rapra sits closest to the viewport center, so it is the candidate that gets engaged.
    assert adapter.clicks == [(WINDOW_HANDLE, 310, 310)]
    assert observed[0] == frozenset({"Flame", "Rapra"})
    assert observed[-1] == frozenset({"Flame"})

    # The next candidate click must land on the only monster whose quota is still open;
    # the ticks in between only reconcile and retire the finished engagement.
    for _ in range(3):
        orchestrator.tick()
    assert adapter.clicks[-1] == (WINDOW_HANDLE, 30, 30)


def test_reaching_every_quota_completes_the_session() -> None:
    adapter = _InputAdapter()
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 1),)))
    orchestrator = _orchestrator(
        [*_kill_states(1.0, "Flame", (FLAME,)), _state(5.0, mobs=(FLAME,))], adapter, tracker
    )
    orchestrator.start()

    for _ in range(4):
        orchestrator.tick()
    result = orchestrator.tick()

    assert result.mode is FarmingMode.COMPLETED
    assert adapter.closed_windows == []


def test_a_completed_session_closes_the_client_when_the_operator_asked_for_it() -> None:
    adapter = _InputAdapter()
    tracker = KillGoalTracker(
        KillGoalConfig((MobKillQuota("Flame", 1),), close_client_on_completion=True)
    )
    orchestrator = _orchestrator(
        [*_kill_states(1.0, "Flame", (FLAME,)), _state(5.0), _state(6.0)], adapter, tracker
    )
    orchestrator.start()

    for _ in range(6):
        orchestrator.tick()

    assert orchestrator.mode is FarmingMode.COMPLETED
    # Exactly one request: a completed session keeps ticking in standby.
    assert adapter.closed_windows == [WINDOW_HANDLE]


def test_the_dashboard_receives_live_quota_progress_and_the_completed_state() -> None:
    adapter = _InputAdapter()
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    tracker = KillGoalTracker(KillGoalConfig((MobKillQuota("Flame", 1),)))
    orchestrator = _orchestrator(
        [*_kill_states(1.0, "Flame", (FLAME,)), _state(5.0)],
        adapter,
        tracker,
        dashboard_feed=feed,
    )
    orchestrator.start()

    for _ in range(5):
        orchestrator.tick()

    assert updates[-1].kill_progress == (MobKillProgress("Flame", 1, 1),)
    assert updates[-1].status is BotStatus.COMPLETED
