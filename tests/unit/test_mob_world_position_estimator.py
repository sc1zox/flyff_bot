"""Bottom-centre unprojection of detections onto authoritative walkable surfaces."""

from __future__ import annotations

from math import sqrt
from time import perf_counter

import pytest

from flyff_bot.features.automation.models import Viewport, VisibleMob
from flyff_bot.features.navigation.live_camera import CameraState, Vector3D
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshBaker
from flyff_bot.features.navigation.raycast import ray_triangle_distance
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex
from flyff_bot.features.perception import (
    MobWorldPositionEstimator,
    estimate_mob_world_positions,
    ground_contact_anchor,
    with_estimated_world_positions,
)

VIEWPORT_WIDTH = 200
VIEWPORT_HEIGHT = 100
BATCH_DETECTION_COUNT = 20
BATCH_BUDGET_SECONDS = 0.002
BATCH_SAMPLE_COUNT = 5
# A quad edge has to leave room for the baker's agent radius, so the plate is built from
# 4-unit quads: 512 walkable triangles spread over sixteen chunks per side.
TERRAIN_QUAD_UNITS = 4.0
TERRAIN_CELLS_PER_SIDE = 16
TERRAIN_HALF_EXTENT_UNITS = TERRAIN_QUAD_UNITS * TERRAIN_CELLS_PER_SIDE / 2.0


def test_ground_contact_anchor_uses_the_bounding_box_bottom_center() -> None:
    mob = VisibleMob(1, "Aibatt", 0.9, 40, 30, 21, 11)

    assert ground_contact_anchor(mob) == (50.5, 41.0)


def test_flat_surface_estimate_carries_polygon_identity_and_measured_distances() -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(elevation=-1.0),))

    estimates = estimate_mob_world_positions(
        (_mob_at(100.0, 100.0),),
        _camera(),
        WorldPosition(0.0, -1.0, 0.0),
        VIEWPORT_WIDTH,
        VIEWPORT_HEIGHT,
        mesh,
    )

    estimate = estimates[0]
    assert estimate is not None
    assert estimate.position == WorldPosition(0.0, -1.0, 1.0)
    assert estimate.navmesh_polygon_id == 1
    assert estimate.distance_to_player == pytest.approx(1.0)
    assert estimate.ray_distance == pytest.approx(sqrt(2.0))
    assert (estimate.class_name, estimate.confidence) == ("Aibatt", 0.9)


def test_inclined_surface_estimate_follows_the_ramp_elevation() -> None:
    ramp = WorldTriangle(
        WorldVertex(-8.0, -2.0, 0.0),
        WorldVertex(8.0, -2.0, 0.0),
        WorldVertex(0.0, 0.0, 8.0),
        "ramp",
    )
    mesh = NavMeshBaker().bake((ramp,))

    estimate = estimate_mob_world_positions(
        (_mob_at(100.0, 100.0),),
        _camera(),
        WorldPosition(0.0, 0.0, 0.0),
        VIEWPORT_WIDTH,
        VIEWPORT_HEIGHT,
        mesh,
    )[0]

    assert estimate is not None
    # The ray meets the ramp where the surface's interpolated height crosses it.
    assert estimate.position.x == pytest.approx(0.0)
    assert estimate.position.z == pytest.approx(1.6)
    assert estimate.position.y == pytest.approx(-1.6)


def test_multi_layer_geometry_hits_the_bridge_deck_and_not_the_ground_below() -> None:
    ground, deck = _deck(elevation=-5.0), _deck(elevation=-1.0)
    mesh = NavMeshBaker().bake((ground, deck))

    estimate = estimate_mob_world_positions(
        (_mob_at(100.0, 100.0),),
        _camera(),
        WorldPosition(0.0, -1.0, 0.0),
        VIEWPORT_WIDTH,
        VIEWPORT_HEIGHT,
        mesh,
    )[0]

    assert estimate is not None
    assert estimate.position == WorldPosition(0.0, -1.0, 1.0)
    assert estimate.ray_distance == pytest.approx(sqrt(2.0))


