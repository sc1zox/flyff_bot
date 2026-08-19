"""Tests for learned route planning, stuck recovery, and guarded pathing dispatch."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from minimap_doubles import MirrorOdometer

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import FarmingMode, FarmingOrchestrator
from flyff_bot.features.navigation.execution import PathingInputDispatcher
from flyff_bot.features.navigation.pathing import (
    PathingConfig,
    PathingController,
    PathingDecision,
    PathingMode,
)
from flyff_bot.features.navigation.planning import LeashBound, RouteConfig, RoutePlanner
from flyff_bot.features.navigation.spatial import (
    GridCell,
    SpatialMap,
    SpatialMapConfig,
    WorldPoint,
)
from flyff_bot.features.navigation.tracking import MovementModel, StallConfig
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.features.vision.models import CapturedFrame, ClientSize

CELL_SIZE_UNITS = 10.0
WINDOW_HANDLE = 42
MAP_CONFIG = SpatialMapConfig(
    cell_size_pixels=CELL_SIZE_UNITS,
    spawn_half_life_seconds=600.0,
    maximum_link_span_cells=1,
)
PATHING_CONFIG = PathingConfig(
    step_duration_seconds=0.5,
    turn_duration_seconds=0.25,
    heading_tolerance_degrees=25.0,
    movement=MovementModel(
        forward_speed_pixels_per_second=10.0,
        turn_degrees_per_second=90.0,
    ),
    stall=StallConfig(motion_threshold=1.0, stall_timeout_seconds=0.1),
    route=RouteConfig(minimum_hotspot_weight=1.0),
)
REFERENCE_VIEWPORT = Viewport(100, 100)


class _Adapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.keys: list[tuple[int, float]] = []
        self.clicks: list[tuple[int, int, int]] = []
        self.closed_windows: list[int] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def close_window(self, window_handle: int) -> bool:
        self.closed_windows.append(window_handle)
        return True

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        self.keys.append((virtual_key, duration_seconds))


class _Pipeline:
    def __init__(self, states: list[WorldState]) -> None:
        self._states = iter(states)

    def tick(self, _window_handle: int, _previous: WorldState) -> PerceptionTick:
        return PerceptionTick(next(self._states), (), frozenset())


def _frame() -> CapturedFrame:
    return CapturedFrame(np.zeros((32, 32, 3), dtype=np.uint8), ClientSize(32, 32))


def _center(cell: GridCell) -> WorldPoint:
    return WorldPoint((cell.x + 0.5) * CELL_SIZE_UNITS, (cell.y + 0.5) * CELL_SIZE_UNITS)


def _walk(spatial_map: SpatialMap, cells: list[GridCell], at_seconds: float = 0.0) -> None:
    for index, cell in enumerate(cells):
        spatial_map.record_visit(_center(cell), at_seconds + index)


def _state(
    time: float,
    *,
    mobs: tuple[VisibleMob, ...] = (),
    stuck: bool = False,
    viewport: Viewport = REFERENCE_VIEWPORT,
) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        is_stuck=stuck,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=viewport,
    )


def _waypoint_cells(controller: PathingController) -> tuple[GridCell, ...]:
    """Return the grid cells the controller's continuous route still passes through."""

    return tuple(controller.spatial_map.cell_of(point) for point in controller.waypoints)


def _corridor_map() -> SpatialMap:
    """Return a map with a short blocked-prone corridor and a longer detour."""

    spatial_map = SpatialMap(MAP_CONFIG)
    _walk(spatial_map, [GridCell(0, 0), GridCell(1, 0), GridCell(2, 0)])
    _walk(
        spatial_map,
        [GridCell(0, 0), GridCell(0, 1), GridCell(1, 1), GridCell(2, 1), GridCell(2, 0)],
        at_seconds=10.0,
    )
    return spatial_map


def test_route_planning_prefers_the_shortest_recorded_corridor() -> None:
    planner = RoutePlanner(_corridor_map())

    route = planner.plan(GridCell(0, 0), GridCell(2, 0))

    assert route.cells == (GridCell(0, 0), GridCell(1, 0), GridCell(2, 0))
    assert route.cost == pytest.approx(2.0)


