"""Tests for the remaining synthetic supervisor contract."""

from flyff_bot.features.automation.models import DesiredState, FailureFlag, Position, WorldState
from flyff_bot.features.automation.supervisor import Supervisor, SupervisorConfig


def _state(
    *,
    observed_at_seconds: float = 0.0,
    mob_count: int = 0,
    marker: int = 0,
    is_stuck: bool = False,
) -> WorldState:
    return WorldState(
        observed_at_seconds=observed_at_seconds,
        position=Position(0, 0),
        nearby_mob_count=mob_count,
        progress_marker=marker,
        is_stuck=is_stuck,
    )


def test_supervisor_detects_observable_runtime_failures() -> None:
    supervisor = Supervisor(SupervisorConfig(no_progress_timeout_seconds=5.0))
    desired = DesiredState(minimum_mob_count=1)
    supervisor.reconcile(desired, _state(marker=1))

    result = supervisor.reconcile(
        desired,
        _state(observed_at_seconds=5.0, marker=1, is_stuck=True),
    )

    assert result.failures == frozenset(FailureFlag)


def test_supervisor_resets_no_progress_timeout_after_progress() -> None:
    supervisor = Supervisor(SupervisorConfig(no_progress_timeout_seconds=5.0))
    desired = DesiredState()
    supervisor.reconcile(desired, _state(marker=1))
    supervisor.reconcile(desired, _state(observed_at_seconds=5.0, marker=1))

    result = supervisor.reconcile(desired, _state(observed_at_seconds=6.0, marker=2))

    assert result.is_healthy
