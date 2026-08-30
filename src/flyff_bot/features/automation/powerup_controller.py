"""Interval-driven power-up scheduling and guarded timed-hotkey dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from flyff_bot.features.automation.controllers import DEFAULT_KEY_PRESS_DURATION_SECONDS

DEFAULT_POWERUP_STAGGER_SECONDS = 0.030
DEFAULT_POWERUP_INTERVAL_SECONDS = 180
MINIMUM_POWERUP_INTERVAL_SECONDS = 1
MAXIMUM_POWERUP_INTERVAL_SECONDS = 86400


@dataclass(frozen=True, slots=True)
class PowerUpEntry:
    """One configured timed hotkey refreshed on a recurring interval."""

    virtual_key: int
    interval_seconds: int
    label: str = ""
    enabled: bool = True
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS

    def __post_init__(self) -> None:
        if not (
            MINIMUM_POWERUP_INTERVAL_SECONDS
            <= self.interval_seconds
            <= MAXIMUM_POWERUP_INTERVAL_SECONDS
        ):
            raise ValueError(
                "Power-up interval must be between "
                f"{MINIMUM_POWERUP_INTERVAL_SECONDS} and "
                f"{MAXIMUM_POWERUP_INTERVAL_SECONDS} seconds."
            )
        if self.key_press_duration_seconds <= 0.0:
            raise ValueError("Power-up key press duration must be positive.")


@dataclass(frozen=True, slots=True)
class PowerUpConfig:
    """The operator-configured list of timed hotkeys for one session.

    An empty entry tuple is a legitimate configuration: it means the operator
    deliberately keeps no timed hotkeys, not that defaults should be restored.
    """

    entries: tuple[PowerUpEntry, ...] = ()
    stagger_seconds: float = DEFAULT_POWERUP_STAGGER_SECONDS

    def __post_init__(self) -> None:
        if self.stagger_seconds < 0.0:
            raise ValueError("Power-up stagger seconds must not be negative.")


@dataclass(frozen=True, slots=True)
class PowerUpDecision:
    """The outcome of evaluating power-up timers for one tick."""

    triggered: bool
    entry_index: int | None = None
    virtual_key: int | None = None
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS


class PowerUpInputAdapter(Protocol):
    """Guarded platform operations needed to dispatch timed hotkeys."""

    def is_aborted(self) -> bool:
        """Return whether the emergency-stop hotkey was pressed."""

    def is_foreground(self, window_handle: int) -> bool:
        """Return whether the client window is active."""

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        """Press and release a virtual key while honoring the emergency stop."""


class PowerUpScheduler:
    """Accumulate active session time per entry and report the next due hotkey.

    Time is accumulated only across the ticks the caller actually steps, so a
    paused, unfocused, or stopped session freezes every countdown instead of
    letting wall-clock time expire timers behind the operator's back. A decision
    is only consumed by `confirm`, so a keystroke the dispatcher refuses stays
    due until the guards allow it through.
    """

    def __init__(self, config: PowerUpConfig | None = None) -> None:
        self._config = config or PowerUpConfig()
        self._elapsed_seconds = [
            float(entry.interval_seconds) if entry.enabled else 0.0
            for entry in self._config.entries
        ]
        self._last_step_at_seconds: float | None = None
        self._last_dispatch_at_seconds: float | None = None

    @property
    def config(self) -> PowerUpConfig:
        """Return the active power-up configuration."""

        return self._config

    def elapsed_seconds(self, entry_index: int) -> float:
        """Return the active time accumulated for one entry since its last press."""

        return self._elapsed_seconds[entry_index]

    def update_config(self, config: PowerUpConfig) -> None:
        """Apply a new configuration while preserving unchanged entries' countdowns.

        Editing an unrelated row must not restart a 3600 s buff timer, so elapsed
        time carries over for every position whose key and interval are unchanged.
        New or enabled entries are initialized as immediately due.
        """

        preserved: list[float] = []
        for index, entry in enumerate(config.entries):
            previous = self._config.entries[index] if index < len(self._config.entries) else None
            carries_over = (
                previous is not None
                and previous.virtual_key == entry.virtual_key
                and previous.interval_seconds == entry.interval_seconds
                and previous.enabled == entry.enabled
            )
            preserved.append(
                self._elapsed_seconds[index]
                if carries_over
                else (float(entry.interval_seconds) if entry.enabled else 0.0)
            )
        self._config = config
        self._elapsed_seconds = preserved

    def halt(self) -> None:
        """Freeze every countdown without discarding the time already accumulated."""

        self._last_step_at_seconds = None

    def reset(self) -> None:
        """Restart every countdown, making all enabled entries due on next start."""

        self._elapsed_seconds = [
            float(entry.interval_seconds) if entry.enabled else 0.0
            for entry in self._config.entries
        ]
        self._last_step_at_seconds = None
        self._last_dispatch_at_seconds = None

    def step(self, at_seconds: float) -> PowerUpDecision:
        """Accumulate elapsed active time and report the first entry that is due."""

        previous_step_at = self._last_step_at_seconds
        self._last_step_at_seconds = at_seconds
        if previous_step_at is not None:
            elapsed_since_step = max(0.0, at_seconds - previous_step_at)
            for index, entry in enumerate(self._config.entries):
                if entry.enabled:
                    self._elapsed_seconds[index] += elapsed_since_step

        if self._is_staggering(at_seconds):
            return PowerUpDecision(triggered=False)

        for index, entry in enumerate(self._config.entries):
            if entry.enabled and self._elapsed_seconds[index] >= entry.interval_seconds:
                return PowerUpDecision(
                    triggered=True,
                    entry_index=index,
                    virtual_key=entry.virtual_key,
                    key_press_duration_seconds=entry.key_press_duration_seconds,
                )
        return PowerUpDecision(triggered=False)

    def confirm(self, decision: PowerUpDecision, at_seconds: float) -> None:
        """Restart one entry's countdown after its keystroke actually reached the client."""

        if not decision.triggered or decision.entry_index is None:
            return
        if decision.entry_index < len(self._elapsed_seconds):
            self._elapsed_seconds[decision.entry_index] = 0.0
        self._last_dispatch_at_seconds = at_seconds

    def _is_staggering(self, at_seconds: float) -> bool:
        """Report whether the configured gap after the previous keystroke still applies."""

        if self._last_dispatch_at_seconds is None:
            return False
        return at_seconds - self._last_dispatch_at_seconds < self._config.stagger_seconds


class PowerUpInputDispatcher:
    """Send timed hotkeys only while the client is focused and END is clear."""

    def __init__(self, adapter: PowerUpInputAdapter, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, decision: PowerUpDecision) -> bool:
        """Dispatch one due power-up hotkey when every safety guard allows it."""

        if (
            not decision.triggered
            or decision.virtual_key is None
            or self._adapter.is_aborted()
            or not self._adapter.is_foreground(self._window_handle)
        ):
            return False

        self._adapter.send_key(decision.virtual_key, decision.key_press_duration_seconds)
        return True