def test_repeated_stalls_push_route_planning_onto_the_costlier_detour() -> None:
    spatial_map = _corridor_map()
    planner = RoutePlanner(spatial_map)
    for index in range(3):
        spatial_map.record_visit(_center(GridCell(0, 0)), 20.0 + index)
        spatial_map.record_stall(_center(GridCell(1, 0)), 21.0 + index)

    route = planner.plan(GridCell(0, 0), GridCell(2, 0))

    assert route.cells == (
        GridCell(0, 0),
        GridCell(0, 1),
        GridCell(1, 1),
        GridCell(2, 1),
        GridCell(2, 0),
    )


def test_explicitly_avoided_cells_produce_an_alternative_bypass_route() -> None:
    planner = RoutePlanner(_corridor_map())

    route = planner.plan(GridCell(0, 0), GridCell(2, 0), avoided=frozenset({GridCell(1, 0)}))

    assert GridCell(1, 0) not in route.cells
    assert route.cells[-1] == GridCell(2, 0)


def test_unreachable_goals_yield_an_empty_route() -> None:
    planner = RoutePlanner(_corridor_map())

    assert planner.plan(GridCell(0, 0), GridCell(9, 9)).is_empty


def test_route_selection_prefers_dense_clusters_over_nearer_sparse_ones() -> None:
    spatial_map = _corridor_map()
    spatial_map.record_spawn(_center(GridCell(1, 0)), 0.0)
    for _sighting in range(6):
        spatial_map.record_spawn(_center(GridCell(2, 0)), 0.0)

    route = RoutePlanner(spatial_map).best_spawn_route(GridCell(0, 0), 0.0)

    assert route.cells[-1] == GridCell(2, 0)


def test_circuit_visits_several_clusters_and_returns_to_its_start() -> None:
    spatial_map = _corridor_map()
    for _sighting in range(4):
        spatial_map.record_spawn(_center(GridCell(2, 0)), 0.0)
        spatial_map.record_spawn(_center(GridCell(1, 1)), 0.0)

    circuit = RoutePlanner(spatial_map).circuit(GridCell(0, 0), 0.0)

    assert circuit.cells[0] == GridCell(0, 0)
    assert circuit.cells[-1] == GridCell(0, 0)
    assert {GridCell(2, 0), GridCell(1, 1)} <= set(circuit.cells)


def test_circuit_order_follows_the_current_spawn_density_weights() -> None:
    spatial_map = _corridor_map()
    for _sighting in range(6):
        spatial_map.record_spawn(_center(GridCell(2, 1)), 0.0)
    spatial_map.record_spawn(_center(GridCell(1, 0)), 0.0)
    planner = RoutePlanner(spatial_map)

    first_stop = planner.circuit(GridCell(0, 0), 0.0).cells[1:]

    for _sighting in range(20):
        spatial_map.record_spawn(_center(GridCell(1, 0)), 0.0)
    second_stop = planner.circuit(GridCell(0, 0), 0.0).cells[1:]

    assert first_stop[0] == GridCell(0, 1)
    assert second_stop[0] == GridCell(1, 0)


def test_a_map_without_clusters_plans_no_route() -> None:
    planner = RoutePlanner(_corridor_map())

    assert planner.best_spawn_route(GridCell(0, 0), 0.0).is_empty
    assert planner.circuit(GridCell(0, 0), 0.0).is_empty


def test_invalid_route_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        RouteConfig(minimum_hotspot_weight=0.0)
    with pytest.raises(ValueError):
        RouteConfig(maximum_circuit_stops=0)
    with pytest.raises(ValueError):
        PathingConfig(heading_tolerance_degrees=0.0)


def _hotspot_controller() -> PathingController:
    spatial_map = SpatialMap(MAP_CONFIG)
    _walk(spatial_map, [GridCell(0, 0), GridCell(0, 1), GridCell(0, 2)])
    for _sighting in range(3):
        spatial_map.record_spawn(_center(GridCell(0, 2)), 0.0)
    return PathingController(spatial_map, config=PATHING_CONFIG)


