"""Tests for the internal spawn heatmap, navigation graph, and its persistence."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_D,
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_W,
)
from flyff_bot.features.navigation.persistence import load_spatial_map, save_spatial_map
from flyff_bot.features.navigation.spatial import (
    DEFAULT_MAXIMUM_LINK_SPAN_CELLS,
    DEFAULT_MAXIMUM_STALL_COST_FACTOR,
    DEFAULT_STALL_COST_PENALTY,
    GridCell,
    SpatialMap,
    SpatialMapConfig,
    WorldPoint,
)
from flyff_bot.features.navigation.tracking import (
    MovementModel,
    MovementTracker,
    StallConfig,
    StallDetector,
    bearing_degrees,
    heading_error_degrees,
)
from flyff_bot.features.vision.models import CapturedFrame, ClientSize

CELL_SIZE_UNITS = 10.0
HALF_LIFE_SECONDS = 100.0


def _map(
    *,
    stall_cost_penalty: float = DEFAULT_STALL_COST_PENALTY,
    maximum_stall_cost_factor: float = DEFAULT_MAXIMUM_STALL_COST_FACTOR,
    maximum_link_span_cells: int = DEFAULT_MAXIMUM_LINK_SPAN_CELLS,
) -> SpatialMap:
    return SpatialMap(
        SpatialMapConfig(
            cell_size_units=CELL_SIZE_UNITS,
            spawn_half_life_seconds=HALF_LIFE_SECONDS,
            stall_cost_penalty=stall_cost_penalty,
            maximum_stall_cost_factor=maximum_stall_cost_factor,
            maximum_link_span_cells=maximum_link_span_cells,
        )
    )


def _frame(value: int) -> CapturedFrame:
    pixels = np.full((32, 32, 3), value, dtype=np.uint8)
    return CapturedFrame(pixels, ClientSize(32, 32))


def test_spawn_sightings_accumulate_in_the_cell_that_observed_them() -> None:
    spatial_map = _map()

    spatial_map.record_spawn(WorldPoint(2.0, 3.0), 0.0)
    spatial_map.record_spawn(WorldPoint(7.0, 8.0), 0.0)
    spatial_map.record_spawn(WorldPoint(25.0, 5.0), 0.0)

    assert spatial_map.spawn_weight(GridCell(0, 0), 0.0) == pytest.approx(2.0)
    assert spatial_map.spawn_weight(GridCell(2, 0), 0.0) == pytest.approx(1.0)
    assert spatial_map.spawn_weight(GridCell(9, 9), 0.0) == 0.0


def test_spawn_weight_halves_every_configured_half_life() -> None:
    spatial_map = _map()
    spatial_map.record_spawn(WorldPoint(0.0, 0.0), 0.0)

    assert spatial_map.spawn_weight(GridCell(0, 0), HALF_LIFE_SECONDS) == pytest.approx(0.5)
    assert spatial_map.spawn_weight(GridCell(0, 0), 2 * HALF_LIFE_SECONDS) == pytest.approx(0.25)

    spatial_map.record_spawn(WorldPoint(0.0, 0.0), 2 * HALF_LIFE_SECONDS)

    assert spatial_map.spawn_weight(GridCell(0, 0), 2 * HALF_LIFE_SECONDS) == pytest.approx(1.25)


def test_traversed_positions_build_a_navigation_graph_with_visit_history() -> None:
    spatial_map = _map()

    spatial_map.record_visit(WorldPoint(5.0, 5.0), 1.0)
    spatial_map.record_visit(WorldPoint(15.0, 5.0), 2.0)
    spatial_map.record_visit(WorldPoint(25.0, 5.0), 3.0)
    spatial_map.record_visit(WorldPoint(15.0, 5.0), 4.0)

    assert spatial_map.known_cells() == (GridCell(0, 0), GridCell(1, 0), GridCell(2, 0))
    assert spatial_map.visit_count(GridCell(1, 0)) == 2
    assert spatial_map.last_visited_at_seconds(GridCell(1, 0)) == 4.0
    assert spatial_map.neighbors(GridCell(1, 0)) == (GridCell(0, 0), GridCell(2, 0))
    assert spatial_map.neighbors(GridCell(0, 0)) == (GridCell(1, 0),)


def test_distant_jumps_are_not_recorded_as_traversable_edges() -> None:
    spatial_map = _map(maximum_link_span_cells=2)

    spatial_map.record_visit(WorldPoint(5.0, 5.0), 1.0)
    spatial_map.record_visit(WorldPoint(105.0, 5.0), 2.0)

    assert spatial_map.neighbors(GridCell(0, 0)) == ()
    assert spatial_map.visit_count(GridCell(10, 0)) == 1


def test_stalls_raise_the_cost_of_the_cell_and_the_edge_that_reached_it() -> None:
    spatial_map = _map(stall_cost_penalty=2.0)
    spatial_map.record_visit(WorldPoint(5.0, 5.0), 1.0)
    spatial_map.record_visit(WorldPoint(15.0, 5.0), 2.0)
    baseline = spatial_map.move_cost(GridCell(0, 0), GridCell(1, 0))

    spatial_map.record_stall(WorldPoint(15.0, 5.0), 3.0)

    assert baseline == pytest.approx(1.0)
    assert spatial_map.stall_count(GridCell(1, 0)) == 1
    assert spatial_map.edge_stall_count(GridCell(0, 0), GridCell(1, 0)) == 1
    assert spatial_map.move_cost(GridCell(0, 0), GridCell(1, 0)) == pytest.approx(5.0)


def test_stall_cost_stays_finite_so_a_penalized_area_remains_reachable() -> None:
    spatial_map = _map(stall_cost_penalty=2.0, maximum_stall_cost_factor=3.0)
    spatial_map.record_visit(WorldPoint(5.0, 5.0), 1.0)
    spatial_map.record_visit(WorldPoint(15.0, 5.0), 2.0)
    for index in range(10):
        spatial_map.record_stall(WorldPoint(15.0, 5.0), 3.0 + index)

    assert spatial_map.move_cost(GridCell(0, 0), GridCell(1, 0)) == pytest.approx(3.0)


def test_hotspots_rank_dense_clusters_above_sparse_ones() -> None:
    spatial_map = _map()
    for _sighting in range(3):
        spatial_map.record_spawn(WorldPoint(5.0, 5.0), 0.0)
    spatial_map.record_spawn(WorldPoint(35.0, 5.0), 0.0)

    hotspots = spatial_map.hotspots(0.0, 1.0)

    assert [cell for cell, _weight in hotspots] == [GridCell(0, 0), GridCell(3, 0)]
    assert [cell for cell, _weight in spatial_map.hotspots(0.0, 2.0)] == [GridCell(0, 0)]
    assert hotspots[0][1] == pytest.approx(3.0)


def test_learned_map_survives_a_serialization_round_trip(tmp_path: Path) -> None:
    spatial_map = _map()
    spatial_map.record_visit(WorldPoint(5.0, 5.0), 1.0)
    spatial_map.record_visit(WorldPoint(15.0, 5.0), 2.0)
    spatial_map.record_stall(WorldPoint(15.0, 5.0), 3.0)
    spatial_map.record_spawn(WorldPoint(15.0, 5.0), 3.0)
    path = tmp_path / "nested" / "spatial_map.json"

    save_spatial_map(spatial_map, path)
    restored = load_spatial_map(path, spatial_map.config)

    assert restored.known_cells() == spatial_map.known_cells()
    assert restored.visit_count(GridCell(1, 0)) == 1
    assert restored.stall_count(GridCell(1, 0)) == 1
    assert restored.neighbors(GridCell(0, 0)) == (GridCell(1, 0),)
    assert restored.spawn_weight(GridCell(1, 0), 3.0) == pytest.approx(1.0)
    assert restored.move_cost(GridCell(0, 0), GridCell(1, 0)) == pytest.approx(
        spatial_map.move_cost(GridCell(0, 0), GridCell(1, 0))
    )


def test_missing_map_file_starts_an_empty_map_and_corrupt_content_is_rejected(
    tmp_path: Path,
) -> None:
    assert load_spatial_map(tmp_path / "absent.json").known_cells() == ()

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text(json.dumps({"version": 99, "cells": [], "edges": []}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_spatial_map(corrupt)


def test_invalid_map_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        SpatialMapConfig(cell_size_units=0.0)
    with pytest.raises(ValueError):
        SpatialMapConfig(spawn_half_life_seconds=0.0)
    with pytest.raises(ValueError):
        SpatialMapConfig(maximum_stall_cost_factor=0.5)


def test_movement_pulses_estimate_a_relative_position_and_heading() -> None:
    tracker = MovementTracker(
        MovementModel(
            forward_speed_units_per_second=10.0,
            strafe_speed_units_per_second=10.0,
            turn_degrees_per_second=90.0,
        )
    )

    tracker.apply(VIRTUAL_KEY_W, 1.0)

    assert tracker.position.x == pytest.approx(0.0, abs=1e-9)
    assert tracker.position.y == pytest.approx(10.0)

    tracker.apply(VIRTUAL_KEY_RIGHT, 1.0)
    tracker.apply(VIRTUAL_KEY_W, 1.0)

    assert tracker.heading_degrees == pytest.approx(90.0)
    assert tracker.position.x == pytest.approx(10.0)
    assert tracker.position.y == pytest.approx(10.0)

    tracker.apply(VIRTUAL_KEY_LEFT, 1.0)
    tracker.apply(VIRTUAL_KEY_D, 1.0)

    assert tracker.position.x == pytest.approx(20.0)
    assert tracker.position.y == pytest.approx(10.0)


def test_bearing_and_heading_error_use_shortest_signed_turns() -> None:
    assert bearing_degrees(WorldPoint(0.0, 0.0), WorldPoint(0.0, 5.0)) == pytest.approx(0.0)
    assert bearing_degrees(WorldPoint(0.0, 0.0), WorldPoint(5.0, 0.0)) == pytest.approx(90.0)
    assert heading_error_degrees(350.0, 10.0) == pytest.approx(20.0)
    assert heading_error_degrees(10.0, 350.0) == pytest.approx(-20.0)


def test_stall_is_reported_only_after_repeated_motionless_movement_samples() -> None:
    detector = StallDetector(StallConfig(motion_threshold=1.0, consecutive_samples=2))

    assert not detector.observe(_frame(10), movement_commanded=True)
    assert not detector.observe(_frame(10), movement_commanded=True)
    assert detector.observe(_frame(10), movement_commanded=True)
    assert detector.is_stalled


def test_visible_progress_or_idle_ticks_clear_the_stall_streak() -> None:
    detector = StallDetector(StallConfig(motion_threshold=1.0, consecutive_samples=1))
    detector.observe(_frame(10), movement_commanded=True)
    assert detector.observe(_frame(10), movement_commanded=True)

    assert not detector.observe(_frame(200), movement_commanded=True)

    detector.observe(_frame(200), movement_commanded=True)
    assert detector.is_stalled
    assert not detector.observe(_frame(200), movement_commanded=False)
    assert not detector.is_stalled
