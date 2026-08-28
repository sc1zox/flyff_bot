"""Offline RL transition export from recorded farming telemetry.

One exported row is one real interval of one recorded session: the state observed at a target
decision, the exact parameterized choice that was taken, the reward observed until the next
decision in that same session, the state at that next decision, both masks, and how the
interval ended. Nothing is ever joined across a ``session_id``, an episode, or a decision
boundary (BUG-031).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from flyff_bot.features.policy.action_payloads import TacticalAction, TargetAction
from flyff_bot.features.policy.contract import (
    CONTRACT_DOCUMENT_KEY,
    ContractStamp,
    current_contract_stamp,
    verify_contract_document,
)
from flyff_bot.features.rl.actions import (
    ParameterizedAction,
    TacticalActionCatalog,
    TacticalActionMask,
)
from flyff_bot.features.rl.masking import build_tactical_mask
from flyff_bot.features.rl.models import ObservationSpace, RlObservation, Transition
from flyff_bot.features.rl.rewards import (
    DEFAULT_REWARD_CONFIG,
    RewardConfig,
    RewardEngine,
    RewardEvent,
)
from flyff_bot.features.telemetry.models import (
    CandidateFeatures,
    CombatOutcome,
    NavigationOutcome,
    TelemetryEventKind,
    TelemetryPosition,
)
from flyff_bot.features.telemetry.storage import SqliteTelemetryStore

PARQUET_COMPRESSION = "zstd"
RL_TRANSITIONS_FILE = "rl_transitions.parquet"
RL_PROVENANCE_FILE = "rl_provenance.json"
RL_TRANSITION_SCHEMA_VERSION = "us084-v1"
# Parquet stores its own key-value metadata as bytes, so the dataset carries the same stamp the
# provenance document does without a per-row string column.
CONTRACT_METADATA_KEY = b"decision_contract"
DEFAULT_EXPORT_PATROL_RADIUS = 1000.0
NANOSECONDS_PER_SECOND = 1_000_000_000

# Every event family the reward and the state of one interval are reconstructed from.
_EXPORTED_EVENT_KINDS = (
    TelemetryEventKind.SESSION_HEADER,
    TelemetryEventKind.WORLD_SNAPSHOT,
    TelemetryEventKind.TARGET_SELECTED,
    TelemetryEventKind.KILL_CYCLE,
    TelemetryEventKind.NAVIGATION_EPISODE,
    TelemetryEventKind.COMBAT_EPISODE,
    TelemetryEventKind.OBJECTIVE_PROGRESS,
)

SessionEvents = dict[TelemetryEventKind, list[dict[str, Any]]]


class TelemetryTransitionExporter:
    """Convert recorded decisions into offline MDP transitions without live access."""

    def __init__(
        self,
        store: SqliteTelemetryStore,
        *,
        reward_config: RewardConfig | None = None,
        patrol_radius: float = DEFAULT_EXPORT_PATROL_RADIUS,
    ) -> None:
        self._store = store
        self._patrol_radius = patrol_radius
        self.reward_config = reward_config or DEFAULT_REWARD_CONFIG

    def export(self, output_directory: Path) -> tuple[Path, Path]:
        """Write transition and provenance artifacts, returning both paths."""

        transitions = self.transitions()
        if not transitions:
            raise ValueError("No complete recorded decision transition was found.")
        output_directory.mkdir(parents=True, exist_ok=True)
        transitions_path = output_directory / RL_TRANSITIONS_FILE
        provenance_path = output_directory / RL_PROVENANCE_FILE
        pq.write_table(self._table(transitions), transitions_path, compression=PARQUET_COMPRESSION)
        provenance_path.write_text(self.provenance(), encoding="utf-8")
        return transitions_path, provenance_path

    def provenance(self) -> str:
        """Return the document stating which contract and reward version produced the rows."""

        return json.dumps(
            {
                "schema_version": RL_TRANSITION_SCHEMA_VERSION,
                CONTRACT_DOCUMENT_KEY: self._stamp().as_document(),
                "reward_config_version": self.reward_config.version,
                "reward_config_json": self.reward_config.as_json(),
                "tactical_parameter_digests": self._tactical_parameter_digests(),
            },
            sort_keys=True,
        )

    def _stamp(self) -> ContractStamp:
        return current_contract_stamp(reward_config_version=self.reward_config.version)

    def _tactical_parameter_digests(self) -> list[str]:
        """Return every exact tactical vector represented by the exported sessions."""

        return sorted(
            {
                str(payload["tactical_parameter_digest"])
                for kind in (
                    TelemetryEventKind.SESSION_HEADER,
                    TelemetryEventKind.TARGET_SELECTED,
                )
                for event in self._store.events(kind)
                if isinstance((payload := event.get("payload")), dict)
                and isinstance(payload.get("tactical_parameter_digest"), str)
                and payload["tactical_parameter_digest"]
            }
        )

    def transitions(self) -> list[Transition]:
        """Return every complete transition, grouped and ordered per recorded session."""

        by_session = self._events_by_session()
        return [
            transition
            for session_id in sorted(by_session)
            for transition in self._session_transitions(session_id, by_session[session_id])
        ]

    def _events_by_session(self) -> dict[str, SessionEvents]:
        by_session: dict[str, SessionEvents] = defaultdict(lambda: defaultdict(list))
        for kind in _EXPORTED_EVENT_KINDS:
            for event in self._store.events(kind):
                by_session[str(event["session_id"])][kind].append(event)
        return by_session

    def _session_transitions(self, session_id: str, events: SessionEvents) -> list[Transition]:
        decisions = events.get(TelemetryEventKind.TARGET_SELECTED, [])
        snapshots = events.get(TelemetryEventKind.WORLD_SNAPSHOT, [])
        if not decisions or not snapshots:
            return []
        _session_tactical_parameter_digest(events)
        session_end_ns = max(
            int(event["timestamp_ns"]) for family in events.values() for event in family
        )
        transitions: list[Transition] = []
        episode_index = 0
        for index, decision in enumerate(decisions):
            timestamp_ns = int(decision["timestamp_ns"])
            is_last = index + 1 == len(decisions)
            interval_end_ns = (
                session_end_ns + 1 if is_last else int(decisions[index + 1]["timestamp_ns"])
            )
            previous = _latest_snapshot(snapshots, lower_ns=None, upper_ns=timestamp_ns)
            following = _latest_snapshot(snapshots, lower_ns=timestamp_ns, upper_ns=interval_end_ns)
            action = _action(decision)
            if previous is None or following is None or action is None:
                continue
            tactical_parameter_digest = _decision_tactical_parameter_digest(decision)

            observation = ObservationSpace.from_telemetry_snapshot(
                previous["payload"], _candidates(decision)
            )
            next_observation = ObservationSpace.from_telemetry_snapshot(
                following["payload"],
                () if is_last else _candidates(decisions[index + 1]),
            )
            reward_event = interval_reward_event(
                events, start_ns=timestamp_ns, end_ns=min(interval_end_ns, session_end_ns + 1)
            )
            terminated = reward_event.objective_completed
            transitions.append(
                Transition(
                    observation,
                    action,
                    RewardEngine(self.reward_config).reward(reward_event),
                    next_observation,
                    self._mask(observation),
                    terminated,
                    self._mask(next_observation),
                    is_last and not terminated,
                    session_id,
                    episode_index,
                    tactical_parameter_digest,
                )
            )
            if terminated:
                episode_index += 1
        return transitions

    def _mask(self, observation: RlObservation) -> TacticalActionMask:
        return build_tactical_mask(
            observation,
            patrol_center=(
                observation.kinematics.position_x,
                observation.kinematics.position_y,
                observation.kinematics.position_z,
            ),
            patrol_radius=self._patrol_radius,
        )

    def _table(self, transitions: list[Transition]) -> pa.Table:
        schema = pa.schema(
            [
                pa.field("session_id", pa.string(), nullable=False),
                pa.field("episode_index", pa.int32(), nullable=False),
                pa.field("tactical_parameter_digest", pa.string(), nullable=False),
                pa.field("observation", pa.list_(pa.float64()), nullable=False),
                pa.field("action", pa.int32(), nullable=False),
                pa.field("action_candidate_index", pa.int32()),
                pa.field("action_target_class_id", pa.int32()),
                pa.field("action_parameters_json", pa.string(), nullable=False),
                pa.field("reward", pa.float64(), nullable=False),
                pa.field("reward_config_version", pa.string(), nullable=False),
                pa.field("reward_components_json", pa.string(), nullable=False),
                pa.field("next_observation", pa.list_(pa.float64()), nullable=False),
                pa.field("action_mask", pa.list_(pa.bool_()), nullable=False),
                pa.field("candidate_mask", pa.list_(pa.bool_()), nullable=False),
                pa.field("next_action_mask", pa.list_(pa.bool_()), nullable=False),
                pa.field("next_candidate_mask", pa.list_(pa.bool_()), nullable=False),
                pa.field("terminated", pa.bool_(), nullable=False),
                pa.field("truncated", pa.bool_(), nullable=False),
                pa.field("readiness_state", pa.string(), nullable=False),
                pa.field("readiness_primary_reason", pa.string()),
                pa.field("failed_source_codes", pa.list_(pa.string()), nullable=False),
                pa.field("sample_ages_seconds_json", pa.string(), nullable=False),
                pa.field("action_blocked", pa.bool_(), nullable=False),
                pa.field("next_readiness_state", pa.string(), nullable=False),
                pa.field("next_readiness_primary_reason", pa.string()),
                pa.field("next_failed_source_codes", pa.list_(pa.string()), nullable=False),
                pa.field("next_sample_ages_seconds_json", pa.string(), nullable=False),
                pa.field("next_action_blocked", pa.bool_(), nullable=False),
            ],
            metadata={
                CONTRACT_METADATA_KEY: json.dumps(
                    self._stamp().as_document(), sort_keys=True
                ).encode("utf-8")
            },
        )
        rows = [
            {
                "session_id": item.session_id,
                "episode_index": item.episode_index,
                "tactical_parameter_digest": item.tactical_parameter_digest,
                "observation": ObservationSpace.encode(item.observation).tolist(),
                "action": int(item.action.action),
                "action_candidate_index": item.action.candidate_index,
                "action_target_class_id": item.action.target_class_id,
                "action_parameters_json": _action_json(item.action),
                "reward": item.reward,
                "reward_config_version": self.reward_config.version,
                "reward_components_json": self.reward_config.as_json(),
                "next_observation": ObservationSpace.encode(item.next_observation).tolist(),
                "action_mask": list(item.action_mask.actions),
                "candidate_mask": list(item.action_mask.candidates),
                "next_action_mask": list(item.next_action_mask.actions),
                "next_candidate_mask": list(item.next_action_mask.candidates),
                "terminated": item.terminated,
                "truncated": item.truncated,
                "readiness_state": item.observation.readiness.state,
                "readiness_primary_reason": item.observation.readiness.primary_reason,
                "failed_source_codes": list(item.observation.readiness.failed_source_codes),
                "sample_ages_seconds_json": json.dumps(
                    dict(item.observation.readiness.sample_ages_seconds), sort_keys=True
                ),
                "action_blocked": item.observation.readiness.action_blocked,
                "next_readiness_state": item.next_observation.readiness.state,
                "next_readiness_primary_reason": item.next_observation.readiness.primary_reason,
                "next_failed_source_codes": list(
                    item.next_observation.readiness.failed_source_codes
                ),
                "next_sample_ages_seconds_json": json.dumps(
                    dict(item.next_observation.readiness.sample_ages_seconds), sort_keys=True
                ),
                "next_action_blocked": item.next_observation.readiness.action_blocked,
            }
            for item in transitions
        ]
        return pa.Table.from_pylist(rows, schema=schema)


def read_transition_contract(transitions_path: Path) -> ContractStamp:
    """Return the contract an exported dataset was produced under, or reject the dataset.

    A dataset whose stamp disagrees with the running application describes different columns,
    different action indices or differently weighted rewards, so it is refused instead of being
    read as if it matched (US-079).
    """

    metadata = pq.read_schema(transitions_path).metadata or {}
    document = metadata.get(CONTRACT_METADATA_KEY)
    return verify_contract_document(
        None if document is None else json.loads(document.decode("utf-8"))
    )


def interval_reward_event(events: SessionEvents, *, start_ns: int, end_ns: int) -> RewardEvent:
    """Return the reward facts observed inside exactly one decision interval.

    An episode is attributed to the interval its *end* falls into, so no navigation, combat,
    kill, or objective observation is ever counted for two decisions.
    """

    interval_seconds = max(0.0, (end_ns - start_ns) / NANOSECONDS_PER_SECOND)
    cycles = _within(events.get(TelemetryEventKind.KILL_CYCLE, []), start_ns, end_ns)
    navigation = _ended_within(
        events.get(TelemetryEventKind.NAVIGATION_EPISODE, []), start_ns, end_ns
    )
    combat = _ended_within(events.get(TelemetryEventKind.COMBAT_EPISODE, []), start_ns, end_ns)
    progress = _within(events.get(TelemetryEventKind.OBJECTIVE_PROGRESS, []), start_ns, end_ns)

    travel_seconds = sum(_elapsed_seconds(episode) for episode in navigation)
    combat_seconds = sum(_elapsed_seconds(episode) for episode in combat)
    failed_action = any(
        str(episode.get("outcome")) != NavigationOutcome.REACHED_TARGET.value
        for episode in navigation
    ) or any(str(episode.get("outcome")) != CombatOutcome.KILL_VERIFIED.value for episode in combat)
    return RewardEvent(
        verified_kill=any(bool(cycle.get("verified_kill", False)) for cycle in cycles),
        quest_progress_delta=sum(_number(item.get("progress_delta")) for item in progress),
        objective_completed=any(bool(item.get("objective_completed", False)) for item in progress),
        travel_seconds=travel_seconds,
        idle_seconds=max(0.0, interval_seconds - travel_seconds - combat_seconds),
        stuck_seconds=sum(_number(episode.get("stall_duration_seconds")) for episode in navigation),
        recovery_seconds=sum(_number(episode.get("evasion_seconds")) for episode in navigation),
        failed_action=failed_action,
    )


def _action(decision: dict[str, Any]) -> ParameterizedAction | None:
    """Return the exact parameterized choice one recorded decision executed."""

    payload = decision["payload"]
    recorded = _recorded_action(payload.get("executed_action"))
    if recorded is not None:
        return recorded
    selected_index = payload.get("selected_candidate_index")
    if not isinstance(selected_index, int):
        return None
    selected = next(
        (
            candidate
            for candidate in payload.get("candidates", ())
            if candidate.get("candidate_index") == selected_index
        ),
        None,
    )
    if selected is None:
        return None
    return TacticalActionCatalog.encode(
        TargetAction(int(selected["class_id"]), None, None, None, candidate_index=selected_index)
    )


def _recorded_action(document: object) -> ParameterizedAction | None:
    """Reconstruct the lossless action document recorded at the guarded click boundary."""

    if not isinstance(document, dict):
        return None
    try:
        return ParameterizedAction(
            action=TacticalAction(int(document["action"])),
            candidate_index=_optional_int(document.get("candidate_index")),
            target_class_id=_optional_int(document.get("target_class_id")),
            destination=_optional_world_point(document.get("destination")),
            attack_point=_optional_world_point(document.get("attack_point")),
            approach_angle=_optional_float(document.get("approach_angle")),
            approach_distance_units=_optional_float(document.get("approach_distance_units")),
            corridor_id=_optional_string(document.get("corridor_id")),
            interaction_target_id=_optional_string(document.get("interaction_target_id")),
            interaction_type=_optional_string(document.get("interaction_type")),
            wait_seconds=_optional_float(document.get("wait_seconds")),
            wait_reason=_optional_string(document.get("wait_reason")),
            navigate_reason=_optional_string(document.get("navigate_reason")),
        )
    except KeyError, TypeError, ValueError:
        return None


def _session_tactical_parameter_digest(events: SessionEvents) -> str:
    """Require one immutable tactical-vector identity for every exported session."""

    headers = events.get(TelemetryEventKind.SESSION_HEADER, [])
    digests = {
        str(payload["tactical_parameter_digest"])
        for header in headers
        if isinstance((payload := header.get("payload")), dict)
        and isinstance(payload.get("tactical_parameter_digest"), str)
        and payload["tactical_parameter_digest"]
    }
    if len(digests) != 1:
        raise ValueError("Session tactical parameter provenance is missing or ambiguous.")
    return next(iter(digests))


def _decision_tactical_parameter_digest(decision: dict[str, Any]) -> str:
    """Require the exact decision-time vector with no session-default substitution."""

    payload = decision.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Decision tactical parameter provenance is invalid.")
    digest = payload.get("tactical_parameter_digest")
    if not isinstance(digest, str) or not digest:
        raise ValueError("Decision tactical parameter provenance is invalid.")
    return digest


def _action_json(action: ParameterizedAction) -> str:
    """Serialize every action parameter so the exported choice stays loss-free."""

    return json.dumps(asdict(action), sort_keys=True)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError
    return float(value)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError
    return value


def _optional_world_point(value: object) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, list | tuple) or len(value) != 3:
        raise TypeError
    coordinates = tuple(_optional_float(item) for item in value)
    if any(item is None for item in coordinates):
        raise TypeError
    return coordinates  # type: ignore[return-value]


def _candidates(event: dict[str, Any]) -> tuple[CandidateFeatures, ...]:
    payload = event["payload"]
    return tuple(
        CandidateFeatures(
            candidate["candidate_index"],
            candidate["class_id"],
            candidate["class_name"],
            candidate["confidence"],
            candidate["x"],
            candidate["y"],
            candidate["width"],
            candidate["height"],
            candidate.get("center_x", 0.0),
            candidate.get("center_y", 0.0),
            candidate.get("screen_distance_to_center"),
            candidate.get("bbox_area", 0),
            _world_position(candidate.get("world_position")),
            candidate.get("relative_distance"),
            candidate.get("relative_elevation"),
            candidate.get("target_navmesh_polygon_id"),
            candidate.get("path_distance"),
            candidate.get("is_locked_out", False),
        )
        for candidate in payload["candidates"]
    )


def _world_position(payload: object) -> TelemetryPosition | None:
    if not isinstance(payload, dict):
        return None
    values = tuple(payload.get(axis) for axis in ("x", "y", "z"))
    if any(not isinstance(value, int | float) for value in values):
        return None
    return TelemetryPosition(float(values[0]), float(values[1]), float(values[2]))  # type: ignore[arg-type]


def _latest_snapshot(
    snapshots: list[dict[str, Any]], *, lower_ns: int | None, upper_ns: int
) -> dict[str, Any] | None:
    return max(
        (
            item
            for item in snapshots
            if int(item["timestamp_ns"]) < upper_ns
            and (lower_ns is None or int(item["timestamp_ns"]) > lower_ns)
        ),
        key=lambda item: int(item["timestamp_ns"]),
        default=None,
    )


def _within(events: list[dict[str, Any]], start_ns: int, end_ns: int) -> list[dict[str, Any]]:
    return [event["payload"] for event in events if start_ns <= int(event["timestamp_ns"]) < end_ns]


def _ended_within(events: list[dict[str, Any]], start_ns: int, end_ns: int) -> list[dict[str, Any]]:
    return [
        payload
        for event in events
        if start_ns <= int((payload := event["payload"]).get("ended_at_ns", -1)) < end_ns
    ]


def _elapsed_seconds(episode: dict[str, Any]) -> float:
    started = episode.get("started_at_ns")
    ended = episode.get("ended_at_ns")
    if not isinstance(started, int) or not isinstance(ended, int):
        return 0.0
    return max(0.0, (ended - started) / NANOSECONDS_PER_SECOND)


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0
