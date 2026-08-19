"""Parsing and passability extraction of client world files (US-045)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from world_fixtures import (
    WORLD_SCRIPT,
    dynamic_object_payload,
    flat_heights,
    land_block_payload,
    raise_vertex,
    region_script,
    respawn_record,
    utf16_payload,
    write_world_directory,
)

from flyff_bot.features.navigation.world_extractor import (
    IMPASSABLE_SLOPE_GRADIENT,
    LAND_BLOCK_CELLS_PER_SIDE,
    LAND_BLOCK_VERTICES_PER_SIDE,
    LandBlock,
    ObstacleKind,
    WorldCoordinate,
    WorldDimensions,
    WorldExtractionError,
    WorldVectorMap,
    decode_land_block,
    discover_world_directories,
    dynamic_object_model_names,
    extract_world,
    land_block_obstacles,
    load_monster_names,
    load_world_map,
    nearest_zone,
    parse_dynamic_objects,
    parse_region_script,
    parse_world_script,
    read_world_text,
    save_world_map,
    summarize,
)

EDEN_MONSTER_NAMES = {1453: "Flame", 1454: "LadyBlum", 1455: "MiniMush"}
DIMENSIONS = WorldDimensions(blocks_x=2, blocks_z=2, meters_per_unit=4.0)


def test_the_world_script_states_the_block_grid_and_terrain_scale() -> None:
    dimensions = parse_world_script(WORLD_SCRIPT)

    assert dimensions.blocks_x == 2
    assert dimensions.blocks_z == 2
    assert dimensions.meters_per_unit == pytest.approx(4.0)
    # 128 quads per block at four world units each is the client's own map extent.
    assert dimensions.width_units == pytest.approx(1024.0)
    assert dimensions.depth_units == pytest.approx(1024.0)


def test_a_world_script_without_a_size_is_refused() -> None:
    with pytest.raises(WorldExtractionError):
        parse_world_script("// World script\nMPU 4\n")


def test_client_scripts_are_decoded_from_utf16_and_from_plain_ansi() -> None:
    """The client writes `.rgn` as UTF-16 with a mark and `.wld` as plain bytes."""

    assert read_world_text(utf16_payload("respawn7")) == "respawn7"
    assert read_world_text(b"size 5, 5") == "size 5, 5"


def test_respawn_records_become_typed_spawn_zones_with_their_monster_names() -> None:
    text = region_script(
        [
            respawn_record(1453, (100.0, 92.0, 200.0), (80, 180, 120, 220), 26, 30),
            respawn_record(1455, (300.0, 92.0, 400.0), (280, 380, 320, 420), 8, 60),
        ]
    )

    zones = parse_region_script(text, EDEN_MONSTER_NAMES)

    assert len(zones) == 2
    first = zones[0]
    assert first.monster_id == 1453
    assert first.monster_name == "Flame"
    assert first.capacity == 26
    assert first.respawn_seconds == 30
    assert first.centroid == WorldCoordinate(100.0, 200.0)
    assert first.anchor == WorldCoordinate(100.0, 200.0)
    assert first.contains(WorldCoordinate(85.0, 215.0))
    assert not first.contains(WorldCoordinate(130.0, 215.0))


def test_records_that_are_not_monster_respawns_are_skipped_rather_than_rejected() -> None:
    text = region_script(
        [
            'title 0 "Eden"',
            "region3 1 0 0 100 100",
            respawn_record(1453, (10.0, 0.0, 10.0), (0, 0, 20, 20), 5, 30, kind=6),
            respawn_record(1454, (50.0, 0.0, 50.0), (40, 40, 60, 60), 5, 30),
        ]
    )

    zones = parse_region_script(text, EDEN_MONSTER_NAMES)

    assert [zone.monster_id for zone in zones] == [1454]


def test_a_monster_without_a_mapped_name_keeps_its_numeric_identity() -> None:
    text = region_script([respawn_record(9999, (10.0, 0.0, 10.0), (0, 0, 20, 20), 5, 30)])

    zones = parse_region_script(text, EDEN_MONSTER_NAMES)

    assert zones[0].monster_name is None
    assert zones[0].monster_id == 9999


def test_a_truncated_respawn_record_is_reported_rather_than_silently_dropped() -> None:
    with pytest.raises(WorldExtractionError):
        parse_region_script(region_script(["respawn7 5 1453 1.0 2.0 3.0"]))


def test_a_terrain_block_decodes_its_coordinates_and_full_height_grid() -> None:
    heights = raise_vertex(flat_heights(100.0), column=3, row=4, height=140.0)

    block = decode_land_block(land_block_payload(3, 2, heights))

    assert (block.block_x, block.block_z) == (3, 2)
    assert len(block.heights) == LAND_BLOCK_VERTICES_PER_SIDE**2
    assert block.height(3, 4) == pytest.approx(140.0)
    assert block.height(0, 0) == pytest.approx(100.0)


def test_an_unsupported_terrain_block_version_is_refused() -> None:
    with pytest.raises(WorldExtractionError):
        decode_land_block(land_block_payload(0, 0, flat_heights(), version=9))


def test_a_truncated_terrain_block_is_refused() -> None:
    with pytest.raises(WorldExtractionError):
        decode_land_block(land_block_payload(0, 0, flat_heights()[:100]))


def test_level_terrain_produces_no_impassable_geometry() -> None:
    block = decode_land_block(land_block_payload(0, 0, flat_heights()))

    assert land_block_obstacles(block, DIMENSIONS) == ()


def test_a_lifted_vertex_blocks_exactly_the_quads_that_touch_it() -> None:
    """A vertex raised by more than one metre per metre of run is a cliff corner."""

    lift = 100.0 + IMPASSABLE_SLOPE_GRADIENT * DIMENSIONS.meters_per_unit + 1.0
    heights = raise_vertex(flat_heights(100.0), column=10, row=20, height=lift)
    block = decode_land_block(land_block_payload(1, 1, heights))

    obstacles = land_block_obstacles(block, DIMENSIONS)

    # The four quads around the vertex merge into rows, and every one of them is a slope.
    assert obstacles
    assert {obstacle.kind for obstacle in obstacles} == {ObstacleKind.SLOPE}
    origin = DIMENSIONS.block_span_units
    covered = WorldCoordinate(origin + 10.0 * 4.0, origin + 20.0 * 4.0)
    assert any(obstacle.contains(covered) for obstacle in obstacles)
    # Block (1, 1) starts at 512 world units on both axes, so nothing may be emitted before it.
    assert all(
        obstacle.minimum_x >= origin and obstacle.minimum_z >= origin for obstacle in obstacles
    )


def test_contiguous_impassable_quads_merge_into_whole_rectangles() -> None:
    """A raster of single quads would give the planner thousands of redundant corners."""

    heights = flat_heights(100.0)
    for column in range(20, 30):
        heights = raise_vertex(heights, column, 40, 400.0)

    obstacles = land_block_obstacles(
        decode_land_block(land_block_payload(0, 0, heights)), DIMENSIONS
    )

    # The lifted run spans ten vertices, so the blocked band is two quad rows deep and at
    # most a handful of rectangles wide - never one rectangle per quad.
    assert len(obstacles) < LAND_BLOCK_CELLS_PER_SIDE
    widest = max(obstacles, key=lambda obstacle: obstacle.maximum_x - obstacle.minimum_x)
    assert widest.maximum_x - widest.minimum_x > DIMENSIONS.meters_per_unit


def test_placed_objects_become_square_footprints_inside_the_region() -> None:
    payload = dynamic_object_payload([(100.0, 20.0, 200.0)])

    footprints = parse_dynamic_objects(payload, DIMENSIONS)

    assert len(footprints) == 1
    assert footprints[0].kind is ObstacleKind.OBJECT
    assert footprints[0].contains(WorldCoordinate(100.0, 200.0))
    assert dynamic_object_model_names(payload) == ("TestProp",)


def test_a_placed_object_outside_the_region_is_discarded() -> None:
    """A position off the map is the clearest evidence the record layout does not fit."""

    payload = dynamic_object_payload([(90_000.0, 20.0, 90_000.0)])

    assert parse_dynamic_objects(payload, DIMENSIONS) == ()


def test_a_dynamic_object_file_that_does_not_divide_into_records_is_refused() -> None:
    with pytest.raises(WorldExtractionError):
        parse_dynamic_objects(dynamic_object_payload([(1.0, 1.0, 1.0)])[:-7], DIMENSIONS)


def test_extracting_a_region_gathers_zones_terrain_and_objects(tmp_path: Path) -> None:
    heights = raise_vertex(flat_heights(100.0), column=5, row=5, height=500.0)
    directory = write_world_directory(
        tmp_path,
        "wdtest",
        region_records=[
            respawn_record(1453, (100.0, 92.0, 200.0), (80, 180, 120, 220), 26, 30),
            respawn_record(1455, (300.0, 92.0, 400.0), (280, 380, 320, 420), 8, 60),
        ],
        blocks=[(0, 0, heights)],
        objects=[(150.0, 20.0, 150.0)],
    )

    world_map = extract_world(directory, monster_names=EDEN_MONSTER_NAMES)

    assert world_map.world_name == "wdtest"
    assert world_map.terrain_block_count == 1
    assert len(world_map.zones) == 2
    assert world_map.monster_names == ("Flame", "MiniMush")
    assert world_map.terrain.height_at(WorldCoordinate(20.0, 20.0)) == pytest.approx(500.0)
    assert world_map.terrain.height_at(WorldCoordinate(18.0, 20.0)) == pytest.approx(300.0)
    kinds = {obstacle.kind for obstacle in world_map.obstacles}
    assert kinds == {ObstacleKind.SLOPE, ObstacleKind.OBJECT}


def test_a_region_without_terrain_blocks_still_extracts_its_spawn_zones(tmp_path: Path) -> None:
    """A region whose terrain lives only inside the packed archive is not a failure."""

    directory = write_world_directory(
        tmp_path,
        "wdsparse",
        region_records=[respawn_record(1453, (10.0, 0.0, 10.0), (0, 0, 20, 20), 4, 30)],
    )

    world_map = extract_world(directory, monster_names=EDEN_MONSTER_NAMES)

    assert world_map.terrain_block_count == 0
    assert world_map.obstacles == ()
    assert len(world_map.zones) == 1


def test_terrain_field_includes_the_outer_edge_of_its_last_block() -> None:
    block = LandBlock(0, 0, tuple(flat_heights(75.0)))
    world_map = WorldVectorMap("edge", WorldDimensions(1, 1, 4.0), terrain_blocks=(block,))

    assert world_map.terrain.height_at(WorldCoordinate(512.0, 512.0)) == pytest.approx(75.0)


def test_a_directory_without_a_world_script_is_refused(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()

    with pytest.raises(WorldExtractionError):
        extract_world(tmp_path / "empty")


def test_only_directories_holding_a_world_script_are_offered_as_regions(tmp_path: Path) -> None:
    write_world_directory(tmp_path, "wdbeta")
    write_world_directory(tmp_path, "wdalpha")
    (tmp_path / "notaregion").mkdir()

    assert [path.name for path in discover_world_directories(tmp_path)] == ["wdalpha", "wdbeta"]
    assert discover_world_directories(tmp_path / "missing") == ()


def test_an_extracted_map_round_trips_through_its_json_document(tmp_path: Path) -> None:
    directory = write_world_directory(
        tmp_path / "client",
        "wdtest",
        region_records=[respawn_record(1453, (100.0, 92.0, 200.0), (80, 180, 120, 220), 26, 30)],
        blocks=[(0, 0, raise_vertex(flat_heights(100.0), 5, 5, 500.0))],
    )
    world_map = extract_world(directory, monster_names=EDEN_MONSTER_NAMES)

    saved = save_world_map(world_map, tmp_path / "worlds")
    restored = load_world_map(saved)

    assert saved.name == "wdtest.json"
    assert restored == world_map


def test_a_persisted_map_of_an_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    document = {"version": 99, "world_name": "x", "dimensions": {}, "zones": [], "obstacles": []}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(WorldExtractionError):
        load_world_map(path)


def test_schema_v1_world_map_requires_re_extraction(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "world_name": "wdtest",
                "dimensions": {"blocks_x": 1, "blocks_z": 1, "meters_per_unit": 4.0},
                "terrain_block_count": 1,
                "zones": [],
                "obstacles": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(WorldExtractionError, match="Unsupported world vector map version: 1"):
        load_world_map(path)


def test_zones_of_one_monster_are_offered_densest_first() -> None:
    world_map = WorldVectorMap(
        "wdtest",
        DIMENSIONS,
        parse_region_script(
            region_script(
                [
                    respawn_record(1453, (10.0, 0.0, 10.0), (0, 0, 20, 20), 5, 30),
                    respawn_record(1453, (90.0, 0.0, 90.0), (80, 80, 100, 100), 30, 30),
                    respawn_record(1455, (50.0, 0.0, 50.0), (40, 40, 60, 60), 9, 60),
                ]
            ),
            EDEN_MONSTER_NAMES,
        ),
    )

    flames = world_map.zones_for("Flame")

    assert [zone.capacity for zone in flames] == [30, 5]
    assert world_map.zones_for("Rapra") == ()
    assert nearest_zone(flames, WorldCoordinate(0.0, 0.0)) is flames[1]


def test_the_shipped_monster_table_names_every_eden_class() -> None:
    """The extractor must be able to address a zone by the same name the dashboard offers."""

    names = load_monster_names(Path("data/assets/world/monster_ids.json"))

    assert set(names.values()) == {
        "Flame",
        "LadyBlum",
        "MiniMush",
        "NightMist",
        "Oldrut",
        "Rapra",
    }


def test_an_extraction_summary_reports_what_the_dialog_shows(tmp_path: Path) -> None:
    directory = write_world_directory(
        tmp_path,
        "wdtest",
        region_records=[respawn_record(1453, (10.0, 0.0, 10.0), (0, 0, 20, 20), 4, 30)],
    )
    world_map = extract_world(directory, monster_names=EDEN_MONSTER_NAMES)

    summary = summarize(world_map, tmp_path / "wdtest.json")

    assert summary.world_name == "wdtest"
    assert summary.zone_count == 1
    assert summary.monster_names == ("Flame",)
    assert summary.output_path.name == "wdtest.json"