def test_pathing_walks_toward_a_learned_cluster_that_lies_straight_ahead() -> None:
    controller = _hotspot_controller()

    decision = controller.step(0.0)

    assert decision.mode is PathingMode.TRAVELING
    assert decision.virtual_key == VIRTUAL_KEY_W
    assert decision.key_press_duration_seconds == pytest.approx(0.5)


def test_pathing_reaches_the_learned_cluster_and_then_repeats_the_circuit() -> None:
    controller = _hotspot_controller()
    visited: set[GridCell] = set()

    for index in range(60):
        decision = controller.step(float(index) * 0.1)
        if decision.virtual_key is None:
            break
        controller.confirm(decision)
        visited.add(controller.spatial_map.cell_of(controller.position))

    assert GridCell(0, 2) in visited
    assert controller.mode is PathingMode.IDLE
    assert controller.step(6.0).virtual_key is not None


def test_an_unlearned_map_stays_idle_so_staged_search_keeps_control() -> None:
    controller = PathingController(SpatialMap(MAP_CONFIG), config=PATHING_CONFIG)

    decision = controller.step(0.0)

    assert decision.mode is PathingMode.IDLE
    assert decision.virtual_key is None


def _advance(controller: PathingController, odometer: MirrorOdometer, seconds: float) -> None:
    """Dispatch one pathing step and let the client double move accordingly."""

    decision = controller.step(seconds)
    controller.confirm(decision)
    if decision.virtual_key is not None and decision.key_press_duration_seconds is not None:
        odometer.command(decision.virtual_key, decision.key_press_duration_seconds)


def _commanded(
    controller: PathingController, odometer: MirrorOdometer, virtual_key: int, seconds: float
) -> None:
    """Fold one externally dispatched pulse into both the estimate and the client double."""

    controller.integrate_movement(virtual_key, seconds)
    odometer.command(virtual_key, seconds)


def test_a_stall_retreats_to_the_last_safe_waypoint_and_bypasses_the_blocked_cell() -> None:
    spatial_map = _corridor_map()
    for _sighting in range(3):
        spatial_map.record_spawn(_center(GridCell(2, 0)), 0.0)
    odometer = MirrorOdometer(PATHING_CONFIG.movement)
    controller = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)
    controller.observe(_state(0.0))
    seconds = 0.0

    for index in range(30):
        seconds = 1.0 + index * 0.1
        _advance(controller, odometer, seconds)
        controller.observe(_state(seconds))
        if spatial_map.cell_of(controller.position) == GridCell(1, 0):
            break

    assert controller.safe_waypoint == _center(GridCell(0, 0))

    odometer.block()
    for _sample in range(6):
        seconds += 0.1
        _advance(controller, odometer, seconds)
        controller.observe(_state(seconds))
        if controller.is_stalled:
            break

    stalled_mode = controller.mode
    assert controller.is_stalled
    assert stalled_mode is PathingMode.RETREATING
    assert spatial_map.stall_count(GridCell(1, 0)) >= 1

    odometer.unblock()
    recovered: PathingMode = stalled_mode
    for _step in range(60):
        seconds += 0.1
        decision = controller.step(seconds)
        if decision.virtual_key is None or decision.key_press_duration_seconds is None:
            break
        controller.confirm(decision)
        odometer.command(decision.virtual_key, decision.key_press_duration_seconds)
        controller.observe(_state(seconds))
        recovered = controller.mode
        if recovered is PathingMode.TRAVELING:
            break

    assert recovered is PathingMode.TRAVELING
    assert GridCell(1, 0) not in _waypoint_cells(controller)
    assert GridCell(2, 0) in _waypoint_cells(controller)


def test_a_registered_stall_marks_the_obstacle_cell_without_latching_the_stuck_verdict() -> None:
    """BUG-009: the stall must survive turn ticks, then be consumed by its registration."""

    spatial_map = _corridor_map()
    odometer = MirrorOdometer(PATHING_CONFIG.movement)
    controller = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)
    controller.observe(_state(0.0))
    odometer.block()
    seconds = 0.1

    for _sample in range(10):
        _commanded(controller, odometer, VIRTUAL_KEY_W, 0.1)
        controller.observe(_state(seconds))
        if controller.is_stalled:
            break
        seconds += 0.1
        # A turn tick commands no forward movement and must not discard the stall evidence.
        _commanded(controller, odometer, VIRTUAL_KEY_RIGHT, 0.1)
        controller.observe(_state(seconds))
        seconds += 0.1

    assert controller.is_stalled
    assert controller.mode is PathingMode.RETREATING
    assert spatial_map.stall_count(GridCell(0, 0)) == 1

    seconds += 0.1
    controller.observe(_state(seconds))

    assert not controller.is_stalled
    assert controller.mode is PathingMode.RETREATING


