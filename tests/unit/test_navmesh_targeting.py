"""Regression coverage for NavMesh authority in combat candidate selection."""

from __future__ import annotations

from flyff_bot.features.automation.controllers import CombatController, CombatMode
from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.navigation.live_camera import CameraState
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshBaker
from flyff_bot.features.navigation.targeting import enrich_visible_mobs
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex

GROUND_ELEVATION = -1.0
LEASH_RADIUS_UNITS = 50.0


def _state(*mobs: VisibleMob) -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=Viewport(200, 100),
    )


def _mob(
    class_id: int,
    x: int,
    *,
    distance: float | None,
    reachable: bool | None = True,
    within_leash: bool | None = True,
) -> VisibleMob:
    return VisibleMob(
        class_id,
        f"mob-{class_id}",
        0.9,
        x,
        40,
        10,
        10,
        world_x=10.0 if distance is not None else None,
        world_y=0.0 if distance is not None else None,
        world_z=10.0 if distance is not None else None,
        navmesh_polygon_id=class_id if distance is not None else None,
        navmesh_path_distance=distance,
        navmesh_reachable=reachable,
        navmesh_within_leash=within_leash,
    )


def test_unreachable_candidate_is_never_selected_even_when_nearest_on_screen() -> None:
    unreachable = _mob(1, 95, distance=1.0, reachable=False)
    reachable = _mob(2, 20, distance=9.0)

    decision = CombatController().step(_state(unreachable, reachable))

    assert decision.mode is CombatMode.TARGETING
    assert decision.selected_mob == reachable


def test_shortest_reachable_navmesh_path_beats_viewport_proximity() -> None:
    long_path = _mob(1, 95, distance=20.0)
    short_path = _mob(2, 20, distance=5.0)

    decision = CombatController().step(_state(long_path, short_path))

    assert decision.selected_mob == short_path


def test_unprojected_candidate_is_a_lower_priority_viewport_fallback() -> None:
    projected = _mob(1, 20, distance=40.0)
    unprojected = _mob(2, 95, distance=None, reachable=None, within_leash=None)

    decision = CombatController().step(_state(projected, unprojected))

    assert decision.selected_mob == projected


def test_candidate_outside_the_navmesh_leash_is_rejected() -> None:
    outside = _mob(1, 95, distance=1.0, within_leash=False)

    decision = CombatController().step(_state(outside))

    assert decision.mode is CombatMode.IDLE


def test_routing_reuses_the_perception_estimate_without_casting_a_second_ray() -> None:
    # The box points at the sky, so only the measurement the perception tick already
    # attached can produce a route; a second cast would find nothing.
    measured = VisibleMob(
        1,
        "Aibatt",
        0.9,
        90,
        0,
        20,
        20,
        world_x=0.0,
        world_y=GROUND_ELEVATION,
        world_z=1.0,
        navmesh_polygon_id=1,
    )

    enriched = _enriched(measured)[0]

    assert (enriched.world_x, enriched.world_y, enriched.world_z) == (0.0, GROUND_ELEVATION, 1.0)
    assert enriched.navmesh_polygon_id == 1
    assert enriched.navmesh_reachable is True
    assert enriched.navmesh_within_leash is True
    assert enriched.navmesh_path_distance is not None


def test_routing_still_projects_a_detection_no_perception_feed_measured() -> None:
    unmeasured = VisibleMob(1, "Aibatt", 0.9, 90, 80, 20, 20)

    enriched = _enriched(unmeasured)[0]

    assert (enriched.world_x, enriched.world_y, enriched.world_z) == (0.0, GROUND_ELEVATION, 1.0)
    assert enriched.navmesh_polygon_id == 1
    assert enriched.navmesh_reachable is True


def _enriched(*mobs: VisibleMob) -> tuple[VisibleMob, ...]:
    player = WorldPosition(0.0, GROUND_ELEVATION, 0.0)
    return enrich_visible_mobs(
        mobs,
        viewport=Viewport(200, 100),
        player_position=player,
        camera_state=_camera(),
        navmesh=_ground_mesh(),
        anchor_position=player,
        leash_radius_units=LEASH_RADIUS_UNITS,
    )


def _ground_mesh() -> BakedNavMesh:
    return NavMeshBaker().bake(
        (
            WorldTriangle(
                WorldVertex(-4.0, GROUND_ELEVATION, 0.0),
                WorldVertex(4.0, GROUND_ELEVATION, 4.0),
                WorldVertex(4.0, GROUND_ELEVATION, 0.0),
                "fixture",
            ),
        )
    )


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
