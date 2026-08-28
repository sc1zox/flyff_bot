"""Turn detected bounding boxes into measured NavMesh positions, or into nothing at all.

A box' bottom centre is where the entity touches walkable ground, so it is the only anchor
that unprojects without the parallax error a torso or head centre carries.  Everything here
is a read-only computation over an already captured frame, a polled camera snapshot, and an
offline baked mesh: a missing feed or a ray that meets no walkable surface yields ``None``
rather than a synthesized coordinate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import dist
from typing import Protocol

from flyff_bot.features.automation.models import Viewport, VisibleMob
from flyff_bot.features.automation.observation_interval import (
    ObservationInterval,
    ObservationSample,
    ObservationSource,
    evaluate_observation_interval,
)
from flyff_bot.features.navigation.live_camera import CameraState, unproject_screen_ray
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh


@dataclass(frozen=True, slots=True)
class EstimatedMobWorldPosition:
    """One detection resolved to the walkable surface its feet stand on."""

    position: WorldPosition
    navmesh_polygon_id: int | None
    distance_to_player: float
    confidence: float
    class_name: str
    ray_distance: float


class MobWorldGeometryFeed(Protocol):
    """The live read-only geometry one perception tick unprojects detections against.

    The sample timestamps are part of the contract rather than an optional extra: a camera
    pose and a player coordinate cannot be fused without knowing whether they describe the
    same instant, and a feed that cannot say when it read something cannot be fused at all.
    """

    @property
    def camera_state(self) -> CameraState | None: ...

    @property
    def live_position(self) -> WorldPosition | None: ...

    @property
    def navmesh(self) -> BakedNavMesh | None: ...

    @property
    def camera_sampled_at_seconds(self) -> float | None: ...

    @property
    def live_sampled_at_seconds(self) -> float | None: ...

    @property
    def observed_world_id(self) -> int | None: ...


@dataclass(frozen=True, slots=True)
class MobWorldObservation:
    """One tick's world estimates together with the interval that justifies them.

    When the interval is incoherent every estimate is ``None``: the criterion is that a
    stale or cross-world sample is rejected rather than combined, so there is deliberately
    no partial result to fall back on.
    """

    estimates: tuple[EstimatedMobWorldPosition | None, ...]
    interval: ObservationInterval


def ground_contact_anchor(mob: VisibleMob) -> tuple[float, float]:
    """Return the bottom-centre pixel at which a detected entity meets the ground."""

    return mob.x + mob.width / 2.0, float(mob.y + mob.height)


def estimate_mob_world_positions(
    detections: tuple[VisibleMob, ...],
    camera_state: CameraState | None,
    player_position: WorldPosition | None,
    viewport_width: int,
    viewport_height: int,
    navmesh: BakedNavMesh | None,
) -> tuple[EstimatedMobWorldPosition | None, ...]:
    """Estimate one world position per detection, keeping the detections' own order.

    Entries stay index-aligned with ``detections`` so a caller can attach a result to the
    box it came from; a detection without a measured surface hit is ``None``.
    """

    if (
        camera_state is None
        or navmesh is None
        or player_position is None
        or viewport_width <= 0
        or viewport_height <= 0
    ):
        return (None,) * len(detections)
    return tuple(
        _estimate(mob, camera_state, player_position, viewport_width, viewport_height, navmesh)
        for mob in detections
    )


def with_estimated_world_positions(
    detections: tuple[VisibleMob, ...],
    estimates: tuple[EstimatedMobWorldPosition | None, ...],
) -> tuple[VisibleMob, ...]:
    """Attach measured coordinates to detections, leaving unresolved ones untouched."""

    return tuple(
        mob
        if estimate is None
        else replace(
            mob,
            world_x=estimate.position.x,
            world_y=estimate.position.y,
            world_z=estimate.position.z,
            navmesh_polygon_id=estimate.navmesh_polygon_id,
        )
        for mob, estimate in zip(detections, estimates, strict=True)
    )


class MobWorldPositionEstimator:
    """Bind one live geometry feed so a perception tick can estimate a whole batch."""

    def __init__(self, geometry: MobWorldGeometryFeed) -> None:
        self._geometry = geometry

    def observe(
        self,
        detections: tuple[VisibleMob, ...],
        viewport: Viewport,
        at_seconds: float,
        adopted_world_id: int | None = None,
    ) -> MobWorldObservation:
        """Estimate positions only when this tick's samples describe one instant.

        ``adopted_world_id`` is the world the session's offline geometry was built for. It is
        compared against the world the client reports, so a mesh baked for another map is
        refused instead of being raycast into.
        """

        geometry = self._geometry
        interval = evaluate_observation_interval(
            self._samples(adopted_world_id), at_seconds=at_seconds
        )
        if not interval.is_coherent:
            return MobWorldObservation((None,) * len(detections), interval)
        return MobWorldObservation(
            estimate_mob_world_positions(
                detections,
                geometry.camera_state,
                geometry.live_position,
                viewport.width,
                viewport.height,
                geometry.navmesh,
            ),
            interval,
        )

    def _samples(self, adopted_world_id: int | None) -> tuple[ObservationSample, ...]:
        """Describe what each source contributed to this tick, present or not."""

        geometry = self._geometry
        observed_world_id = geometry.observed_world_id
        return (
            ObservationSample(
                ObservationSource.CAMERA,
                sampled_at_seconds=geometry.camera_sampled_at_seconds,
                world_id=observed_world_id,
                is_available=geometry.camera_state is not None,
            ),
            ObservationSample(
                ObservationSource.GPS,
                sampled_at_seconds=geometry.live_sampled_at_seconds,
                world_id=observed_world_id,
                is_available=geometry.live_position is not None,
            ),
            ObservationSample(
                ObservationSource.NAVMESH,
                world_id=adopted_world_id,
                is_live=False,
                is_available=geometry.navmesh is not None,
            ),
            ObservationSample(
                ObservationSource.WORLD_MAP,
                world_id=adopted_world_id,
                is_live=False,
                # The adopted map steers travel rather than unprojection, so a session
                # without one still fuses candidates; it simply states no world.
                is_available=True,
            ),
        )


def _estimate(
    mob: VisibleMob,
    camera_state: CameraState,
    player_position: WorldPosition,
    viewport_width: int,
    viewport_height: int,
    navmesh: BakedNavMesh,
) -> EstimatedMobWorldPosition | None:
    anchor_x, anchor_y = ground_contact_anchor(mob)
    if not (0.0 <= anchor_x <= viewport_width and 0.0 <= anchor_y <= viewport_height):
        return None
    try:
        ray = unproject_screen_ray(
            anchor_x, anchor_y, viewport_width, viewport_height, camera_state
        )
    except ValueError:
        # A degenerate camera matrix is a transient read, not a reason to drop the tick.
        return None
    hit = navmesh.raycast(ray.origin, ray.direction)
    if hit is None:
        return None
    return EstimatedMobWorldPosition(
        position=hit.position,
        navmesh_polygon_id=hit.polygon_id,
        distance_to_player=dist(
            (player_position.x, player_position.y, player_position.z),
            (hit.position.x, hit.position.y, hit.position.z),
        ),
        confidence=mob.confidence,
        class_name=mob.class_name,
        ray_distance=hit.ray_distance,
    )