def test_the_retreat_anchor_never_moves_into_a_cell_that_registered_a_stall() -> None:
    """BUG-009: retreating must reach verified ground, not the cell the obstacle blocked."""

    spatial_map = _corridor_map()
    odometer = MirrorOdometer(PATHING_CONFIG.movement)
    controller = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)
    controller.observe(_state(0.0))

    _commanded(controller, odometer, VIRTUAL_KEY_RIGHT, 1.0)
    _commanded(controller, odometer, VIRTUAL_KEY_W, 1.5)
    controller.observe(_state(1.0))

    assert controller.safe_waypoint == _center(GridCell(0, 0))

    odometer.block()
    seconds = 1.1
    for _sample in range(6):
        _commanded(controller, odometer, VIRTUAL_KEY_W, 0.1)
        controller.observe(_state(seconds))
        seconds += 0.1
        if controller.is_stalled:
            break

    assert spatial_map.stall_count(GridCell(1, 0)) == 1

    odometer.unblock()
    odometer.displace(-_center(GridCell(1, 0)).x, 0.0)
    controller.observe(_state(seconds))

    assert spatial_map.cell_of(controller.position) == GridCell(0, 0)
    assert controller.safe_waypoint == _center(GridCell(0, 0))


def test_a_stall_without_a_safe_waypoint_reports_blocked_without_moving() -> None:
    controller = PathingController(_corridor_map(), config=PATHING_CONFIG)
    controller._register_stall(WorldPoint(0.0, 0.0), 1.0)

    decision = controller.step(1.0)

    assert decision.mode is PathingMode.BLOCKED
    assert decision.virtual_key is None


def test_pathing_dispatch_is_blocked_by_emergency_stop_and_lost_focus() -> None:
    decision = PathingDecision(PathingMode.TRAVELING, VIRTUAL_KEY_W, 0.5)

    for adapter in (_Adapter(aborted=True), _Adapter(foreground=False)):
        assert not PathingInputDispatcher(adapter, WINDOW_HANDLE).dispatch(decision)
        assert adapter.keys == []

    allowed = _Adapter()
    assert PathingInputDispatcher(allowed, WINDOW_HANDLE).dispatch(decision)
    assert allowed.keys == [(VIRTUAL_KEY_W, 0.5)]


def test_decisions_without_input_are_never_dispatched() -> None:
    adapter = _Adapter()

    assert not PathingInputDispatcher(adapter, WINDOW_HANDLE).dispatch(
        PathingDecision(PathingMode.IDLE)
    )
    assert adapter.keys == []


def _orchestrator(
    states: list[WorldState], adapter: _Adapter, pathing: PathingController | None
) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        adapter,
        WINDOW_HANDLE,
        pathing=pathing,
    )


def test_searching_follows_the_learned_route_before_the_staged_search_stages() -> None:
    adapter = _Adapter()
    orchestrator = _orchestrator([_state(1.0)], adapter, _hotspot_controller())
    orchestrator.start()

    tick = orchestrator.tick()

    assert tick.mode is FarmingMode.SEARCHING
    assert tick.dispatched
    assert adapter.keys == [(VIRTUAL_KEY_W, 0.5)]


def test_searching_falls_back_to_staged_search_without_learned_routes() -> None:
    adapter = _Adapter()
    empty = PathingController(SpatialMap(MAP_CONFIG), config=PATHING_CONFIG)
    orchestrator = _orchestrator([_state(1.0), _state(20.0)], adapter, empty)
    orchestrator.start()

    orchestrator.tick()
    orchestrator.tick()

    assert [key for key, _duration in adapter.keys] == [VIRTUAL_KEY_RIGHT]


