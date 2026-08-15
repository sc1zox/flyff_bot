"""Tests for learned route planning, stuck recovery, and guarded pathing dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import pytest

from flyff_bot.features.automation.controllers import VIRTUAL_KEY_RIGHT, VIRTUAL_KEY_W
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
from flyff_bot.features.navigation.planning import RouteConfig, RoutePlanner
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
    cell_size_units=CELL_SIZE_UNITS,
    spawn_half_life_seconds=600.0,
    maximum_link_span_cells=1,
)
PATHING_CONFIG = PathingConfig(
    step_duration_seconds=0.5,
    turn_duration_seconds=0.25,
    heading_tolerance_degrees=25.0,
    movement=MovementModel(
        forward_speed_units_per_second=10.0,
        strafe_speed_units_per_second=10.0,
        turn_degrees_per_second=90.0,
    ),
    stall=StallConfig(motion_threshold=1.0, consecutive_samples=1),
    route=RouteConfig(minimum_hotspot_weight=1.0),
)


class _Adapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.keys: list[tuple[int, float]] = []
        self.clicks: list[tuple[int, int, int]] = []

    def is_aborted(self) -> bool:
        return self.aborted

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


def _state(time: float, *, mobs: tuple[VisibleMob, ...] = (), stuck: bool = False) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        is_stuck=stuck,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=Viewport(100, 100),
    )


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


def test_a_stall_retreats_to_the_last_safe_waypoint_and_bypasses_the_blocked_cell() -> None:
    spatial_map = _corridor_map()
    for _sighting in range(3):
        spatial_map.record_spawn(_center(GridCell(2, 0)), 0.0)
    controller = PathingController(spatial_map, config=PATHING_CONFIG)
    controller.observe(_state(0.0))
    seconds = 0.0

    for index in range(30):
        seconds = 1.0 + index * 0.1
        controller.confirm(controller.step(seconds))
        controller.observe(_state(seconds))
        if spatial_map.cell_of(controller.position) == GridCell(1, 0):
            break

    assert controller.safe_waypoint == _center(GridCell(0, 0))

    frozen = _frame()
    controller.observe(_state(seconds), frozen)
    for _sample in range(6):
        seconds += 0.1
        controller.confirm(controller.step(seconds))
        controller.observe(_state(seconds), frozen)
        if controller.is_stalled:
            break

    stalled_mode = controller.mode
    assert controller.is_stalled
    assert stalled_mode is PathingMode.RETREATING
    assert spatial_map.stall_count(GridCell(1, 0)) >= 1

    recovered: PathingMode = stalled_mode
    for _step in range(60):
        seconds += 0.1
        decision = controller.step(seconds)
        if decision.virtual_key is None:
            break
        controller.confirm(decision)
        controller.observe(_state(seconds))
        recovered = controller.mode
        if recovered is PathingMode.TRAVELING:
            break

    assert recovered is PathingMode.TRAVELING
    assert GridCell(1, 0) not in controller.waypoints
    assert GridCell(2, 0) in controller.waypoints


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
