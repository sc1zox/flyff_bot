"""Background driver that keeps the farming tick loop off the Qt GUI thread."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic

DEFAULT_WORKER_JOIN_TIMEOUT_SECONDS = 5.0
# How often the UI re-evaluates worker liveness, and how far a heartbeat may fall behind the
# tick interval before the dashboard stops presenting the last state as current.
WORKER_WATCHDOG_INTERVAL_SECONDS = 1.0
WORKER_HEARTBEAT_STALE_MULTIPLIER = 50
MINIMUM_WORKER_HEARTBEAT_STALE_SECONDS = 5.0

_WORKER_THREAD_NAME = "flyff-bot-session"


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    """Observable liveness and latest contained tick fault for one worker."""

    tick_count: int = 0
    last_heartbeat_seconds: float | None = None
    exception_type: str | None = None
    exception_message: str | None = None


class SessionWorker:
    """Call one tick function on a fixed interval from a dedicated worker thread.

    A tick captures a frame and may run OCR, which is far too slow for the Qt event loop.
    Results reach the UI through `DashboardFeed`'s signal, so this worker never touches a
    widget itself.
    """

    def __init__(
        self,
        tick: Callable[[], object],
        interval_seconds: float,
        *,
        on_fault: Callable[[Exception], None] | None = None,
        on_heartbeat: Callable[[WorkerHealth], None] | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if interval_seconds <= 0.0:
            raise ValueError("Session worker tick interval must be positive.")
        self._tick = tick
        self._interval_seconds = interval_seconds
        self._on_fault = on_fault
        self._on_heartbeat = on_heartbeat
        self._clock = clock
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._health = WorkerHealth()
        self._health_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Report whether the worker thread is currently alive."""

        return self._thread is not None and self._thread.is_alive()

    @property
    def health(self) -> WorkerHealth:
        """Return the most recently published worker heartbeat."""

        with self._health_lock:
            return self._health

    def start(self) -> None:
        """Start ticking in the background; starting an already running worker is refused."""

        if self.is_running:
            raise RuntimeError("Session worker is already running.")
        self._stop_requested.clear()
        with self._health_lock:
            self._health = WorkerHealth()
        self._thread = threading.Thread(target=self._run, name=_WORKER_THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self, timeout_seconds: float = DEFAULT_WORKER_JOIN_TIMEOUT_SECONDS) -> None:
        """Signal the loop to end and wait for the worker thread to finish."""

        self._stop_requested.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout_seconds)
        self._thread = None

    def _run(self) -> None:
        # Waiting on the stop event instead of sleeping makes teardown immediate rather
        # than leaving the window blocked for up to one whole interval.
        while not self._stop_requested.is_set():
            try:
                self._tick()
            except Exception as error:
                self._record_fault(error)
                if self._on_fault is not None:
                    # A UI/diagnostic callback must not recreate the silent worker death
                    # this boundary exists to prevent.
                    with suppress(Exception):
                        self._on_fault(error)
            else:
                self._record_heartbeat()
            self._stop_requested.wait(self._interval_seconds)

    def _record_heartbeat(self) -> None:
        with self._health_lock:
            self._health = WorkerHealth(
                tick_count=self._health.tick_count + 1,
                last_heartbeat_seconds=self._clock(),
                exception_type=self._health.exception_type,
                exception_message=self._health.exception_message,
            )
            health = self._health
        if self._on_heartbeat is not None:
            self._on_heartbeat(health)

    def _record_fault(self, error: Exception) -> None:
        with self._health_lock:
            self._health = WorkerHealth(
                tick_count=self._health.tick_count,
                last_heartbeat_seconds=self._clock(),
                exception_type=type(error).__name__,
                exception_message=str(error),
            )
            health = self._health
        if self._on_heartbeat is not None:
            self._on_heartbeat(health)


def is_worker_stalled(
    *,
    is_running: bool,
    health: WorkerHealth,
    now: float,
    tick_interval_seconds: float,
) -> bool:
    """Return whether the worker stopped publishing ticks and the UI is showing stale state.

    A dead thread is stalled immediately. A live thread is judged on its heartbeat: one tick
    may legitimately take far longer than the interval, so only a heartbeat older than the
    generous multiple below counts as a stall (US-086).
    """

    if not is_running:
        return True
    if health.last_heartbeat_seconds is None:
        return False
    stale_after = max(
        tick_interval_seconds * WORKER_HEARTBEAT_STALE_MULTIPLIER,
        MINIMUM_WORKER_HEARTBEAT_STALE_SECONDS,
    )
    return now - health.last_heartbeat_seconds > stale_after
