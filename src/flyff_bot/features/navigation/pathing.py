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
from flyff_bot.features.vision.minimap import (
    MINIMAP_SURFACE_RADIUS_PIXELS,
    MinimapOdometer,
    MinimapOdometryFeed,
    MinimapReading,
)
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.ui.dashboard import CellSnapshot, EdgeSnapshot, NavigationSnapshot

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
    ) -> None:
        self._config = config or PathingConfig()
        self._map = spatial_map or SpatialMap()
        self._planner = RoutePlanner(self._map, self._config.route)
        self._tracker = MovementTracker(self._config.movement, self._config.tracking)
        self._odometer: MinimapOdometryFeed = odometer or MinimapOdometer()
        self._stalls = StallDetector(self._config.stall)
        self._map_path = map_path
        self._mode = PathingMode.IDLE
        self._waypoints: tuple[GridCell, ...] = ()
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

        return self._tracker.position

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
    def waypoints(self) -> tuple[GridCell, ...]:
        """Return the cells of the current route that are still to be reached."""

        return self._waypoints[self._waypoint_index :]

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
        waypoints = tuple(
            (self._map.center_of(cell).x, self._map.center_of(cell).y)
            for cell in self._waypoints[self._waypoint_index :]
        )
        safe = (
            (self._safe_waypoint.x, self._safe_waypoint.y)
            if self._safe_waypoint is not None
            else None
        )
        return NavigationSnapshot(
            player_x=self._tracker.position.x,
            player_y=self._tracker.position.y,
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
        )

    def track(self, state: WorldState, frame: CapturedFrame | None = None) -> TrackingQuality:
        """Update the measured position estimate without writing anything to the map.

        This is the standby path: it follows motion the operator produces by hand while the
        session is paused, and it dispatches no input of any kind.
        """

        reading: MinimapReading | None = self._odometer.observe(frame)
        update = self._tracker.observe(reading, state.observed_at_seconds)
        self._measured_speed_pixels_per_second = update.measured_speed_pixels_per_second
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
        )
        self._movement_commanded = False
        if self._map_read_only or quality is TrackingQuality.DEGRADED:
            # The map stays read-only while the position is unknown, and equally while a
            # loaded profile could not be re-anchored (US-036): routes may still be followed
            # or abandoned, but nothing new is learned, and the trail is broken so recovery
            # cannot link an edge across the unobserved span. Stall-driven retreat needs the
            # map to record the obstacle, so it stays off on this path too.
            self._map.break_trail()
            self._stalled = stalled
            return
        cell = self._map.record_visit(position, at_seconds)
        for mob in state.visible_mobs:
            mob_point = self._estimate_mob_position(
                position, self._tracker.heading_degrees, mob, state.viewport
            )
            if mob_point is None:
                continue
            self._map.record_spawn(mob_point, at_seconds)
        if stalled and self._mode not in {PathingMode.RETREATING, PathingMode.BLOCKED}:
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

        if self._map_read_only or self._tracker.quality is TrackingQuality.DEGRADED:
            return False
        if self._mode in {PathingMode.RETREATING, PathingMode.BLOCKED}:
            return False
        self._register_stall(self._tracker.position, at_seconds)
        self._stalled = True
        return True

    def integrate_movement(self, virtual_key: int, duration_seconds: float) -> None:
        """Integrate an external movement or camera-rotation pulse into the position estimate."""

        if duration_seconds <= 0.0:
            return
        self._tracker.apply(virtual_key, duration_seconds)
        self._movement_commanded = virtual_key == VIRTUAL_KEY_W

    def step(self, at_seconds: float) -> PathingDecision:
        """Return the next interruptible movement request without dispatching input."""

        if self._mode is PathingMode.RETREATING:
            return self._retreat(at_seconds)
        if self._needs_route(at_seconds):
            self._plan(at_seconds)
        if not self._waypoints:
            self._mode = PathingMode.IDLE
            return PathingDecision(PathingMode.IDLE)
        return self._follow_route(at_seconds)

    def confirm(self, decision: PathingDecision) -> None:
        """Fold one successfully dispatched pathing input into the position estimate."""

        if decision.virtual_key is None or decision.key_press_duration_seconds is None:
            return
        self.integrate_movement(decision.virtual_key, decision.key_press_duration_seconds)

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
        save_profile(NavigationProfile(self._map, anchor), target_path)
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

    def reset(self) -> None:
        """Clear all learned cells, routes, and measured positions."""

        self._map = SpatialMap(self._map.config)
        self._planner = RoutePlanner(self._map, self._config.route)
        self._anchor_state = ProfileAnchorState.SESSION
        self._map_read_only = False
        self._reset_state()

    def _reset_state(self) -> None:
        self._tracker.reset()
        self._odometer.reset()
        self._stalls.reset()
        self._mode = PathingMode.IDLE
        self._waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._safe_waypoint = None
        self._safe_cell = None
        self._avoided = frozenset()
        self._movement_commanded = False
        self._stalled = False
        self._measured_speed_pixels_per_second = None
        self._anchor_candidate = None
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
            target = self._map.center_of(self._waypoints[self._waypoint_index])
            if distance_pixels(self._tracker.position, target) > self._arrival_radius:
                return self._steer(PathingMode.TRAVELING, target)
            self._waypoint_index += 1
        self._waypoints = ()
        self._waypoint_index = 0
        self._planned_at_seconds = None
        self._mode = PathingMode.IDLE
        return PathingDecision(PathingMode.IDLE)

    def _steer(self, mode: PathingMode, target: WorldPoint) -> PathingDecision:
        self._mode = mode
        error = heading_error_degrees(
            self._tracker.heading_degrees, bearing_degrees(self._tracker.position, target)
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
        self._waypoints = route.waypoints
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING if self._waypoints else PathingMode.IDLE

    @property
    def _arrival_radius(self) -> float:
        return self._map.config.cell_size_pixels * ARRIVAL_RADIUS_CELL_FRACTION
