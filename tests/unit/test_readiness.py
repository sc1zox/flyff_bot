from __future__ import annotations

from dataclasses import replace

import pytest

from flyff_bot.features.automation.readiness import (
    CapabilityRequirement,
    LiveProviderSample,
    LiveReadinessGate,
    LiveStateSource,
    ProviderHealth,
    ProviderRegistration,
    ReadinessReason,
    ReadinessState,
    SessionCapability,
)


def _registration(
    source: LiveStateSource,
    *,
    freshness_limit_seconds: float = 1.0,
) -> ProviderRegistration:
    return ProviderRegistration(source, freshness_limit_seconds)


def _sample(
    source: LiveStateSource,
    *,
    at_seconds: float = 10.0,
    health: ProviderHealth = ProviderHealth.HEALTHY,
    diagnostic_code: str = "ok",
) -> LiveProviderSample:
    return LiveProviderSample(source, health, at_seconds, diagnostic_code)


def _gate(
    *sources: LiveStateSource,
    capability: SessionCapability = SessionCapability.NAVIGATION,
) -> LiveReadinessGate:
    gate = LiveReadinessGate()
    for source in sources:
        gate.register_provider(_registration(source))
    gate.register_capability(CapabilityRequirement(capability, frozenset(sources)))
    return gate


def test_gate_returns_one_immutable_ready_status_in_stable_source_order() -> None:
    gate = _gate(
        LiveStateSource.GPS,
        LiveStateSource.WINDOW_FOREGROUND,
        LiveStateSource.CAMERA,
    )
    for source in (
        LiveStateSource.CAMERA,
        LiveStateSource.GPS,
        LiveStateSource.WINDOW_FOREGROUND,
    ):
        gate.update(_sample(source))

    status = gate.evaluate(10.5)

    assert status.state is ReadinessState.READY
    assert status.primary_reason is None
    assert not status.action_blocked
    assert not status.failures
    assert tuple(item.source for item in status.sources) == (
        LiveStateSource.WINDOW_FOREGROUND,
        LiveStateSource.GPS,
        LiveStateSource.CAMERA,
    )
    assert status.capabilities[0].capability is SessionCapability.NAVIGATION
    assert not status.capabilities[0].blocked
    with pytest.raises(AttributeError):
        status.action_blocked = True  # type: ignore[misc]


def test_duplicate_provider_and_capability_registration_are_rejected() -> None:
    gate = LiveReadinessGate()
    gate.register_provider(_registration(LiveStateSource.GPS))
    gate.register_capability(
        CapabilityRequirement(SessionCapability.NAVIGATION, frozenset({LiveStateSource.GPS}))
    )

    with pytest.raises(ValueError, match="already registered"):
        gate.register_provider(_registration(LiveStateSource.GPS))
    with pytest.raises(ValueError, match="already registered"):
        gate.register_capability(
            CapabilityRequirement(
                SessionCapability.NAVIGATION,
                frozenset({LiveStateSource.GPS}),
            )
        )


def test_unregistered_required_provider_fails_closed_without_blocking_independent_capability() -> (
    None
):
    gate = LiveReadinessGate()
    gate.register_provider(_registration(LiveStateSource.PERCEPTION_FRAME))
    gate.update(_sample(LiveStateSource.PERCEPTION_FRAME))
    gate.register_capability(
        CapabilityRequirement(
            SessionCapability.COMBAT,
            frozenset({LiveStateSource.PERCEPTION_FRAME, LiveStateSource.PLAYER_STATS}),
        )
    )
    gate.register_capability(
        CapabilityRequirement(
            SessionCapability.READ_ONLY_PREVIEW,
            frozenset({LiveStateSource.PERCEPTION_FRAME}),
            blocks_session_actions=False,
        )
    )

    status = gate.evaluate(10.0)

    assert status.state is ReadinessState.BLOCKED
    assert status.primary_reason is ReadinessReason.UNREGISTERED
    assert status.failed_source_codes == (LiveStateSource.PLAYER_STATS.value,)
    readiness = {item.capability: item for item in status.capabilities}
    assert readiness[SessionCapability.COMBAT].blocked
    assert not readiness[SessionCapability.READ_ONLY_PREVIEW].blocked
    assert status.action_blocked


def test_registered_optional_provider_without_a_sample_is_visible_but_does_not_block() -> None:
    gate = LiveReadinessGate()
    gate.register_provider(_registration(LiveStateSource.PERCEPTION_FRAME))
    gate.register_provider(_registration(LiveStateSource.DUNGEON_STATE))
    gate.register_capability(
        CapabilityRequirement(
            SessionCapability.READ_ONLY_PREVIEW,
            frozenset({LiveStateSource.PERCEPTION_FRAME}),
            blocks_session_actions=False,
        )
    )
    gate.update(_sample(LiveStateSource.PERCEPTION_FRAME))

    status = gate.evaluate(10.0)

    assert status.state is ReadinessState.READY
    assert status.primary_reason is None
    assert status.failed_source_codes == (LiveStateSource.DUNGEON_STATE.value,)
    assert not status.action_blocked