def test_a_visible_mob_interrupts_learned_pathing_immediately() -> None:
    adapter = _Adapter()
    mob = VisibleMob(1, "Mushpang", 0.9, 20, 20, 20, 20)
    orchestrator = _orchestrator([_state(1.0, mobs=(mob,))], adapter, _hotspot_controller())
    orchestrator.start()

    tick = orchestrator.tick()

    assert tick.mode is FarmingMode.TARGETING
    assert adapter.keys == []
    assert adapter.clicks == [(WINDOW_HANDLE, 30, 30)]


def test_combat_ticks_follow_the_measured_motion_without_a_combat_side_integration() -> None:
    """US-035: motion during `TARGETING` / `COMBAT` reaches the estimate through the sensor."""

    adapter = _Adapter()
    mob = VisibleMob(1, "Mushpang", 0.9, 20, 20, 20, 20)
    odometer = MirrorOdometer(PATHING_CONFIG.movement)
    pathing = PathingController(SpatialMap(MAP_CONFIG), config=PATHING_CONFIG, odometer=odometer)
    orchestrator = _orchestrator(
        [_state(1.0, mobs=(mob,)), _state(1.2, mobs=(mob,)), _state(1.4, mobs=(mob,))],
        adapter,
        pathing,
    )
    orchestrator.start()

    orchestrator.tick()
    assert orchestrator.mode is FarmingMode.TARGETING
    start = pathing.position

    # The client keeps auto-running towards the target; the bot commands no movement key.
    odometer.displace(6.0, 8.0)
    orchestrator.tick()
    odometer.displace(6.0, 8.0)
    orchestrator.tick()

    assert orchestrator.mode in {FarmingMode.TARGETING, FarmingMode.COMBAT}
    assert VIRTUAL_KEY_W not in [key for key, _duration in adapter.keys]
    assert pathing.position.x == pytest.approx(start.x + 12.0)
    assert pathing.position.y == pytest.approx(start.y + 16.0)


def test_standby_ticks_follow_manual_movement_without_learning_anything() -> None:
    """US-035: the estimate tracks the operator while the session is paused."""

    adapter = _Adapter()
    odometer = MirrorOdometer(PATHING_CONFIG.movement)
    spatial_map = SpatialMap(MAP_CONFIG)
    pathing = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)
    orchestrator = _orchestrator([_state(1.0), _state(1.2)], adapter, pathing)

    orchestrator.tick()
    odometer.displace(9.0, -4.0)
    orchestrator.tick()

    assert orchestrator.mode is FarmingMode.PAUSED
    assert adapter.keys == []
    assert pathing.position.x == pytest.approx(9.0)
    assert pathing.position.y == pytest.approx(-4.0)
    assert spatial_map.known_cells() == ()


def test_emergency_stop_and_lost_focus_send_no_pathing_input() -> None:
    for adapter in (_Adapter(aborted=True), _Adapter(foreground=False)):
        orchestrator = _orchestrator([_state(1.0)], adapter, _hotspot_controller())
        orchestrator.start()

        orchestrator.tick()

        assert adapter.keys == []


def test_the_learned_map_is_persisted_when_a_session_stops(tmp_path: Path) -> None:
    map_path = tmp_path / "spatial_map.json"
    spatial_map = SpatialMap(MAP_CONFIG)
    _walk(spatial_map, [GridCell(0, 0), GridCell(0, 1)])
    pathing = PathingController(spatial_map, config=PATHING_CONFIG, map_path=map_path)
    orchestrator = _orchestrator([_state(1.0)], _Adapter(), pathing)

    orchestrator.pause()

    assert map_path.is_file()


# --- Leash enforcement (US-037) -------------------------------------------------------------
#
# On the 10 px grid of MAP_CONFIG the cell centres sit at 7.07, 15.81 and 25.5 px from the
# session anchor for (0, 0), (0, 1) and (0, 2), so a 20 px leash splits the corridor cleanly
# between the second and the third cell.
LEASH_RADIUS_PIXELS = 20.0
WIDE_LEASH_RADIUS_PIXELS = 40.0


def _column_map() -> SpatialMap:
    """Return a straight recorded column running away from the session anchor."""

    spatial_map = SpatialMap(MAP_CONFIG)
    _walk(
        spatial_map,
        [GridCell(0, 0), GridCell(0, 1), GridCell(0, 2), GridCell(0, 3), GridCell(0, 4)],
    )
    return spatial_map


