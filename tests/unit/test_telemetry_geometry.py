"""Measured camera/NavMesh features used only by telemetry target decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.navigation.live_camera import CameraState
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import NavMeshBaker
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex
from flyff_bot.features.tactical_parameters import DEFAULT_TACTICAL_PARAMETERS
from flyff_bot.features.telemetry import (
    JsonlTelemetryWorker,
    TelemetryRecorder,
    TelemetrySessionMetadata,
)
from flyff_bot.features.telemetry.geometry import navmesh_slope, project_candidate


def test_project_candidate_uses_the_bottom_center_ray_and_walkable_mesh_hit() -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(),))

    candidate = project_candidate(
        camera=_camera(),
        navmesh=mesh,
        player_position=WorldPosition(0.0, -1.0, 0.0),
        viewport_width=200,
        viewport_height=100,
        screen_x=100.0,
        screen_bottom_y=100.0,
    )

    assert candidate is not None
    assert candidate.position == WorldPosition(0.0, -1.0, 1.0)
    assert candidate.polygon_id == 1
    assert candidate.relative_distance == pytest.approx(1.0)
    assert candidate.relative_elevation == pytest.approx(0.0)


def test_project_candidate_and_slope_remain_explicitly_unavailable_without_measurements() -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(),))

    assert (
        project_candidate(
            camera=None,
            navmesh=mesh,
            player_position=WorldPosition(0.0, 0.0, 0.0),
            viewport_width=200,
            viewport_height=100,
            screen_x=100.0,
            screen_bottom_y=100.0,
        )
        is None
    )
    assert navmesh_slope(mesh, WorldPosition(0.0, -1.0, 1.0)) == pytest.approx(0.0)
    assert navmesh_slope(None, WorldPosition(0.0, -1.0, 1.0)) is None


def test_recorder_serializes_measured_candidate_geometry(tmp_path: Path) -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(),))
    timestamps = iter((1, 2, 3))
    recorder = TelemetryRecorder(
        TelemetrySessionMetadata(area_id="area", session_id="geometry"),
        lambda session_id, area_id: JsonlTelemetryWorker(session_id, area_id, root=tmp_path),
        clock_ns=lambda: next(timestamps),
        navmesh=mesh,
    )
    recorder.start(active_spawn_zone={"monster_id": 1, "monster_name": "Aibatt"})
    recorder.record_target_selection(
        WorldState(
            observed_at_seconds=1.0,
            position=Position(0, 0),
            nearby_mob_count=1,
            inventory=(),
            progress_marker=0,
            viewport=Viewport(200, 100),
            visible_mobs=(VisibleMob(1, "Aibatt", 0.9, 90, 80, 20, 20),),
        ),
        100,
        90,
        reason="nearest",
        tactical_parameter_digest=DEFAULT_TACTICAL_PARAMETERS.content_digest,
        player_position=WorldPosition(0.0, -1.0, 0.0),
        camera_state=_camera(),
    )
    recorder.close()

    payload = next(tmp_path.glob("area/*/session_geometry.jsonl")).read_text(encoding="utf-8")
    assert '"world_position":{"x":0.0,"y":-1.0,"z":1.0}' in payload
    assert '"target_navmesh_polygon_id":"1"' in payload
    assert '"active_spawn_zone":{"monster_id":1,"monster_name":"Aibatt"}' in payload


def _camera() -> CameraState:
    identity = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    return CameraState(
        position=WorldPosition(0.0, 0.0, 0.0),
        pitch_radians=0.0,
        yaw_radians=0.0,
        zoom_distance=0.0,
        vertical_fov_radians=1.0,
        view_matrix=identity,
        projection_matrix=identity,
        view_projection_matrix=identity,
        inverse_view_projection_matrix=identity,
    )


def _flat_triangle() -> WorldTriangle:
    return WorldTriangle(
        WorldVertex(-4.0, -1.0, 0.0),
        WorldVertex(4.0, -1.0, 4.0),
        WorldVertex(4.0, -1.0, 0.0),
        "fixture",
    )