def test_freshness_boundary_is_inclusive_and_a_new_sample_recovers_only_affected_capability() -> (
    None
):
    gate = LiveReadinessGate()
    gate.register_provider(_registration(LiveStateSource.GPS, freshness_limit_seconds=2.0))
    gate.register_provider(_registration(LiveStateSource.PERCEPTION_FRAME))
    gate.register_capability(
        CapabilityRequirement(SessionCapability.NAVIGATION, frozenset({LiveStateSource.GPS}))
    )
    gate.register_capability(
        CapabilityRequirement(
            SessionCapability.READ_ONLY_PREVIEW,
            frozenset({LiveStateSource.PERCEPTION_FRAME}),
            blocks_session_actions=False,
        )
    )
    gate.update(_sample(LiveStateSource.GPS, at_seconds=8.0))
    gate.update(_sample(LiveStateSource.PERCEPTION_FRAME, at_seconds=10.0))

    assert gate.evaluate(10.0).state is ReadinessState.READY
    stale = gate.evaluate(10.001)
    assert stale.primary_reason is ReadinessReason.STALE
    assert stale.failures[0].age_seconds == pytest.approx(2.001)
    readiness = {item.capability: item for item in stale.capabilities}
    assert readiness[SessionCapability.NAVIGATION].blocked
    assert not readiness[SessionCapability.READ_ONLY_PREVIEW].blocked

    gate.update(_sample(LiveStateSource.GPS, at_seconds=10.001))
    recovered = gate.evaluate(10.001)
    assert recovered.state is ReadinessState.READY
    assert not recovered.action_blocked


def test_all_failures_are_exposed_while_precedence_and_tie_break_are_deterministic() -> None:
    sources = (
        LiveStateSource.GPS,
        LiveStateSource.CAMERA,
        LiveStateSource.PLAYER_STATS,
        LiveStateSource.DUNGEON_STATE,
    )
    gate = _gate(*sources)
    gate.update(_sample(LiveStateSource.GPS, at_seconds=7.0))
    gate.update(
        _sample(
            LiveStateSource.CAMERA,
            health=ProviderHealth.UNAVAILABLE,
            diagnostic_code="handle_lost",
        )
    )
    gate.update(
        _sample(
            LiveStateSource.PLAYER_STATS,
            health=ProviderHealth.MALFORMED,
            diagnostic_code="malformed_read",
        )
    )
    gate.update(
        _sample(
            LiveStateSource.DUNGEON_STATE,
            health=ProviderHealth.UNSUPPORTED,
            diagnostic_code="unconfigured_profile",
        )
    )

    status = gate.evaluate(10.0)

    assert status.primary_reason is ReadinessReason.MALFORMED
    assert status.primary_source is LiveStateSource.PLAYER_STATS
    assert tuple(item.source for item in status.failures) == sources
    assert tuple(item.reason for item in status.failures) == (
        ReadinessReason.STALE,
        ReadinessReason.UNAVAILABLE,
        ReadinessReason.MALFORMED,
        ReadinessReason.UNSUPPORTED,
    )


@pytest.mark.parametrize("timestamp", [None, float("nan"), float("inf")])
def test_healthy_samples_with_missing_or_non_finite_timestamps_are_malformed(
    timestamp: float | None,
) -> None:
    gate = _gate(LiveStateSource.PLAYER_STATS, capability=SessionCapability.COMBAT)
    gate.update(
        LiveProviderSample(
            LiveStateSource.PLAYER_STATS,
            ProviderHealth.HEALTHY,
            timestamp,
            "ok",
        )
    )

    status = gate.evaluate(10.0)

    assert status.primary_reason is ReadinessReason.MALFORMED
    assert status.failures[0].diagnostic_code == "invalid_timestamp"


def test_clock_discontinuity_requires_new_samples_from_every_required_source() -> None:
    gate = _gate(LiveStateSource.GPS, LiveStateSource.CAMERA)
    gate.update(_sample(LiveStateSource.GPS))
    gate.update(_sample(LiveStateSource.CAMERA))
    assert gate.evaluate(10.0).state is ReadinessState.READY

    gate.update(_sample(LiveStateSource.GPS, at_seconds=12.0))
    discontinuity = gate.evaluate(11.0)
    assert discontinuity.primary_reason is ReadinessReason.CLOCK_DISCONTINUITY

    gate.update(_sample(LiveStateSource.GPS, at_seconds=11.0))
    still_blocked = gate.evaluate(11.0)
    assert still_blocked.primary_reason is ReadinessReason.CLOCK_DISCONTINUITY

    gate.update(_sample(LiveStateSource.CAMERA, at_seconds=11.0))
    assert gate.evaluate(11.0).state is ReadinessState.READY

    backwards = gate.evaluate(10.5)
    assert backwards.primary_reason is ReadinessReason.CLOCK_DISCONTINUITY


def test_emergency_and_shutdown_are_idempotent_terminal_overrides() -> None:
    emergency_gate = _gate(LiveStateSource.WINDOW_FOREGROUND)
    emergency_gate.update(_sample(LiveStateSource.WINDOW_FOREGROUND))
    emergency_gate.emergency_stop()
    emergency_gate.emergency_stop()
    emergency = emergency_gate.evaluate(10.0)
    assert emergency.state is ReadinessState.CANCELLED
    assert emergency.primary_reason is ReadinessReason.EMERGENCY_STOP
    assert emergency.action_blocked
    emergency_gate.update(
        replace(_sample(LiveStateSource.WINDOW_FOREGROUND), sampled_at_seconds=11.0)
    )
    assert emergency_gate.evaluate(11.0).primary_reason is ReadinessReason.EMERGENCY_STOP

    shutdown_gate = _gate(LiveStateSource.WINDOW_FOREGROUND)
    shutdown_gate.close()
    shutdown_gate.close()
    shutdown = shutdown_gate.evaluate(10.0)
    assert shutdown.state is ReadinessState.CANCELLED
    assert shutdown.primary_reason is ReadinessReason.SHUTDOWN
    assert shutdown.action_blocked
