"""Typed contracts for the offline farming and navigation simulator."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.telemetry.models import KillCycle

SIMULATOR_SCHEMA_VERSION = "us072-v1"
DEFAULT_TICK_SECONDS = 0.5
DEFAULT_SPEED_UNITS_PER_SECOND = 10.0
DEFAULT_TURN_RATE_RADIANS_PER_SECOND = 3.0
DEFAULT_COMBAT_TIME_SIGMA = 0.25
DEFAULT_RECOVERY_TIME_SIGMA = 0.4
DEFAULT_STUCK_PROBABILITY_PER_UNIT = 0.001
MINIMUM_SAMPLED_SECONDS = 0.05


def sample_log_normal(random_source: random.Random, mean_seconds: float, sigma: float) -> float:
    """Sample a positive duration whose arithmetic mean is calibrated."""

    if mean_seconds <= 0.0:
        raise ValueError("A sampled duration must have a positive target mean.")
    normal_sigma = math.sqrt(math.log1p((sigma / mean_seconds) ** 2))
    normal_mu = math.log(mean_seconds) - normal_sigma * normal_sigma / 2.0
    value = math.exp(random_source.gauss(normal_mu, normal_sigma))
    return max(MINIMUM_SAMPLED_SECONDS, value)


class QuestObjectiveKind(StrEnum):
    """The objective types modeled by the offline quest engine."""

    GO_TO = "go_to"
    KILL = "kill"
    INTERACT = "interact"
    TALK_TO_NPC = "talk_to_npc"


class MonsterLifecycle(StrEnum):
    """The observable lifecycle of one simulated monster."""

    SPAWNING = "spawning"
    ALIVE = "alive"
    IN_COMBAT = "in_combat"
    DEAD = "dead"
    DESPAWNING = "despawning"


@dataclass(frozen=True, slots=True)
class QuestObjective:
    """One client-level goal tracked without inventing quest script behavior."""

    kind: QuestObjectiveKind
    identifier: str | None = None
    monster_id: int | None = None
    npc_id: str | None = None
    position_x: float | None = None
    position_z: float | None = None
    radius_units: float = 5.0
    required_count: int = 1

    def __post_init__(self) -> None:
        if self.required_count < 1:
            raise ValueError("A quest objective requires at least one completion.")
        if self.kind is QuestObjectiveKind.KILL and self.monster_id is None:
            raise ValueError("A kill objective needs a monster ID.")
        if self.kind in (QuestObjectiveKind.INTERACT, QuestObjectiveKind.TALK_TO_NPC):
            if not self.identifier and not self.npc_id:
                raise ValueError("An interaction objective needs an object or NPC identifier.")
            if self.position_x is None or self.position_z is None:
                raise ValueError("An interaction objective needs a world position.")
        if self.kind is QuestObjectiveKind.GO_TO and (
            self.position_x is None or self.position_z is None
        ):
            raise ValueError("A movement objective needs a world position.")
        if self.radius_units <= 0.0:
            raise ValueError("A quest objective radius must be positive.")


@dataclass(frozen=True, slots=True)
class SimulatorConfig:
    """All stochastic and kinematic parameters used by one simulation."""

    tick_seconds: float = DEFAULT_TICK_SECONDS
    nominal_speed_units_per_second: float = DEFAULT_SPEED_UNITS_PER_SECOND
    turn_rate_radians_per_second: float = DEFAULT_TURN_RATE_RADIANS_PER_SECOND
    combat_time_mu: float = 1.0
    combat_time_sigma: float = DEFAULT_COMBAT_TIME_SIGMA
    stuck_probability_per_unit: float = DEFAULT_STUCK_PROBABILITY_PER_UNIT
    recovery_time_mu: float = 0.7
    recovery_time_sigma: float = DEFAULT_RECOVERY_TIME_SIGMA
    maximum_episode_seconds: float = 3600.0
    schema_version: str = SIMULATOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        positive_fields = (
            ("tick_seconds", self.tick_seconds),
            ("nominal_speed", self.nominal_speed_units_per_second),
            ("turn_rate", self.turn_rate_radians_per_second),
            ("maximum_episode_seconds", self.maximum_episode_seconds),
        )
        if any(value <= 0.0 for _label, value in positive_fields):
            raise ValueError("Simulator timing, speed, and episode limits must be positive.")
        if self.combat_time_sigma < 0.0 or self.recovery_time_sigma < 0.0:
            raise ValueError("Log-normal sigma values must not be negative.")
        if not 0.0 <= self.stuck_probability_per_unit <= 1.0:
            raise ValueError("Stuck probability per unit must be between zero and one.")


@dataclass(frozen=True, slots=True)
class SimulationMetrics:
    """Aggregate outcomes produced entirely in memory."""

    elapsed_seconds: float
    kill_count: int
    travel_seconds: float
    combat_seconds: float
    recovery_seconds: float
    idle_seconds: float
    distance_units: float
    stuck_count: int

    @property
    def kills_per_minute(self) -> float:
        return self.kill_count * 60.0 / self.elapsed_seconds if self.elapsed_seconds else 0.0

    @property
    def mean_travel_seconds(self) -> float:
        return self.travel_seconds / self.kill_count if self.kill_count else 0.0


@dataclass(frozen=True, slots=True)
class CalibrationBaseline:
    """Empirical farming statistics fitted from recorded US-054 kill cycles."""

    session_duration_seconds: float
    kill_count: int
    kills_per_minute: float
    mean_travel_seconds: float
    mean_combat_seconds: float
    stuck_frequency: float
    mean_recovery_seconds: float


@dataclass(frozen=True, slots=True)
class CalibrationTolerance:
    """Maximum accepted relative deviation from measured baselines."""

    kills_per_minute_fraction: float = 0.10
    travel_time_fraction: float = 0.10

    def __post_init__(self) -> None:
        if min(self.kills_per_minute_fraction, self.travel_time_fraction) <= 0.0:
            raise ValueError("Calibration tolerances must be positive.")


def fit_calibration(
    kill_cycles: tuple[KillCycle, ...], session_duration_seconds: float
) -> CalibrationBaseline:
    """Fit the aggregate baselines used by US-072 validation."""

    if not kill_cycles:
        raise ValueError("Calibration needs at least one recorded kill cycle.")
    if session_duration_seconds <= 0.0:
        raise ValueError("Calibration session duration must be positive.")
    verified = [cycle for cycle in kill_cycles if cycle.verified_kill]
    travel_times = [cycle.navigation_seconds for cycle in verified]
    combat_times = [cycle.combat_seconds for cycle in verified]
    recovery_times = [cycle.stall_seconds for cycle in kill_cycles if cycle.stall_seconds > 0.0]
    kill_count = len(verified)
    return CalibrationBaseline(
        session_duration_seconds=session_duration_seconds,
        kill_count=kill_count,
        kills_per_minute=kill_count * 60.0 / session_duration_seconds,
        mean_travel_seconds=sum(travel_times) / len(travel_times),
        mean_combat_seconds=sum(combat_times) / len(combat_times),
        stuck_frequency=len(recovery_times) / len(kill_cycles),
        mean_recovery_seconds=(
            sum(recovery_times) / len(recovery_times) if recovery_times else 0.0
        ),
    )
