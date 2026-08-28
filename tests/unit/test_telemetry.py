from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.automation.readiness import (
    LiveReadinessStatus,
    LiveStateSource,
    ProviderHealth,
    ReadinessReason,
    ReadinessState,
    SourceReadiness,
)
from flyff_bot.features.navigation.live_position import PositionSource, WorldPosition
from flyff_bot.features.navigation.navmesh import NavMeshBaker
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex
from flyff_bot.features.tactical_parameters import (
    DEFAULT_TACTICAL_PARAMETERS,
    TACTICAL_PARAMETER_SCHEMA_VERSION,
)
from flyff_bot.features.telemetry import (
    JsonlTelemetryWorker,
    KinematicsDeriver,
    TelemetryPosition,
    TelemetryRecorder,
    TelemetrySessionMetadata,
)
from flyff_bot.features.telemetry.models import CombatVerificationSource


def _state() -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=1,
        inventory=(),
        progress_marker=0,
        viewport=Viewport(100, 100),
        visible_mobs=(VisibleMob(1, "Aibatt", 0.9, 40, 30, 20, 20),),
    )


def test_kinematics_derives_velocity_only_for_monotonic_live_positions() -> None:
    deriver = KinematicsDeriver()
    assert deriver.observe(1_000_000_000, TelemetryPosition(1.0, 2.0, 3.0)) is None
    velocity = deriver.observe(2_000_000_000, TelemetryPosition(3.0, 2.0, 4.0))
    assert velocity is not None
    assert (velocity.x, velocity.y, velocity.z, velocity.speed) == (2.0, 0.0, 1.0, 2.23606797749979)
    assert deriver.observe(2_000_000_000, TelemetryPosition(4.0, 2.0, 4.0)) is None


def test_recorder_writes_versioned_header_snapshots_and_explicit_nulls(tmp_path: Path) -> None:
    timestamps = iter((100, 200, 300, 400))
    recorder = TelemetryRecorder(
        TelemetrySessionMetadata(area_id="Wd Eden", session_id="session-1"),
        lambda session_id, area_id: JsonlTelemetryWorker(session_id, area_id, root=tmp_path),
        clock_ns=lambda: next(timestamps),
        utc_now=lambda: datetime(2026, 8, 19, tzinfo=UTC),
    )
    recorder.start(
        tactical_parameter_schema_version=TACTICAL_PARAMETER_SCHEMA_VERSION,
        tactical_parameter_digest=DEFAULT_TACTICAL_PARAMETERS.content_digest,
    )
    failure = SourceReadiness(
        LiveStateSource.GPS,
        ProviderHealth.UNAVAILABLE,
        0.25,
        ReadinessReason.UNAVAILABLE,
        "process_not_found",
    )
    recorder.record_snapshot(
        _state(),
        "searching",
        live_position=None,
        readiness=LiveReadinessStatus(
            state=ReadinessState.BLOCKED,
            sources=(failure,),
            failures=(failure,),
            primary_reason=ReadinessReason.UNAVAILABLE,
            primary_source=LiveStateSource.GPS,
            action_blocked=True,
        ),
    )
    recorder.record_target_selection(
        _state(),
        50,
        40,
        reason="nearest_to_viewport_center",
        tactical_parameter_digest=DEFAULT_TACTICAL_PARAMETERS.content_digest,
    )
    recorder.close()

    path = _session_file(tmp_path, "Wd_Eden", "session-1")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["event_kind"] for record in records] == [
        "session_header",
        "world_snapshot",
        "target_selected",
    ]
    assert records[0]["schema_version"] == 5
    assert records[0]["payload"]["tactical_parameter_schema_version"] == "us084-v1"
    assert (
        records[0]["payload"]["tactical_parameter_digest"]
        == DEFAULT_TACTICAL_PARAMETERS.content_digest
    )
    assert records[1]["payload"]["player_position"] is None
    assert records[1]["payload"]["readiness_state"] == "blocked"
    assert records[1]["payload"]["readiness_primary_reason"] == "unavailable"
    assert records[1]["payload"]["failed_source_codes"] == ["gps"]
    assert records[1]["payload"]["sample_ages_seconds"] == [["gps", 0.25]]
    assert records[1]["payload"]["action_blocked"] is True
    assert records[2]["payload"]["candidates"][0]["world_position"] is None


