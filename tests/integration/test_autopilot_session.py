"""End-to-end unattended-session coverage against fakes only (US-086).

These tests drive the real `FarmingOrchestrator.tick` path and the real `SessionWorker`, with
no game client, no window, and no dispatched Win32 input. What they prove is exactly what the
manual Windows checklist would otherwise have to prove by hand: a tick fault is contained, a
death is a state rather than a potion loop, a lost focus resumes on its own, and the arbiter
picks the next goal without the operator.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import cast

from flyff_bot.features.automation.autopilot import (
    MAXIMUM_EVENT_BUDGET,
    AutopilotCompletionReason,
    AutopilotConfig,
    AutopilotGoalKind,
)
from flyff_bot.features.automation.models import (
    PlayerVitals,
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import (
    FarmingConfig,
    FarmingMode,
    FarmingOrchestrator,
)
from flyff_bot.features.automation.respawn import RespawnMenuPerceiver, RespawnObservation
from flyff_bot.features.diagnostics import SessionEventKind, SessionEventLogger
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.ui.session_worker import SessionWorker

WINDOW_HANDLE = 4_242
FALLBACK_MONSTER = "Mushpang"
TICK_INTERVAL_SECONDS = 0.01
WORKER_WAIT_TIMEOUT_SECONDS = 5.0
DEAD_HP = 0.0
ALIVE_HP = 100.0
RESPAWN_POSITION = Position(320, 240)


class _Clock:
    """A monotonic clock the test advances explicitly."""

    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


class _Pipeline:
    """Replay a scripted perception sequence, holding the last state once exhausted."""

    def __init__(self, states: list[WorldState]) -> None:
        self._states = list(states)
        self._index = 0

    def tick(
        self,
        _window_handle: int,
        _previous: WorldState,
        *,
        poll_live_providers: bool = True,
    ) -> PerceptionTick:
        del poll_live_providers
        state = self._states[min(self._index, len(self._states) - 1)]
        self._index += 1
        return PerceptionTick(state, (), frozenset(), frame=None)


class _RaisingPipeline:
    """Fail every perception tick the way an unexpected runtime fault would."""

    def __init__(self) -> None:
        self.calls = 0

    def tick(
        self,
        _window_handle: int,
        _previous: WorldState,
        *,
        poll_live_providers: bool = True,
    ) -> PerceptionTick:
        del poll_live_providers
        self.calls += 1
        raise RuntimeError("perception exploded")


class _InputAdapter:
    """Record every dispatch instead of touching Win32."""

    def __init__(self, *, foreground: bool = True) -> None:
        self.foreground = foreground
        self.aborted = False
        self.clicks: list[tuple[int, int, int]] = []
        self.keys: list[tuple[int, float]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def close_window(self, _window_handle: int) -> bool:
        return True

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_keys_while_guarded(
        self,
        _window_handle: int,
        virtual_keys: tuple[int, ...] | list[int] | int,
        duration_seconds: float,
    ) -> None:
        keys = (virtual_keys,) if isinstance(virtual_keys, int) else tuple(virtual_keys)
        for key in keys:
            self.keys.append((key, duration_seconds))


class _RespawnPerceiver:
    """Report the revive option without OCR or a frame."""

    def __init__(self, observation: RespawnObservation) -> None:
        self._observation = observation
        self.calls = 0

    def observe(self, _frame: CapturedFrame | None) -> RespawnObservation:
        self.calls += 1
        return self._observation


def _state(at_seconds: float, *, hp: float = ALIVE_HP) -> WorldState:
    return WorldState(
        observed_at_seconds=at_seconds,
        position=Position(0, 0),
        nearby_mob_count=0,
        inventory=(),
        progress_marker=0,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=(),
        viewport=Viewport(640, 480),
        player_vitals=PlayerVitals(hp_percentage=hp),
    )


def _orchestrator(
    pipeline: object,
    adapter: _InputAdapter,
    clock: _Clock,
    *,
    autopilot: AutopilotConfig | None = None,
    respawn_menu_perceiver: _RespawnPerceiver | None = None,
    event_logger: SessionEventLogger | None = None,
) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast("PerceptionPipeline", pipeline),
        adapter,
        WINDOW_HANDLE,
        config=FarmingConfig(
            autopilot=autopilot or AutopilotConfig(fallback_monster_names=(FALLBACK_MONSTER,)),
        ),
        respawn_menu_perceiver=cast("RespawnMenuPerceiver", respawn_menu_perceiver),
        event_logger=event_logger,
        clock=clock,
    )


def _kinds(logger: SessionEventLogger) -> list[SessionEventKind]:
    return [event.kind for event in logger.recent_events]


def _mode(orchestrator: FarmingOrchestrator) -> FarmingMode:
    """Read the mode through a widening call, so a later assertion is not narrowed away."""

    return orchestrator.mode


def test_a_tick_fault_keeps_the_worker_alive_and_shows_a_faulted_session(tmp_path: Path) -> None:
    logger = SessionEventLogger(tmp_path)
    clock = _Clock()
    adapter = _InputAdapter()
    orchestrator = _orchestrator(
        _RaisingPipeline(),
        adapter,
        clock,
        # A budget the repeated faults of this fake cannot exhaust, so the assertion is about
        # containment rather than about how many ticks happened to run before the worker stopped.
        autopilot=AutopilotConfig(maximum_tick_faults=MAXIMUM_EVENT_BUDGET),
        event_logger=logger,
    )
    orchestrator.arm_autopilot()
    faulted = threading.Event()

    def on_fault(error: Exception) -> None:
        orchestrator.handle_tick_fault(error)
        faulted.set()

    worker = SessionWorker(orchestrator.tick, TICK_INTERVAL_SECONDS, on_fault=on_fault)

    worker.start()
    try:
        assert faulted.wait(WORKER_WAIT_TIMEOUT_SECONDS)
        # The worker survives the fault and keeps ticking rather than dying silently.
        assert worker.is_running
    finally:
        worker.stop()

    assert orchestrator.mode is FarmingMode.FAULTED
    assert adapter.keys == []
    fault_events = [
        event for event in logger.recent_events if event.kind is SessionEventKind.TICK_FAULT
    ]
    assert fault_events
    assert fault_events[0].exception_type == "RuntimeError"
    assert fault_events[0].exception_message == "perception exploded"
    snapshot = orchestrator.autopilot_snapshot
    assert snapshot.tick_faults >= 1
    assert snapshot.last_fault == "RuntimeError: perception exploded"


def test_repeated_tick_faults_end_the_session_on_the_configured_budget() -> None:
    clock = _Clock()
    adapter = _InputAdapter()
    orchestrator = _orchestrator(
        _RaisingPipeline(),
        adapter,
        clock,
        autopilot=AutopilotConfig(maximum_tick_faults=1),
    )
    orchestrator.arm_autopilot()

    for _ in range(3):
        try:
            orchestrator.tick()
        except RuntimeError as error:
            orchestrator.handle_tick_fault(error)

    assert orchestrator.mode is FarmingMode.COMPLETED
    summary = orchestrator.autopilot_snapshot
    assert summary.completion_reason is AutopilotCompletionReason.TICK_FAULT_BUDGET


def test_a_death_dispatches_the_observed_revive_option_and_resumes_on_respawn() -> None:
    clock = _Clock()
    adapter = _InputAdapter()
    perceiver = _RespawnPerceiver(RespawnObservation(RESPAWN_POSITION, "lodestar", 1.0))
    pipeline = _Pipeline(
        [
            _state(1.0, hp=DEAD_HP),
            _state(3.0, hp=DEAD_HP),
            _state(4.0, hp=DEAD_HP),
            _state(6.0, hp=ALIVE_HP),
        ]
    )
    orchestrator = _orchestrator(pipeline, adapter, clock, respawn_menu_perceiver=perceiver)
    orchestrator.arm_autopilot()

    orchestrator.tick()
    orchestrator.tick()

    assert _mode(orchestrator) is FarmingMode.DEAD
    # No vitals key is dispatched at zero HP; the death state replaces the potion loop.
    assert adapter.keys == []

    orchestrator.tick()
    assert adapter.clicks == [(WINDOW_HANDLE, RESPAWN_POSITION.x, RESPAWN_POSITION.y)]

    orchestrator.tick()
    assert _mode(orchestrator) is FarmingMode.SEARCHING
    assert orchestrator.autopilot_snapshot.deaths == 1
    assert orchestrator.autopilot_snapshot.recoveries == 1


def test_a_death_without_autopilot_waits_for_the_operator() -> None:
    clock = _Clock()
    adapter = _InputAdapter()
    orchestrator = _orchestrator(
        _Pipeline([_state(1.0, hp=DEAD_HP), _state(3.0, hp=DEAD_HP)]), adapter, clock
    )
    orchestrator.start()

    orchestrator.tick()
    orchestrator.tick()

    assert orchestrator.mode is FarmingMode.DEAD
    assert adapter.clicks == []
    assert adapter.keys == []


def test_more_deaths_than_the_budget_pause_autopilot_instead_of_respawning_again() -> None:
    clock = _Clock()
    adapter = _InputAdapter()
    perceiver = _RespawnPerceiver(RespawnObservation(RESPAWN_POSITION, "lodestar", 1.0))
    orchestrator = _orchestrator(
        _Pipeline(
            [
                _state(1.0, hp=DEAD_HP),
                _state(3.0, hp=DEAD_HP),
                _state(4.0, hp=ALIVE_HP),
                _state(5.0, hp=DEAD_HP),
                _state(7.0, hp=DEAD_HP),
            ]
        ),
        adapter,
        clock,
        autopilot=AutopilotConfig(maximum_deaths=1),
        respawn_menu_perceiver=perceiver,
    )
    orchestrator.arm_autopilot()

    for _ in range(5):
        orchestrator.tick()

    assert orchestrator.autopilot_snapshot.deaths == 2
    assert not orchestrator.autopilot_snapshot.armed
    assert orchestrator.mode is FarmingMode.PAUSED
    assert adapter.clicks == []


def test_lost_focus_pauses_and_the_session_resumes_itself_after_the_backoff() -> None:
    clock = _Clock()
    adapter = _InputAdapter()
    orchestrator = _orchestrator(
        _Pipeline([_state(float(index)) for index in range(1, 8)]),
        adapter,
        clock,
        autopilot=AutopilotConfig(
            recovery_backoff_seconds=2.0, fallback_monster_names=(FALLBACK_MONSTER,)
        ),
    )
    orchestrator.arm_autopilot()

    adapter.foreground = False
    orchestrator.tick()
    assert _mode(orchestrator) is FarmingMode.PAUSED

    adapter.foreground = True
    orchestrator.tick()
    # The backoff has not elapsed, so the session waits rather than thrashing.
    assert _mode(orchestrator) is FarmingMode.PAUSED

    clock.advance(3.0)
    orchestrator.tick()

    assert _mode(orchestrator) is FarmingMode.SEARCHING
    assert orchestrator.autopilot_snapshot.recoveries == 1


def test_a_client_absent_beyond_the_maximum_ends_the_session() -> None:
    clock = _Clock()
    adapter = _InputAdapter(foreground=False)
    orchestrator = _orchestrator(
        _Pipeline([_state(float(index)) for index in range(1, 6)]),
        adapter,
        clock,
        autopilot=AutopilotConfig(maximum_absence_seconds=5.0),
    )
    orchestrator.arm_autopilot()

    orchestrator.tick()
    clock.advance(10.0)
    orchestrator.tick()

    assert orchestrator.mode is FarmingMode.COMPLETED
    assert (
        orchestrator.autopilot_snapshot.completion_reason
        is AutopilotCompletionReason.CLIENT_ABSENCE
    )


def test_arming_autopilot_arbitrates_a_goal_without_operator_input() -> None:
    clock = _Clock()
    adapter = _InputAdapter()
    logger = SessionEventLogger()
    orchestrator = _orchestrator(
        _Pipeline([_state(1.0)]),
        adapter,
        clock,
        event_logger=logger,
    )

    orchestrator.arm_autopilot()

    snapshot = orchestrator.autopilot_snapshot
    assert snapshot.armed
    assert snapshot.goal is not None
    assert snapshot.goal.goal is AutopilotGoalKind.FALLBACK_FARM
    assert SessionEventKind.AUTOPILOT_GOAL in _kinds(logger)
    # The arbiter armed the configured fallback zone by itself.
    assert orchestrator.kill_goals.active_class_names == frozenset({FALLBACK_MONSTER})


def test_the_time_budget_finishes_the_session_with_a_reportable_summary() -> None:
    clock = _Clock()
    adapter = _InputAdapter()
    orchestrator = _orchestrator(
        _Pipeline([_state(float(index)) for index in range(1, 5)]),
        adapter,
        clock,
        autopilot=AutopilotConfig(
            session_budget_seconds=60.0, fallback_monster_names=(FALLBACK_MONSTER,)
        ),
    )
    orchestrator.arm_autopilot()
    orchestrator.tick()

    clock.advance(61.0)
    orchestrator.tick()

    assert orchestrator.mode is FarmingMode.COMPLETED
    snapshot = orchestrator.autopilot_snapshot
    assert snapshot.completion_reason is AutopilotCompletionReason.TIME_BUDGET
    assert not snapshot.armed
    assert adapter.keys == []
