"""Central, typed readiness classification for live autonomous capabilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class LiveStateSource(StrEnum):
    """Stable identities for live facts consumed by current session capabilities."""

    WINDOW_FOREGROUND = "window_foreground"
    PERCEPTION_FRAME = "perception_frame"
    GPS = "gps"
    CAMERA = "camera"
    PLAYER_STATS = "player_stats"
    DUNGEON_STATE = "dungeon_state"


class SessionCapability(StrEnum):
    """Live behaviors whose dependencies are evaluated independently."""

    READ_ONLY_PREVIEW = "read_only_preview"
    CAMERA_ALIGNMENT = "camera_alignment"
    NAVIGATION = "navigation"
    COMBAT = "combat"
    VITALS = "vitals"
    DUNGEON_AUTOMATION = "dungeon_automation"


class ProviderHealth(StrEnum):
    """Provider-owned classification before central freshness evaluation."""

    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    MALFORMED = "malformed"
    CANCELLED = "cancelled"


class ReadinessReason(StrEnum):
    """Stable aggregate and per-source block reasons in precedence order."""

    EMERGENCY_STOP = "emergency_stop"
    SHUTDOWN = "shutdown"
    CLOCK_DISCONTINUITY = "clock_discontinuity"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    UNREGISTERED = "unregistered"
    STALE = "stale"


class ReadinessState(StrEnum):
    """Aggregate readiness of the declared session capabilities."""

    READY = "ready"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """Freshness policy for one registered live source."""

    source: LiveStateSource
    freshness_limit_seconds: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.freshness_limit_seconds) or self.freshness_limit_seconds <= 0.0:
            raise ValueError("A provider freshness limit must be finite and positive.")


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    """The registered sources required by one independently reported capability."""

    capability: SessionCapability
    required_sources: frozenset[LiveStateSource]
    blocks_session_actions: bool = True

    def __post_init__(self) -> None:
        if not self.required_sources:
            raise ValueError("A live capability must require at least one source.")


@dataclass(frozen=True, slots=True)
class LiveProviderSample:
    """One normalized provider result; no client-specific enum crosses this boundary."""

    source: LiveStateSource
    health: ProviderHealth
    sampled_at_seconds: float | None
    diagnostic_code: str

    def __post_init__(self) -> None:
        if not self.diagnostic_code or self.diagnostic_code != self.diagnostic_code.strip():
            raise ValueError("A provider sample needs a stable, trimmed diagnostic code.")


@dataclass(frozen=True, slots=True)
class SourceReadiness:
    """Central health, age, and consequence classification for one source."""

    source: LiveStateSource
    health: ProviderHealth
    age_seconds: float | None
    reason: ReadinessReason | None
    diagnostic_code: str
    required_by: tuple[SessionCapability, ...] = ()

    @property
    def is_ready(self) -> bool:
        return self.reason is None


@dataclass(frozen=True, slots=True)
class CapabilityReadiness:
    """Readiness of one capability without hiding simultaneous source failures."""

    capability: SessionCapability
    blocked: bool
    failures: tuple[SourceReadiness, ...] = ()


@dataclass(frozen=True, slots=True)
class LiveReadinessStatus:
    """One immutable aggregate computed once for a live session tick."""

    state: ReadinessState = ReadinessState.READY
    sources: tuple[SourceReadiness, ...] = ()
    capabilities: tuple[CapabilityReadiness, ...] = ()
    failures: tuple[SourceReadiness, ...] = ()
    primary_reason: ReadinessReason | None = None
    primary_source: LiveStateSource | None = None
    action_blocked: bool = False
    evaluated_at_seconds: float = 0.0
    # Sources the session stopped requiring because they can never recover on this client.
    # They keep reporting their own health, but nothing is blocked on them any more.
    degraded_sources: tuple[LiveStateSource, ...] = ()

    def is_degraded(self, source: LiveStateSource) -> bool:
        """Return whether one source was demoted to an optional, non-blocking feed."""

        return source in self.degraded_sources

    @property
    def failed_source_codes(self) -> tuple[str, ...]:
        """Return ordered stable source codes for telemetry and RL records."""

        return tuple(item.source.value for item in self.failures)

    @property
    def sample_ages_seconds(self) -> tuple[tuple[str, float | None], ...]:
        """Return every source age without fabricating ages for absent samples."""

        return tuple((item.source.value, item.age_seconds) for item in self.sources)


_REASON_PRECEDENCE = {
    ReadinessReason.EMERGENCY_STOP: 0,
    ReadinessReason.SHUTDOWN: 1,
    ReadinessReason.CLOCK_DISCONTINUITY: 2,
    ReadinessReason.MALFORMED: 3,
    ReadinessReason.UNSUPPORTED: 4,
    ReadinessReason.UNAVAILABLE: 5,
    ReadinessReason.UNREGISTERED: 5,
    ReadinessReason.STALE: 6,
}
# A source with no block reason is not a failure at all, so it sorts behind every ranked one.
_UNRANKED_REASON_PRECEDENCE = len(_REASON_PRECEDENCE)
_SOURCE_ORDER = {source: index for index, source in enumerate(LiveStateSource)}
_CAPABILITY_ORDER = {capability: index for index, capability in enumerate(SessionCapability)}


class LiveReadinessGate:
    """Register providers and deterministically evaluate current live-state readiness."""

    def __init__(self) -> None:
        self._providers: dict[LiveStateSource, ProviderRegistration] = {}
        self._capabilities: dict[SessionCapability, CapabilityRequirement] = {}
        self._samples: dict[LiveStateSource, LiveProviderSample] = {}
        self._sample_versions: dict[LiveStateSource, int] = {}
        self._last_evaluated_at_seconds: float | None = None
        self._clock_recovery_versions: dict[LiveStateSource, int] | None = None
        self._terminal_reason: ReadinessReason | None = None
        self._degraded_sources: set[LiveStateSource] = set()

    def register_provider(self, registration: ProviderRegistration) -> None:
        """Register one source exactly once; duplicate registration is a setup error."""

        if registration.source in self._providers:
            raise ValueError(f"Provider {registration.source.value} is already registered.")
        self._providers[registration.source] = registration
        self._sample_versions[registration.source] = 0

    def register_capability(self, requirement: CapabilityRequirement) -> None:
        """Declare a capability dependency graph without silently registering its sources."""

        if requirement.capability in self._capabilities:
            raise ValueError(f"Capability {requirement.capability.value} is already registered.")
        self._capabilities[requirement.capability] = requirement

    def update(self, sample: LiveProviderSample) -> None:
        """Replace one registered provider sample with its newest normalized result."""

        if sample.source not in self._providers:
            raise ValueError(f"Provider {sample.source.value} is not registered.")
        self._samples[sample.source] = sample
        self._sample_versions[sample.source] += 1

    def demote_source(self, source: LiveStateSource) -> bool:
        """Stop requiring one source so a permanent failure cannot block the session forever.

        A capability left without any requirement is unregistered outright: there is nothing
        left for it to be ready or blocked on. Returns whether this call demoted the source.
        """

        if source in self._degraded_sources:
            return False
        self._degraded_sources.add(source)
        remaining: dict[SessionCapability, CapabilityRequirement] = {}
        for capability, requirement in self._capabilities.items():
            required = requirement.required_sources - {source}
            if not required:
                continue
            remaining[capability] = (
                requirement
                if required == requirement.required_sources
                else CapabilityRequirement(
                    capability,
                    required,
                    blocks_session_actions=requirement.blocks_session_actions,
                )
            )
        self._capabilities = remaining
        return True

    def emergency_stop(self) -> None:
        """Latch the terminal emergency override; repeated calls are harmless."""

        if self._terminal_reason is None:
            self._terminal_reason = ReadinessReason.EMERGENCY_STOP

    def close(self) -> None:
        """Latch terminal shutdown unless the stronger emergency override already won."""

        if self._terminal_reason is None:
            self._terminal_reason = ReadinessReason.SHUTDOWN

    def evaluate(self, at_seconds: float) -> LiveReadinessStatus:
        """Compute one immutable aggregate from the newest sample of every source."""

        if not math.isfinite(at_seconds) or at_seconds < 0.0:
            raise ValueError("A readiness evaluation timestamp must be finite and non-negative.")
        self._detect_clock_discontinuity(at_seconds)
        required_sources = self._required_sources()
        self._clear_recovered_clock_discontinuity(required_sources)
        sources = tuple(
            self._source_readiness(source, at_seconds, required_sources)
            for source in self._all_sources()
        )
        failures = tuple(item for item in sources if not item.is_ready)
        failures_by_source = {item.source: item for item in failures}
        capabilities = tuple(
            CapabilityReadiness(
                requirement.capability,
                blocked=bool(
                    capability_failures := tuple(
                        failures_by_source[source]
                        for source in sorted(
                            requirement.required_sources, key=_SOURCE_ORDER.__getitem__
                        )
                        if source in failures_by_source
                    )
                ),
                failures=capability_failures,
            )
            for requirement in sorted(
                self._capabilities.values(), key=lambda item: _CAPABILITY_ORDER[item.capability]
            )
        )
        terminal_reason = self._terminal_reason
        if terminal_reason is not None:
            capabilities = tuple(
                CapabilityReadiness(item.capability, True, item.failures) for item in capabilities
            )
            return LiveReadinessStatus(
                state=ReadinessState.CANCELLED,
                sources=sources,
                capabilities=capabilities,
                failures=failures,
                primary_reason=terminal_reason,
                action_blocked=True,
                evaluated_at_seconds=at_seconds,
                degraded_sources=self._ordered_degraded_sources(),
            )
        required_failures = tuple(item for item in failures if item.source in required_sources)
        primary = min(required_failures, key=self._failure_sort_key) if required_failures else None
        action_blocked = any(
            capability.blocked and self._capabilities[capability.capability].blocks_session_actions
            for capability in capabilities
        )
        self._last_evaluated_at_seconds = max(
            at_seconds, self._last_evaluated_at_seconds or at_seconds
        )
        return LiveReadinessStatus(
            state=ReadinessState.BLOCKED
            if any(item.blocked for item in capabilities)
            else ReadinessState.READY,
            sources=sources,
            capabilities=capabilities,
            failures=failures,
            primary_reason=None if primary is None else primary.reason,
            primary_source=None if primary is None else primary.source,
            action_blocked=action_blocked,
            evaluated_at_seconds=at_seconds,
            degraded_sources=self._ordered_degraded_sources(),
        )

    def _ordered_degraded_sources(self) -> tuple[LiveStateSource, ...]:
        return tuple(sorted(self._degraded_sources, key=_SOURCE_ORDER.__getitem__))

    def _detect_clock_discontinuity(self, at_seconds: float) -> None:
        backwards = (
            self._last_evaluated_at_seconds is not None
            and at_seconds < self._last_evaluated_at_seconds
        )
        future_sample = any(
            sample.health is ProviderHealth.HEALTHY
            and sample.sampled_at_seconds is not None
            and math.isfinite(sample.sampled_at_seconds)
            and sample.sampled_at_seconds > at_seconds
            for sample in self._samples.values()
        )
        if (backwards or future_sample) and self._clock_recovery_versions is None:
            self._clock_recovery_versions = dict(self._sample_versions)

    def _clear_recovered_clock_discontinuity(
        self, required_sources: frozenset[LiveStateSource]
    ) -> None:
        recovery_versions = self._clock_recovery_versions
        if recovery_versions is None:
            return
        registered_required = required_sources.intersection(self._providers)
        if registered_required and all(
            self._sample_versions[source] > recovery_versions.get(source, 0)
            for source in registered_required
        ):
            self._clock_recovery_versions = None

    def _source_readiness(
        self,
        source: LiveStateSource,
        at_seconds: float,
        required_sources: frozenset[LiveStateSource],
    ) -> SourceReadiness:
        required_by = tuple(
            requirement.capability
            for requirement in sorted(
                self._capabilities.values(), key=lambda item: _CAPABILITY_ORDER[item.capability]
            )
            if source in requirement.required_sources
        )
        registration = self._providers.get(source)
        if registration is None:
            return SourceReadiness(
                source,
                ProviderHealth.UNAVAILABLE,
                None,
                ReadinessReason.UNREGISTERED,
                "unregistered",
                required_by,
            )
        sample = self._samples.get(source)
        if sample is None:
            return SourceReadiness(
                source,
                ProviderHealth.UNAVAILABLE,
                None,
                ReadinessReason.UNAVAILABLE,
                "no_sample",
                required_by,
            )
        timestamp = sample.sampled_at_seconds
        age = (
            at_seconds - timestamp
            if timestamp is not None and math.isfinite(timestamp) and timestamp <= at_seconds
            else None
        )
        recovery_versions = self._clock_recovery_versions
        if (
            source in required_sources
            and recovery_versions is not None
            and self._sample_versions[source] <= recovery_versions.get(source, 0)
        ):
            return SourceReadiness(
                source,
                sample.health,
                age,
                ReadinessReason.CLOCK_DISCONTINUITY,
                "clock_discontinuity",
                required_by,
            )
        if sample.health is ProviderHealth.HEALTHY:
            if timestamp is None or not math.isfinite(timestamp):
                reason = ReadinessReason.MALFORMED
                diagnostic_code = "invalid_timestamp"
            elif timestamp > at_seconds:
                reason = ReadinessReason.CLOCK_DISCONTINUITY
                diagnostic_code = "clock_discontinuity"
            elif age is not None and age > registration.freshness_limit_seconds:
                reason = ReadinessReason.STALE
                diagnostic_code = sample.diagnostic_code
            else:
                reason = None
                diagnostic_code = sample.diagnostic_code
        else:
            reason = {
                ProviderHealth.UNAVAILABLE: ReadinessReason.UNAVAILABLE,
                ProviderHealth.UNSUPPORTED: ReadinessReason.UNSUPPORTED,
                ProviderHealth.MALFORMED: ReadinessReason.MALFORMED,
                ProviderHealth.CANCELLED: ReadinessReason.SHUTDOWN,
            }[sample.health]
            diagnostic_code = sample.diagnostic_code
        return SourceReadiness(
            source,
            sample.health,
            age,
            reason,
            diagnostic_code,
            required_by,
        )

    def _required_sources(self) -> frozenset[LiveStateSource]:
        return frozenset(
            source
            for requirement in self._capabilities.values()
            for source in requirement.required_sources
        )

    def _all_sources(self) -> tuple[LiveStateSource, ...]:
        sources = set(self._providers)
        sources.update(self._required_sources())
        return tuple(sorted(sources, key=_SOURCE_ORDER.__getitem__))

    @staticmethod
    def _failure_sort_key(item: SourceReadiness) -> tuple[int, int]:
        """Order failures by reason precedence, sorting a ready source behind every failure."""

        precedence = (
            _UNRANKED_REASON_PRECEDENCE if item.reason is None else _REASON_PRECEDENCE[item.reason]
        )
        return precedence, _SOURCE_ORDER[item.source]
