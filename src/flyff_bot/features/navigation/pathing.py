"""Authoritative 3D closed-loop pathing controller over live GPS, camera state, and NavMesh."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from flyff_bot.features.automation.models import VisibleMob, WorldState
from flyff_bot.features.input_control.keymap import (
    VIRTUAL_KEY_A,
    VIRTUAL_KEY_D,
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_S,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.navigation.attack_point_planner import (
    MELEE_ATTACK_MAXIMUM_DISTANCE_UNITS,
    MELEE_ATTACK_MINIMUM_DISTANCE_UNITS,
    AttackPointPlanner,
    EngagementRadii,
    should_replan_attack_target,
)
from flyff_bot.features.navigation.live_camera import (
    CameraReadErrorCode,
    CameraState,
    LiveCameraReader,
)
from flyff_bot.features.navigation.live_position import (
    LivePositionReader,
    PositionReadErrorCode,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.navmesh import BakedNavMesh
from flyff_bot.features.navigation.snapshots import (
    NavigationSnapshot,
    NavMeshMobSnapshot,
    VectorZoneSnapshot,
)
from flyff_bot.features.navigation.stall_recovery import (
    REPEATED_LOCAL_STALL_HIT_COUNT,
    RecoveryContext,
    RecoveryEvent,
    RecoveryEventKind,
    RecoveryPhase,
    RepeatedLocalStallTracker,
    StallObservation,
    TemporaryObstacleRegistry,
    plan_escape_candidates,
    select_escape,
)
from flyff_bot.features.navigation.targeting import enrich_visible_mobs, mob_world_position
from flyff_bot.features.navigation.teleport import (
    TeleportConfig,
    TeleportController,
    TeleportStatus,
)
from flyff_bot.features.navigation.teleporter_dispatch import (
    CombatObservation,
    TeleporterDispatcher,
    TeleporterDispatchStatus,
)
from flyff_bot.features.navigation.teleporter_models import TeleporterDestination
from flyff_bot.features.navigation.tracking import (
    StallConfig,
    StallDetector,
)
from flyff_bot.features.navigation.vector_navigation import (
    VectorZoneNavigator,
)
from flyff_bot.features.navigation.world_extractor import VectorSpawnZone, WorldCoordinate
from flyff_bot.features.tactical_parameters import TacticalParameterSpace
from flyff_bot.features.vision.models import CapturedFrame

DEFAULT_PATHING_STEP_DURATION_SECONDS = 0.6
DEFAULT_PATHING_TURN_DURATION_SECONDS = 0.08
DEFAULT_HEADING_TOLERANCE_DEGREES = 25.0
DEFAULT_HEADING_PIVOT_THRESHOLD_DEGREES = 45.0
DEFAULT_REPLAN_INTERVAL_SECONDS = 20.0
DEFAULT_NAVMESH_LEASH_RADIUS_UNITS = 100.0
DEFAULT_NAVMESH_WAYPOINT_ARRIVAL_UNITS = 1.5
DEFAULT_NAVMESH_ENGAGEMENT_DISTANCE_UNITS = 3.0
DEFAULT_QUEST_INTERACTION_DISTANCE_UNITS = 3.0
FULL_TURN_DEGREES = 360.0
HALF_TURN_DEGREES = 180.0


def bearing_degrees(origin_x: float, origin_z: float, target_x: float, target_z: float) -> float:
    """Return the clockwise compass bearing from origin to target in world coordinates."""

    return math.degrees(math.atan2(target_x - origin_x, target_z - origin_z)) % FULL_TURN_DEGREES


def heading_error_degrees(heading_degrees: float, bearing: float) -> float:
    """Return the shortest signed turn from a heading to a bearing."""

    return (bearing - heading_degrees + HALF_TURN_DEGREES) % FULL_TURN_DEGREES - HALF_TURN_DEGREES


class PathingMode(StrEnum):
    """The observable phases of authoritative navigation."""

    IDLE = "idle"
    TRAVELING = "traveling"
    BLOCKED = "blocked"
    TELEPORTING = "teleporting"


@dataclass(frozen=True, slots=True)
class PathingDecision:
    """One interruptible movement request, if the current phase wants to move."""

    mode: PathingMode
    virtual_key: int | None = None
    key_press_duration_seconds: float | None = None
    virtual_keys: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class PathingConfig:
    """Timing, steering tolerance, and sub-model settings for authoritative pathing."""

    step_duration_seconds: float = DEFAULT_PATHING_STEP_DURATION_SECONDS
    turn_duration_seconds: float = DEFAULT_PATHING_TURN_DURATION_SECONDS
    heading_tolerance_degrees: float = DEFAULT_HEADING_TOLERANCE_DEGREES
    heading_pivot_threshold_degrees: float = DEFAULT_HEADING_PIVOT_THRESHOLD_DEGREES
    replan_interval_seconds: float = DEFAULT_REPLAN_INTERVAL_SECONDS
    navmesh_leash_radius_units: float = DEFAULT_NAVMESH_LEASH_RADIUS_UNITS
    navmesh_waypoint_arrival_units: float = DEFAULT_NAVMESH_WAYPOINT_ARRIVAL_UNITS
    navmesh_engagement_distance_units: float = DEFAULT_NAVMESH_ENGAGEMENT_DISTANCE_UNITS
    quest_interaction_distance_units: float = DEFAULT_QUEST_INTERACTION_DISTANCE_UNITS
    stall: StallConfig = field(default_factory=StallConfig)

    def __post_init__(self) -> None:
        if self.step_duration_seconds <= 0.0 or self.turn_duration_seconds <= 0.0:
            raise ValueError("Pathing step durations must be positive.")
        if not 0.0 < self.heading_tolerance_degrees < 180.0:
            raise ValueError("Pathing heading tolerance must be between 0 and 180 degrees.")
        if not self.heading_tolerance_degrees <= self.heading_pivot_threshold_degrees < 180.0:
            raise ValueError("Pathing pivot threshold must be at least the heading tolerance.")
        if self.replan_interval_seconds <= 0.0:
            raise ValueError("Pathing replan interval must be positive.")
        if self.navmesh_leash_radius_units <= 0.0:
            raise ValueError("NavMesh leash radius must be positive.")
        if self.navmesh_waypoint_arrival_units <= 0.0:
            raise ValueError("NavMesh waypoint arrival tolerance must be positive.")
        if self.navmesh_engagement_distance_units <= 0.0:
            raise ValueError("NavMesh engagement distance must be positive.")
        if self.quest_interaction_distance_units <= 0.0:
            raise ValueError("NavMesh quest interaction distance must be positive.")


class PathingController:
    """Steer exclusively over live GPS, camera geometry, and authoritative NavMesh."""

    def __init__(
        self,
        *,
        config: PathingConfig | None = None,
        vector_navigator: VectorZoneNavigator | None = None,
        position_reader: LivePositionReader | None = None,
        camera_reader: LiveCameraReader | None = None,
        navmesh: BakedNavMesh | None = None,
        teleport_config: TeleportConfig | None = None,
        teleporter_dispatcher: TeleporterDispatcher | None = None,
        tactical_parameters: TacticalParameterSpace | None = None,
    ) -> None:
        self._config = config or PathingConfig()
        if tactical_parameters is not None:
            self._config = _pathing_config_with_parameters(self._config, tactical_parameters)
        self._stalls = StallDetector(self._config.stall)
        self._vector_navigator = vector_navigator
        self._position_reader = position_reader
        self._camera_reader = camera_reader
        self._navmesh = navmesh
        if vector_navigator is not None:
            # Patrol routing, combat approaches, and stall-recovery escape routing must all
            # read one authoritative mesh (US-093).
            if self._navmesh is None:
                self._navmesh = vector_navigator.navmesh
            vector_navigator.attach_navmesh(self._navmesh)
        self._navmesh_anchor: WorldPosition | None = None
        self._objective_anchor: WorldPosition | None = None
        self._objective_leash_radius_units: float | None = None
        self._navmesh_target: WorldPosition | None = None
        self._navmesh_mobs: tuple[NavMeshMobSnapshot, ...] = ()
        self._navigation_trajectory: list[WorldPosition] = []
        self._position_source = PositionSource.UNAVAILABLE
        self._position_error_code: PositionReadErrorCode | None = None
        self._live_position: WorldPosition | None = None
        self._live_sampled_at_seconds: float | None = None
        self._camera_state: CameraState | None = None
        self._camera_sampled_at_seconds: float | None = None
        self._observed_world_id: int | None = None
        self._camera_error_code: CameraReadErrorCode | None = None
        self._attack_point_planner: AttackPointPlanner | None = None
        self._planned_attack_target: WorldPosition | None = None
        self._world_waypoints: tuple[WorldPosition, ...] = ()
        self._teleport = TeleportController(teleport_config)
        self._teleporter_dispatcher = teleporter_dispatcher
        self._pending_decision: PathingDecision | None = None
        self._obstacles = TemporaryObstacleRegistry()
        self._repeated_stalls = RepeatedLocalStallTracker()
        self._recovery = RecoveryContext()
        self._recovery_events: list[RecoveryEvent] = []
        self._stall_previous_position: WorldPosition | None = None
        self._vector_zone: VectorSpawnZone | None = None
        self._mode = PathingMode.IDLE
        self._waypoint_index = 0
        self._planned_at_seconds: float | None = None
        self._movement_commanded = False
        self._stalled = False
        self._heading_degrees: float = 0.0
        self._completed_zone_sweeps = 0

    @property
    def is_gps_available(self) -> bool:
        """Return whether live client GPS is currently available and finite."""

        return self._position_source is PositionSource.LIVE and self._live_position is not None

    @property
    def has_position_provider(self) -> bool:
        """Return whether authoritative GPS polling is configured."""

        return self._position_reader is not None

    @property
    def has_camera_provider(self) -> bool:
        """Return whether authoritative camera polling is configured."""

        return self._camera_reader is not None

    @property
    def mode(self) -> PathingMode:
        """Return the current pathing phase."""

        return self._mode

    @property
    def position_source(self) -> PositionSource:
        """Return whether pathing is anchored by live GPS or has no position at all."""

        return self._position_source

    @property
    def position_error_code(self) -> PositionReadErrorCode | None:
        """Return the current reason live GPS is unavailable, if any."""

        return self._position_error_code

    @property
    def live_position(self) -> WorldPosition | None:
        """Return the newest client coordinate, when available."""

        return self._live_position

    @property
    def heading_degrees(self) -> float:
        """Return current character heading in compass degrees."""

        if self._camera_state is not None:
            return self._camera_state.yaw_degrees
        return self._heading_degrees

    @property
    def camera_state(self) -> CameraState | None:
        """Return the latest camera state without polling it again."""

        return self._camera_state

    @property
    def camera_error_code(self) -> CameraReadErrorCode | None:
        """Return the latest camera read error code, if any."""

        return self._camera_error_code

    @property
    def camera_sampled_at_seconds(self) -> float | None:
        """Return when the newest valid or failed camera poll was attempted."""

        return self._camera_sampled_at_seconds

    @property
    def navmesh(self) -> BakedNavMesh | None:
        """Return the optional offline mesh used for active target navigation."""

        return self._navmesh

    @property
    def navmesh_anchor(self) -> WorldPosition | None:
        """Return the measured start-of-session leash anchor, when GPS was available."""

        return self._navmesh_anchor

    @property
    def teleporter_dispatcher(self) -> TeleporterDispatcher | None:
        """Return the guarded long-range travel dispatcher, when one is configured."""

        return self._teleporter_dispatcher

    def observe_world_id(self) -> int | None:
        """Return the world the client reports the character is in, when it is readable.

        Sampling happens only when a goal asks which world it has to travel into; the
        per-tick observation loop is deliberately left untouched.
        """

        dispatcher = self._teleporter_dispatcher
        if dispatcher is None:
            return None
        self._observed_world_id = dispatcher.observer.observe().world_id
        return self._observed_world_id

    @property
    def observed_world_id(self) -> int | None:
        """Return the world last read from the client, without reading it again.

        Perception needs the world on every tick to notice a cross-world sample, but a
        read-only memory poll per tick buys nothing: the character's world changes only
        across a teleport, which goes through :meth:`observe_world_id` anyway.
        """

        return self._observed_world_id

    @property
    def leash_anchor(self) -> WorldPosition | None:
        """Return the position the targeting leash is currently measured from."""

        return self._objective_anchor or self._navmesh_anchor

    @property
    def leash_radius_units(self) -> float:
        """Return the radius the targeting leash currently admits."""

        if self._objective_leash_radius_units is not None:
            return self._objective_leash_radius_units
        return self._config.navmesh_leash_radius_units

    def set_objective_leash(
        self, anchor: WorldPosition | None, radius_units: float | None = None
    ) -> None:
        """Re-anchor the targeting leash on the active goal's area.

        Passing ``None`` restores the measured start-of-session anchor and the configured
        radius, which is what a session without a resolved objective area uses.
        """

        if anchor is not None and radius_units is not None and radius_units <= 0.0:
            raise ValueError("An objective leash radius must be positive.")
        self._objective_anchor = anchor
        self._objective_leash_radius_units = None if anchor is None else radius_units

    @property
    def navmesh_target(self) -> WorldPosition | None:
        """Return the selected measured target while a Funnel approach is active."""

        return self._navmesh_target

    @property
    def active_spawn_zone_metadata(self) -> dict[str, object] | None:
        """Return the configured extracted spawn-zone record for a session header."""

        navigator = self._vector_navigator
        zone = None if navigator is None else navigator.configured_zone
        return None if zone is None else zone.to_dict()

    @property
    def live_sampled_at_seconds(self) -> float | None:
        """Return when the newest live coordinate was actually sampled."""

        return self._live_sampled_at_seconds

    @property
    def world_waypoints(self) -> tuple[WorldPosition, ...]:
        """Return the remaining authoritative waypoints, if a live route exists."""

        return self._world_waypoints[self._waypoint_index :]

    @property
    def waypoints(self) -> tuple[WorldPosition, ...]:
        """Alias for world_waypoints."""

        return self.world_waypoints

    @property
    def terrain_slope(self) -> float | None:
        """Return the heightfield gradient at the latest live coordinate."""

        navigator = self._vector_navigator
        position = self._live_position
        if navigator is None or position is None:
            return None
        return navigator.world_map.terrain.gradient_at(WorldCoordinate(position.x, position.z))

    @property
    def is_recovering(self) -> bool:
        """Return whether a stall is being worked through by a local replan or an escape."""

        return self._recovery.is_recovering

    @property
    def temporary_world_blocks(self) -> tuple[WorldPosition, ...]:
        """Return active NavMesh-projected stall obstacles currently excluded from replans."""

        return self._obstacles.positions(self._live_sampled_at_seconds or 0.0)

    @property
    def is_stalled(self) -> bool:
        """Return the stall verdict of the most recent observation."""

        return self._stalled

    @property
    def completed_zone_sweeps(self) -> int:
        """Return how many full patrol laps of the active camp produced no confirmed kill.

        A camp that is swept end to end without a kill is exhausted, which is what hands a
        multi-zone selection to its next spawn zone (US-059).
        """

        return self._completed_zone_sweeps

    @property
    def vector_navigator(self) -> VectorZoneNavigator | None:
        """Return the goal-driven vector navigator, when an extracted map is loaded."""

        return self._vector_navigator

    @property
    def vector_navigation_active(self) -> bool:
        """Return whether an extracted world map is steering this session."""

        return self._vector_navigator is not None and self._vector_navigator.is_active

    @property
    def vector_navigation_gps_unavailable(self) -> bool:
        """Return whether active vector navigation is blocked solely by missing live GPS."""

        return not self.is_gps_available

    def attach_vector_navigator(self, navigator: VectorZoneNavigator | None) -> None:
        """Adopt or drop the extracted-map navigator and force a replan on the next step.

        Adoption is also where the session settles on one baked collision mesh: the loaded
        mesh wins, and a mesh the operator loaded next to the world map is adopted when this
        controller was built without one. Patrol routes and combat approaches then read the
        same polygons (US-091).
        """

        if navigator is not None:
            if self._navmesh is None:
                self._navmesh = navigator.navmesh
                self._attack_point_planner = None
            navigator.attach_navmesh(self._navmesh)
        self._vector_navigator = navigator
        self._vector_zone = None
        self._world_waypoints = ()
        self._navmesh_target = None
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._completed_zone_sweeps = 0

    def request_teleporter_destination(
        self, destination: TeleporterDestination, at_seconds: float
    ) -> bool:
        """Arm one guarded client teleporter transition."""

        dispatcher = self._teleporter_dispatcher
        if dispatcher is None:
            return False
        self._world_waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._navmesh_target = None
        self._recovery.reset()
        self._recovery_events.clear()
        self._pending_decision = None
        dispatcher.request(destination, at_seconds)
        return True

    def snapshot(self, at_seconds: float = 0.0) -> NavigationSnapshot:
        """Return an immutable snapshot of authoritative 3D GPS, NavMesh, and active route."""

        pos = self._live_position
        px = pos.x if pos is not None else 0.0
        py = pos.z if pos is not None else 0.0
        zone = self._vector_zone
        vector_zone = (
            None if zone is None or self._vector_navigator is None else _zone_snapshot(zone)
        )
        vector_zones = (
            tuple(_zone_snapshot(z) for z in self._vector_navigator.preferred_zones)
            if self._vector_navigator is not None
            else ()
        )
        waypoints = tuple((wp.x, wp.z) for wp in self._world_waypoints[self._waypoint_index :])
        return NavigationSnapshot(
            player_x=px,
            player_y=py,
            heading_degrees=self.heading_degrees,
            waypoints=waypoints,
            vector_zone=vector_zone,
            vector_zones=vector_zones,
            position_source=self._position_source,
            position_error_code=self._position_error_code,
            world_position=self._live_position,
            camera_state=self._camera_state,
            camera_error_code=self._camera_error_code,
            world_waypoints=self._world_waypoints,
            terrain_samples=(
                () if self._vector_navigator is None else self._vector_navigator.terrain_samples
            ),
            navmesh_mobs=self._navmesh_mobs,
            navigation_trajectory=tuple(self._navigation_trajectory),
        )

    def track(self, state: WorldState, frame: CapturedFrame | None = None) -> None:
        """Update live GPS and camera estimates without dispatching input."""

        self._poll_live_position(state.observed_at_seconds)
        self._poll_live_camera(state.observed_at_seconds)
        if self._navmesh_anchor is None and self._live_position is not None:
            self._navmesh_anchor = self._live_position
        if self._navmesh_target is not None and self._live_position is not None:
            self._navigation_trajectory.append(self._live_position)

    def enrich_visible_mobs(self, state: WorldState) -> tuple[VisibleMob, ...]:
        """Attach authoritative 3D NavMesh coordinates and reachability to visible mobs."""

        mobs = enrich_visible_mobs(
            state.visible_mobs,
            viewport=state.viewport,
            player_position=self._live_position,
            camera_state=self._camera_state,
            navmesh=self._navmesh,
            anchor_position=self.leash_anchor,
            leash_radius_units=self.leash_radius_units,
        )
        self._navmesh_mobs = tuple(
            NavMeshMobSnapshot(
                mob.world_x,
                mob.world_z,
                mob.navmesh_reachable,
                selected=(
                    self._navmesh_target is not None
                    and mob.world_x == self._navmesh_target.x
                    and mob.world_z == self._navmesh_target.z
                ),
            )
            for mob in mobs
            if mob.world_x is not None and mob.world_z is not None
        )
        return mobs

    def begin_target_approach(self, mob: VisibleMob, at_seconds: float) -> bool:
        """Start a Funnel route to one selected measured mob."""

        target = mob_world_position(mob)
        start = self._live_position
        if (
            target is None
            or start is None
            or self._camera_state is None
            or self._navmesh is None
            or mob.navmesh_reachable is not True
            or mob.navmesh_within_leash is not True
        ):
            return False
        route = self._plan_target_route(start, target)
        if not route:
            return False
        self._planned_attack_target = target
        self._navmesh_target = target
        self._navigation_trajectory = [start]
        self._world_waypoints = route
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING
        return True

    def begin_tactical_attack_point_approach(
        self,
        mob: VisibleMob,
        attack_point: tuple[float, float, float],
        at_seconds: float,
    ) -> bool:
        """Start a route to the exact prevalidated point selected by a learned action."""

        target = mob_world_position(mob)
        start = self._live_position
        mesh = self._navmesh
        point = WorldPosition(*attack_point)
        if (
            target is None
            or start is None
            or self._camera_state is None
            or mesh is None
            or mob.navmesh_reachable is not True
            or mob.navmesh_within_leash is not True
        ):
            return False
        route = mesh.find_path(start, point)
        if not route:
            return False
        self._planned_attack_target = target
        self._navmesh_target = point
        self._navigation_trajectory = [start]
        self._world_waypoints = route
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING
        return True

    def plan_tactical_attack_point(
        self, mob: VisibleMob, distance_units: float
    ) -> tuple[WorldPosition, float] | None:
        """Return one NavMesh-contained, policy-rankable point at an exact safe radius."""

        target = mob_world_position(mob)
        start = self._live_position
        mesh = self._navmesh
        if target is None or start is None or mesh is None or not mesh.polygons:
            return None
        planner = self._attack_point_planner or AttackPointPlanner(mesh)
        self._attack_point_planner = planner
        plan = planner.plan(
            start,
            target,
            EngagementRadii(distance_units, distance_units),
            heading_degrees=self.heading_degrees,
            obstacles=self.temporary_world_blocks,
        )
        if plan is None:
            return None
        return plan.selected.position, plan.selected.angle_degrees

    def _plan_target_route(
        self,
        start: WorldPosition,
        target: WorldPosition,
    ) -> tuple[WorldPosition, ...]:
        """Prefer a contained attack point and fall back to direct Funnel routing."""

        mesh = self._navmesh
        if mesh is None:
            return ()
        planner = self._attack_point_planner
        if planner is None and mesh.polygons:
            planner = AttackPointPlanner(mesh)
            self._attack_point_planner = planner
        route: tuple[WorldPosition, ...] | None = None
        if planner is not None:
            configured_distance = self._config.navmesh_engagement_distance_units
            plan = planner.plan(
                start,
                target,
                EngagementRadii(
                    min(configured_distance, MELEE_ATTACK_MINIMUM_DISTANCE_UNITS),
                    max(configured_distance, MELEE_ATTACK_MAXIMUM_DISTANCE_UNITS),
                ),
                heading_degrees=self.heading_degrees,
                obstacles=self.temporary_world_blocks,
            )
            route = plan.waypoints if plan is not None else None
            self._planned_attack_target = target
        return route if route is not None else mesh.find_path(start, target)

    def begin_position_approach(self, target: WorldPosition, at_seconds: float) -> bool:
        """Start a NavMesh route to an exact world position such as a configured NPC."""

        start = self._live_position
        if start is None or self._camera_state is None or self._navmesh is None:
            return False
        route = self._navmesh.find_path(start, target)
        if not route:
            return False
        self._planned_attack_target = None
        self._navmesh_target = target
        self._navigation_trajectory = [start]
        self._world_waypoints = route
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING
        return True

    def cancel_target_approach(self) -> None:
        """Discard a selected-target route."""

        self._navmesh_target = None
        self._planned_attack_target = None
        self._navigation_trajectory = []
        self._world_waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._recovery.reset()
        self._mode = PathingMode.IDLE

    def target_in_engagement_range(self) -> bool:
        """Report whether live GPS is close enough to hand the target to combat."""

        target = self._navmesh_target
        position = self._live_position
        if target is None or position is None:
            return False
        arrival_distance = (
            self._config.navmesh_waypoint_arrival_units
            if self._planned_attack_target is not None
            and self._planned_attack_target != self._navmesh_target
            else self._config.navmesh_engagement_distance_units
        )
        return (
            math.dist((position.x, position.y, position.z), (target.x, target.y, target.z))
            <= arrival_distance
        )

    def position_target_in_interaction_range(self) -> bool:
        """Report whether live GPS is close enough to interact with an exact target."""

        target = self._navmesh_target
        position = self._live_position
        if target is None or position is None:
            return False
        return (
            math.dist((position.x, position.y, position.z), (target.x, target.y, target.z))
            <= self._config.quest_interaction_distance_units
        )

    def update_engagement_distance(self, distance_units: float) -> None:
        """Apply a dynamic combat-class engagement distance without dropping the route."""

        self._config = replace(
            self._config,
            navmesh_engagement_distance_units=distance_units,
        )

    def update_tactical_parameters(self, parameters: TacticalParameterSpace) -> None:
        """Atomically apply the shared navigation heuristics without dropping a route."""

        self._config = _pathing_config_with_parameters(self._config, parameters)
        self._stalls = StallDetector(self._config.stall)

    def observe(self, state: WorldState, frame: CapturedFrame | None = None) -> None:
        """Record live position delta and stall evidence for one tick."""

        at_seconds = state.observed_at_seconds
        previous_position = self._live_position
        self._stall_previous_position = previous_position
        self.track(state, frame)
        stalled = self._stalls.observe(
            frame,
            movement_commanded=self._movement_commanded,
            at_seconds=at_seconds,
            live_position=self._live_position,
            live_sampled_at_seconds=self._live_sampled_at_seconds,
        )
        self._movement_commanded = False
        if not self.is_gps_available:
            self._stalled = stalled
            return
        if stalled and self._mode is not PathingMode.BLOCKED and self._live_position is not None:
            self._register_stall(previous_position, at_seconds)
        self._stalled = stalled

    def register_obstacle(self, at_seconds: float) -> bool:
        """Record an externally detected obstacle ahead of the current position."""

        if self._mode is PathingMode.BLOCKED:
            return False
        if self._live_position is not None:
            self._register_stall(self._stall_previous_position, at_seconds)
            self._stalled = True
            return True
        return False

    def record_kill(self, monster_name: str) -> bool:
        """Attribute one confirmed kill to vector goals and advance zone on quota completion."""

        navigator = self._vector_navigator
        if navigator is None or not monster_name:
            return False
        self._completed_zone_sweeps = 0
        if not navigator.record_kill(monster_name):
            return False
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._vector_zone = None
        self._world_waypoints = ()
        return True

    def advance_to_next_zone(self) -> VectorSpawnZone | None:
        """Advance the vector navigator to the next configured spawn zone and reset routing."""

        navigator = self._vector_navigator
        if navigator is None:
            return None
        zone = navigator.advance_to_next_zone()
        if zone is None:
            return None
        self._completed_zone_sweeps = 0
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._vector_zone = None
        self._world_waypoints = ()
        return zone

    def integrate_movement(self, virtual_key: int | Sequence[int], duration_seconds: float) -> None:
        """Record movement intent for stall detection gating."""

        if duration_seconds <= 0.0:
            return
        keys = tuple(virtual_key) if not isinstance(virtual_key, int) else (virtual_key,)
        self._movement_commanded = any(
            key in {VIRTUAL_KEY_W, VIRTUAL_KEY_A, VIRTUAL_KEY_S, VIRTUAL_KEY_D} for key in keys
        )

    def step(self, at_seconds: float) -> PathingDecision:
        """Return the next movement request. Enforces strict GPS requirement."""

        self._poll_live_position(at_seconds)
        self._poll_live_camera(at_seconds)
        if not self.is_gps_available:
            self._block_navigation()
            return PathingDecision(PathingMode.BLOCKED)
        if self._tick_teleporter(at_seconds):
            return PathingDecision(PathingMode.TELEPORTING)
        if self._pending_decision is not None:
            decision = self._pending_decision
            self._pending_decision = None
            return decision
        if self._needs_route(at_seconds):
            self._plan(at_seconds)
        if self._pending_decision is not None:
            decision = self._pending_decision
            self._pending_decision = None
            return decision
        if not self._world_waypoints:
            if self._mode in {PathingMode.TELEPORTING, PathingMode.BLOCKED}:
                return PathingDecision(self._mode)
            self._mode = PathingMode.IDLE
            return PathingDecision(PathingMode.IDLE)
        return self._follow_route(at_seconds)

    def confirm(self, decision: PathingDecision) -> None:
        """Acknowledge a successfully dispatched movement."""

        if decision.key_press_duration_seconds is None:
            return
        keys = (
            decision.virtual_keys
            if decision.virtual_keys
            else ((decision.virtual_key,) if decision.virtual_key is not None else ())
        )
        if keys:
            self.integrate_movement(keys, decision.key_press_duration_seconds)

    def drain_recovery_events(self) -> tuple[RecoveryEvent, ...]:
        """Return and clear the recovery milestones queued since the last drain."""

        events = tuple(self._recovery_events)
        self._recovery_events.clear()
        return events

    def _tick_teleporter(self, at_seconds: float) -> bool:
        """Advance a pending guarded teleporter transition, if one is armed."""

        dispatcher = self._teleporter_dispatcher
        if dispatcher is None or dispatcher.destination is None:
            return False
        result = dispatcher.tick(
            CombatObservation(False, 100.0, at_seconds),
            at_seconds=at_seconds,
        )
        if result.status in {
            TeleporterDispatchStatus.DEFERRED,
            TeleporterDispatchStatus.DISPATCHED,
        }:
            self._mode = PathingMode.TELEPORTING
            return True
        if result.status is TeleporterDispatchStatus.CONFIRMED:
            self._teleporter_dispatcher = None
            self._mode = PathingMode.BLOCKED
            return False
        self._block_navigation()
        return True

    def reject(self, decision: PathingDecision) -> None:
        """Return a rejected teleport request to ground routing."""

        if decision.mode is not PathingMode.TELEPORTING:
            return
        self._teleport.reject_pending()
        self._mode = PathingMode.IDLE
        self._planned_at_seconds = None

    def emergency_stop(self) -> None:
        """Immediately idle navigation and close client handles."""

        self._mode = PathingMode.IDLE
        self._world_waypoints = ()
        self._pending_decision = None
        self._obstacles.clear()
        self._repeated_stalls.clear()
        self._recovery.reset()
        self._recovery_events.clear()
        self._stall_previous_position = None
        self._movement_commanded = False
        self._navmesh_target = None
        self._navigation_trajectory = []
        self._stalls.reset()
        self._teleport.reset()
        if self._teleporter_dispatcher is not None:
            self._teleporter_dispatcher.cancel()
        if self._position_reader is not None:
            self._position_reader.close()
        if self._camera_reader is not None:
            self._camera_reader.close()
        self._live_position = None
        self._live_sampled_at_seconds = None
        self._camera_state = None
        self._camera_sampled_at_seconds = None
        self._camera_error_code = None
        self._position_source = PositionSource.UNAVAILABLE
        self._position_error_code = None

    def block_for_readiness(self) -> None:
        """Clear ephemeral movement and teleporter intent without closing live readers."""

        self._block_navigation()
        self._navmesh_target = None
        self._navigation_trajectory = []
        self._teleport.reset()
        if self._teleporter_dispatcher is not None:
            self._teleporter_dispatcher.cancel()

    def close(self) -> None:
        """Release resources on teardown."""

        self.emergency_stop()

    def mark_gps_offline(self, error_code: PositionReadErrorCode) -> None:
        """Expose GPS failure without retaining stale live coordinates."""

        if self._position_reader is not None:
            self._position_reader.close()
        self._position_source = PositionSource.UNAVAILABLE
        self._position_error_code = error_code
        self._live_position = None
        self._live_sampled_at_seconds = None
        self._block_navigation()

    def _block_navigation(self) -> None:
        self._world_waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._pending_decision = None
        self._recovery.reset()
        self._movement_commanded = False
        self._mode = PathingMode.BLOCKED

    def _register_stall(self, previous_position: WorldPosition | None, at_seconds: float) -> None:
        """Capture a structured stall, project the obstacle, and start geometric recovery.

        No blind macro is queued: the active route is invalidated, the obstruction is
        projected onto the mesh ahead of the character, and recovery continues through the
        standard ``_steer()`` pipeline while the controller stays in ``TRAVELING`` (US-093).
        """

        live = self._live_position
        if live is None:
            return
        waypoint = self._current_route_waypoint()
        observation = StallObservation(
            previous_position=previous_position or live,
            current_position=live,
            intended_direction=self._intended_direction(live, waypoint),
            intended_waypoint=waypoint,
            current_polygon_id=(
                None if self._navmesh is None else self._navmesh.polygon_or_region_id(live)
            ),
            timestamp=at_seconds,
        )
        self._recovery.last_observation = observation
        self._recovery.stall_count += 1
        if self._recovery.original_goal is None:
            self._recovery.original_goal = self._navmesh_target or self._active_goal_position()
        self._queue_recovery_event(RecoveryEventKind.STALL_DETECTED, live, at_seconds)
        obstacle = self._obstacles.register(
            observation, navmesh=self._navmesh, at_seconds=at_seconds
        )
        if obstacle is not None:
            self._queue_recovery_event(
                RecoveryEventKind.TEMPORARY_OBSTACLE_CREATED,
                obstacle.position,
                at_seconds,
                obstacle_radius=obstacle.radius,
                hit_count=obstacle.hit_count,
            )
        hits = self._repeated_stalls.record(live, at_seconds)
        self._world_waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        if self._mode is not PathingMode.TELEPORTING:
            self._mode = PathingMode.TRAVELING
        if hits >= REPEATED_LOCAL_STALL_HIT_COUNT:
            self._recovery.phase = RecoveryPhase.ESCAPE
            self._queue_recovery_event(
                RecoveryEventKind.REPEATED_LOCAL_STALL, live, at_seconds, hit_count=hits
            )
        else:
            self._recovery.phase = RecoveryPhase.LOCAL_REPLAN
            self._queue_recovery_event(RecoveryEventKind.LOCAL_REPLAN_REQUESTED, live, at_seconds)
        self._stalls.reset()

    def _queue_recovery_event(
        self,
        kind: RecoveryEventKind,
        position: WorldPosition,
        at_seconds: float,
        *,
        obstacle_radius: float | None = None,
        hit_count: int | None = None,
    ) -> None:
        self._recovery_events.append(
            RecoveryEvent(kind, position, at_seconds, obstacle_radius, hit_count)
        )

    def _current_route_waypoint(self) -> WorldPosition | None:
        if self._world_waypoints and self._waypoint_index < len(self._world_waypoints):
            return self._world_waypoints[self._waypoint_index]
        return None

    def _intended_direction(
        self, live: WorldPosition, waypoint: WorldPosition | None
    ) -> tuple[float, float]:
        if waypoint is not None:
            delta_x = waypoint.x - live.x
            delta_z = waypoint.z - live.z
            if math.hypot(delta_x, delta_z) > 0.0:
                return (delta_x, delta_z)
        heading = math.radians(self.heading_degrees)
        return (math.sin(heading), math.cos(heading))

    def _active_goal_position(self) -> WorldPosition | None:
        navigator = self._vector_navigator
        zone = None if navigator is None else navigator.active_zone
        if zone is None:
            return None
        return WorldPosition(zone.center_x, zone.center_y, zone.center_z)

    def _poll_live_position(self, at_seconds: float) -> None:
        reader = self._position_reader
        if reader is None:
            return
        if self._live_sampled_at_seconds == at_seconds and self._live_position is not None:
            return
        reading = reader.poll(at_seconds)
        self._position_source = reading.source
        self._position_error_code = None if reading.error is None else reading.error.code
        self._live_position = reading.position
        self._live_sampled_at_seconds = reading.sampled_at_seconds
        if not self.is_gps_available:
            self._block_navigation()

    def _poll_live_camera(self, at_seconds: float) -> None:
        reader = self._camera_reader
        if reader is None:
            return
        # Guarded against this tick's own camera sample, never against the GPS sample: the
        # position is polled first, so comparing against it would suppress every camera read
        # after the first one and freeze the heading (BUG-019).
        if self._camera_state is not None and self._camera_sampled_at_seconds == at_seconds:
            return
        reading = reader.poll(at_seconds)
        self._camera_sampled_at_seconds = reading.sampled_at_seconds or at_seconds
        self._camera_state = reading.state
        self._camera_error_code = None if reading.error is None else reading.error.code
        if reading.state is not None:
            self._heading_degrees = reading.state.yaw_degrees

    def _follow_route(self, at_seconds: float) -> PathingDecision:
        pos = self._live_position
        if pos is None:
            self._block_navigation()
            return PathingDecision(PathingMode.BLOCKED)
        while self._waypoint_index < len(self._world_waypoints):
            target = self._world_waypoints[self._waypoint_index]
            arrival_radius = (
                self._config.navmesh_waypoint_arrival_units
                if self._navmesh_target is not None
                else self._config.navmesh_waypoint_arrival_units * 2.0
            )
            dist = math.hypot(target.x - pos.x, target.z - pos.z)
            if dist > arrival_radius:
                return self._steer(PathingMode.TRAVELING, target.x, target.z)
            self._waypoint_index += 1
        resumed_from_escape = self._recovery.escape_waypoint is not None
        if (
            self._world_waypoints
            and self._navmesh_target is None
            and self._vector_zone is not None
            and not resumed_from_escape
        ):
            self._completed_zone_sweeps += 1
        self._world_waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        if resumed_from_escape:
            # The escape point was reached: resume routing to the original goal instead of
            # idling, so the trap does not simply re-arm on the next tick (US-093).
            self._recovery.reset()
            self._plan(at_seconds)
            if self._world_waypoints:
                return self._follow_route(at_seconds)
        self._mode = PathingMode.IDLE
        return PathingDecision(PathingMode.IDLE)

    def _steer(self, mode: PathingMode, target_x: float, target_z: float) -> PathingDecision:
        pos = self._live_position
        if pos is None:
            return PathingDecision(PathingMode.BLOCKED)
        self._mode = mode
        bearing = bearing_degrees(pos.x, pos.z, target_x, target_z)
        error = heading_error_degrees(self.heading_degrees, bearing)
        if abs(error) > self._config.heading_pivot_threshold_degrees:
            rotation_key = VIRTUAL_KEY_RIGHT if error > 0.0 else VIRTUAL_KEY_LEFT
            return PathingDecision(mode, rotation_key, self._config.turn_duration_seconds)
        if abs(error) > self._config.heading_tolerance_degrees:
            rotation_key = VIRTUAL_KEY_RIGHT if error > 0.0 else VIRTUAL_KEY_LEFT
            return PathingDecision(
                mode,
                key_press_duration_seconds=self._config.turn_duration_seconds,
                virtual_keys=(VIRTUAL_KEY_W, rotation_key),
            )
        return PathingDecision(mode, VIRTUAL_KEY_W, self._config.step_duration_seconds)

    def _needs_route(self, at_seconds: float) -> bool:
        if not self._world_waypoints or self._planned_at_seconds is None:
            return True
        return at_seconds - self._planned_at_seconds >= self._config.replan_interval_seconds

    def _plan(self, at_seconds: float) -> None:
        if self._plan_navmesh_target_route(at_seconds):
            return
        if self._plan_vector_route(at_seconds):
            return
        # Nothing could be routed: abandon recovery so a stuck route can never latch the
        # controller into a permanent recovering state (US-093).
        self._recovery.reset()
        self._world_waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.IDLE

    def _plan_navmesh_target_route(self, at_seconds: float) -> bool:
        target = self._navmesh_target
        start = self._live_position
        mesh = self._navmesh
        if target is None:
            return False
        if start is None or mesh is None:
            self.cancel_target_approach()
            return True
        previous_target = self._planned_attack_target
        if previous_target is not None and previous_target != target:
            route = mesh.find_path(start, target, obstacles=self._obstacles.circles(at_seconds))
            if not route:
                self.cancel_target_approach()
                return True
            self._world_waypoints = route
            self._waypoint_index = 0
            self._planned_at_seconds = at_seconds
            self._mode = PathingMode.TRAVELING
            return True
        if previous_target is not None and not should_replan_attack_target(previous_target, target):
            return False
        route = self._plan_target_route(start, target)
        if not route:
            self.cancel_target_approach()
            return True
        self._world_waypoints = route
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING
        return True

    def _plan_vector_route(self, at_seconds: float) -> bool:
        navigator = self._vector_navigator
        if navigator is None or not navigator.is_active:
            self._vector_zone = None
            return False
        live = self._live_position
        if not self.is_gps_available or live is None:
            self._block_navigation()
            return True
        selection = navigator.select_world_zone(live)
        if selection is None:
            self._block_navigation()
            return True
        target = WorldPosition(
            selection.zone.center_x,
            selection.zone.center_y,
            selection.zone.center_z,
        )
        dispatch = self._teleport.update(live, target, at_seconds)
        if dispatch is not None:
            self._pending_decision = PathingDecision(
                PathingMode.TELEPORTING,
                dispatch.virtual_key,
                dispatch.duration_seconds,
            )
            self._mode = PathingMode.TELEPORTING
            self._vector_zone = selection.zone
            return True
        if self._teleport.status is TeleportStatus.WAITING_FOR_POSITION:
            self._mode = PathingMode.TELEPORTING
            self._vector_zone = selection.zone
            return True
        if self._recovery.original_goal is None:
            self._recovery.original_goal = target
        if self._recovery.phase is RecoveryPhase.ESCAPE:
            # Repeated local stalls at one spot: hand the trap straight to the geometric
            # escape planner instead of re-planning through the same pocket (US-093).
            if self._plan_escape_route(at_seconds, target):
                return True
            self._block_navigation()
            return True
        active_blocks = self._obstacles.positions(at_seconds)
        plan = navigator.plan_live_route(live, temporary_blocks=active_blocks)
        self._vector_zone = plan.zone
        if plan.is_empty:
            # Every leg of the camp route was refused, which is what standing inside a canyon
            # or a collision pocket looks like from the router. Walking to the nearest
            # reachable mesh node first is what turns that dead end back into a route
            # (US-093).
            if self._plan_escape_route(at_seconds, target):
                return True
            self._block_navigation()
            return True
        self._world_waypoints = plan.world_waypoints
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING
        if self._recovery.phase is RecoveryPhase.LOCAL_REPLAN:
            self._queue_recovery_event(RecoveryEventKind.LOCAL_REPLAN_SUCCEEDED, live, at_seconds)
            self._recovery.phase = RecoveryPhase.NONE
        return True

    def _plan_escape_route(self, at_seconds: float, destination: WorldPosition) -> bool:
        """Route to a verified walkable NavMesh point that makes progress towards the goal.

        Candidate points are sampled on concentric radial rings, projected onto the mesh,
        and kept only when they clear the slope limit, stand clear of every recorded
        obstacle, and shorten the distance to the goal; the best-scoring one becomes a
        temporary waypoint routed through the standard steering pipeline (US-093).
        """

        mesh = self._navmesh
        live = self._live_position
        if mesh is None or live is None or not mesh.polygons:
            return False
        candidates = plan_escape_candidates(
            mesh=mesh,
            live=live,
            goal=destination,
            obstacles=self._obstacles.circles(at_seconds),
        )
        chosen = select_escape(candidates)
        if chosen is None:
            self._queue_recovery_event(RecoveryEventKind.ESCAPE_PLAN_FAILED, live, at_seconds)
            return False
        self._world_waypoints = chosen.route
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING
        self._recovery.phase = RecoveryPhase.ESCAPE
        self._recovery.escape_waypoint = chosen.position
        if self._recovery.original_goal is None:
            self._recovery.original_goal = destination
        self._queue_recovery_event(
            RecoveryEventKind.ESCAPE_PLAN_SUCCEEDED, chosen.position, at_seconds
        )
        return True


def _pathing_config_with_parameters(
    config: PathingConfig, parameters: TacticalParameterSpace
) -> PathingConfig:
    stall = config.stall
    return replace(
        config,
        heading_tolerance_degrees=parameters.heading_tolerance_degrees,
        heading_pivot_threshold_degrees=parameters.heading_pivot_threshold_degrees,
        replan_interval_seconds=parameters.replan_interval_seconds,
        navmesh_waypoint_arrival_units=parameters.navmesh_waypoint_arrival_units,
        navmesh_engagement_distance_units=parameters.engagement_distance_units,
        stall=StallConfig(
            live_motion_threshold_units_per_second=(stall.live_motion_threshold_units_per_second),
            live_stall_timeout_seconds=parameters.stall_timeout_seconds,
            motion_threshold=stall.motion_threshold,
            stall_timeout_seconds=parameters.stall_timeout_seconds,
            movement_grace_seconds=stall.movement_grace_seconds,
            sample_stride=stall.sample_stride,
            center_mask_width_fraction=stall.center_mask_width_fraction,
            center_mask_height_fraction=stall.center_mask_height_fraction,
        ),
    )


def _zone_snapshot(zone: VectorSpawnZone) -> VectorZoneSnapshot:
    """Return one bound spawn zone drawn in client world units."""

    return VectorZoneSnapshot(
        monster_name=zone.monster_name or str(zone.monster_id),
        center_x=zone.center_x,
        center_y=zone.center_z,
        half_width_pixels=(zone.maximum_x - zone.minimum_x) / 2.0,
        half_depth_pixels=(zone.maximum_z - zone.minimum_z) / 2.0,
        capacity=zone.capacity,
    )
