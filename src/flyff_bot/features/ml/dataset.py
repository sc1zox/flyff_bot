"""Offline ingestion of the US-054 Parquet telemetry into supervised farming samples.

The builder joins the three exported tables into one row per *executed* target decision. Only
the candidate the bot actually selected becomes a supervised sample: unselected candidates stay
counterfactually unknown and contribute nothing but observed context counts, so no synthetic
reward is ever attributed to an action that was never taken.
"""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from flyff_bot.features.ml.features import (
    WorldPoint,
    angular_difference,
    bearing,
    corridor_metrics,
    route_slope,
)
from flyff_bot.features.telemetry.exporter import (
    KILL_CYCLES_FILE,
    NAVIGATION_TRAJECTORIES_FILE,
    TARGET_DECISIONS_FILE,
)

NANOSECONDS_PER_SECOND = 1_000_000_000
# Follow-up value horizons. A kill closer than one horizon to the end of its session is
# right-censored: the window was never fully observed, so the label stays unknown.
FOLLOWUP_SHORT_WINDOW_SECONDS = 5.0
FOLLOWUP_LONG_WINDOW_SECONDS = 10.0
# Backward window used for the historical rate features. Two minutes is long enough to smooth
# single-kill noise and short enough to still describe the spot currently being farmed.
RECENT_HISTORY_WINDOW_SECONDS = 120.0
# World units within which another candidate counts as part of the same local cluster.
NEARBY_CANDIDATE_DISTANCE_UNITS = 40.0
DEFAULT_HOLDOUT_FRACTION = 0.25


class SplitStrategy(StrEnum):
    """How a dataset was divided so that no session appears on both sides."""

    SESSION = "session"
    TEMPORAL = "temporal"


class FollowupValueDefinition(StrEnum):
    """The versioned observable that defines post-kill farming value."""

    KILLS_NEXT_5S = "kills_next_5s"
    KILLS_NEXT_10S = "kills_next_10s"
    TARGETABLE_MOBS_AFTER_KILL = "targetable_mobs_after_kill"


class DatasetErrorCode(StrEnum):
    """Machine-readable reasons an offline dataset cannot be built."""

    TABLE_MISSING = "table_missing"
    TABLE_UNREADABLE = "table_unreadable"
    NO_SAMPLES = "no_samples"


