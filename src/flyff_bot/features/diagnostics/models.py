"""Typed structured records for the session event diagnostics log."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SessionEventKind(StrEnum):
    """The category of one recorded session event."""

    MODE_TRANSITION = "mode_transition"
    FOCUS_LOST = "focus_lost"
    EMERGENCY_STOPPED = "emergency_stopped"
    OBSTACLE_STALL = "obstacle_stall"
    SUPERVISOR_FAILURE = "supervisor_failure"
    FRAME_CAPTURE_ERROR = "frame_capture_error"
    GOAL_COMPLETED = "goal_completed"
    CAPABILITY_DEGRADED = "capability_degraded"


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """One immutable record of a farming-session mode transition or diagnostic trigger."""

    timestamp: str
    kind: SessionEventKind
    previous_mode: str
    new_mode: str
    reason: str | None = None
    foreground_window_title: str | None = None
    foreground_window_process: str | None = None