def test_worker_drops_a_full_queue_without_blocking(tmp_path: Path) -> None:
    worker = JsonlTelemetryWorker("session", "area", root=tmp_path, capacity=1)
    worker._stopped.set()  # Avoid scheduling a filesystem worker race.
    assert not worker.submit({})
    worker.close()


def test_recorder_derives_live_velocity(tmp_path: Path) -> None:
    timestamps = iter((1, 1_000_000_001, 2_000_000_001, 3_000_000_001))
    recorder = TelemetryRecorder(
        TelemetrySessionMetadata(area_id="area", session_id="live"),
        lambda session_id, area_id: JsonlTelemetryWorker(session_id, area_id, root=tmp_path),
        clock_ns=lambda: next(timestamps),
        utc_now=lambda: datetime(2026, 8, 19, tzinfo=UTC),
    )
    recorder.start()
    recorder.record_snapshot(
        _state(),
        "searching",
        live_position=WorldPosition(1.0, 2.0, 3.0),
        position_source=PositionSource.LIVE,
    )
    recorder.record_snapshot(
        _state(),
        "searching",
        live_position=WorldPosition(2.0, 2.0, 3.0),
        position_source=PositionSource.LIVE,
    )
    recorder.close()
    records = [
        json.loads(line)
        for line in _session_file(tmp_path, "area", "live").read_text(encoding="utf-8").splitlines()
    ]
    assert records[2]["payload"]["player_velocity"] == {"x": 1.0, "y": 0.0, "z": 0.0}


