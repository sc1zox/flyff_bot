"""Typed, serializable telemetry contracts for offline farming analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum
from math import sqrt
from typing import Any
from uuid import uuid4

TELEMETRY_SCHEMA_VERSION = 4
TRAJECTORY_SCHEMA_VERSION = 2


class TelemetryEventKind(StrEnum):
    """The append-only record types written for one farming session."""

    SESSION_HEADER = "session_header"
    WORLD_SNAPSHOT = "world_snapshot"
    TARGET_SELECTED = "target_selected"
    NAVIGATION_EPISODE = "navigation_episode"
    COMBAT_EPISODE = "combat_episode"
    KILL_CYCLE = "kill_cycle"
    STALL_EVENT = "stall_event"
    OBJECTIVE_PROGRESS = "objective_progress"


class NavigationOutcome(StrEnum):
    """The observed end state of one navigation episode."""

    REACHED_TARGET = "reached_target"
    ROUTE_UNAVAILABLE = "route_unavailable"
    SESSION_CLOSED = "session_closed"


class CombatOutcome(StrEnum):
    """The observed end state of one combat engagement."""

    KILL_VERIFIED = "kill_verified"
    TARGET_LOST = "target_lost"


class CombatVerificationSource(StrEnum):
    """The observation that confirmed a target defeat."""

    HUD_COUNTER = "hud_counter"
    HP_ZERO = "hp_zero"


@dataclass(frozen=True, slots=True)
class TelemetryPosition:
    """A position in client-world units, never a screen-coordinate estimate."""

    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class TelemetryVelocity:
    """A derived world-space velocity vector in units per second."""

    x: float
    y: float
    z: float

    @property
    def speed(self) -> float:
        """Return the scalar magnitude of this vector."""

        return sqrt(self.x**2 + self.y**2 + self.z**2)


@dataclass(frozen=True, slots=True)
class TelemetrySessionMetadata:
    """Immutable metadata supplied when a telemetry session starts."""

    area_id: str
    client_sha256: str | None = None
    bot_version: str | None = None
    active_models: tuple[str, ...] = ()
    navmesh_version: str | None = None
    active_spawn_zone: dict[str, Any] | None = None
    session_id: str = ""
    session_start_utc: str = ""

    def with_generated_identity(self, *, session_start_utc: str) -> TelemetrySessionMetadata:
        """Return metadata with a UUID4 and UTC timestamp when callers omitted them."""

        return TelemetrySessionMetadata(
            area_id=self.area_id,
            client_sha256=self.client_sha256,
            bot_version=self.bot_version,
            active_models=self.active_models,
            navmesh_version=self.navmesh_version,
            active_spawn_zone=self.active_spawn_zone,
            session_id=self.session_id or str(uuid4()),
            session_start_utc=self.session_start_utc or session_start_utc,
        )


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    """The numeric state collected once per successful farming observation."""

    timestamp_ns: int
    player_position: TelemetryPosition | None
    player_velocity: TelemetryVelocity | None
    player_speed: float | None
    position_source: str
    player_navmesh_polygon_id: str | None
    player_terrain_slope: float | None
    hp_percentage: float
    mp_percentage: float
    fp_percentage: float
    buff_cooldowns: dict[str, float]
    farming_mode: str
    visible_mob_count: int
    readiness_state: str
    readiness_primary_reason: str | None
    failed_source_codes: tuple[str, ...]
    sample_ages_seconds: tuple[tuple[str, float | None], ...]
    action_blocked: bool


@dataclass(frozen=True, slots=True)
class CandidateFeatures:
    """Noise-free features for one visible target candidate at selection time."""

    candidate_index: int
    class_id: int
    class_name: str
    confidence: float
    x: int
    y: int
    width: int
    height: int
    center_x: float
    center_y: float
    screen_distance_to_center: float | None
    bbox_area: int
    world_position: TelemetryPosition | None
    relative_distance: float | None
    relative_elevation: float | None
    target_navmesh_polygon_id: str | None
    path_distance: float | None
    is_locked_out: bool


@dataclass(frozen=True, slots=True)
class TargetDecision:
    """One chosen candidate and the complete ordered candidate matrix."""

    timestamp_ns: int
    player_position: TelemetryPosition | None
    selected_candidate_index: int
    decision_reason: str
    decision_latency_ms: float
    candidates: tuple[CandidateFeatures, ...]


@dataclass(frozen=True, slots=True)
class NavigationEpisode:
    """A completed movement attempt and its sampled GPS trajectory."""

    started_at_ns: int
    ended_at_ns: int
    start_position: TelemetryPosition | None
    target_position: TelemetryPosition | None
    planned_route: tuple[TelemetryPosition, ...]
    planned_length: float | None
    actual_travel_distance: float
    trajectory: tuple[tuple[int, TelemetryPosition, float | None, str | None, bool], ...]
    replans_count: int
    stall_events: int
    stall_duration_seconds: float
    collision_evasions: int
    outcome: str
    # The measured time spent executing evasive recovery input, kept separate from
    # ``stall_duration_seconds`` so being blocked and recovering stay distinguishable.
    evasion_seconds: float = 0.0

    @property
    def path_efficiency(self) -> float | None:
        """Return plan / observed distance only when it is mathematically defined."""

        if self.planned_length is None or self.actual_travel_distance <= 0.0:
            return None
        return self.planned_length / self.actual_travel_distance


@dataclass(frozen=True, slots=True)
class AttackAction:
    """One foreground-guarded combat key that was actually dispatched."""

    timestamp_ns: int
    virtual_key: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class CombatEpisode:
    """A completed combat attempt and its visual verification result."""

    started_at_ns: int
    ended_at_ns: int
    target_name: str | None
    player_hp_start: float
    player_hp_end: float
    target_hp_start_pct: float | None
    target_hp_end_pct: float | None
    attack_actions: tuple[AttackAction, ...]
    outcome: str
    verification_source: CombatVerificationSource | None


@dataclass(frozen=True, slots=True)
class KillCycle:
    """A reproducible kill-to-kill timing decomposition and RL reward inputs."""

    timestamp_ns: int
    decision_seconds: float
    navigation_seconds: float
    combat_seconds: float
    idle_seconds: float
    damage_taken: float
    stall_seconds: float
    verified_kill: bool
    reward: float
    target_decision_timestamp_ns: int | None = None

    @property
    def total_seconds(self) -> float:
        """Return the exact sum persisted for this kill-to-kill cycle."""

        return (
            self.decision_seconds
            + self.navigation_seconds
            + self.combat_seconds
            + self.idle_seconds
        )


@dataclass(frozen=True, slots=True)
class ObjectiveProgress:
    """One observed advance of the active kill quota or quest objective."""

    timestamp_ns: int
    quest_id: str | None
    progress_delta: float
    objective_completed: bool


def primitive(value: object) -> object:
    """Convert typed telemetry data to JSON-compatible primitives without lossy guesses."""

    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {key: primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple | list):
        return [primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): primitive(item) for key, item in value.items()}
    return value
