"""Authoritative NavMesh enrichment for otherwise client-space mob detections."""

from __future__ import annotations

from dataclasses import replace
from math import dist

from flyff_bot.features.automation.models import Viewport, VisibleMob
from flyff_bot.features.navigation.live_camera import CameraState
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh
from flyff_bot.features.telemetry.geometry import project_candidate


def enrich_visible_mobs(
    mobs: tuple[VisibleMob, ...],
    *,
    viewport: Viewport,
    player_position: WorldPosition | None,
    camera_state: CameraState | None,
    navmesh: BakedNavMesh | None,
    anchor_position: WorldPosition | None,
    leash_radius_units: float,
) -> tuple[VisibleMob, ...]:
    """Attach only measured geometry to detections, retaining explicit missing values.

    No camera state, live GPS, or mesh means that the original 2D detections are returned
    unchanged.  This preserves the established viewport selection fallback rather than
    representing an estimate as authoritative geometry.
    """

    if (
        navmesh is None
        or camera_state is None
        or player_position is None
        or anchor_position is None
        or not viewport.has_size
    ):
        return mobs
    enriched: list[VisibleMob] = []
    for mob in mobs:
        hit = project_candidate(
            camera=camera_state,
            navmesh=navmesh,
            player_position=player_position,
            viewport_width=viewport.width,
            viewport_height=viewport.height,
            screen_x=mob.x + mob.width / 2.0,
            screen_bottom_y=mob.y + mob.height,
        )
        if hit is None:
            enriched.append(mob)
            continue
        reachable = navmesh.is_reachable(player_position, hit.position)
        anchor_distance = navmesh.path_distance(anchor_position, hit.position)
        within_leash = anchor_distance is not None and anchor_distance <= leash_radius_units
        enriched.append(
            replace(
                mob,
                world_x=hit.position.x,
                world_y=hit.position.y,
                world_z=hit.position.z,
                navmesh_polygon_id=hit.polygon_id,
                navmesh_path_distance=hit.path_distance,
                navmesh_reachable=reachable,
                navmesh_within_leash=within_leash,
            )
        )
    return tuple(enriched)


def mob_world_position(mob: VisibleMob) -> WorldPosition | None:
    """Return a complete measured mob position, never a screen-coordinate substitute."""

    if mob.world_x is None or mob.world_y is None or mob.world_z is None:
        return None
    return WorldPosition(mob.world_x, mob.world_y, mob.world_z)


def world_distance(first: WorldPosition, second: WorldPosition) -> float:
    """Return the exact Euclidean distance between two measured world coordinates."""

    return dist((first.x, first.y, first.z), (second.x, second.y, second.z))
