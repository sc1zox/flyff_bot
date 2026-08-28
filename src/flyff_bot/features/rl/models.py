"""Typed state contracts for the offline tactical RL environment."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from flyff_bot.features.policy.action_payloads import OBJECTIVE_KIND_ORDER, ObjectiveKind
from flyff_bot.features.rl.actions import ParameterizedAction, TacticalActionMask
from flyff_bot.features.telemetry.models import CandidateFeatures

# Every optional measurement is encoded as a value plus a paired missing indicator, so an
# absent observation can never alias a measured zero (BUG-031). Signed quantities keep their
# sign instead of being clamped at zero for the same reason.
OBSERVATION_DIMENSION = 105
RL_OBSERVATION_SCHEMA_VERSION = "us083-v1"
CANDIDATE_SLOTS = 4
CANDIDATE_FEATURE_COUNT = 11
POSITION_SCALE_UNITS = 10000.0
ELEVATION_SCALE_UNITS = 100.0
DISTANCE_SCALE_UNITS = 1000.0
SLOPE_SCALE_DEGREES = 90.0
VELOCITY_SCALE_UNITS_PER_SECOND = 10.0
MISSING_INDICATOR = 1.0
PRESENT_INDICATOR = 0.0
# An objective identity is a free-form string, so it is encoded as one bounded digest column.
# The digest is a content hash rather than ``hash()``, which is salted per process and would
# make the same objective encode differently in two runs.
IDENTITY_DIGEST_BYTES = 8
IDENTITY_DIGEST_MAXIMUM = float(2 ** (8 * IDENTITY_DIGEST_BYTES) - 1)
UNIT_SCALE = 1.0
# Bounds for the exact-profile columns. They are saturation limits, not game rules: a value
# beyond one of them clips to the edge of the range rather than escaping [-1, 1], and every
# column carries its own missing indicator so a clipped value is still distinguishable from
# an unread one. The character cap and the attribute ceiling are set well above anything the
# client reports so that ordinary play never spends its whole range in the top few percent.
LEVEL_SCALE = 200.0
ATTRIBUTE_SCALE_POINTS = 500.0
FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class PlayerKinematics:
    position_x: float
    position_y: float
    position_z: float
    heading_radians: float
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    velocity_z: float = 0.0

    @property
    def speed(self) -> float:
        return float(np.linalg.norm((self.velocity_x, self.velocity_y, self.velocity_z)))


@dataclass(frozen=True, slots=True)
class PlayerVitals:
    hp_percentage: float
    mp_percentage: float
    fp_percentage: float
    buff_cooldowns: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class NavMeshContext:
    current_polygon_id: str | None
    terrain_slope: float | None
    active_route_distance: float | None


@dataclass(frozen=True, slots=True)
class CandidateObservation:
    candidate_index: int
    class_id: int
    confidence: float
    position_x: float | None
    position_y: float | None
    position_z: float | None
    path_distance: float | None
    relative_elevation: float | None
    is_dead: bool = False
    is_locked_out: bool = False
    is_unreachable: bool = False


@dataclass(frozen=True, slots=True)
class OperationalState:
    current_target_index: int | None
    recent_kill_rate_per_minute: float
    recent_stuck_count: int
    mode: Literal["farming", "navigation", "quest"] | str


@dataclass(frozen=True, slots=True)
class ObjectiveState:
    """The goal one decision is conditioned on (US-079).

    Two identical world states that are being observed under two different objectives must not
    encode to the same vector: without the objective identity, its kind, its position in the
    quest sequence and its measured progress, a policy cannot tell which goal it is serving.
    ``objective_target_distance`` is the remaining route distance to that objective.
    """

    quest_id: str | None = None
    objective_progress: tuple[tuple[int, float], ...] = ()
    objective_target_distance: float | None = None
    objective_id: str | None = None
    objective_kind: ObjectiveKind | None = None
    objective_index: int | None = None
    objective_count: int = 1
    measured_progress: float | None = None
    required_progress: float | None = None

    def __post_init__(self) -> None:
        if self.objective_count < 1:
            raise ValueError("An objective sequence holds at least one objective.")
        if self.objective_index is not None and not 0 <= self.objective_index < (
            self.objective_count
        ):
            raise ValueError("An objective index lies inside its own sequence.")
        if self.required_progress is not None and self.required_progress <= 0.0:
            raise ValueError("A required objective progress is positive.")


@dataclass(frozen=True, slots=True)
class PlayerProfileObservation:
    """The proven exact-profile statistics one decision was encoded from (US-083).

    Every statistic is optional and encodes as a value paired with its own missing indicator,
    so a field the client never exposed cannot alias a measured zero. ``is_authoritative`` is
    the provenance column: it states whether any of these numbers came from a fingerprinted
    client read at all, which is what separates "the character has no FP" from "this install
    has no profile and cannot say".

    ``target_identity_agreed`` carries the client-versus-visual reconciliation as a tri-state:
    agreed, disagreed, or - as ``None`` - never proven either way. A policy that cannot see the
    disagreement would keep ranking a candidate the client says it is not fighting.
    """

    is_authoritative: bool = False
    level: float | None = None
    experience_fraction: float | None = None
    strength: float | None = None
    stamina: float | None = None
    dexterity: float | None = None
    intelligence: float | None = None
    target_hp_fraction: float | None = None
    target_is_alive: bool | None = None
    target_identity_agreed: bool | None = None


@dataclass(frozen=True, slots=True)
class ReadinessObservation:
    """Exact central readiness fields retained alongside the normalized vector."""

    state: str = "ready"
    primary_reason: str | None = None
    failed_source_codes: tuple[str, ...] = ()
    sample_ages_seconds: tuple[tuple[str, float | None], ...] = ()
    action_blocked: bool = False


@dataclass(frozen=True, slots=True)
class RlObservation:
    kinematics: PlayerKinematics
    vitals: PlayerVitals
    navmesh: NavMeshContext
    candidates: tuple[CandidateObservation, ...]
    operational: OperationalState
    objective: ObjectiveState
    readiness: ReadinessObservation = field(default_factory=ReadinessObservation)
    profile: PlayerProfileObservation = field(default_factory=PlayerProfileObservation)


@dataclass(frozen=True, slots=True)
class Transition:
    """One complete MDP interval recorded inside a single session and episode.

    Every field describes the same real interval: the state at the decision, the exact
    parameterized choice that was taken, the reward observed until the following decision, the
    state at that following decision, both masks, and how the interval ended (BUG-031).
    """

    observation: RlObservation
    action: ParameterizedAction
    reward: float
    next_observation: RlObservation
    action_mask: TacticalActionMask
    terminated: bool
    next_action_mask: TacticalActionMask = field(default_factory=TacticalActionMask)
    truncated: bool = False
    session_id: str = ""
    episode_index: int = 0
    tactical_parameter_digest: str = ""


class ObservationSpace:
    """Convert typed observations into bounded normalized vectors."""

    @staticmethod
    def encode(observation: RlObservation) -> FloatArray:
        values = [
            _signed_unit(observation.kinematics.position_x, POSITION_SCALE_UNITS),
            _signed_unit(observation.kinematics.position_y, POSITION_SCALE_UNITS),
            _signed_unit(observation.kinematics.position_z, POSITION_SCALE_UNITS),
            np.sin(observation.kinematics.heading_radians),
            np.cos(observation.kinematics.heading_radians),
            *_clipped_vector(
                (
                    observation.kinematics.velocity_x,
                    observation.kinematics.velocity_y,
                    observation.kinematics.velocity_z,
                ),
                VELOCITY_SCALE_UNITS_PER_SECOND,
            ),
            min(observation.kinematics.speed / VELOCITY_SCALE_UNITS_PER_SECOND, 1.0),
        ]
        values.extend(
            [
                _unit(observation.vitals.hp_percentage),
                _unit(observation.vitals.mp_percentage),
                _unit(observation.vitals.fp_percentage),
            ]
        )
        valid_ages = [
            age
            for _source, age in observation.readiness.sample_ages_seconds
            if age is not None and np.isfinite(age) and age >= 0.0
        ]
        values.extend(
            [
                float(observation.readiness.state == "ready"),
                float(observation.readiness.action_blocked),
                min(len(observation.readiness.failed_source_codes) / 6.0, 1.0),
                min(max(valid_ages, default=0.0) / 60.0, 1.0),
            ]
        )
        cooldowns = list(observation.vitals.buff_cooldowns[:3])
        cooldowns.extend([0.0] * (3 - len(cooldowns)))
        values.extend(_unit(value) for value in cooldowns)
        values.append(float(observation.navmesh.current_polygon_id is not None))
        values.extend(
            _optional_pair(observation.navmesh.terrain_slope, SLOPE_SCALE_DEGREES, signed=True)
        )
        values.extend(
            _optional_pair(observation.navmesh.active_route_distance, DISTANCE_SCALE_UNITS)
        )
        candidate_values = list(_ABSENT_CANDIDATE_SLOT) * CANDIDATE_SLOTS
        for slot, candidate in enumerate(observation.candidates[:CANDIDATE_SLOTS]):
            offset = slot * CANDIDATE_FEATURE_COUNT
            candidate_values[offset : offset + CANDIDATE_FEATURE_COUNT] = [
                _unit(candidate.confidence),
                float(candidate.class_id % 1000) / 1000.0,
                *_optional_pair(candidate.path_distance, DISTANCE_SCALE_UNITS),
                *_optional_pair(candidate.relative_elevation, ELEVATION_SCALE_UNITS, signed=True),
                *_optional_pair(candidate.position_x, POSITION_SCALE_UNITS, signed=True),
                *_optional_pair(candidate.position_y, POSITION_SCALE_UNITS, signed=True),
                float(candidate.is_dead or candidate.is_locked_out or candidate.is_unreachable),
            ]
        values.extend(candidate_values)
        values.extend(
            [
                float(observation.operational.current_target_index is not None),
                min(max(observation.operational.recent_kill_rate_per_minute / 60.0, 0.0), 1.0),
                min(observation.operational.recent_stuck_count / 10.0, 1.0),
                float(observation.objective.quest_id is not None),
                *_optional_pair(
                    observation.objective.objective_target_distance, DISTANCE_SCALE_UNITS
                ),
                sum(progress[1] for progress in observation.objective.objective_progress)
                / max(sum(progress[0] for progress in observation.objective.objective_progress), 1),
            ]
        )
        values.extend(_profile_columns(observation.profile))
        values.extend(_goal_columns(observation.objective))
        encoded = np.asarray(values, dtype=np.float64)
        if encoded.shape != (OBSERVATION_DIMENSION,) or not np.all(np.isfinite(encoded)):
            raise ValueError("An RL observation could not be normalized.")
        if np.any((encoded < -1.0) | (encoded > 1.0)):
            raise ValueError("An RL observation fell outside [-1, 1].")
        return encoded

    @classmethod
    def from_telemetry_snapshot(
        cls,
        snapshot: dict[str, object],
        candidates: tuple[CandidateFeatures, ...] = (),
    ) -> RlObservation:
        position = _mapping(snapshot.get("player_position"))
        velocity = _mapping(snapshot.get("player_velocity"))
        buff_values = list(_mapping(snapshot.get("buff_cooldowns")).values())[:3]
        buff_cooldowns = tuple(float(str(value)) for value in buff_values)
        while len(buff_cooldowns) < 3:
            buff_cooldowns = (*buff_cooldowns, 0.0)

        candidate_observations: list[CandidateObservation] = []
        for candidate in candidates[:4]:
            world = candidate.world_position
            candidate_observations.append(
                CandidateObservation(
                    candidate.candidate_index,
                    candidate.class_id,
                    candidate.confidence,
                    None if world is None else world.x,
                    None if world is None else world.y,
                    None if world is None else world.z,
                    candidate.path_distance,
                    candidate.relative_elevation,
                    is_locked_out=candidate.is_locked_out,
                )
            )

        return RlObservation(
            PlayerKinematics(
                float(str(position["x"])),
                float(str(position["y"])),
                float(str(position["z"])),
                0.0,
                float(str(velocity["x"])),
                float(str(velocity["y"])),
                float(str(velocity["z"])),
            ),
            PlayerVitals(
                float(str(snapshot.get("hp_percentage", 0.0))),
                float(str(snapshot.get("mp_percentage", 0.0))),
                float(str(snapshot.get("fp_percentage", 0.0))),
                buff_cooldowns,
            ),
            NavMeshContext(
                _optional_text(snapshot.get("player_navmesh_polygon_id")),
                _optional_number(snapshot.get("player_terrain_slope")),
                None,
            ),
            tuple(candidate_observations),
            OperationalState(None, 0.0, 0, str(snapshot.get("farming_mode", "unknown"))),
            ObjectiveState(None, (), None),
            ReadinessObservation(
                state=str(snapshot.get("readiness_state", "ready")),
                primary_reason=_optional_text(snapshot.get("readiness_primary_reason")),
                failed_source_codes=_text_tuple(snapshot.get("failed_source_codes")),
                sample_ages_seconds=_sample_ages(snapshot.get("sample_ages_seconds")),
                action_blocked=bool(snapshot.get("action_blocked", False)),
            ),
        )


def _goal_columns(objective: ObjectiveState) -> list[float]:
    """Return the goal-conditioned block of one observation.

    The block names *which* objective is being pursued, not only how far away it is, so the
    same world state under two different goals encodes differently (US-079).
    """

    index_fraction = (
        None
        if objective.objective_index is None
        else objective.objective_index / objective.objective_count
    )
    progress_fraction = (
        None
        if objective.measured_progress is None or objective.required_progress is None
        else objective.measured_progress / objective.required_progress
    )
    return [
        *_identity_pair(objective.objective_id),
        *(float(objective.objective_kind is kind) for kind in OBJECTIVE_KIND_ORDER),
        *_optional_pair(index_fraction, UNIT_SCALE),
        *_optional_pair(progress_fraction, UNIT_SCALE),
    ]


def _identity_pair(identity: str | None) -> tuple[float, float]:
    """Return a stable bounded digest of one identity paired with its missing indicator."""

    if identity is None:
        return 0.0, MISSING_INDICATOR
    digest = hashlib.blake2b(identity.encode("utf-8"), digest_size=IDENTITY_DIGEST_BYTES).digest()
    return int.from_bytes(digest, "big") / IDENTITY_DIGEST_MAXIMUM, PRESENT_INDICATOR


def _clipped_vector(values: tuple[float, ...], maximum_abs: float) -> tuple[float, ...]:
    return tuple(min(max(value / maximum_abs, -1.0), 1.0) for value in values)


def _unit(value: float) -> float:
    return min(max(float(value) / 100.0, 0.0), 1.0)


def _signed_unit(value: float, maximum: float) -> float:
    """Scale a measurement into ``[-1, 1]`` without discarding its sign."""

    return min(max(float(value) / maximum, -1.0), 1.0)


def _profile_columns(profile: PlayerProfileObservation) -> list[float]:
    """Encode every proven statistic with its provenance and its missingness."""

    return [
        float(profile.is_authoritative),
        *_optional_pair(profile.level, LEVEL_SCALE),
        *_optional_pair(profile.experience_fraction, UNIT_SCALE),
        *_optional_pair(profile.strength, ATTRIBUTE_SCALE_POINTS),
        *_optional_pair(profile.stamina, ATTRIBUTE_SCALE_POINTS),
        *_optional_pair(profile.dexterity, ATTRIBUTE_SCALE_POINTS),
        *_optional_pair(profile.intelligence, ATTRIBUTE_SCALE_POINTS),
        *_optional_pair(profile.target_hp_fraction, UNIT_SCALE),
        *_optional_flag(profile.target_is_alive),
        *_optional_flag(profile.target_identity_agreed),
    ]


def _optional_flag(value: bool | None) -> tuple[float, float]:
    """Return a tri-state flag as a value paired with its explicit missing indicator."""

    if value is None:
        return 0.0, MISSING_INDICATOR
    return float(value), PRESENT_INDICATOR


def _optional_pair(
    value: float | None, maximum: float, *, signed: bool = False
) -> tuple[float, float]:
    """Return a scaled measurement paired with its explicit missing indicator."""

    if value is None:
        return 0.0, MISSING_INDICATOR
    scaled = _signed_unit(value, maximum) if signed else min(max(float(value) / maximum, 0.0), 1.0)
    return scaled, PRESENT_INDICATOR


# An unoccupied candidate slot is not a candidate at coordinate zero: every optional column is
# reported missing and the slot is flagged unusable.
_ABSENT_CANDIDATE_SLOT: tuple[float, ...] = (
    0.0,
    0.0,
    0.0,
    MISSING_INDICATOR,
    0.0,
    MISSING_INDICATOR,
    0.0,
    MISSING_INDICATOR,
    0.0,
    MISSING_INDICATOR,
    1.0,
)


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _optional_number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)


def _sample_ages(value: object) -> tuple[tuple[str, float | None], ...]:
    if not isinstance(value, list | tuple):
        return ()
    ages: list[tuple[str, float | None]] = []
    for item in value:
        if not isinstance(item, list | tuple) or len(item) != 2:
            continue
        age = item[1]
        ages.append((str(item[0]), float(age) if isinstance(age, int | float) else None))
    return tuple(ages)