def _leashed_controller(radius_pixels: float = LEASH_RADIUS_PIXELS) -> PathingController:
    """Return a controller over the recorded column with one hotspot outside the leash."""

    spatial_map = _column_map()
    for _sighting in range(3):
        spatial_map.record_spawn(_center(GridCell(0, 2)), 0.0)
    return PathingController(
        spatial_map, config=replace(PATHING_CONFIG, leash_radius_pixels=radius_pixels)
    )


def test_hotspots_outside_the_leash_are_not_selectable_route_targets() -> None:
    spatial_map = _column_map()
    for _sighting in range(3):
        spatial_map.record_spawn(_center(GridCell(0, 2)), 0.0)
    planner = RoutePlanner(spatial_map)

    unleashed = planner.best_spawn_route(GridCell(0, 0), 0.0)
    leashed = planner.best_spawn_route(GridCell(0, 0), 0.0, leash=LeashBound(LEASH_RADIUS_PIXELS))

    assert unleashed.cells[-1] == GridCell(0, 2)
    assert leashed.is_empty


def test_a_goal_outside_the_leash_is_unreachable_even_when_recorded() -> None:
    planner = RoutePlanner(_column_map())

    route = planner.plan(GridCell(0, 0), GridCell(0, 3), leash=LeashBound(LEASH_RADIUS_PIXELS))

    assert route.is_empty


def test_no_waypoint_of_a_leashed_route_lies_outside_the_leash() -> None:
    spatial_map = _column_map()
    for _sighting in range(6):
        spatial_map.record_spawn(_center(GridCell(0, 4)), 0.0)
    for _sighting in range(2):
        spatial_map.record_spawn(_center(GridCell(0, 1)), 0.0)
    leash = LeashBound(LEASH_RADIUS_PIXELS)

    route = RoutePlanner(spatial_map).circuit(GridCell(0, 0), 0.0, leash=leash)

    assert not route.is_empty
    assert all(leash.contains(spatial_map.center_of(cell)) for cell in route.waypoints)


def test_a_route_planned_from_outside_the_leash_leads_back_inside() -> None:
    spatial_map = _column_map()
    leash = LeashBound(LEASH_RADIUS_PIXELS)

    route = RoutePlanner(spatial_map).return_route(GridCell(0, 4), leash)

    assert not route.is_empty
    assert leash.contains(spatial_map.center_of(route.cells[-1]))


def test_the_controller_walks_back_instead_of_idling_when_pushed_out_of_the_leash() -> None:
    controller = _leashed_controller()
    # 4.5 s of forward travel at the configured 10 px/s puts the estimate at y = 45, which is
    # cell (0, 4) and well outside the 20 px leash.
    controller.integrate_movement(VIRTUAL_KEY_W, 4.5)

    decision = controller.step(0.0)

    assert decision.mode is PathingMode.TRAVELING
    assert controller.waypoints
    assert _waypoint_cells(controller)[-1] == GridCell(0, 1)


def test_a_leash_change_applies_at_the_next_replan_without_restarting_the_session() -> None:
    controller = _leashed_controller()

    assert controller.step(0.0).mode is PathingMode.IDLE

    controller.leash_radius_pixels = WIDE_LEASH_RADIUS_PIXELS
    decision = controller.step(1.0)

    assert decision.mode is PathingMode.TRAVELING
    assert GridCell(0, 2) in _waypoint_cells(controller)


def test_the_drawn_leash_and_the_enforced_leash_are_the_same_value() -> None:
    controller = _leashed_controller()
    controller.step(0.0)

    narrow = controller.snapshot(0.0)

    controller.leash_radius_pixels = WIDE_LEASH_RADIUS_PIXELS
    controller.step(1.0)
    wide = controller.snapshot(1.0)

    # The inspector draws snapshot.leash_radius_pixels; the planner enforced the same number,
    # which is why the hotspot outside the narrow radius becomes reachable under the wide one.
    assert narrow.leash_radius_pixels == pytest.approx(LEASH_RADIUS_PIXELS)
    assert wide.leash_radius_pixels == pytest.approx(WIDE_LEASH_RADIUS_PIXELS)
    assert controller.leash_radius_pixels == pytest.approx(wide.leash_radius_pixels)
    assert GridCell(0, 2) in _waypoint_cells(controller)


