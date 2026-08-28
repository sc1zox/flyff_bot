"""Unit tests for the background tick loop that keeps OCR off the Qt GUI thread."""

from __future__ import annotations

import threading

import pytest

from flyff_bot.ui.session_worker import (
    MINIMUM_WORKER_HEARTBEAT_STALE_SECONDS,
    WORKER_HEARTBEAT_STALE_MULTIPLIER,
    SessionWorker,
    WorkerHealth,
    is_worker_stalled,
)

TICK_INTERVAL_SECONDS = 0.01
TICK_WAIT_TIMEOUT_SECONDS = 5.0


def test_worker_ticks_on_a_thread_other_than_the_caller() -> None:
    """The whole point is that a tick never runs on the thread that started it."""

    ticked = threading.Event()
    tick_threads: list[int] = []

    def tick() -> None:
        tick_threads.append(threading.get_ident())
        ticked.set()

    worker = SessionWorker(tick, TICK_INTERVAL_SECONDS)
    worker.start()
    try:
        assert ticked.wait(TICK_WAIT_TIMEOUT_SECONDS)
    finally:
        worker.stop()

    assert tick_threads
    assert tick_threads[0] != threading.get_ident()


def test_worker_stops_and_stays_stopped() -> None:
    ticks = threading.Semaphore(0)
    worker = SessionWorker(ticks.release, TICK_INTERVAL_SECONDS)
    worker.start()
    assert ticks.acquire(timeout=TICK_WAIT_TIMEOUT_SECONDS)

    worker.stop()

    assert not worker.is_running
    while ticks.acquire(blocking=False):  # drain ticks already recorded
        pass
    assert not ticks.acquire(timeout=TICK_INTERVAL_SECONDS * 10)


def test_worker_refuses_a_second_start_while_running() -> None:
    worker = SessionWorker(lambda: None, TICK_INTERVAL_SECONDS)
    worker.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            worker.start()
    finally:
        worker.stop()


def test_worker_can_be_restarted_after_stopping() -> None:
    ticks = threading.Semaphore(0)
    worker = SessionWorker(ticks.release, TICK_INTERVAL_SECONDS)

    worker.start()
    assert ticks.acquire(timeout=TICK_WAIT_TIMEOUT_SECONDS)
    worker.stop()
    worker.start()
    try:
        assert ticks.acquire(timeout=TICK_WAIT_TIMEOUT_SECONDS)
    finally:
        worker.stop()


def test_worker_stop_is_safe_before_it_ever_started() -> None:
    worker = SessionWorker(lambda: None, TICK_INTERVAL_SECONDS)

    worker.stop()

    assert not worker.is_running


def test_worker_contains_a_tick_fault_and_continues_heartbeating() -> None:
    ticks = threading.Event()
    faults: list[str] = []
    calls = 0

    def tick() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("expected fault")
        ticks.set()

    worker = SessionWorker(
        tick,
        TICK_INTERVAL_SECONDS,
        on_fault=lambda error: faults.append(str(error)),
    )
    worker.start()
    try:
        assert ticks.wait(TICK_WAIT_TIMEOUT_SECONDS)
    finally:
        worker.stop()

    assert faults == ["expected fault"]
    assert worker.health.tick_count >= 1
    assert worker.health.exception_type == "RuntimeError"


@pytest.mark.parametrize("interval", [0.0, -1.0])
def test_worker_rejects_a_non_positive_interval(interval: float) -> None:
    with pytest.raises(ValueError, match="tick interval"):
        SessionWorker(lambda: None, interval)


def test_a_stopped_worker_is_reported_as_stalled_immediately() -> None:
    assert is_worker_stalled(
        is_running=False,
        health=WorkerHealth(tick_count=5, last_heartbeat_seconds=100.0),
        now=100.0,
        tick_interval_seconds=TICK_INTERVAL_SECONDS,
    )


def test_a_worker_that_has_not_ticked_yet_is_not_called_stalled() -> None:
    assert not is_worker_stalled(
        is_running=True,
        health=WorkerHealth(),
        now=100.0,
        tick_interval_seconds=TICK_INTERVAL_SECONDS,
    )


def test_a_slow_tick_is_tolerated_but_a_silent_worker_is_not() -> None:
    health = WorkerHealth(tick_count=3, last_heartbeat_seconds=100.0)
    stale_after = max(
        TICK_INTERVAL_SECONDS * WORKER_HEARTBEAT_STALE_MULTIPLIER,
        MINIMUM_WORKER_HEARTBEAT_STALE_SECONDS,
    )

    assert not is_worker_stalled(
        is_running=True,
        health=health,
        now=100.0 + stale_after,
        tick_interval_seconds=TICK_INTERVAL_SECONDS,
    )
    assert is_worker_stalled(
        is_running=True,
        health=health,
        now=100.0 + stale_after + 0.1,
        tick_interval_seconds=TICK_INTERVAL_SECONDS,
    )
