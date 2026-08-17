"""Tests for the internal spawn heatmap, navigation graph, and its persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