def test_hotspots_skipped_by_the_leash_are_reported_to_the_dashboard() -> None:
    controller = _leashed_controller()

    controller.step(0.0)
    skipped = controller.snapshot(0.0).hotspots_outside_leash

    controller.leash_radius_pixels = WIDE_LEASH_RADIUS_PIXELS
    controller.step(1.0)

    assert skipped == 1
    assert controller.snapshot(1.0).hotspots_outside_leash == 0


def test_a_leash_radius_that_is_not_positive_is_rejected() -> None:
    controller = _leashed_controller()

    with pytest.raises(ValueError):
        controller.leash_radius_pixels = 0.0
    with pytest.raises(ValueError):
        LeashBound(-1.0)

    assert controller.leash_radius_pixels == pytest.approx(LEASH_RADIUS_PIXELS)


# --- Unplaceable spawn sightings (US-037) ---------------------------------------------------


def test_a_sighting_without_a_known_viewport_is_not_recorded_at_all() -> None:
    spatial_map = SpatialMap(MAP_CONFIG)
    controller = PathingController(
        spatial_map, config=PATHING_CONFIG, odometer=MirrorOdometer(PATHING_CONFIG.movement)
    )
    mobs = (VisibleMob(0, "Aibatt", 0.9, 40, 40, 20, 20),)

    controller.observe(_state(0.0, mobs=mobs, viewport=Viewport()))

    assert spatial_map.known_cells() == (GridCell(0, 0),)
    assert spatial_map.spawn_weight(GridCell(0, 0), 0.0) == pytest.approx(0.0)


def test_a_sighting_with_a_known_viewport_is_still_recorded() -> None:
    spatial_map = SpatialMap(MAP_CONFIG)
    controller = PathingController(
        spatial_map, config=PATHING_CONFIG, odometer=MirrorOdometer(PATHING_CONFIG.movement)
    )
    mobs = (VisibleMob(0, "Aibatt", 0.9, 40, 40, 20, 20),)

    controller.observe(_state(0.0, mobs=mobs))

    assert any(spatial_map.spawn_weight(cell, 0.0) > 0.0 for cell in spatial_map.known_cells())


def test_an_externally_detected_obstacle_penalizes_the_blocked_cell_and_retreats() -> None:
    """US-039: the combat approach is walked by the client, so its stall is reported in."""

    spatial_map = _corridor_map()
    odometer = MirrorOdometer(PATHING_CONFIG.movement)
    controller = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)
    controller.observe(_state(0.0))
    _commanded(controller, odometer, VIRTUAL_KEY_W, 1.5)
    controller.observe(_state(1.0))
    blocked = spatial_map.cell_of(controller.position)

    assert controller.register_obstacle(1.0)

    assert spatial_map.stall_count(blocked) == 1
    assert controller.mode is PathingMode.RETREATING
    assert blocked not in _waypoint_cells(controller)


def test_an_unknown_position_learns_nothing_from_an_external_obstacle() -> None:
    """A stall is only evidence about a place while the place itself is known."""

    spatial_map = _corridor_map()
    controller = PathingController(spatial_map, config=PATHING_CONFIG)

    assert not controller.register_obstacle(1.0)
    assert spatial_map.stall_count(GridCell(0, 0)) == 0


def test_an_external_obstacle_during_an_ongoing_retreat_is_not_registered_twice() -> None:
    spatial_map = _corridor_map()
    odometer = MirrorOdometer(PATHING_CONFIG.movement)
    controller = PathingController(spatial_map, config=PATHING_CONFIG, odometer=odometer)
    controller.observe(_state(0.0))
    _commanded(controller, odometer, VIRTUAL_KEY_W, 1.5)
    controller.observe(_state(1.0))
    blocked = spatial_map.cell_of(controller.position)
    controller.register_obstacle(1.0)

    assert not controller.register_obstacle(1.5)
    assert spatial_map.stall_count(blocked) == 1
