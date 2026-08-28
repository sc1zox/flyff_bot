"""Pure unattended-session arbitration and budget tests."""

from __future__ import annotations

import pytest

from flyff_bot.features.automation.autopilot import (
    MAXIMUM_EVENT_BUDGET,
    MAXIMUM_SESSION_BUDGET_SECONDS,
    AutopilotCompletionReason,
    AutopilotConfig,
    AutopilotConfigError,
    AutopilotGoalKind,
    AutopilotGoalReason,
    AutopilotSessionController,
    AutopilotSummary,
    DeathDetector,
    RollingBudget,
    arbitrate_goal,
)


def test_goal_arbiter_uses_the_documented_priority_order() -> None:
    decision = arbitrate_goal(
        active_quest=True,
        active_kill_objective=True,
        completed_quest=True,
        next_quest_available=True,
        fallback_zone_configured=True,
    )

    assert decision is not None
    assert decision.goal is AutopilotGoalKind.FARM_QUEST_OBJECTIVE


def test_goal_arbiter_records_the_fallback_reason() -> None:
    decision = arbitrate_goal(
        active_quest=False,
        active_kill_objective=False,
        completed_quest=False,
        next_quest_available=False,
        fallback_zone_configured=True,
    )

    assert decision is not None
    assert decision.goal is AutopilotGoalKind.FALLBACK_FARM
    assert decision.reason is AutopilotGoalReason.NO_EXECUTABLE_QUEST


def test_goal_arbiter_refuses_to_invent_a_fallback_zone() -> None:
    assert (
        arbitrate_goal(
            active_quest=False,
            active_kill_objective=False,
            completed_quest=False,
            next_quest_available=False,
            fallback_zone_configured=False,
        )
        is None
    )


def test_rolling_budget_expires_old_events() -> None:
    budget = RollingBudget(window_seconds=10.0, maximum=1)

    assert not budget.record(0.0)
    assert budget.record(5.0)
    assert not budget.record(16.0)
    assert budget.count == 1


@pytest.mark.parametrize("budget", [0.0, float("inf"), MAXIMUM_SESSION_BUDGET_SECONDS + 1.0])
def test_autopilot_config_rejects_a_time_budget_outside_its_finite_range(budget: float) -> None:
    with pytest.raises(AutopilotConfigError, match="session budget"):
        AutopilotConfig(session_budget_seconds=budget)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"maximum_deaths": -1},
        {"maximum_recoveries": MAXIMUM_EVENT_BUDGET + 1},
        {"recovery_backoff_seconds": 0.0},
        {"maximum_absence_seconds": float("nan")},
        {"death_confirmation_seconds": 0.0},
        {"event_window_seconds": 0.0},
        {"fallback_monster_names": ("   ",)},
    ],
)
def test_every_autopilot_setting_refuses_a_value_outside_its_range(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(AutopilotConfigError):
        AutopilotConfig(**kwargs)  # type: ignore[arg-type]


def test_rolling_budget_refuses_a_backwards_timestamp() -> None:
    budget = RollingBudget(window_seconds=10.0, maximum=5)
    budget.record(5.0)

    with pytest.raises(ValueError, match="monotonic"):
        budget.record(4.0)


def test_death_is_confirmed_once_after_the_named_zero_hp_dwell() -> None:
    detector = DeathDetector(confirmation_seconds=1.5)

    assert not detector.observe(0.0, 10.0)
    assert not detector.observe(0.0, 11.0)
    assert detector.observe(0.0, 11.5)
    # A confirmed death is reported exactly once, so the death budget stays honest.
    assert not detector.observe(0.0, 20.0)


def test_a_surviving_hit_never_confirms_a_death() -> None:
    detector = DeathDetector(confirmation_seconds=1.0)

    assert not detector.observe(0.0, 10.0)
    assert not detector.observe(5.0, 10.5)
    assert not detector.observe(0.0, 11.5)


def test_a_policy_fault_budget_counts_consecutive_faults_only() -> None:
    controller = AutopilotSessionController(AutopilotConfig(maximum_policy_faults=2))

    assert not controller.record_policy_fault()
    assert not controller.record_policy_fault()
    controller.clear_policy_faults()
    assert not controller.record_policy_fault()
    assert not controller.record_policy_fault()
    assert controller.record_policy_fault()


def test_an_armed_session_reports_its_elapsed_and_remaining_budget() -> None:
    controller = AutopilotSessionController(AutopilotConfig(session_budget_seconds=100.0))
    controller.arm(10.0)

    snapshot = controller.snapshot(40.0)

    assert snapshot.armed
    assert snapshot.elapsed_seconds == 30.0
    assert snapshot.remaining_seconds == 70.0
    assert not controller.time_exhausted(40.0)
    assert controller.time_exhausted(110.0)


def test_a_completed_session_reports_a_typed_summary_and_disarms() -> None:
    controller = AutopilotSessionController(AutopilotConfig())
    controller.arm(0.0)
    controller.record_death(1.0)
    controller.record_recovery(2.0)

    summary = controller.complete(
        AutopilotCompletionReason.TIME_BUDGET, 60.0, kills=7, completed_quests=2
    )

    assert summary == AutopilotSummary(60.0, 7, 2, 1, 1, AutopilotCompletionReason.TIME_BUDGET)
    assert not controller.armed
    assert controller.snapshot(60.0).completion_reason is AutopilotCompletionReason.TIME_BUDGET


def test_a_blocked_session_waits_out_the_bounded_backoff_before_resuming() -> None:
    controller = AutopilotSessionController(
        AutopilotConfig(recovery_backoff_seconds=2.0, maximum_absence_seconds=10.0)
    )
    controller.arm(0.0)
    controller.begin_recovery(5.0)

    assert not controller.recovery_due(6.0)
    assert controller.recovery_due(7.0)
    assert not controller.absence_exhausted(14.0)
    assert controller.absence_exhausted(15.0)