def test_a_ray_towards_the_sky_or_along_the_horizon_stays_unmeasured() -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(elevation=-1.0),))
    camera = _camera()
    player = WorldPosition(0.0, -1.0, 0.0)

    sky = estimate_mob_world_positions(
        (_mob_at(100.0, 0.0),), camera, player, VIEWPORT_WIDTH, VIEWPORT_HEIGHT, mesh
    )
    horizon = estimate_mob_world_positions(
        (_mob_at(100.0, VIEWPORT_HEIGHT / 2),),
        camera,
        player,
        VIEWPORT_WIDTH,
        VIEWPORT_HEIGHT,
        mesh,
    )

    assert sky == (None,)
    assert horizon == (None,)


def test_estimates_degrade_to_none_without_camera_mesh_gps_or_viewport() -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(elevation=-1.0),))
    detections = (_mob_at(100.0, 100.0),)
    player = WorldPosition(0.0, -1.0, 0.0)

    assert estimate_mob_world_positions(
        detections, None, player, VIEWPORT_WIDTH, VIEWPORT_HEIGHT, mesh
    ) == (None,)
    assert estimate_mob_world_positions(
        detections, _camera(), player, VIEWPORT_WIDTH, VIEWPORT_HEIGHT, None
    ) == (None,)
    assert estimate_mob_world_positions(
        detections, _camera(), None, VIEWPORT_WIDTH, VIEWPORT_HEIGHT, mesh
    ) == (None,)
    assert estimate_mob_world_positions(detections, _camera(), player, 0, 0, mesh) == (None,)


def test_a_box_reaching_past_the_viewport_bottom_is_not_unprojected() -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(elevation=-1.0),))

    estimates = estimate_mob_world_positions(
        (VisibleMob(1, "Aibatt", 0.9, 90, 90, 20, 20),),
        _camera(),
        WorldPosition(0.0, -1.0, 0.0),
        VIEWPORT_WIDTH,
        VIEWPORT_HEIGHT,
        mesh,
    )

    assert estimates == (None,)


def test_attached_estimates_enrich_only_the_detections_that_were_measured() -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(elevation=-1.0),))
    detections = (_mob_at(100.0, 100.0), _mob_at(100.0, 0.0))

    enriched = with_estimated_world_positions(
        detections,
        estimate_mob_world_positions(
            detections,
            _camera(),
            WorldPosition(0.0, -1.0, 0.0),
            VIEWPORT_WIDTH,
            VIEWPORT_HEIGHT,
            mesh,
        ),
    )

    assert (enriched[0].world_x, enriched[0].world_y, enriched[0].world_z) == (0.0, -1.0, 1.0)
    assert enriched[0].navmesh_polygon_id == 1
    assert enriched[1] == detections[1]


def test_estimator_reads_the_live_geometry_feed_and_follows_it_offline() -> None:
    mesh = NavMeshBaker().bake((_flat_triangle(elevation=-1.0),))
    feed = _GeometryFeed(_camera(), WorldPosition(0.0, -1.0, 0.0), mesh)
    estimator = MobWorldPositionEstimator(feed)
    detections = (_mob_at(100.0, 100.0),)

    measured = estimator.estimate(detections, Viewport(VIEWPORT_WIDTH, VIEWPORT_HEIGHT))
    feed.navmesh = None
    unavailable = estimator.estimate(detections, Viewport(VIEWPORT_WIDTH, VIEWPORT_HEIGHT))

    assert measured[0] is not None
    assert unavailable == (None,)


def test_chunk_filtered_batch_of_twenty_detections_stays_within_the_frame_budget() -> None:
    mesh = _terrain_mesh()
    camera = _camera()
    player = WorldPosition(0.0, 0.0, 0.0)
    detections = tuple(_mob_at(4.0 + index * 9.0, 100.0) for index in range(BATCH_DETECTION_COUNT))

    durations: list[float] = []
    for _sample in range(BATCH_SAMPLE_COUNT):
        started_at = perf_counter()
        estimates = estimate_mob_world_positions(
            detections, camera, player, VIEWPORT_WIDTH, VIEWPORT_HEIGHT, mesh
        )
        durations.append(perf_counter() - started_at)

    assert all(estimate is not None for estimate in estimates)
    assert min(durations) <= BATCH_BUDGET_SECONDS