class DatasetError(RuntimeError):
    """A telemetry dataset could not be read or produced no linked samples."""

    def __init__(self, code: DatasetErrorCode, detail: str = "") -> None:
        super().__init__(f"{code.value}:{detail}" if detail else code.value)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """One evaluated target candidate as it was observed at decision time."""

    candidate_index: int
    selected: bool
    class_id: float | None
    confidence: float | None
    relative_distance: float | None
    relative_elevation: float | None
    path_distance: float | None
    is_locked_out: bool


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One target decision together with its complete observed candidate matrix."""

    session_id: str
    timestamp_ns: int
    selected_candidate_index: int
    decision_latency_ms: float | None
    candidates: tuple[CandidateRecord, ...]

    @property
    def selected_candidate(self) -> CandidateRecord | None:
        """Return the executed candidate, or ``None`` when the decision logged none."""

        return next((candidate for candidate in self.candidates if candidate.selected), None)

    @property
    def targetable_candidate_count(self) -> int:
        """Return how many observed candidates were not on the spatial lockout list."""

        return sum(1 for candidate in self.candidates if not candidate.is_locked_out)


@dataclass(frozen=True, slots=True)
class NavigationRecord:
    """One navigation episode, its planned corridor, and its sampled GPS trajectory."""

    session_id: str
    episode_started_at_ns: int
    outcome: str | None
    start_position: WorldPoint | None
    target_position: WorldPoint | None
    planned_route: tuple[WorldPoint, ...]
    planned_length: float | None
    actual_travel_distance: float | None
    stall_events: int | None
    trajectory: tuple[tuple[int, WorldPoint], ...]


@dataclass(frozen=True, slots=True)
class KillCycleRecord:
    """One observed kill-to-kill cycle and its timing decomposition."""

    session_id: str
    timestamp_ns: int
    decision_seconds: float
    navigation_seconds: float
    combat_seconds: float
    idle_seconds: float
    damage_taken: float
    stall_seconds: float
    verified_kill: bool
    reward: float
    target_decision_timestamp_ns: int | None

    @property
    def total_seconds(self) -> float:
        """Return the reconstructed kill-to-kill duration of this cycle."""

        return (
            self.decision_seconds
            + self.navigation_seconds
            + self.combat_seconds
            + self.idle_seconds
        )


@dataclass(frozen=True, slots=True)
class FarmingLabels:
    """Ground truth read strictly from observed session transitions."""

    actual_travel_time: float | None
    stuck_occurred: bool
    actual_stuck_time: float | None
    actual_recovery_time: float | None
    actual_kill_time: float | None
    kill_to_kill_time: float | None
    targetable_mobs_after_kill: float | None
    kills_next_5s: float | None
    kills_next_10s: float | None

    def followup_value(self, definition: FollowupValueDefinition) -> float | None:
        """Return the configured post-kill value observable for this cycle."""

        match definition:
            case FollowupValueDefinition.KILLS_NEXT_5S:
                return self.kills_next_5s
            case FollowupValueDefinition.KILLS_NEXT_10S:
                return self.kills_next_10s
            case FollowupValueDefinition.TARGETABLE_MOBS_AFTER_KILL:
                return self.targetable_mobs_after_kill


@dataclass(frozen=True, slots=True)
class FarmingSample:
    """One executed target decision, its derived features, and its observed outcome."""

    session_id: str
    decision_timestamp_ns: int
    features: dict[str, float | None]
    labels: FarmingLabels
    unselected_candidate_count: int


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    """A leakage-free division of samples into training and holdout blocks."""

    train: tuple[FarmingSample, ...]
    holdout: tuple[FarmingSample, ...]
    strategy: SplitStrategy

    @property
    def session_ids(self) -> tuple[str, ...]:
        """Return every distinct session contributing to this split, in stable order."""

        return tuple(sorted({sample.session_id for sample in self.train + self.holdout}))


def load_target_decisions(path: Path) -> tuple[DecisionRecord, ...]:
    """Read the exported candidate matrix back into one record per target decision."""

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_table(path):
        grouped[(str(row["session_id"]), int(row["timestamp_ns"]))].append(row)
    decisions: list[DecisionRecord] = []
    for (session_id, timestamp_ns), rows in grouped.items():
        rows.sort(key=lambda row: int(row["candidate_index"]))
        first = rows[0]
        decisions.append(
            DecisionRecord(
                session_id=session_id,
                timestamp_ns=timestamp_ns,
                selected_candidate_index=int(first["selected_candidate_index"]),
                decision_latency_ms=_optional_float(first.get("decision_latency_ms")),
                candidates=tuple(_candidate(row) for row in rows),
            )
        )
    decisions.sort(key=lambda decision: (decision.session_id, decision.timestamp_ns))
    return tuple(decisions)


def load_navigation_episodes(path: Path) -> tuple[NavigationRecord, ...]:
    """Read the exported 10 Hz trajectory rows back into one record per episode."""

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_table(path):
        grouped[(str(row["session_id"]), int(row["episode_started_at_ns"]))].append(row)
    episodes: list[NavigationRecord] = []
    for (session_id, started_at_ns), rows in grouped.items():
        rows.sort(key=lambda row: int(row["trajectory_index"]))
        first = rows[0]
        trajectory = tuple(
            (int(row["timestamp_ns"]), point)
            for row in rows
            if (point := _point(row, "x", "y", "z")) is not None
        )
        episodes.append(
            NavigationRecord(
                session_id=session_id,
                episode_started_at_ns=started_at_ns,
                outcome=None if first.get("outcome") is None else str(first["outcome"]),
                start_position=_point(first, "start_x", "start_y", "start_z"),
                target_position=_point(first, "target_x", "target_y", "target_z"),
                planned_route=_planned_route(first.get("planned_route_json")),
                planned_length=_optional_float(first.get("planned_length")),
                actual_travel_distance=_optional_float(first.get("actual_travel_distance")),
                stall_events=_optional_int(first.get("stall_events")),
                trajectory=trajectory,
            )
        )
    episodes.sort(key=lambda episode: (episode.session_id, episode.episode_started_at_ns))
    return tuple(episodes)


def load_kill_cycles(path: Path) -> tuple[KillCycleRecord, ...]:
    """Read the exported kill-to-kill cycles back into typed outcome records."""

    cycles = [
        KillCycleRecord(
            session_id=str(row["session_id"]),
            timestamp_ns=int(row["timestamp_ns"]),
            decision_seconds=_float(row.get("decision_seconds")),
            navigation_seconds=_float(row.get("navigation_seconds")),
            combat_seconds=_float(row.get("combat_seconds")),
            idle_seconds=_float(row.get("idle_seconds")),
            damage_taken=_float(row.get("damage_taken")),
            stall_seconds=_float(row.get("stall_seconds")),
            verified_kill=bool(row.get("verified_kill")),
            reward=_float(row.get("reward")),
            target_decision_timestamp_ns=_optional_int(row.get("target_decision_timestamp_ns")),
        )
        for row in _read_table(path)
    ]
    cycles.sort(key=lambda cycle: (cycle.session_id, cycle.timestamp_ns))
    return tuple(cycles)


def build_samples(dataset_directory: Path) -> tuple[FarmingSample, ...]:
    """Join the three telemetry tables into deterministically linked training samples."""

    decisions = load_target_decisions(dataset_directory / TARGET_DECISIONS_FILE)
    episodes = load_navigation_episodes(dataset_directory / NAVIGATION_TRAJECTORIES_FILE)
    cycles = load_kill_cycles(dataset_directory / KILL_CYCLES_FILE)
    samples = _correlate(decisions, episodes, cycles)
    if not samples:
        raise DatasetError(DatasetErrorCode.NO_SAMPLES, str(dataset_directory))
    return samples


def split_samples(
    samples: tuple[FarmingSample, ...],
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
) -> DatasetSplit:
    """Hold out whole sessions, falling back to a contiguous tail of a single session."""

    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError("holdout_fraction must lie strictly between 0 and 1")
    ordered = tuple(sorted(samples, key=_sample_order))
    by_session: dict[str, list[FarmingSample]] = defaultdict(list)
    for sample in ordered:
        by_session[sample.session_id].append(sample)
    if len(by_session) > 1:
        return _session_split(ordered, by_session, holdout_fraction)
    chronological = tuple(sorted(ordered, key=lambda sample: sample.decision_timestamp_ns))
    boundary = max(1, len(chronological) - max(1, round(len(chronological) * holdout_fraction)))
    return DatasetSplit(
        train=chronological[:boundary],
        holdout=chronological[boundary:],
        strategy=SplitStrategy.TEMPORAL,
    )


def _session_split(
    ordered: tuple[FarmingSample, ...],
    by_session: dict[str, list[FarmingSample]],
    holdout_fraction: float,
) -> DatasetSplit:
    """Move whole sessions into the holdout, which is what prevents session leakage."""

    holdout_target = max(1, round(len(ordered) * holdout_fraction))
    holdout: list[FarmingSample] = []
    train: list[FarmingSample] = []
    # Smallest sessions first keeps the realized holdout close to the requested share.
    for session_id in sorted(by_session, key=lambda key: (len(by_session[key]), key)):
        session_samples = by_session[session_id]
        if len(holdout) < holdout_target and len(train) + len(session_samples) < len(ordered):
            holdout.extend(session_samples)
        else:
            train.extend(session_samples)
    return DatasetSplit(
        train=tuple(sorted(train, key=_sample_order)),
        holdout=tuple(sorted(holdout, key=_sample_order)),
        strategy=SplitStrategy.SESSION,
    )


def _sample_order(sample: FarmingSample) -> tuple[str, int]:
    return sample.session_id, sample.decision_timestamp_ns


def _correlate(
    decisions: tuple[DecisionRecord, ...],
    episodes: tuple[NavigationRecord, ...],
    cycles: tuple[KillCycleRecord, ...],
) -> tuple[FarmingSample, ...]:
    decision_by_key = {
        (decision.session_id, decision.timestamp_ns): decision for decision in decisions
    }
    episodes_by_session: dict[str, list[NavigationRecord]] = defaultdict(list)
    for episode in episodes:
        episodes_by_session[episode.session_id].append(episode)
    decision_times: dict[str, list[int]] = defaultdict(list)
    for decision in decisions:
        decision_times[decision.session_id].append(decision.timestamp_ns)
    cycles_by_session: dict[str, list[KillCycleRecord]] = defaultdict(list)
    for cycle in cycles:
        cycles_by_session[cycle.session_id].append(cycle)
    session_end_ns = _session_end_timestamps(decisions, episodes, cycles)
    session_start_ns = _session_start_timestamps(decisions, episodes, cycles)

    samples: list[FarmingSample] = []
    for cycle in cycles:
        if cycle.target_decision_timestamp_ns is None:
            continue
        linked = decision_by_key.get((cycle.session_id, cycle.target_decision_timestamp_ns))
        if linked is None or linked.selected_candidate is None:
            continue
        travelled = _matching_episode(episodes_by_session[cycle.session_id], linked, cycle)
        samples.append(
            FarmingSample(
                session_id=cycle.session_id,
                decision_timestamp_ns=linked.timestamp_ns,
                features=_features(
                    linked,
                    travelled,
                    session_cycles=cycles_by_session[cycle.session_id],
                    session_start_ns=session_start_ns[cycle.session_id],
                ),
                labels=_labels(
                    cycle,
                    travelled,
                    session_cycles=cycles_by_session[cycle.session_id],
                    session_decision_times=decision_times[cycle.session_id],
                    decision_by_key=decision_by_key,
                    session_end_ns=session_end_ns[cycle.session_id],
                ),
                unselected_candidate_count=len(linked.candidates) - 1,
            )
        )
    samples.sort(key=_sample_order)
    return tuple(samples)


def _matching_episode(
    episodes: list[NavigationRecord], decision: DecisionRecord, cycle: KillCycleRecord
) -> NavigationRecord | None:
    """Return the navigation episode the bot ran between this decision and its kill."""

    matches = [
        episode
        for episode in episodes
        if decision.timestamp_ns <= episode.episode_started_at_ns <= cycle.timestamp_ns
    ]
    return matches[-1] if matches else None


def _features(
    decision: DecisionRecord,
    episode: NavigationRecord | None,
    *,
    session_cycles: list[KillCycleRecord],
    session_start_ns: int,
) -> dict[str, float | None]:
    selected = decision.selected_candidate
    if selected is None:
        raise DatasetError(DatasetErrorCode.NO_SAMPLES, decision.session_id)
    start = _episode_start(episode)
    target = None if episode is None else episode.target_position
    player_heading = _observed_heading(episode)
    target_bearing = (
        None
        if start is None or target is None
        else bearing(target[0] - start[0], target[2] - start[2])
    )
    corridor = corridor_metrics(() if episode is None else episode.planned_route)
    recent_kill_rate, recent_stuck_rate = _recent_rates(
        session_cycles, decision.timestamp_ns, session_start_ns
    )
    return {
        "path_distance": selected.path_distance,
        "relative_distance": selected.relative_distance,
        "relative_elevation": selected.relative_elevation,
        "player_heading": player_heading,
        "target_bearing": target_bearing,
        "heading_error": angular_difference(player_heading, target_bearing),
        "terrain_slope": route_slope(start, target),
        "corridor_length": corridor.length,
        "corridor_waypoint_count": float(corridor.waypoint_count) if episode is not None else None,
        "corridor_turn_angle_total": corridor.turn_angle_total,
        "corridor_max_turn_angle": corridor.max_turn_angle,
        "corridor_detour_ratio": corridor.detour_ratio,
        "target_class_id": selected.class_id,
        "detection_confidence": selected.confidence,
        "visible_mob_count": float(len(decision.candidates)),
        "reachable_mob_count": float(
            sum(1 for candidate in decision.candidates if candidate.path_distance is not None)
        ),
        "nearby_targetable_mob_count": _nearby_targetable_count(decision),
        "recent_kill_rate": recent_kill_rate,
        "recent_stuck_rate": recent_stuck_rate,
        "decision_latency_ms": decision.decision_latency_ms,
    }


def _episode_start(episode: NavigationRecord | None) -> WorldPoint | None:
    if episode is None:
        return None
    if episode.start_position is not None:
        return episode.start_position
    return episode.trajectory[0][1] if episode.trajectory else None


def _observed_heading(episode: NavigationRecord | None) -> float | None:
    """Return the heading of the first real displacement the player actually travelled."""

    if episode is None or len(episode.trajectory) < 2:
        return None
    origin = episode.trajectory[0][1]
    for _, point in episode.trajectory[1:]:
        heading = bearing(point[0] - origin[0], point[2] - origin[2])
        if heading is not None:
            return heading
    return None


def _nearby_targetable_count(decision: DecisionRecord) -> float | None:
    measured = [
        candidate.relative_distance
        for candidate in decision.candidates
        if candidate.relative_distance is not None and not candidate.is_locked_out
    ]
    if not any(candidate.relative_distance is not None for candidate in decision.candidates):
        return None
    return float(sum(1 for distance in measured if distance <= NEARBY_CANDIDATE_DISTANCE_UNITS))


def _recent_rates(
    session_cycles: list[KillCycleRecord], timestamp_ns: int, session_start_ns: int
) -> tuple[float | None, float | None]:
    """Return observed kills per second and stuck share over the preceding history window."""

    window_ns = int(RECENT_HISTORY_WINDOW_SECONDS * NANOSECONDS_PER_SECOND)
    lower = max(session_start_ns, timestamp_ns - window_ns)
    observed_ns = timestamp_ns - lower
    preceding = [cycle for cycle in session_cycles if lower <= cycle.timestamp_ns < timestamp_ns]
    kill_rate = (
        None
        if observed_ns <= 0
        else sum(1 for cycle in preceding if cycle.verified_kill)
        / (observed_ns / NANOSECONDS_PER_SECOND)
    )
    stuck_rate = (
        None
        if not preceding
        else sum(1 for cycle in preceding if cycle.stall_seconds > 0.0) / len(preceding)
    )
    return kill_rate, stuck_rate


def _labels(
    cycle: KillCycleRecord,
    episode: NavigationRecord | None,
    *,
    session_cycles: list[KillCycleRecord],
    session_decision_times: list[int],
    decision_by_key: dict[tuple[str, int], DecisionRecord],
    session_end_ns: int,
) -> FarmingLabels:
    stuck_occurred = cycle.stall_seconds > 0.0 or (
        episode is not None and episode.stall_events is not None and episode.stall_events > 0
    )
    return FarmingLabels(
        actual_travel_time=cycle.navigation_seconds,
        stuck_occurred=stuck_occurred,
        actual_stuck_time=cycle.stall_seconds,
        # The US-054 schema observes the interval the bot spent recovering as exactly the
        # measured stall interval. A cycle without a stall never recovered from anything, so
        # its recovery time stays unknown instead of being recorded as a real zero.
        actual_recovery_time=cycle.stall_seconds if stuck_occurred else None,
        actual_kill_time=cycle.combat_seconds,
        kill_to_kill_time=cycle.total_seconds,
        targetable_mobs_after_kill=_targetable_after_kill(
            cycle, session_decision_times, decision_by_key
        ),
        kills_next_5s=_kills_within(
            cycle, session_cycles, FOLLOWUP_SHORT_WINDOW_SECONDS, session_end_ns
        ),
        kills_next_10s=_kills_within(
            cycle, session_cycles, FOLLOWUP_LONG_WINDOW_SECONDS, session_end_ns
        ),
    )


def _targetable_after_kill(
    cycle: KillCycleRecord,
    session_decision_times: list[int],
    decision_by_key: dict[tuple[str, int], DecisionRecord],
) -> float | None:
    """Return how many mobs the next observed decision could still target after this kill."""

    index = bisect_right(session_decision_times, cycle.timestamp_ns)
    if index >= len(session_decision_times):
        return None
    following = decision_by_key.get((cycle.session_id, session_decision_times[index]))
    return None if following is None else float(following.targetable_candidate_count)


def _kills_within(
    cycle: KillCycleRecord,
    session_cycles: list[KillCycleRecord],
    window_seconds: float,
    session_end_ns: int,
) -> float | None:
    """Count verified kills inside a fully observed window, or ``None`` when censored."""

    horizon_ns = cycle.timestamp_ns + int(window_seconds * NANOSECONDS_PER_SECOND)
    if horizon_ns > session_end_ns:
        return None
    timestamps = [entry.timestamp_ns for entry in session_cycles]
    lower = bisect_right(timestamps, cycle.timestamp_ns)
    upper = bisect_left(timestamps, horizon_ns + 1)
    return float(sum(1 for entry in session_cycles[lower:upper] if entry.verified_kill))


def _session_end_timestamps(
    decisions: tuple[DecisionRecord, ...],
    episodes: tuple[NavigationRecord, ...],
    cycles: tuple[KillCycleRecord, ...],
) -> dict[str, int]:
    ends: dict[str, int] = {}
    for session_id, timestamp in _session_timestamps(decisions, episodes, cycles):
        ends[session_id] = max(ends.get(session_id, timestamp), timestamp)
    return ends


def _session_start_timestamps(
    decisions: tuple[DecisionRecord, ...],
    episodes: tuple[NavigationRecord, ...],
    cycles: tuple[KillCycleRecord, ...],
) -> dict[str, int]:
    starts: dict[str, int] = {}
    for session_id, timestamp in _session_timestamps(decisions, episodes, cycles):
        starts[session_id] = min(starts.get(session_id, timestamp), timestamp)
    return starts


def _session_timestamps(
    decisions: tuple[DecisionRecord, ...],
    episodes: tuple[NavigationRecord, ...],
    cycles: tuple[KillCycleRecord, ...],
) -> list[tuple[str, int]]:
    stamps: list[tuple[str, int]] = [
        (decision.session_id, decision.timestamp_ns) for decision in decisions
    ]
    stamps.extend((cycle.session_id, cycle.timestamp_ns) for cycle in cycles)
    for episode in episodes:
        stamps.append((episode.session_id, episode.episode_started_at_ns))
        stamps.extend((episode.session_id, timestamp) for timestamp, _ in episode.trajectory)
    return stamps


def _candidate(row: dict[str, Any]) -> CandidateRecord:
    return CandidateRecord(
        candidate_index=int(row["candidate_index"]),
        selected=bool(row.get("selected")),
        class_id=_optional_float(row.get("class_id")),
        confidence=_optional_float(row.get("confidence")),
        relative_distance=_optional_float(row.get("relative_distance")),
        relative_elevation=_optional_float(row.get("relative_elevation")),
        path_distance=_optional_float(row.get("path_distance")),
        is_locked_out=bool(row.get("is_locked_out")),
    )


def _planned_route(payload: object) -> tuple[WorldPoint, ...]:
    if not isinstance(payload, str):
        return ()
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(
        point
        for entry in decoded
        if isinstance(entry, dict) and (point := _point(entry, "x", "y", "z")) is not None
    )


def _point(row: dict[str, Any], *axes: str) -> WorldPoint | None:
    values = [_optional_float(row.get(axis)) for axis in axes]
    if len(values) != 3 or any(value is None for value in values):
        return None
    first, second, third = values
    return float(first or 0.0), float(second or 0.0), float(third or 0.0)


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _float(value: object) -> float:
    return _optional_float(value) or 0.0


def _read_table(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DatasetError(DatasetErrorCode.TABLE_MISSING, str(path))
    try:
        rows = pq.read_table(path).to_pylist()
    except (OSError, ValueError) as error:
        raise DatasetError(DatasetErrorCode.TABLE_UNREADABLE, str(path)) from error
    return [row for row in rows if isinstance(row, dict)]
