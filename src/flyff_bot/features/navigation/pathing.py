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
from flyff_bot.features.navigation.persistence import load_spatial_map, save_spatial_map
from flyff_bot.features.navigation.planning import Route, RouteConfig, RoutePlanner
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
DEFAULT_LEASH_RADIUS_PIXELS = 50.0
ARRIVAL_RADIUS_CELL_FRACTION = 0.5


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
    def is_stalled(self) -> bool:
        """Return the stall verdict of the most recent observation."""

        return self._stalled

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
            leash_radius_pixels=self._config.leash_radius_pixels,
            tracking_quality=self._tracker.quality,
            zoom_signature_anchor=self._tracker.zoom_signature_anchor,
        )

    def track(self, state: WorldState, frame: CapturedFrame | None = None) -> TrackingQuality:
        """Update the measured position estimate without writing anything to the map.

        This is the standby path: it follows motion the operator produces by hand while the
        session is paused, and it dispatches no input of any kind.
        """

        reading: MinimapReading | None = self._odometer.observe(frame)
        update = self._tracker.observe(reading, state.observed_at_seconds)
        self._measured_speed_pixels_per_second = update.measured_speed_pixels_per_second
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
        if quality is TrackingQuality.DEGRADED:
            # The map stays read-only while the position is unknown: routes may still be
            # followed or abandoned, but nothing new is learned, and the trail is broken so
            # recovery cannot link an edge across the unobserved span.
            self._map.break_trail()
            self._stalled = stalled
            return
        cell = self._map.record_visit(position, at_seconds)
        for mob in state.visible_mobs:
            mob_point = self._estimate_mob_position(
                position, self._tracker.heading_degrees, mob, state.viewport
            )
            self._map.record_spawn(mob_point, at_seconds)
        if stalled and self._mode not in {PathingMode.RETREATING, PathingMode.BLOCKED}:
            self._register_stall(position, at_seconds)
        elif not stalled and self._map.stall_count(cell) == 0:
            self._remember_safe_waypoint(cell, position)
        self._stalled = stalled

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

    def load_map(self, path: Path) -> None:
        """Load a persisted map snapshot from disk and reset pathing state."""

        self._map = load_spatial_map(path, self._map.config)
        self._planner = RoutePlanner(self._map, self._config.route)
        self._map_path = path
        self._reset_state()

    def save_map(self, path: Path | None = None) -> None:
        """Save the current spatial map to disk under the specified or configured path."""

        target_path = path or self._map_path
        if target_path is not None:
            self._map_path = target_path
            save_spatial_map(self._map, target_path)

    def reset(self) -> None:
        """Clear all learned cells, routes, and dead-reckoned positions."""

        self._map = SpatialMap(self._map.config)
        self._planner = RoutePlanner(self._map, self._config.route)
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

    def _estimate_mob_position(
        self,
        player_pos: WorldPoint,
        heading_degrees: float,
        mob: VisibleMob,
        viewport: Viewport | None,
    ) -> WorldPoint:
        if viewport is None or viewport.width <= 0 or viewport.height <= 0:
            rad = math.radians(heading_degrees)
            return WorldPoint(
                player_pos.x + math.sin(rad) * 30.0,
                player_pos.y + math.cos(rad) * 30.0,
            )

        screen_cx = viewport.width / 2.0
        mob_cx = mob.x + mob.width / 2.0
        rel_x = max(-1.0, min(1.0, (mob_cx - screen_cx) / screen_cx))
        bearing = (heading_degrees + rel_x * 30.0) % 360.0

        mob_bottom = mob.y + mob.height
        dist_factor = max(0.0, min(1.0, 1.0 - (mob_bottom / viewport.height)))
        distance = 15.0 + dist_factor * 35.0

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
        route: Route = self._planner.circuit(start, at_seconds, avoided=self._avoided)
        if route.is_empty:
            route = self._planner.best_spawn_route(start, at_seconds, avoided=self._avoided)
        self._waypoints = route.waypoints
        self._waypoint_index = 0
        self._planned_at_seconds = at_seconds
        self._mode = PathingMode.TRAVELING if self._waypoints else PathingMode.IDLE

    @property
    def _arrival_radius(self) -> float:
        return self._map.config.cell_size_pixels * ARRIVAL_RADIUS_CELL_FRACTION
