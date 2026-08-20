"""Unrecoverable-stuck detection and guarded emergency teleport dispatch (US-040)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from flyff_bot.features.automation.controllers import (
    DEFAULT_KEY_PRESS_DURATION_SECONDS,
    VIRTUAL_KEY_F4,
)

DEFAULT_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS = 60.0
MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS = 10.0
MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS = 300.0
# The client needs a moment to finish the teleport transition and redraw the destination
# before any perception reading or movement command means anything again.
DEFAULT_TELEPORT_SETTLE_SECONDS = 2.0
# Live GPS reports client world units, so progress is measured in the same units the
# navigation stack plans in. This mirrors `REPEATED_STALL_RADIUS_UNITS`, the radius two
# stalls count as the same spot within: a character that actually walked out of that radius
# made progress, while GPS jitter around a wedged character stays below it.
DEFAULT_PROGRESS_DISTANCE_UNITS = 3.0
DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY = VIRTUAL_KEY_F4


class EmergencyRecoveryAction(StrEnum):
    """What the unrecoverable-stuck monitor asks the session to do."""

    # The session is either making progress or has not been stuck long enough yet.
    NONE = "none"
    # The configured teleport hotkey should be dispatched.
    TELEPORT = "teleport"
    # The timeout expired but no teleport hotkey is configured, so only the operator can
    # free the character. The session pauses and says so instead of pressing nothing.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class EmergencyRecoveryConfig:
    """Operator settings for the last-resort teleport out of un-walkable geometry."""

    # ``None`` means the operator deliberately assigned no teleport item or skill hotkey.
    teleport_virtual_key: int | None = DEFAULT_EMERGENCY_TELEPORT_VIRTUAL_KEY
    stuck_timeout_seconds: float = DEFAULT_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS
    settle_delay_seconds: float = DEFAULT_TELEPORT_SETTLE_SECONDS
    progress_distance_units: float = DEFAULT_PROGRESS_DISTANCE_UNITS
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS

    def __post_init__(self) -> None:
        if not (
            MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS
            <= self.stuck_timeout_seconds
            <= MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS
        ):
            raise ValueError(
                "Unrecoverable stuck timeout must be between "
                f"{MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS} and "
                f"{MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS} seconds."
            )
        if self.settle_delay_seconds < 0.0:
            raise ValueError("Emergency teleport settle delay must not be negative.")
        if self.progress_distance_units <= 0.0:
            raise ValueError("Emergency recovery progress distance must be positive.")
        if self.key_press_duration_seconds <= 0.0:
            raise ValueError("Emergency teleport key press duration must be positive.")


@dataclass(frozen=True, slots=True)
class EmergencyRecoveryDecision:
    """The outcome of evaluating the unrecoverable-stuck timer for one tick."""

    action: EmergencyRecoveryAction = EmergencyRecoveryAction.NONE
    virtual_key: int | None = None
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS


class EmergencyTeleportInputAdapter(Protocol):
    """Guarded platform operations needed to dispatch the emergency teleport hotkey."""

    def is_aborted(self) -> bool:
        """Return whether the emergency-stop hotkey was pressed."""

    def is_foreground(self, window_handle: int) -> bool:
        """Return whether the client window is active."""

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        """Press and release a virtual key while honoring the emergency stop."""


class EmergencyRecoveryMonitor:
    """Accumulate the continuous span without progress and report when it is hopeless.

    Progress is any of the three things a healthy session produces: a verified position
    that actually moved, an engaged target, or a confirmed kill. Their absence is what
    every micro-unstuck mechanism failing looks like from here, so one accumulator covers
    all of them rather than one timer per recovery stage.

    Time is only accumulated across the ticks the caller actually steps, so a paused,
    unfocused, or teleporting session freezes the timer instead of letting wall-clock time
    expire it behind the operator's back.
    """

    def __init__(self, config: EmergencyRecoveryConfig | None = None) -> None:
        self._config = config or EmergencyRecoveryConfig()
        self._stuck_seconds = 0.0
        self._last_step_at_seconds: float | None = None
        self._reference_x: float | None = None
        self._reference_z: float | None = None

    @property
    def config(self) -> EmergencyRecoveryConfig:
        """Return the active emergency recovery configuration."""

        return self._config

    @property
    def stuck_seconds(self) -> float:
        """Return the continuous span the session has made no progress in."""

        return self._stuck_seconds

    def update_config(self, config: EmergencyRecoveryConfig) -> None:
        """Apply new operator settings without discarding the accumulated span."""

        self._config = config

    def halt(self) -> None:
        """Freeze the accumulator without discarding the time already accumulated."""

        self._last_step_at_seconds = None

    def reset(self) -> None:
        """Forget the accumulated span and the position it was measured against."""

        self._stuck_seconds = 0.0
        self._last_step_at_seconds = None
        self._reference_x = None
        self._reference_z = None

    def observe(
        self,
        at_seconds: float,
        *,
        position_x: float | None = None,
        position_z: float | None = None,
        engaged: bool = False,
    ) -> EmergencyRecoveryDecision:
        """Fold one tick into the timer and report whether recovery is now due.

        ``position_x``/``position_z`` are the live GPS coordinates of the horizontal
        world plane in client world units; passing ``None`` means the position is currently
        unknown, which is no evidence of progress and no evidence against it either, so only
        the reference point is left untouched.
        """

        previous_step_at = self._last_step_at_seconds
        self._last_step_at_seconds = at_seconds
        if self._made_progress(position_x, position_z, engaged=engaged):
            self._stuck_seconds = 0.0
            return EmergencyRecoveryDecision()
        if previous_step_at is None:
            # The first tick after start or resume only seeds the clock, so a halted span
            # never counts towards the timeout.
            return EmergencyRecoveryDecision()
        self._stuck_seconds += max(0.0, at_seconds - previous_step_at)
        if self._stuck_seconds < self._config.stuck_timeout_seconds:
            return EmergencyRecoveryDecision()
        virtual_key = self._config.teleport_virtual_key
        if virtual_key is None:
            return EmergencyRecoveryDecision(EmergencyRecoveryAction.UNAVAILABLE)
        return EmergencyRecoveryDecision(
            EmergencyRecoveryAction.TELEPORT,
            virtual_key,
            self._config.key_press_duration_seconds,
        )

    def _made_progress(
        self, position_x: float | None, position_z: float | None, *, engaged: bool
    ) -> bool:
        """Report whether this tick carries evidence that the session is not wedged."""

        if engaged:
            self._reference_x = position_x
            self._reference_z = position_z
            return True
        if position_x is None or position_z is None:
            return False
        if self._reference_x is None or self._reference_z is None:
            # The first known position is the reference every later one is compared to; it
            # is not itself displacement, so it does not clear an accumulated span.
            self._reference_x = position_x
            self._reference_z = position_z
            return False
        moved = math.hypot(position_x - self._reference_x, position_z - self._reference_z)
        if moved < self._config.progress_distance_units:
            return False
        self._reference_x = position_x
        self._reference_z = position_z
        return True


class EmergencyTeleportDispatcher:
    """Send the emergency teleport hotkey only while the client is focused and END is clear."""

    def __init__(self, adapter: EmergencyTeleportInputAdapter, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, decision: EmergencyRecoveryDecision) -> bool:
        """Dispatch the teleport hotkey when every safety guard allows it."""

        if (
            decision.action is not EmergencyRecoveryAction.TELEPORT
            or decision.virtual_key is None
            or self._adapter.is_aborted()
            or not self._adapter.is_foreground(self._window_handle)
        ):
            return False
        self._adapter.send_key(decision.virtual_key, decision.key_press_duration_seconds)
        return True