def test_chunk_traversal_returns_the_same_surface_as_an_exhaustive_scan() -> None:
    mesh = _terrain_mesh()
    origin = WorldPosition(1.0, 12.0, 1.0)

    for step in range(24):
        direction = Vector3D(0.35 - step * 0.03, -1.0, 0.2 + step * 0.02).normalized()
        hit = mesh.raycast(origin, direction)
        expected = _exhaustive_ray_distance(mesh, origin, direction)
        assert (hit is None) == (expected is None)
        if hit is not None and expected is not None:
            assert hit.ray_distance == pytest.approx(expected)


def _exhaustive_ray_distance(
    mesh: BakedNavMesh, origin: WorldPosition, direction: Vector3D
) -> float | None:
    """Return the nearest hit distance of a deliberately unaccelerated full-mesh scan."""

    distances = [
        distance
        for polygon in mesh.polygons
        if (
            distance := ray_triangle_distance(
                origin,
                direction,
                polygon.triangle.first,
                polygon.triangle.second,
                polygon.triangle.third,
            )
        )
        is not None
    ]
    return min(distances) if distances else None


def _terrain_mesh() -> BakedNavMesh:
    """Bake a gently sloped 64x64-unit ground plate of 512 walkable triangles."""

    triangles: list[WorldTriangle] = []
    for cell_x in range(TERRAIN_CELLS_PER_SIDE):
        for cell_z in range(TERRAIN_CELLS_PER_SIDE):
            first_x = cell_x * TERRAIN_QUAD_UNITS - TERRAIN_HALF_EXTENT_UNITS
            first_z = cell_z * TERRAIN_QUAD_UNITS - TERRAIN_HALF_EXTENT_UNITS
            last_x, last_z = first_x + TERRAIN_QUAD_UNITS, first_z + TERRAIN_QUAD_UNITS
            corners = {
                (first_x, first_z): _terrain_height(first_x, first_z),
                (last_x, first_z): _terrain_height(last_x, first_z),
                (first_x, last_z): _terrain_height(first_x, last_z),
                (last_x, last_z): _terrain_height(last_x, last_z),
            }
            triangles.append(
                WorldTriangle(
                    WorldVertex(first_x, corners[(first_x, first_z)], first_z),
                    WorldVertex(last_x, corners[(last_x, first_z)], first_z),
                    WorldVertex(last_x, corners[(last_x, last_z)], last_z),
                    "terrain",
                )
            )
            triangles.append(
                WorldTriangle(
                    WorldVertex(first_x, corners[(first_x, first_z)], first_z),
                    WorldVertex(last_x, corners[(last_x, last_z)], last_z),
                    WorldVertex(first_x, corners[(first_x, last_z)], last_z),
                    "terrain",
                )
            )
    return NavMeshBaker().bake(tuple(triangles))


def _terrain_height(x: float, z: float) -> float:
    return -6.0 + (x + z) / 64.0


class _GeometryFeed:
    """A mutable stand-in for the pathing controller's read-only geometry properties."""

    def __init__(
        self, camera_state: CameraState | None, position: WorldPosition | None, mesh: BakedNavMesh
    ) -> None:
        self.camera_state = camera_state
        self.live_position = position
        self.navmesh: BakedNavMesh | None = mesh


def _mob_at(center_x: float, bottom_y: float) -> VisibleMob:
    width, height = 10, 20
    return VisibleMob(
        1,
        "Aibatt",
        0.9,
        int(center_x - width / 2),
        int(bottom_y) - height,
        width,
        height,
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


def _deck(*, elevation: float) -> WorldTriangle:
    """Return one broad level surface, wide enough to occlude a deck beneath it."""

    return WorldTriangle(
        WorldVertex(-16.0, elevation, -16.0),
        WorldVertex(16.0, elevation, -16.0),
        WorldVertex(0.0, elevation, 16.0),
        "deck",
    )


def _flat_triangle(*, elevation: float) -> WorldTriangle:
    return WorldTriangle(
        WorldVertex(-4.0, elevation, 0.0),
        WorldVertex(4.0, elevation, 4.0),
        WorldVertex(4.0, elevation, 0.0),
        "fixture",
    )
