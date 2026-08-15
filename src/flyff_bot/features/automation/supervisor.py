"""World-state reconciliation and recovery signal detection."""

from __future__ import annotations

from dataclasses import dataclass

from flyff_bot.features.automation.models import DesiredState, FailureFlag, WorldState


@dataclass(frozen=True, slots=True)
class SupervisorConfig:
    """Named timing policy for reconciliation failures."""

    no_progress_timeout_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """The failures found for one desired/observed state comparison."""

    failures: frozenset[FailureFlag]

    @property
    def is_healthy(self) -> bool:
        """Return whether the state requires no recovery."""

        return not self.failures


class Supervisor:
    """Track progress across snapshots and reconcile them with a desired state."""

    def __init__(self, config: SupervisorConfig | None = None) -> None:
        self._config = config or SupervisorConfig()
        self._progress_marker: int | None = None
        self._last_progress_at_seconds: float | None = None

    def reconcile(self, desired: DesiredState, observed: WorldState) -> Reconciliation:
        """Return current recovery signals without blocking the caller's loop."""

        failures: set[FailureFlag] = set()
        if observed.is_stuck:
            failures.add(FailureFlag.STUCK)
        if desired.minimum_mob_count > observed.nearby_mob_count:
            failures.add(FailureFlag.NO_MOBS)
        if not self._has_required_inventory(desired, observed):
            failures.add(FailureFlag.INVENTORY_MISMATCH)
        if self._has_timed_out_without_progress(observed):
            failures.add(FailureFlag.NO_PROGRESS)
        return Reconciliation(frozenset(failures))

    def _has_required_inventory(self, desired: DesiredState, observed: WorldState) -> bool:
        quantities = {entry.item: entry.quantity for entry in observed.inventory}
        return all(
            quantities.get(entry.item, 0) >= entry.quantity for entry in desired.required_inventory
        )

    def _has_timed_out_without_progress(self, observed: WorldState) -> bool:
        if self._progress_marker != observed.progress_marker:
            self._progress_marker = observed.progress_marker
            self._last_progress_at_seconds = observed.observed_at_seconds
            return False
        if self._last_progress_at_seconds is None:
            self._last_progress_at_seconds = observed.observed_at_seconds
            return False
        elapsed = observed.observed_at_seconds - self._last_progress_at_seconds
        return elapsed >= self._config.no_progress_timeout_seconds
