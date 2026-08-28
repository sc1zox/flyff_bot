"""Report what a farming session actually achieved, and what it spent doing it (US-083).

A single "kills per minute" number hides every way a session can be slow. Two sessions with
the same rate can differ entirely in where the time went -- one walking, one waiting on
respawns, one dying and recovering -- and an operator who cannot see the split cannot tell
which knob to turn. So the decomposition is reported alongside the rate rather than folded
into it, and each cost keeps its own unit instead of being normalised into a score.

Two rules keep the report honest. Only verified kills count towards yield: a kill the session
could not confirm is time spent, not value earned, and counting it would let a session look
productive precisely when its verification is broken. And expected loot is never reported as
yield -- the client states what a mover *may* drop, the session observes what it actually
collected, and the report only ever shows the second. Labelling a declared drop as real yield
is the one thing this criterion explicitly forbids.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from flyff_bot.features.telemetry.models import KillCycle

SECONDS_PER_MINUTE = 60.0


@dataclass(frozen=True, slots=True)
class FarmingEfficiencyReport:
    """One session's verified yield and its separately reported costs.

    Every field is a measurement of something that happened. Nothing here is an estimate, a
    projection, or a client-declared value: an operator reading this is reading the session.
    """

    verified_kills: int
    elapsed_seconds: float
    decision_seconds: float
    navigation_seconds: float
    combat_seconds: float
    idle_seconds: float
    stall_seconds: float
    distance_units: float
    damage_taken_percent: float
    action_failures: int
    #: The reward weights this session was steered by, so two reports built under different
    #: weights are never compared as though they measured the same objective.
    reward_config_version: str
    #: Present only when the operator configured a verified loot value *and* the session
    #: actually observed the collection. ``None`` means "not measured", never zero.
    collected_loot_value: float | None = None

    @property
    def verified_kills_per_minute(self) -> float | None:
        """Return confirmed kills per real elapsed minute, or ``None`` before any time passed.

        ``None`` rather than zero: a session that has run for no time has not achieved a rate
        of zero, it has no rate yet, and showing zero reads as a session that is failing.
        """

        if self.elapsed_seconds <= 0.0:
            return None
        return self.verified_kills / (self.elapsed_seconds / SECONDS_PER_MINUTE)

    @property
    def accounted_seconds(self) -> float:
        """Return the time the decomposition explains, which may trail elapsed time."""

        return (
            self.decision_seconds
            + self.navigation_seconds
            + self.combat_seconds
            + self.idle_seconds
        )

    @property
    def unaccounted_seconds(self) -> float:
        """Return elapsed time no bucket claimed, rather than silently absorbing it.

        Time that no bucket explains is itself a finding: it usually means a session spent it
        somewhere nothing was recording, and hiding it inside "idle" would make the gap
        invisible exactly when it matters.
        """

        return max(0.0, self.elapsed_seconds - self.accounted_seconds)


def summarize_efficiency(
    cycles: Iterable[KillCycle],
    *,
    elapsed_seconds: float,
    reward_config_version: str,
    distance_units: float = 0.0,
    action_failures: int = 0,
    collected_loot_value: float | None = None,
) -> FarmingEfficiencyReport:
    """Aggregate recorded kill cycles into one separately-itemised efficiency report.

    ``collected_loot_value`` is passed through untouched and stays ``None`` unless the caller
    actually observed a collection. There is deliberately no parameter for expected or
    declared drop value: the report has no way to express it, so it cannot accidentally show
    one as yield.
    """

    verified = 0
    decision = navigation = combat = idle = stall = damage = 0.0
    for cycle in cycles:
        if cycle.verified_kill:
            verified += 1
        decision += _finite(cycle.decision_seconds)
        navigation += _finite(cycle.navigation_seconds)
        combat += _finite(cycle.combat_seconds)
        idle += _finite(cycle.idle_seconds)
        stall += _finite(cycle.stall_seconds)
        damage += _finite(cycle.damage_taken)
    return FarmingEfficiencyReport(
        verified_kills=verified,
        elapsed_seconds=max(0.0, _finite(elapsed_seconds)),
        decision_seconds=decision,
        navigation_seconds=navigation,
        combat_seconds=combat,
        idle_seconds=idle,
        stall_seconds=stall,
        distance_units=max(0.0, _finite(distance_units)),
        damage_taken_percent=damage,
        action_failures=max(0, action_failures),
        reward_config_version=reward_config_version,
        collected_loot_value=collected_loot_value,
    )


def _finite(value: float) -> float:
    """Return a usable measurement, treating a non-finite one as nothing measured."""

    return float(value) if math.isfinite(value) else 0.0