def test_recorder_wires_loaded_navmesh_polygon_for_live_gps_only(tmp_path: Path) -> None:
    mesh = NavMeshBaker().bake(
        (
            WorldTriangle(
                WorldVertex(0.0, 0.0, 0.0),
                WorldVertex(4.0, 0.0, 0.0),
                WorldVertex(0.0, 0.0, 4.0),
                "fixture",
            ),
        )
    )
    timestamps = iter((1, 2, 3, 4))
    recorder = TelemetryRecorder(
        TelemetrySessionMetadata(area_id="area", session_id="navmesh"),
        lambda session_id, area_id: JsonlTelemetryWorker(session_id, area_id, root=tmp_path),
        clock_ns=lambda: next(timestamps),
        utc_now=lambda: datetime(2026, 8, 19, tzinfo=UTC),
        navmesh=mesh,
    )
    recorder.start()
    recorder.record_snapshot(
        _state(),
        "searching",
        live_position=WorldPosition(1.0, 0.0, 1.0),
        position_source=PositionSource.LIVE,
    )
    recorder.record_snapshot(
        _state(),
        "searching",
        live_position=WorldPosition(1.0, 0.0, 1.0),
        position_source=PositionSource.UNAVAILABLE,
    )
    recorder.close()
    records = [
        json.loads(line)
        for line in _session_file(tmp_path, "area", "navmesh")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert records[1]["payload"]["player_navmesh_polygon_id"] == "1"
    assert records[2]["payload"]["player_navmesh_polygon_id"] is None


def test_recorder_persists_only_live_terrain_route_trajectory_and_stalls(tmp_path: Path) -> None:
    timestamps = iter((1, 2, 3, 4, 5, 6, 7))
    recorder = TelemetryRecorder(
        TelemetrySessionMetadata(area_id="area", session_id="route"),
        lambda session_id, area_id: JsonlTelemetryWorker(session_id, area_id, root=tmp_path),
        clock_ns=lambda: next(timestamps) * 1_000_000_000,
        utc_now=lambda: datetime(2026, 8, 19, tzinfo=UTC),
    )
    recorder.start()
    recorder.begin_navigation(
        WorldPosition(1.0, 2.0, 3.0),
        (WorldPosition(1.0, 2.0, 3.0), WorldPosition(4.0, 2.0, 3.0)),
    )
    recorder.record_snapshot(
        _state(),
        "searching",
        live_position=WorldPosition(1.0, 2.0, 3.0),
        position_source=PositionSource.LIVE,
    )
    recorder.record_navigation_stall(stalled=True)
    recorder.record_navigation_evasion()
    recorder.record_navigation_stall(stalled=False)
    recorder.finish_navigation("reached_target")
    recorder.close()

    records = [
        json.loads(line)
        for line in _session_file(tmp_path, "area", "route")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    episode = next(
        record["payload"] for record in records if record["event_kind"] == "navigation_episode"
    )
    assert episode["trajectory"] == [
        [4_000_000_000, {"x": 1.0, "y": 2.0, "z": 3.0}, None, None, False]
    ]
    assert episode["planned_length"] == 3.0
    assert episode["stall_events"] == 1
    assert episode["stall_duration_seconds"] == 1.0
    assert episode["collision_evasions"] == 1


def test_target_selection_keeps_live_position_and_controller_lockout(tmp_path: Path) -> None:
    timestamps = iter((100, 200, 300))
    recorder = TelemetryRecorder(
        TelemetrySessionMetadata(area_id="area", session_id="locked"),
        lambda session_id, area_id: JsonlTelemetryWorker(session_id, area_id, root=tmp_path),
        clock_ns=lambda: next(timestamps),
        utc_now=lambda: datetime(2026, 8, 19, tzinfo=UTC),
    )
    recorder.start()
    recorder.record_target_selection(
        _state(),
        50,
        40,
        reason="nearest",
        tactical_parameter_digest=DEFAULT_TACTICAL_PARAMETERS.content_digest,
        player_position=WorldPosition(9.0, 8.0, 7.0),
        is_locked_out=lambda _x, _y: True,
    )
    recorder.close()
    payload = json.loads(
        _session_file(tmp_path, "area", "locked").read_text(encoding="utf-8").splitlines()[1]
    )["payload"]
    assert payload["player_position"] == {"x": 9.0, "y": 8.0, "z": 7.0}
    assert payload["candidates"][0]["is_locked_out"] is True


def test_experience_totals_report_decisions_episodes_and_decomposed_reward(
    tmp_path: Path,
) -> None:
    """One verified kill closes an episode and lands in the session reward decomposition."""

    timestamps = iter(range(100, 100 + 40 * 1_000_000_000, 1_000_000_000))
    recorder = TelemetryRecorder(
        TelemetrySessionMetadata(area_id="Wd Eden", session_id="totals"),
        lambda session_id, area_id: JsonlTelemetryWorker(session_id, area_id, root=tmp_path),
        clock_ns=lambda: next(timestamps),
        utc_now=lambda: datetime(2026, 8, 28, tzinfo=UTC),
    )
    recorder.start(tactical_parameter_digest=DEFAULT_TACTICAL_PARAMETERS.content_digest)
    state = _state()

    recorder.record_target_selection(
        state,
        50,
        40,
        reason="nearest_to_viewport_center",
        tactical_parameter_digest=DEFAULT_TACTICAL_PARAMETERS.content_digest,
    )
    assert recorder.experience.decisions == 1
    assert recorder.experience.episode_steps == 1

    recorder.record_objective_progress(1.0, quest_id="quest-1", completed=True)
    recorder.begin_combat(state)
    recorder.finish_combat(
        state,
        outcome="kill_verified",
        verification_source=CombatVerificationSource.HP_ZERO,
    )
    totals = recorder.experience

    assert totals.episode_index == 1
    assert totals.episode_steps == 0
    assert totals.verified_kills == 1
    assert totals.kill_reward == 1.0
    assert totals.objective_reward == 2.5
    assert totals.last_termination_reason == "kill_verified"
    assert totals.storage_path.endswith(".jsonl")
    assert totals.recorded_records > 0
    recorder.close()


def _session_file(root: Path, area: str, session_id: str) -> Path:
    """Return the written session log; the worker names its day folder in real UTC time."""

    day = datetime.now(UTC).date().isoformat()
    return root / area / day / f"session_{session_id}.jsonl"
