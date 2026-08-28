"""Separately-itemised farming efficiency, and what it refuses to claim (US-083 AC9)."""

from __future__ import annotations

from flyff_bot.features.telemetry.efficiency import summarize_efficiency
from flyff_bot.features.telemetry.models import KillCycle

REWARD_CONFIG_VERSION = "reward-v3"
ONE_MINUTE_SECONDS = 60.0


def _cycle(
    *,
    verified: bool = True,
    decision: float = 1.0,
    navigation: float = 2.0,
    combat: float = 3.0,
    idle: float = 0.5,
    stall: float = 0.25,
    damage: float = 4.0,
) -> KillCycle:
    return KillCycle(
        timestamp_ns=0,
        decision_seconds=decision,
        navigation_seconds=navigation,
        combat_seconds=combat,
        idle_seconds=idle,
        damage_taken=damage,
        stall_seconds=stall,
        verified_kill=verified,
        reward=0.0,
    )


def test_only_verified_kills_count_towards_yield() -> None:
    # An unconfirmed kill is time spent, not value earned. Counting it would make a session
    # look productive exactly when its verification is broken.
    report = summarize_efficiency(
        (_cycle(verified=True), _cycle(verified=False), _cycle(verified=True)),
        elapsed_seconds=ONE_MINUTE_SECONDS,
        reward_config_version=REWARD_CONFIG_VERSION,
    )

    assert report.verified_kills == 2
    assert report.verified_kills_per_minute == 2.0


def test_every_cost_is_reported_separately_rather_than_combined() -> None:
    report = summarize_efficiency(
        (_cycle(), _cycle()),
        elapsed_seconds=ONE_MINUTE_SECONDS,
        reward_config_version=REWARD_CONFIG_VERSION,
        distance_units=250.0,
        action_failures=3,
    )

    assert report.decision_seconds == 2.0
    assert report.navigation_seconds == 4.0
    assert report.combat_seconds == 6.0
    assert report.idle_seconds == 1.0
    assert report.stall_seconds == 0.5
    assert report.distance_units == 250.0
    assert report.damage_taken_percent == 8.0
    assert report.action_failures == 3


def test_a_session_with_no_elapsed_time_has_no_rate_rather_than_a_rate_of_zero() -> None:
    report = summarize_efficiency(
        (), elapsed_seconds=0.0, reward_config_version=REWARD_CONFIG_VERSION
    )

    assert report.verified_kills_per_minute is None


def test_time_no_bucket_explains_is_reported_rather_than_absorbed() -> None:
    # Hiding unexplained time inside "idle" makes the gap invisible exactly when it matters.
    report = summarize_efficiency(
        (_cycle(decision=1.0, navigation=1.0, combat=1.0, idle=1.0),),
        elapsed_seconds=ONE_MINUTE_SECONDS,
        reward_config_version=REWARD_CONFIG_VERSION,
    )

    assert report.accounted_seconds == 4.0
    assert report.unaccounted_seconds == ONE_MINUTE_SECONDS - 4.0


def test_loot_value_is_absent_unless_a_collection_was_observed() -> None:
    unobserved = summarize_efficiency(
        (_cycle(),),
        elapsed_seconds=ONE_MINUTE_SECONDS,
        reward_config_version=REWARD_CONFIG_VERSION,
    )
    observed = summarize_efficiency(
        (_cycle(),),
        elapsed_seconds=ONE_MINUTE_SECONDS,
        reward_config_version=REWARD_CONFIG_VERSION,
        collected_loot_value=12.0,
    )

    # None means "not measured", never zero: a zero would read as a session that collected
    # nothing rather than one that does not observe collection at all.
    assert unobserved.collected_loot_value is None
    assert observed.collected_loot_value == 12.0


def test_the_reward_weights_a_session_ran_under_are_reported_with_it() -> None:
    # Two reports built under different weights measured different objectives and must never
    # be compared as though they did not.
    report = summarize_efficiency(
        (), elapsed_seconds=ONE_MINUTE_SECONDS, reward_config_version=REWARD_CONFIG_VERSION
    )

    assert report.reward_config_version == REWARD_CONFIG_VERSION


def test_a_non_finite_measurement_is_treated_as_nothing_measured() -> None:
    report = summarize_efficiency(
        (_cycle(navigation=float("inf")),),
        elapsed_seconds=ONE_MINUTE_SECONDS,
        reward_config_version=REWARD_CONFIG_VERSION,
    )

    assert report.navigation_seconds == 0.0
