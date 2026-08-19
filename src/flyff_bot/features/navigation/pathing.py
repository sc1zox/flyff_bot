"""Reactive pathing controller over the learned spawn heatmap and navigation graph."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.automation.models import Viewport, VisibleMob, WorldState
from flyff_bot.features.navigation.anchoring import (
    AnchorMatchOutcome,
    MapAnchor,
    ProfileAnchorState,
    capture_anchor,
    match_anchor,
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
from flyff_bot.features.navigation.persistence import (
    NavigationProfile,
    load_profile,
    save_profile,
)
from flyff_bot.features.navigation.planning import (
    LeashBound,
    Route,
    RouteConfig,
    RoutePlanner,
)
from flyff_bot.features.navigation.spatial import GridCell, SpatialMap, WorldPoint
from flyff_bot.features.navigation.teleport import (
    TeleportConfig,
    TeleportController,
    TeleportStatus,
)
from flyff_bot.features.navigation.tracking import (
    MovementModel,
    MovementTracker,
    StallConfig,
    StallDetector,
    TrackingConfig,
    TrackingQuality,
    bearing_degrees,
    distance_pixels,
    heading_error_degrees,
)
from flyff_bot.features.navigation.vector_navigation import (
    VectorZoneNavigator,
)
from flyff_bot.features.navigation.world_extractor import VectorSpawnZone, WorldCoordinate
from flyff_bot.features.vision.minimap import (
    MINIMAP_SURFACE_RADIUS_PIXELS,
    MinimapOdometer,
    MinimapOdometryFeed,
    MinimapReading,
)
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.ui.dashboard import (
    CellSnapshot,
    EdgeSnapshot,
    NavigationSnapshot,
    VectorZoneSnapshot,
)

DEFAULT_PATHING_STEP_DURATION_SECONDS = 0.6
# One turn pulse must stay inside the heading tolerance or steering oscillates around the
# target bearing. At the measured 240 deg/s (US-035) the tolerance is reached after 0.104 s,
# so the pulse is held below that.
DEFAULT_PATHING_TURN_DURATION_SECONDS = 0.08
DEFAULT_HEADING_TOLERANCE_DEGREES = 25.0
DEFAULT_REPLAN_INTERVAL_SECONDS = 20.0
# The leash became an enforced planning bound in US-037, so its previous value of 50 was
# re-derived rather than carried over. The camp is defined as the terrain the operator can
# see around the anchor on the minimap, which is the measured usable minimap surface
# (docs/sources/2026-08-18-minimap-odometry-calibration.md). Positions are minimap pixels at
# the anchored zoom level, so the two quantities are already in the same unit.
DEFAULT_LEASH_RADIUS_PIXELS = float(MINIMAP_SURFACE_RADIUS_PIXELS)
ARRIVAL_RADIUS_CELL_FRACTION = 0.5
VIRTUAL_KEY_Q = 0x51
VIRTUAL_KEY_S = 0x53
EVASION_STRAFE_DURATION_SECONDS = 0.25
EVASION_BACKSTEP_DURATION_SECONDS = 0.25
REPEATED_STALL_RADIUS_UNITS = 3.0
TEMPORARY_BLOCK_DURATION_SECONDS = 30.0

# Provisional spawn-distance relation. These are estimates, not measurements: the fitted
# inverse-projection relation of US-037 criterion 1 is blocked on recorded approach
# sequences. They are named here so the estimator carries no bare literals, and they are to
# be replaced by the fit rather than hand-tuned.
PROVISIONAL_HORIZONTAL_HALF_ANGLE_DEGREES = 30.0
PROVISIONAL_NEAREST_SIGHTING_DISTANCE_PIXELS = 15.0
PROVISIONAL_SIGHTING_DISTANCE_SPAN_PIXELS = 35.0


class ProfileLoadOutcome(StrEnum):
    """What loading one navigation profile did, or why it did nothing (US-036)."""

    # The stored landmark was matched, so the map is writable in this session's frame.
    ANCHORED = "anchored"
    # The profile carries no landmark and was loaded read-only.
    UNANCHORED = "unanchored"
    # The landmark could not be matched and the operator accepted a read-only load.
    READ_ONLY = "read_only"
    # The landmark could not be matched. Nothing was loaded; the previous map is intact.
    UNMATCHED = "unmatched"
    # The profile was recorded at another minimap scale. Nothing was loaded.
    SCALE_MISMATCH = "scale_mismatch"


@dataclass(frozen=True, slots=True)
class ProfileLoadResult:
    """The outcome of one profile load, with the evidence a refusal has to name."""

    outcome: ProfileLoadOutcome
    stored_zoom_signature: float | None = None
    live_zoom_signature: float | None = None


class PathingMode(StrEnum):
    """The observable phases of learned-route navigation."""

    IDLE = "idle"
    TRAVELING = "traveling"
    RETREATING = "retreating"
    BLOCKED = "blocked"
    TELEPORTING = "teleporting"
    EVADING = "evading"


@dataclass(frozen=True, slots=True)
class PathingDecision:
    """One interruptible movement request, if the current phase wants to move."""

    mode: PathingMode
    virtual_key: int | None = None
    key_press_duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class PathingConfig:
    """Timing, steering tolerance, and sub-model settings for learned pathing."""

    step_duration_seconds: float = DEFAULT_PATHING_STEP_DURATION_SECONDS
    turn_duration_seconds: float = DEFAULT_PATHING_TURN_DURATION_SECONDS
    heading_tolerance_degrees: float = DEFAULT_HEADING_TOLERANCE_DEGREES
    replan_interval_seconds: float = DEFAULT_REPLAN_INTERVAL_SECONDS
    leash_radius_pixels: float = DEFAULT_LEASH_RADIUS_PIXELS
    movement: MovementModel = field(default_factory=MovementModel)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    stall: StallConfig = field(default_factory=StallConfig)
    route: RouteConfig = field(default_factory=RouteConfig)

    def __post_init__(self) -> None:
        if self.step_duration_seconds <= 0.0 or self.turn_duration_seconds <= 0.0:
            raise ValueError("Pathing step durations must be positive.")
        if not 0.0 < self.heading_tolerance_degrees < 180.0:
            raise ValueError("Pathing heading tolerance must be between 0 and 180 degrees.")
        if self.replan_interval_seconds <= 0.0:
            raise ValueError("Pathing replan interval must be positive.")
        if self.leash_radius_pixels <= 0.0:
            raise ValueError("Pathing leash radius must be positive.")


class PathingController:
    """Learn spawn density and traversals, then steer along the best learned route."""

    def __init__(
        self,
        spatial_map: SpatialMap | None = None,
        *,
        config: PathingConfig | None = None,
        map_path: Path | None = None,
        odometer: MinimapOdometryFeed | None = None,
        vector_navigator: VectorZoneNavigator | None = None,
        position_reader: LivePositionReader | None = None,
        camera_reader: LiveCameraReader | None = None,
        teleport_config: TeleportConfig | None = None,
        spawn_point: WorldPoint | None = None,
    ) -> None:
        self._config = config or PathingConfig()
        self._map = spatial_map or SpatialMap()
        self._planner = RoutePlanner(self._map, self._config.route)
        self._tracker = MovementTracker(self._config.movement, self._config.tracking)
        self._odometer: MinimapOdometryFeed = odometer or MinimapOdometer()
        self._stalls = StallDetector(self._config.stall)
        self._map_path = map_path
        self._vector_navigator = vector_navigator
        self._position_reader = position_reader
        self._camera_reader = camera_reader
        self._position_source = PositionSource.MINIMAP_FALLBACK
        self._position_error_code: PositionReadErrorCode | None = None
        self._live_position: WorldPosition | None = None
        self._live_sampled_at_seconds: float | None = None
        self._camera_state: CameraState | None = None
        self._camera_error_code: CameraReadErrorCode | None = None
        self._world_waypoints: tuple[WorldPosition, ...] = ()
        self._route_uses_live_position = False
        self._teleport = TeleportController(teleport_config)
        self._pending_decision: PathingDecision | None = None
        self._evasion_steps: list[PathingDecision] = []
        self._last_live_stall: WorldPosition | None = None
        self._tangent_block: WorldPosition | None = None
        self._temporary_blocks: list[tuple[WorldPosition, float]] = []
        self._vector_zone: VectorSpawnZone | None = None
        self._mode = PathingMode.IDLE
        self._waypoints: tuple[WorldPoint, ...] = ()
        self._waypoint_index = 0
        self._planned_at_seconds: float | None = None
        self._safe_waypoint: WorldPoint | None = None
        self._safe_cell: GridCell | None = None
        self._avoided: frozenset[GridCell] = frozenset()
        self._movement_commanded = False
        self._stalled = False
        self._measured_speed_pixels_per_second: float | None = None
        self._anchor_candidate: MapAnchor | None = None
        self._anchor_state = ProfileAnchorState.SESSION
        self._map_read_only = False
        # The single leash value: both the enforced planning bound and the inspector circle
        # read it, so the drawing cannot describe a radius the planner does not apply.
        self._leash_radius_pixels = self._config.leash_radius_pixels
        self._hotspots_outside_leash = 0
        # The town or respawn anchor an emergency teleport arrives at. It belongs to the
        # map rather than to the session, so it travels with the profile (US-040).
        self._spawn_point = spawn_point

    @property
    def leash_radius_pixels(self) -> float:
        """Return the patrol radius around the session anchor that planning is bound to."""

        return self._leash_radius_pixels

    @leash_radius_pixels.setter
    def leash_radius_pixels(self, radius_pixels: float) -> None:
        """Set the patrol radius; the next replan applies it without restarting the session."""

        if radius_pixels <= 0.0:
            raise ValueError("Pathing leash radius must be positive.")
        self._leash_radius_pixels = radius_pixels

    @property
    def mode(self) -> PathingMode:
        """Return the current pathing phase."""

        return self._mode

    @property
    def spatial_map(self) -> SpatialMap:
        """Return the learned map so a session can inspect or persist it."""

        return self._map

    @property
    def position(self) -> WorldPoint:
        """Return the current position estimate."""

        if self._live_position is not None:
            return WorldPoint(self._live_position.x, self._live_position.z)
        return self._tracker.position

    @property
    def position_source(self) -> PositionSource:
        """Return whether pathing is anchored by live GPS or minimap fallback."""

        return self._position_source

    @property
    def position_error_code(self) -> PositionReadErrorCode | None:
        """Return the current reason live GPS is unavailable, if any."""

        return self._position_error_code

    @property
    def live_position(self) -> WorldPosition | None:
        """Return the newest drift-free client coordinate, when available."""

        return self._live_position

    @property
    def live_sampled_at_seconds(self) -> float | None:
        """Return when the newest live coordinate was actually sampled."""

        return self._live_sampled_at_seconds

    @property
    def world_waypoints(self) -> tuple[WorldPosition, ...]:
        """Return the remaining authoritative terrain-A* waypoints, if a live route exists."""

        return self._world_waypoints[self._waypoint_index :]

    @property
    def terrain_slope(self) -> float | None:
        """Return the US-052 heightfield gradient at the latest live coordinate."""

        navigator = self._vector_navigator
        position = self._live_position
        if navigator is None or position is None:
            return None
        return navigator.world_map.terrain.gradient_at(WorldCoordinate(position.x, position.z))

    @property
    def has_pending_evasion(self) -> bool:
        """Return whether a live collision queued local strafe/backstep recovery."""

        return bool(self._evasion_steps)

    @property
    def temporary_world_blocks(self) -> tuple[WorldPosition, ...]:
        """Return repeated-stall nodes currently excluded from global terrain replans."""

        return tuple(item[0] for item in self._temporary_blocks)

    @property
    def tracking_quality(self) -> TrackingQuality:
        """Return how the current position estimate was obtained."""

        return self._tracker.quality

    @property
    def profile_anchor_state(self) -> ProfileAnchorState:
        """Return how the active map relates to the frame its coordinates were recorded in."""

        return self._anchor_state

    @property
    def map_is_read_only(self) -> bool:
        """Return whether learning is suspended because the map frame is unverified."""

        return self._map_read_only

    @property
    def is_stalled(self) -> bool:
        """Return the stall verdict of the most recent observation."""

        return self._stalled

    @property
    def measured_speed_pixels_per_second(self) -> float | None:
        """Return the speed of the most recent minimap measurement, if there was one.

        A session that has to judge motion outside pathing - the combat approach the game
        client drives after a target click (US-039) - prefers this measurement over the
        peripheral frame difference, which is only the fallback.
        """

        return self._measured_speed_pixels_per_second

    @property
    def safe_waypoint(self) -> WorldPoint | None:
        """Return the last verified stall-free waypoint behind the current cell."""

        return self._safe_waypoint

    @property
    def waypoints(self) -> tuple[WorldPoint, ...]:
        """Return the points of the current route that are still to be reached."""

        return self._waypoints[self._waypoint_index :]

    @property
    def spawn_point(self) -> WorldPoint | None:
        """Return the mapped town or respawn anchor of the active map, if one is set."""

        return self._spawn_point

    def set_spawn_point(self, point: WorldPoint | None) -> None:
        """Mark, move, or clear the spawn anchor an emergency teleport arrives at."""

        self._spawn_point = point

    def mark_spawn_point_here(self) -> WorldPoint | None:
        """Mark the current position as the spawn anchor and return what was stored.

        A position that is not currently measured is no place, so nothing is marked and
        the previously mapped anchor - if any - stays untouched.
        """

        if self._tracker.quality is TrackingQuality.DEGRADED:
            return None
        self._spawn_point = self._tracker.position
        return self._spawn_point

    @property
    def vector_navigator(self) -> VectorZoneNavigator | None:
        """Return the goal-driven vector navigator, when an extracted map is loaded."""

        return self._vector_navigator

    @property
    def vector_navigation_active(self) -> bool:
        """Return whether an extracted world map is steering this session (US-045)."""

        return self._vector_navigator is not None and self._vector_navigator.is_active

    @property
    def vector_navigation_gps_unavailable(self) -> bool:
        """Return whether active vector navigation is blocked solely by missing live GPS."""

        return self._vector_navigation_requires_gps()

    def attach_vector_navigator(self, navigator: VectorZoneNavigator | None) -> None:
        """Adopt or drop the extracted-map navigator and force a replan on the next step."""

        self._vector_navigator = navigator
        self._vector_zone = None
        self._waypoints = ()
        self._world_waypoints = ()
        self._route_uses_live_position = False
        self._waypoint_index = 0
        self._planned_at_seconds = None

    def snapshot(self, at_seconds: float = 0.0) -> NavigationSnapshot:
        """Return an immutable snapshot of the current navigation and map state."""

        cells = tuple(
            CellSnapshot(
                x=cell.x,
                y=cell.y,
                center_x=self._map.center_of(cell).x,
                center_y=self._map.center_of(cell).y,
                visits=self._map.visit_count(cell),
                stalls=self._map.stall_count(cell),
                spawn_weight=self._map.spawn_weight(cell, at_seconds),
            )
            for cell in self._map.known_cells()
        )
        edges: list[EdgeSnapshot] = []
        for origin in self._map.known_cells():
            for destination in self._map.neighbors(origin):
                if (origin.x, origin.y) < (destination.x, destination.y):
                    o_pt = self._map.center_of(origin)
                    d_pt = self._map.center_of(destination)
                    edges.append(
                        EdgeSnapshot(
                            origin_x=o_pt.x,
                            origin_y=o_pt.y,
                            destination_x=d_pt.x,
                            destination_y=d_pt.y,
                            stalls=self._map.edge_stall_count(origin, destination),
                        )
                    )
        waypoints = tuple((point.x, point.y) for point in self._waypoints[self._waypoint_index :])
        safe = (
            (self._safe_waypoint.x, self._safe_waypoint.y)
            if self._safe_waypoint is not None
            else None
        )
        zone = self._vector_zone
        vector_zone = (
            None if zone is None or self._vector_navigator is None else _zone_snapshot(zone)
        )
        spawn = None if self._spawn_point is None else (self._spawn_point.x, self._spawn_point.y)
        return NavigationSnapshot(
            player_x=self.position.x,
            player_y=self.position.y,
            heading_degrees=self._tracker.heading_degrees,
            cells=cells,
            edges=tuple(edges),
            waypoints=waypoints,
            safe_waypoint=safe,
            cell_size_pixels=self._map.config.cell_size_pixels,
            leash_radius_pixels=self._leash_radius_pixels,
            hotspots_outside_leash=self._hotspots_outside_leash,
            tracking_quality=self._tracker.quality,
            zoom_signature_anchor=self._tracker.zoom_signature_anchor,
            profile_anchor_state=self._anchor_state,
            vector_zone=vector_zone,
            position_source=self._position_source,
            position_error_code=self._position_error_code,
            world_position=self._live_position,
            camera_state=self._camera_state,
            camera_error_code=self._camera_error_code,
            world_waypoints=self._world_waypoints,
            terrain_samples=(
                () if self._vector_navigator is None else self._vector_navigator.terrain_samples
            ),
            spawn_point=spawn,
        )

    def track(self, state: WorldState, frame: CapturedFrame | None = None) -> TrackingQuality:
        """Update the measured position estimate without writing anything to the map.

        This is the standby path: it follows motion the operator produces by hand while the
        session is paused, and it dispatches no input of any kind.
        """

        reading: MinimapReading | None = self._odometer.observe(frame)
        update = self._tracker.observe(reading, state.observed_at_seconds)
        self._measured_speed_pixels_per_second = update.measured_speed_pixels_per_second
        self._poll_live_position(state.observed_at_seconds)
        self._poll_live_camera(state.observed_at_seconds)
        if reading is not None and update.quality is TrackingQuality.MEASURED:
            # The freshest confidently measured disk is both what a save stores as the
            # profile's landmark and what a load matches a stored landmark against, so
            # standby tracking alone keeps anchoring possible while the session is paused.
            self._anchor_candidate = capture_anchor(
                reading, self._tracker.position, self._tracker.heading_degrees
            )
        return update.quality

    def observe(self, state: WorldState, frame: CapturedFrame | None = None) -> None:
        """Record visit history, spawn sightings, and stall evidence for one tick."""

        at_seconds = state.observed_at_seconds
        quality = self.track(state, frame)
        position = self._tracker.position
        stalled = self._stalls.observe(
            frame,
            measured_speed_pixels_per_second=self._measured_speed_pixels_per_second,
            movement_commanded=self._movement_commanded,
            at_seconds=at_seconds,
            live_position=self._live_position,
            live_sampled_at_seconds=self._live_sampled_at_seconds,
        )
        self._movement_commanded = False
        if self._map_read_only or (
            quality is TrackingQuality.DEGRADED and self._live_position is None
        ):
            # The map stays read-only while the position is unknown, and equally while a
            # loaded profile could not be re-anchored (US-036): routes may still be followed
            # or abandoned, but nothing new is learned, and the trail is broken so recovery
            # cannot link an edge across the unobserved span. Stall-driven retreat needs the
            # map to record the obstacle, so it stays off on this path too.
            self._map.break_trail()
            self._stalled = stalled
            return
        cell = self._map.record_visit(position, at_seconds)
        if not self.vector_navigation_active:
            # The spawn heatmap is the heuristic that decides *where to explore*. An
            # extracted map already states where the spawns are, so accumulating estimated
            # sightings on top of it would only compete with authoritative geometry
            # (US-045). Visit and stall history keep being written either way: they are what
            # the retreat and the dynamic obstacle safety net read.
            for mob in state.visible_mobs:
                mob_point = self._estimate_mob_position(
                    position, self._tracker.heading_degrees, mob, state.viewport
                )
                if mob_point is None:
                    continue
                self._map.record_spawn(mob_point, at_seconds)
        if stalled and self._mode not in {
            PathingMode.RETREATING,
            PathingMode.BLOCKED,
            PathingMode.EVADING,
        }:
            if self._live_position is not None:
                self._register_live_stall(self._live_position, at_seconds)
            else:
                self._register_stall(position, at_seconds)
        elif not stalled and self._map.stall_count(cell) == 0:
            self._remember_safe_waypoint(cell, position)
        self._stalled = stalled

    def register_obstacle(self, at_seconds: float) -> bool:
        """Record an externally detected obstacle at the current position (US-039).

        The combat approach is walked by the game client, so a stall against terrain during
        it never reaches :meth:`observe`. Registering it here penalizes the blocked cell and
        the edge that reached it exactly like a stall found while pathing itself steered.
        Returns whether the evidence could be written: an unknown or read-only position is
        no place, so nothing is learned from it.
        """

        if self._mode in {PathingMode.RETREATING, PathingMode.BLOCKED}:
            return False
        if self._live_position is not None:
            # A supported client supplies an exact current coordinate, so use the same
            # bounded strafe/backstep and tangent replan as a live stall detected while
            # pathing itself was steering. Keep the prior learned-map penalty too when
            # its minimap estimate is trustworthy; live recovery still works while that
            # map is read-only.
            if not self._map_read_only and self._tracker.quality is not TrackingQuality.DEGRADED:
                cell = self._map.record_stall(self._tracker.position, at_seconds)
                self._avoided = self._avoided | {cell}
            self._register_live_stall(self._live_position, at_seconds)
            self._stalled = True
            return True
        if self._map_read_only or self._tracker.quality is TrackingQuality.DEGRADED:
            return False
        self._register_stall(self._tracker.position, at_seconds)
        self._stalled = True
        return True

    def begin_teleport_recovery(self, at_seconds: float) -> bool:
        """Blame the place an emergency teleport is escaping from and drop the route (US-040).

        The character is about to leave this position by teleport rather than by walking,
        so the cell is penalized exactly like a stall found while pathing steered itself -
        otherwise the next route planned from the spawn anchor would lead straight back off
        the same ledge. The retreat is deliberately not started: there is nothing to retreat
        to once the teleport has moved the character to another part of the map.

        Returns whether the evidence could be written: an unknown or read-only position is
        no place, so nothing is learned from it.
        """

        self._waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._mode = PathingMode.IDLE
        if self._map_read_only or self._tracker.quality is TrackingQuality.DEGRADED:
            return False
        cell = self._map.record_stall(self._tracker.position, at_seconds)
        self._avoided = self._avoided | {cell}
        return True

    def complete_teleport_recovery(self) -> WorldPoint:
        """Re-anchor the position estimate at the mapped spawn point and return it (US-040).

        A teleport moves the character instantly, so every estimate measured before it is
        about somewhere else. The map's own spawn anchor is where the character now stands;
        without a mapped one the session origin is the only defensible answer.
        """

        destination = self._spawn_point or WorldPoint(0.0, 0.0)
        self._tracker.relocate(destination)
        self._odometer.reset()
        self._stalls.reset()
        # The trail is broken so the traversal graph never invents an edge across a jump
        # the character did not walk.
        self._map.break_trail()
        self._safe_waypoint = None
        self._safe_cell = None
        self._movement_commanded = False
        self._stalled = False
        self._measured_speed_pixels_per_second = None
        self._anchor_candidate = None
        self._mode = PathingMode.IDLE
        return destination

    def record_kill(self, monster_name: str) -> bool:
        """Attribute one confirmed kill to the vector goals and report a completed quota.

        A completed quota drops the current route so the next step plans into the next
        unfinished monster's nearest zone without the session being restarted (US-045).
        """

        navigator = self._vector_navigator
        if navigator is None or not monster_name:
            return False
        if not navigator.record_kill(monster_name):
            return False
        self._waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._vector_zone = None
        self._world_waypoints = ()
        self._route_uses_live_position = False
        return True

    def integrate_movement(self, virtual_key: int, duration_seconds: float) -> None:
        """Integrate an external movement or camera-rotation pulse into the position estimate."""

        if duration_seconds <= 0.0:
            return
        self._tracker.apply(virtual_key, duration_seconds)
        self._movement_commanded = virtual_key in {VIRTUAL_KEY_W, VIRTUAL_KEY_Q, VIRTUAL_KEY_S}

    def step(self, at_seconds: float) -> PathingDecision:
        """Return the next interruptible movement request without dispatching input."""

        self._poll_live_position(at_seconds)
        self._poll_live_camera(at_seconds)
        if self._vector_navigation_requires_gps():
            self._block_vector_navigation()
            return PathingDecision(PathingMode.BLOCKED)
        if self._pending_decision is not None:
            decision = self._pending_decision
            self._pending_decision = None
            return decision
        if self._evasion_steps:
            return self._evasion_steps.pop(0)
        if self._mode is PathingMode.RETREATING:
            return self._retreat(at_seconds)
        if self._needs_route(at_seconds):
            self._plan(at_seconds)
        if self._pending_decision is not None:
            decision = self._pending_decision
            self._pending_decision = None
            return decision
        if not self._waypoints:
            if self._mode in {PathingMode.TELEPORTING, PathingMode.BLOCKED}:
                return PathingDecision(self._mode)
            self._mode = PathingMode.IDLE
            return PathingDecision(PathingMode.IDLE)
        return self._follow_route(at_seconds)

    def confirm(self, decision: PathingDecision) -> None:
        """Fold one successfully dispatched pathing input into the position estimate."""

        if decision.virtual_key is None or decision.key_press_duration_seconds is None:
            return
        if decision.mode is PathingMode.TELEPORTING:
            return
        self.integrate_movement(decision.virtual_key, decision.key_press_duration_seconds)

    def reject(self, decision: PathingDecision) -> None:
        """Return a rejected guarded teleport request to direct ground routing."""

        if decision.mode is not PathingMode.TELEPORTING:
            return
        self._teleport.reject_pending()
        self._mode = PathingMode.IDLE
        self._planned_at_seconds = None

    def emergency_stop(self) -> None:
        """Immediately idle navigation and release its read-only client handle."""

        self._mode = PathingMode.IDLE
        self._waypoints = ()
        self._world_waypoints = ()
        self._pending_decision = None
        self._evasion_steps.clear()
        self._tangent_block = None
        self._temporary_blocks.clear()
        self._movement_commanded = False
        self._route_uses_live_position = False
        self._last_live_stall = None
        self._stalls.reset()
        self._teleport.reset()
        if self._position_reader is not None:
            self._position_reader.close()
        if self._camera_reader is not None:
            self._camera_reader.close()
        self._live_position = None
        self._live_sampled_at_seconds = None
        self._camera_state = None
        self._camera_error_code = None
        self._position_source = PositionSource.MINIMAP_FALLBACK
        self._position_error_code = None

    def close(self) -> None:
        """Release external navigation resources during application teardown."""

        self.emergency_stop()

    def persist(self) -> None:
        """Write the learned map to its configured location, if one was provided."""

        self.save_map()

    def load_map(self, path: Path, *, accept_unmatched: bool = False) -> ProfileLoadResult:
        """Re-anchor a persisted profile to where the character stands, or refuse it.

        A profile's coordinates only mean a place while they are read in the frame they were
        recorded in, so loading is a decision rather than a file read (US-036). Without a
        usable landmark match nothing is loaded and the active map stays intact, unless the
        operator has explicitly accepted a read-only load through `accept_unmatched`.
        """

        profile = load_profile(path, self._map.config)
        if profile.anchor is None:
            self._adopt(profile, path, ProfileAnchorState.UNANCHORED, read_only=True)
            return ProfileLoadResult(ProfileLoadOutcome.UNANCHORED)

        # Matching needs a live landmark. Standby tracking supplies one every tick the
        # minimap is readable, so its absence means there is nothing to match against.
        candidate = self._anchor_candidate
        if candidate is not None:
            match = match_anchor(profile.anchor, candidate.surface, candidate.zoom_signature)
            if match.outcome is AnchorMatchOutcome.SCALE_MISMATCH:
                return ProfileLoadResult(
                    ProfileLoadOutcome.SCALE_MISMATCH,
                    stored_zoom_signature=match.stored_zoom_signature,
                    live_zoom_signature=match.live_zoom_signature,
                )
            if match.position is not None:
                # The landmark was captured a moment before the load, so whatever the
                # character covered since then is added on top. Both frames share rotation
                # and scale, which makes that live displacement the same vector in the
                # profile's frame.
                drift_x = self._tracker.position.x - candidate.position.x
                drift_y = self._tracker.position.y - candidate.position.y
                self._adopt(profile, path, ProfileAnchorState.ANCHORED, read_only=False)
                self._tracker.relocate(
                    WorldPoint(match.position.x + drift_x, match.position.y + drift_y)
                )
                return ProfileLoadResult(ProfileLoadOutcome.ANCHORED)

        if not accept_unmatched:
            return ProfileLoadResult(ProfileLoadOutcome.UNMATCHED)
        self._adopt(profile, path, ProfileAnchorState.READ_ONLY, read_only=True)
        return ProfileLoadResult(ProfileLoadOutcome.READ_ONLY)

    def save_map(self, path: Path | None = None) -> ProfileAnchorState:
        """Save the active map and its landmark, and report what a later load will get.

        A read-only map is never written back: its coordinates are offset from the profile's
        frame by an unknown amount, so persisting them would corrupt the very profile the
        session failed to re-anchor to.
        """

        target_path = path or self._map_path
        if self._map_read_only or target_path is None:
            return self._anchor_state
        anchor = (
            self._anchor_candidate
            if self._tracker.quality is not TrackingQuality.DEGRADED
            else None
        )
        self._map_path = target_path
        save_profile(NavigationProfile(self._map, anchor, self._spawn_point), target_path)
        self._anchor_state = (
            ProfileAnchorState.ANCHORED if anchor is not None else ProfileAnchorState.UNANCHORED
        )
        return self._anchor_state

    def _adopt(
        self,
        profile: NavigationProfile,
        path: Path,
        anchor_state: ProfileAnchorState,
        *,
        read_only: bool,
    ) -> None:
        """Make one loaded profile the active map and reset every derived session state."""

        self._map = profile.spatial_map
        self._planner = RoutePlanner(self._map, self._config.route)
        self._map_path = path
        self._anchor_state = anchor_state
        self._map_read_only = read_only
        self._reset_state()
        self._spawn_point = profile.spawn_point

    def reset(self) -> None:
        """Clear all learned cells, routes, measured positions, and the spawn anchor."""

        self._map = SpatialMap(self._map.config)
        self._planner = RoutePlanner(self._map, self._config.route)
        self._anchor_state = ProfileAnchorState.SESSION
        self._map_read_only = False
        self._reset_state()
        self._spawn_point = None

    def _reset_state(self) -> None:
        self._tracker.reset()
        self._odometer.reset()
        self._stalls.reset()
        self._mode = PathingMode.IDLE
        self._waypoints = ()
        self._world_waypoints = ()
        self._route_uses_live_position = False
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._safe_waypoint = None
        self._safe_cell = None
        self._avoided = frozenset()
        self._movement_commanded = False
        self._stalled = False
        self._measured_speed_pixels_per_second = None
        self._anchor_candidate = None
        self._vector_zone = None
        self._pending_decision = None
        self._evasion_steps.clear()
        self._temporary_blocks.clear()
        self._last_live_stall = None
        self._tangent_block = None
        self._teleport.reset()
        # The leash radius is operator configuration rather than learned state, so it
        # deliberately survives a map reset or profile load.
        self._hotspots_outside_leash = 0

    def _estimate_mob_position(
        self,
        player_pos: WorldPoint,
        heading_degrees: float,
        mob: VisibleMob,
        viewport: Viewport | None,
    ) -> WorldPoint | None:
        """Place one sighting on the map, or return ``None`` if it cannot be placed.

        Without the client dimensions a bounding box carries no bearing and no distance, so
        the sighting is dropped instead of being parked at a fixed distance ahead: an
        unplaceable sighting contributes nothing but noise to the heatmap (US-037).
        """

        if viewport is None or viewport.width <= 0 or viewport.height <= 0:
            return None

        screen_cx = viewport.width / 2.0
        mob_cx = mob.x + mob.width / 2.0
        rel_x = max(-1.0, min(1.0, (mob_cx - screen_cx) / screen_cx))
        bearing = (heading_degrees + rel_x * PROVISIONAL_HORIZONTAL_HALF_ANGLE_DEGREES) % 360.0

        mob_bottom = mob.y + mob.height
        dist_factor = max(0.0, min(1.0, 1.0 - (mob_bottom / viewport.height)))
        distance = (
            PROVISIONAL_NEAREST_SIGHTING_DISTANCE_PIXELS
            + dist_factor * PROVISIONAL_SIGHTING_DISTANCE_SPAN_PIXELS
        )

        rad = math.radians(bearing)
        return WorldPoint(
            player_pos.x + math.sin(rad) * distance,
            player_pos.y + math.cos(rad) * distance,
        )

    def _remember_safe_waypoint(self, cell: GridCell, position: WorldPoint) -> None:
        """Keep the cell behind the current one as the verified retreat target."""

        if cell == self._safe_cell:
            return
        previous = self._safe_cell
        if previous is not None and self._map.stall_count(previous) > 0:
            # Retreating into the cell a stall was registered in would walk straight back into the
            # obstacle, so the older verified waypoint is kept instead.
            self._safe_cell = cell
            return
        self._safe_waypoint = position if previous is None else self._map.center_of(previous)
        self._safe_cell = cell

    def _register_stall(self, position: WorldPoint, at_seconds: float) -> None:
        cell = self._map.record_stall(position, at_seconds)
        self._avoided = self._avoided | {cell}
        self._waypoints = ()
        self._waypoint_index = 0
        self._mode = PathingMode.RETREATING
        # The accumulated stall evidence has been consumed by this registration. Clearing it keeps
        # the movement grace from carrying the verdict through the turn ticks of the retreat, which
        # would otherwise hold `WorldState.is_stuck` true for the whole recovery.
        self._stalls.reset()

    def _register_live_stall(self, position: WorldPosition, at_seconds: float) -> None:
        """Run bounded evasion and escalate repeated coordinates into a temporary A* block."""

        previous = self._last_live_stall
        if previous is not None and previous.distance_to(position) <= REPEATED_STALL_RADIUS_UNITS:
            self._temporary_blocks.append((position, at_seconds + TEMPORARY_BLOCK_DURATION_SECONDS))
        self._last_live_stall = position
        self._tangent_block = position
        self._waypoints = ()
        self._world_waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._mode = PathingMode.EVADING
        self._evasion_steps = [
            PathingDecision(PathingMode.EVADING, VIRTUAL_KEY_Q, EVASION_STRAFE_DURATION_SECONDS),
            PathingDecision(PathingMode.EVADING, VIRTUAL_KEY_S, EVASION_BACKSTEP_DURATION_SECONDS),
        ]
        self._stalls.reset()

    def _poll_live_position(self, at_seconds: float) -> None:
        reader = self._position_reader
        if reader is None:
            return
        had_live_position = self._live_position is not None
        reading = reader.poll(at_seconds)
        self._position_source = reading.source
        self._position_error_code = None if reading.error is None else reading.error.code
        self._live_position = reading.position
        self._live_sampled_at_seconds = reading.sampled_at_seconds
        if had_live_position and reading.position is None and self._route_uses_live_position:
            self._waypoints = ()
            self._world_waypoints = ()
            self._waypoint_index = 0
            self._planned_at_seconds = None
            self._route_uses_live_position = False
        if self._vector_navigation_requires_gps():
            self._block_vector_navigation()

    def _poll_live_camera(self, at_seconds: float) -> None:
        reader = self._camera_reader
        if reader is None:
            return
        reading = reader.poll(at_seconds)
        self._camera_state = reading.state
        self._camera_error_code = None if reading.error is None else reading.error.code

    def mark_gps_offline(self, error_code: PositionReadErrorCode) -> None:
        """Expose a foreground-loss GPS failure without retaining a stale live position."""

        if self._position_reader is not None:
            self._position_reader.close()
        self._position_source = PositionSource.MINIMAP_FALLBACK
        self._position_error_code = error_code
        self._live_position = None
        self._live_sampled_at_seconds = None
        if self.vector_navigation_active:
            self._block_vector_navigation()

    def _vector_navigation_requires_gps(self) -> bool:
        return self.vector_navigation_active and (
            self._position_source is not PositionSource.LIVE or self._live_position is None
        )

    def _block_vector_navigation(self) -> None:
        """Clear every vector action so unavailable GPS can never dispatch movement."""

        self._waypoints = ()
        self._world_waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._pending_decision = None
        self._evasion_steps.clear()
        self._movement_commanded = False
        self._route_uses_live_position = False
        self._mode = PathingMode.BLOCKED

    def _retreat(self, at_seconds: float) -> PathingDecision:
        target = self._safe_waypoint
        if target is None:
            self._mode = PathingMode.BLOCKED
            return PathingDecision(PathingMode.BLOCKED)
        if distance_pixels(self._tracker.position, target) <= self._arrival_radius:
            self._stalls.reset()
            self._plan(at_seconds)
            if not self._waypoints:
                self._mode = PathingMode.IDLE
                return PathingDecision(PathingMode.IDLE)
            return self._follow_route(at_seconds)
        return self._steer(PathingMode.RETREATING, target)

    def _follow_route(self, at_seconds: float) -> PathingDecision:
        while self._waypoint_index < len(self._waypoints):
            target = self._waypoints[self._waypoint_index]
            if distance_pixels(self._navigation_position, target) > self._arrival_radius:
                return self._steer(PathingMode.TRAVELING, target)
            self._waypoint_index += 1
        self._waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._world_waypoints = ()
        self._route_uses_live_position = False
        self._mode = PathingMode.IDLE
        return PathingDecision(PathingMode.IDLE)

    def _steer(self, mode: PathingMode, target: WorldPoint) -> PathingDecision:
        self._mode = mode
        error = heading_error_degrees(
            self._tracker.heading_degrees, bearing_degrees(self._navigation_position, target)
        )
        if abs(error) > self._config.heading_tolerance_degrees:
            rotation_key = VIRTUAL_KEY_RIGHT if error > 0.0 else VIRTUAL_KEY_LEFT
            return PathingDecision(mode, rotation_key, self._config.turn_duration_seconds)
        return PathingDecision(mode, VIRTUAL_KEY_W, self._config.step_duration_seconds)

    def _needs_route(self, at_seconds: float) -> bool:
        if not self._waypoints or self._planned_at_seconds is None:
            return True
        return at_seconds - self._planned_at_seconds >= self._config.replan_interval_seconds

    def _plan(self, at_seconds: float) -> None:
        if self._plan_vector_route(at_seconds):
            return
        start = self._map.cell_of(self._tracker.position)
        leash = LeashBound(self._leash_radius_pixels)
        self._hotspots_outside_leash = self._planner.hotspots_outside(at_seconds, leash)
        route: Route
        if not leash.contains(self._map.center_of(start)):
            # Outside the camp the only useful route is the one that leads back into it.
            # Containment is judged on the cell centre here exactly as it is for every other
            # cell, so a start cell that still counts as inside can never plan a route to
            # itself and stall the session.
            route = self._planner.return_route(start, leash, avoided=self._avoided)
        else:
            route = self._planner.circuit(start, at_seconds, avoided=self._avoided, leash=leash)
            if route.is_empty:
                route = self._planner.best_spawn_route(
                    start, at_seconds, avoided=self._avoided, leash=leash
                )
        self._waypoints = tuple(self._map.center_of(cell) for cell in route.waypoints)
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING if self._waypoints else PathingMode.IDLE
        self._route_uses_live_position = False
        self._world_waypoints = ()

    def _plan_vector_route(self, at_seconds: float) -> bool:
        """Plan over the extracted map only when an authoritative GPS coordinate exists."""

        navigator = self._vector_navigator
        if navigator is None or not navigator.is_active:
            self._vector_zone = None
            return False
        live = self._live_position
        if self._position_source is not PositionSource.LIVE or live is None:
            self._block_vector_navigation()
            return True
        selection = navigator.select_world_zone(live)
        if selection is None:
            self._block_vector_navigation()
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
        self._temporary_blocks = [item for item in self._temporary_blocks if item[1] > at_seconds]
        plan = navigator.plan_live_route(
            live,
            temporary_blocks=(
                tuple(item[0] for item in self._temporary_blocks)
                + (() if self._tangent_block is None else (self._tangent_block,))
            ),
        )
        self._tangent_block = None
        self._vector_zone = plan.zone
        if plan.is_empty:
            self._block_vector_navigation()
            return True
        self._waypoints = tuple(WorldPoint(point.x, point.z) for point in plan.points)
        self._world_waypoints = tuple(item.position for item in plan.world_waypoints)
        self._route_uses_live_position = live is not None
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING
        # The leash bounds the heuristic planner around the session anchor; under vector
        # navigation the bound is the spawn zone itself, so nothing is being excluded by it.
        self._hotspots_outside_leash = 0
        return True

    @property
    def _navigation_position(self) -> WorldPoint:
        if self._route_uses_live_position and self._live_position is not None:
            return WorldPoint(self._live_position.x, self._live_position.z)
        return self._tracker.position

    @property
    def _arrival_radius(self) -> float:
        return self._map.config.cell_size_pixels * ARRIVAL_RADIUS_CELL_FRACTION


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
