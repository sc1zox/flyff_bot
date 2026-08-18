"""Unit tests for the background tick loop that keeps OCR off the Qt GUI thread."""

from __future__ import annotations

import threading

import pytest

from flyff_bot.ui.session_worker import SessionWorker

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


@pytest.mark.parametrize("interval", [0.0, -1.0])
def test_worker_rejects_a_non_positive_interval(interval: float) -> None:
    with pytest.raises(ValueError, match="tick interval"):
        SessionWorker(lambda: None, interval)
