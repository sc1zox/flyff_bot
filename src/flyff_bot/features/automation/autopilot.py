"""Fail-closed budget, recovery, and goal-arbitration rules for unattended sessions.

This module owns the part of autopilot that has no window, no input, and no perception: how
long a session may run, how many deaths, recoveries, tick faults, and policy faults it may
absorb before it stops, and which goal it pursues next. Keeping it free of Win32 and Qt is
what lets the whole arbitration and budget surface be tested deterministically (US-086).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

# Four hours is a full unattended evening session and still an order of magnitude below the
# one-day ceiling, which exists so a mistyped budget cannot arm an endless session.
DEFAULT_SESSION_BUDGET_SECONDS = 14_400.0
DEFAULT_EVENT_WINDOW_SECONDS = 3_600.0
DEFAULT_MAXIMUM_DEATHS = 3
DEFAULT_MAXIMUM_RECOVERIES = 10
DEFAULT_MAXIMUM_TICK_FAULTS = 3
DEFAULT_MAXIMUM_POLICY_FAULTS = 3
DEFAULT_RECOVERY_BACKOFF_SECONDS = 2.0
DEFAULT_MAXIMUM_ABSENCE_SECONDS = 300.0
# The client keeps the character at zero HP while the revive menu is open, so a short dwell
# separates a real death from a single frame read mid-hit.
DEFAULT_DEATH_CONFIRMATION_SECONDS = 1.5
DEAD_HP_PERCENTAGE = 0.0

MINIMUM_SESSION_BUDGET_SECONDS = 60.0
MAXIMUM_SESSION_BUDGET_SECONDS = 86_400.0
MINIMUM_EVENT_WINDOW_SECONDS = 10.0
MAXIMUM_EVENT_WINDOW_SECONDS = 86_400.0
MINIMUM_RECOVERY_BACKOFF_SECONDS = 0.1
MAXIMUM_RECOVERY_BACKOFF_SECONDS = 60.0
MINIMUM_ABSENCE_SECONDS = 1.0
MAXIMUM_ABSENCE_SECONDS = 3_600.0
MINIMUM_DEATH_CONFIRMATION_SECONDS = 0.1
MAXIMUM_DEATH_CONFIRMATION_SECONDS = 60.0
MAXIMUM_EVENT_BUDGET = 1_000


class AutopilotConfigError(ValueError):
    """An unattended-session setting is outside its finite supported range."""


class AutopilotGoalKind(StrEnum):
    """The deterministic, explainable priority categories the arbiter chooses between."""

    CONTINUE_QUEST = "continue_quest"
    FARM_QUEST_OBJECTIVE = "farm_quest_objective"
    TURN_IN_QUEST = "turn_in_quest"
    ACCEPT_QUEST = "accept_quest"
    FALLBACK_FARM = "fallback_farm"


class AutopilotGoalReason(StrEnum):
    """Why the arbiter chose the goal it chose."""

    ACTIVE_QUEST = "active_quest"
    ACTIVE_QUEST_KILL_OBJECTIVE = "active_quest_kill_objective"
    QUEST_COMPLETED = "quest_completed"
    NEXT_QUEST_AVAILABLE = "next_quest_available"
    NO_EXECUTABLE_QUEST = "no_executable_quest"


class AutopilotCompletionReason(StrEnum):
    """Which declared budget ended an unattended session."""

    TIME_BUDGET = "session_time_budget_exhausted"
    RECOVERY_BUDGET = "recovery_budget_exhausted"
    TICK_FAULT_BUDGET = "tick_fault_budget_exhausted"
    CLIENT_ABSENCE = "client_absence_exhausted"


@dataclass(frozen=True, slots=True)
class AutopilotConfig:
    """Every unattended-session budget, each with a named default and a finite range."""

    session_budget_seconds: float = DEFAULT_SESSION_BUDGET_SECONDS
    event_window_seconds: float = DEFAULT_EVENT_WINDOW_SECONDS
    maximum_deaths: int = DEFAULT_MAXIMUM_DEATHS
    maximum_recoveries: int = DEFAULT_MAXIMUM_RECOVERIES
    maximum_tick_faults: int = DEFAULT_MAXIMUM_TICK_FAULTS
    maximum_policy_faults: int = DEFAULT_MAXIMUM_POLICY_FAULTS
    recovery_backoff_seconds: float = DEFAULT_RECOVERY_BACKOFF_SECONDS
    maximum_absence_seconds: float = DEFAULT_MAXIMUM_ABSENCE_SECONDS
    death_confirmation_seconds: float = DEFAULT_DEATH_CONFIRMATION_SECONDS
    #: The monster classes the session falls back to farming once no quest is executable.
    #: A zone is identified by the monster that spawns in it, which is what the extracted
    #: world map and the navigator already key on.
    fallback_monster_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_range(
            "session budget",
            self.session_budget_seconds,
            MINIMUM_SESSION_BUDGET_SECONDS,
            MAXIMUM_SESSION_BUDGET_SECONDS,
        )
        _validate_range(
            "event window",
            self.event_window_seconds,
            MINIMUM_EVENT_WINDOW_SECONDS,
            MAXIMUM_EVENT_WINDOW_SECONDS,
        )
        _validate_range(
            "recovery backoff",
            self.recovery_backoff_seconds,
            MINIMUM_RECOVERY_BACKOFF_SECONDS,
            MAXIMUM_RECOVERY_BACKOFF_SECONDS,
        )
        _validate_range(
            "maximum absence",
            self.maximum_absence_seconds,
            MINIMUM_ABSENCE_SECONDS,
            MAXIMUM_ABSENCE_SECONDS,
        )
        _validate_range(
            "death confirmation",
            self.death_confirmation_seconds,
            MINIMUM_DEATH_CONFIRMATION_SECONDS,
            MAXIMUM_DEATH_CONFIRMATION_SECONDS,
        )
        for value in (
            self.maximum_deaths,
            self.maximum_recoveries,
            self.maximum_tick_faults,
            self.maximum_policy_faults,
        ):
            _validate_event_budget(value)
        if any(not name.strip() for name in self.fallback_monster_names):
            raise AutopilotConfigError("An autopilot fallback monster class must not be blank.")

    @property
    def has_fallback_zone(self) -> bool:
        """Return whether a zone was configured for the session to fall back to."""

        return bool(self.fallback_monster_names)


@dataclass(frozen=True, slots=True)
class AutopilotGoalDecision:
    """One explainable selection, free of any presentation string."""

    goal: AutopilotGoalKind
    reason: AutopilotGoalReason


@dataclass(frozen=True, slots=True)
class AutopilotSnapshot:
    """Immutable operator-facing unattended-session state."""

    armed: bool = False
    started_at_seconds: float | None = None
    elapsed_seconds: float = 0.0
    remaining_seconds: float | None = None
    goal: AutopilotGoalDecision | None = None
    deaths: int = 0
    recoveries: int = 0
    tick_faults: int = 0
    policy_faults: int = 0
    last_fault: str | None = None
    last_fault_at_seconds: float | None = None
    completion_reason: AutopilotCompletionReason | None = None


@dataclass(frozen=True, slots=True)
class AutopilotSummary:
    """Typed counters the dashboard renders as one localized completion sentence."""

    duration_seconds: float
    kills: int
    completed_quests: int
    deaths: int
    recoveries: int
    reason: AutopilotCompletionReason


def arbitrate_goal(
    *,
    active_quest: bool,
    active_kill_objective: bool,
    completed_quest: bool,
    next_quest_available: bool,
    fallback_zone_configured: bool,
) -> AutopilotGoalDecision | None:
    """Choose the documented goal order, never inventing a fallback zone.

    The order is fixed and explainable: continue the active quest, farm its kill objective,
    turn a completed quest in, accept the next one, and only then fall back to farming.
    """

    if active_quest:
        if active_kill_objective:
            return AutopilotGoalDecision(
                AutopilotGoalKind.FARM_QUEST_OBJECTIVE,
                AutopilotGoalReason.ACTIVE_QUEST_KILL_OBJECTIVE,
            )
        return AutopilotGoalDecision(
            AutopilotGoalKind.CONTINUE_QUEST, AutopilotGoalReason.ACTIVE_QUEST
        )
    if completed_quest:
        return AutopilotGoalDecision(
            AutopilotGoalKind.TURN_IN_QUEST, AutopilotGoalReason.QUEST_COMPLETED
        )
    if next_quest_available:
        return AutopilotGoalDecision(
            AutopilotGoalKind.ACCEPT_QUEST, AutopilotGoalReason.NEXT_QUEST_AVAILABLE
        )
    if fallback_zone_configured:
        return AutopilotGoalDecision(
            AutopilotGoalKind.FALLBACK_FARM, AutopilotGoalReason.NO_EXECUTABLE_QUEST
        )
    return None


@dataclass(slots=True)
class RollingBudget:
    """Count events inside a monotonic sliding window."""

    window_seconds: float
    maximum: int
    _events: deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        if not math.isfinite(self.window_seconds) or self.window_seconds <= 0.0:
            raise AutopilotConfigError("A rolling budget window must be positive and finite.")
        _validate_event_budget(self.maximum)

    def record(self, at_seconds: float) -> bool:
        """Record one event and report whether the configured maximum was exceeded."""

        if not math.isfinite(at_seconds) or (self._events and at_seconds < self._events[-1]):
            raise ValueError("Rolling-budget timestamps must be finite and monotonic.")
        self._events.append(at_seconds)
        while self._events and at_seconds - self._events[0] > self.window_seconds:
            self._events.popleft()
        return len(self._events) > self.maximum

    @property
    def count(self) -> int:
        """Return how many events are still inside the window."""

        return len(self._events)


@dataclass(slots=True)
class DeathDetector:
    """Confirm a player death only after a named continuous zero-HP dwell.

    Reporting the confirmation exactly once is what keeps the death budget honest: an open
    revive menu holds HP at zero for as long as the operator's autopilot leaves it there.
    """

    confirmation_seconds: float = DEFAULT_DEATH_CONFIRMATION_SECONDS
    _zero_since_seconds: float | None = None
    _confirmed: bool = False

    def observe(self, hp_percentage: float, at_seconds: float) -> bool:
        """Report whether this observation is the moment a death became confirmed."""

        if not math.isfinite(at_seconds):
            raise ValueError("Death observations require a finite timestamp.")
        if not math.isfinite(hp_percentage) or hp_percentage > DEAD_HP_PERCENTAGE:
            self.reset()
            return False
        if self._zero_since_seconds is None:
            self._zero_since_seconds = at_seconds
            return False
        if self._confirmed:
            return False
        if at_seconds - self._zero_since_seconds >= self.confirmation_seconds:
            self._confirmed = True
            return True
        return False

    def reset(self) -> None:
        """Forget the current dwell, used once a respawn is observed."""

        self._zero_since_seconds = None
        self._confirmed = False


@dataclass(slots=True)
class AutopilotSessionController:
    """Own the counters and budgets of one armed unattended session."""

    config: AutopilotConfig
    armed: bool = False
    started_at_seconds: float | None = None
    goal: AutopilotGoalDecision | None = None
    deaths: int = 0
    recoveries: int = 0
    tick_faults: int = 0
    consecutive_policy_faults: int = 0
    last_fault: str | None = None
    last_fault_at_seconds: float | None = None
    completion_reason: AutopilotCompletionReason | None = None
    summary: AutopilotSummary | None = None
    blocked_since_seconds: float | None = None
    retry_after_seconds: float | None = None
    _death_budget: RollingBudget = field(init=False)
    _recovery_budget: RollingBudget = field(init=False)
    _tick_fault_budget: RollingBudget = field(init=False)

    def __post_init__(self) -> None:
        self._death_budget = RollingBudget(
            self.config.event_window_seconds, self.config.maximum_deaths
        )
        self._recovery_budget = RollingBudget(
            self.config.event_window_seconds, self.config.maximum_recoveries
        )
        self._tick_fault_budget = RollingBudget(
            self.config.event_window_seconds, self.config.maximum_tick_faults
        )

    def arm(self, at_seconds: float) -> None:
        """Start one unattended session, clearing the previous session's outcome."""

        self.armed = True
        self.started_at_seconds = at_seconds
        self.completion_reason = None
        self.summary = None
        self.blocked_since_seconds = None
        self.retry_after_seconds = None

    def disarm(self) -> None:
        """Stop steering the session without declaring a budget exhausted."""

        self.armed = False

    def choose_goal(self, decision: AutopilotGoalDecision | None) -> bool:
        """Adopt one arbitration result and report whether it changed."""

        changed = decision != self.goal
        self.goal = decision
        return changed

    def record_death(self, at_seconds: float) -> bool:
        """Count one confirmed death and report whether the budget is exhausted."""

        self.deaths += 1
        return self._death_budget.record(at_seconds)

    def record_tick_fault(self, error: Exception, at_seconds: float) -> bool:
        """Remember one contained tick fault and report whether the budget is exhausted."""

        self.tick_faults += 1
        self.last_fault = f"{type(error).__name__}: {error}"
        self.last_fault_at_seconds = at_seconds
        return self._tick_fault_budget.record(at_seconds)

    def record_policy_fault(self) -> bool:
        """Count one consecutive policy fault and report whether the budget is exhausted."""

        self.consecutive_policy_faults += 1
        return self.consecutive_policy_faults > self.config.maximum_policy_faults

    def clear_policy_faults(self) -> None:
        """Reset the consecutive counter once a policy evaluation succeeded."""

        self.consecutive_policy_faults = 0

    def begin_recovery(self, at_seconds: float) -> None:
        """Start the bounded backoff wait for a blocking condition to clear."""

        if self.blocked_since_seconds is None:
            self.blocked_since_seconds = at_seconds
        self.retry_after_seconds = at_seconds + self.config.recovery_backoff_seconds

    def recovery_due(self, at_seconds: float) -> bool:
        """Return whether the backoff wait has elapsed and a resume may be attempted."""

        return self.retry_after_seconds is not None and at_seconds >= self.retry_after_seconds

    def record_recovery(self, at_seconds: float) -> bool:
        """Count one resumed session and report whether the recovery budget is exhausted."""

        self.recoveries += 1
        self.blocked_since_seconds = None
        self.retry_after_seconds = None
        return self._recovery_budget.record(at_seconds)

    def absence_exhausted(self, at_seconds: float) -> bool:
        """Return whether the blocking condition outlasted the configured maximum."""

        return self.blocked_since_seconds is not None and (
            at_seconds - self.blocked_since_seconds >= self.config.maximum_absence_seconds
        )

    def time_exhausted(self, at_seconds: float) -> bool:
        """Return whether the declared session time budget has run out."""

        return self.started_at_seconds is not None and (
            at_seconds - self.started_at_seconds >= self.config.session_budget_seconds
        )

    def complete(
        self,
        reason: AutopilotCompletionReason,
        at_seconds: float,
        *,
        kills: int,
        completed_quests: int,
    ) -> AutopilotSummary:
        """End the session on a declared budget and return its reportable summary."""

        started = self.started_at_seconds if self.started_at_seconds is not None else at_seconds
        self.armed = False
        self.completion_reason = reason
        self.summary = AutopilotSummary(
            max(0.0, at_seconds - started),
            kills,
            completed_quests,
            self.deaths,
            self.recoveries,
            reason,
        )
        return self.summary

    def snapshot(self, at_seconds: float) -> AutopilotSnapshot:
        """Return the immutable state the dashboard renders."""

        elapsed = (
            0.0
            if self.started_at_seconds is None
            else max(0.0, at_seconds - self.started_at_seconds)
        )
        remaining = (
            None
            if self.started_at_seconds is None
            else max(0.0, self.config.session_budget_seconds - elapsed)
        )
        return AutopilotSnapshot(
            self.armed,
            self.started_at_seconds,
            elapsed,
            remaining,
            self.goal,
            self.deaths,
            self.recoveries,
            self.tick_faults,
            self.consecutive_policy_faults,
            self.last_fault,
            self.last_fault_at_seconds,
            self.completion_reason,
        )


def _validate_range(name: str, value: float, minimum: float, maximum: float) -> None:
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise AutopilotConfigError(
            f"The autopilot {name} must be a finite value between {minimum} and {maximum}."
        )


def _validate_event_budget(value: int) -> None:
    if isinstance(value, bool) or not 0 <= value <= MAXIMUM_EVENT_BUDGET:
        raise AutopilotConfigError(
            f"An autopilot event budget must be between 0 and {MAXIMUM_EVENT_BUDGET}."
        )
