from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.navigation.live_position import PositionSource, WorldPosition
from flyff_bot.features.telemetry import (
    JsonlTelemetryWorker,
    KinematicsDeriver,
    TelemetryPosition,
    TelemetryRecorder,
    TelemetrySessionMetadata,
)


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
    recorder.start()
    recorder.record_snapshot(_state(), "searching", live_position=None)
    recorder.record_target_selection(_state(), 50, 40, reason="nearest_to_viewport_center")
    recorder.close()

    path = tmp_path / "Wd_Eden" / "2026-08-19" / "session_session-1.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["event_kind"] for record in records] == [
        "session_header",
        "world_snapshot",
        "target_selected",
    ]
    assert records[0]["schema_version"] == 1
    assert records[1]["payload"]["player_position"] is None
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
        for line in (tmp_path / "area" / "2026-08-19" / "session_live.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records[2]["payload"]["player_velocity"] == {"x": 1.0, "y": 0.0, "z": 0.0}
