"""Background driver that keeps the farming tick loop off the Qt GUI thread."""

from __future__ import annotations

import threading
from collections.abc import Callable

DEFAULT_WORKER_JOIN_TIMEOUT_SECONDS = 5.0

_WORKER_THREAD_NAME = "flyff-bot-session"


class SessionWorker:
    """Call one tick function on a fixed interval from a dedicated worker thread.

    A tick captures a frame and may run OCR, which is far too slow for the Qt event loop.
    Results reach the UI through `DashboardFeed`'s signal, so this worker never touches a
    widget itself.
    """

    def __init__(self, tick: Callable[[], object], interval_seconds: float) -> None:
        if interval_seconds <= 0.0:
            raise ValueError("Session worker tick interval must be positive.")
        self._tick = tick
        self._interval_seconds = interval_seconds
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Report whether the worker thread is currently alive."""

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start ticking in the background; starting an already running worker is refused."""

        if self.is_running:
            raise RuntimeError("Session worker is already running.")
        self._stop_requested.clear()
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
            self._tick()
            self._stop_requested.wait(self._interval_seconds)
