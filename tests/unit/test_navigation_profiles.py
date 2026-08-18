"""Tests for navigation map profile discovery, persistence, and session reset."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from minimap_doubles import MirrorOdometer

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.automation.orchestrator import (
    FarmingConfig,
    FarmingMode,
    FarmingOrchestrator,
)
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.persistence import (
    count_cells_in_profile,
    list_navigation_profiles,
    sanitize_profile_name,
)
from flyff_bot.features.navigation.spatial import SpatialMap, WorldPoint
from flyff_bot.features.navigation.tracking import MovementModel


def test_sanitize_profile_name() -> None:
    assert sanitize_profile_name("mushpang_valley") == "mushpang_valley"
    assert sanitize_profile_name("  mushpang valley  ") == "mushpang valley"
    assert sanitize_profile_name("flame/north:camp?*") == "flamenorthcamp"
    assert sanitize_profile_name(r'zone\1<2>3|"test"') == "zone123test"
    assert sanitize_profile_name("spot_a.json") == "spot_a"
    assert sanitize_profile_name("  spot_b.JSON  ") == "spot_b"


def test_list_navigation_profiles_empty_and_populated(tmp_path: Path) -> None:
    assert list_navigation_profiles(tmp_path / "non_existent") == []

    nav_dir = tmp_path / "nav"
    nav_dir.mkdir()
    assert list_navigation_profiles(nav_dir) == []

    # Write a valid map profile
    map1 = SpatialMap()
    map1.record_visit(WorldPoint(10.0, 10.0), at_seconds=1.0)
    map1.record_visit(WorldPoint(30.0, 30.0), at_seconds=2.0)
    file1 = nav_dir / "camp_a.json"
    file1.write_text(json.dumps(map1.to_dict()), encoding="utf-8")

    # Write a corrupted profile
    file2 = nav_dir / "corrupted.json"
    file2.write_text("invalid json content", encoding="utf-8")

    profiles = list_navigation_profiles(nav_dir)
    assert len(profiles) == 2
    assert profiles[0].name == "camp_a.json"
    assert profiles[0].cell_count == 2
    assert profiles[1].name == "corrupted.json"
    assert profiles[1].cell_count == 0


def test_count_cells_in_profile_handles_invalid_files(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not json}", encoding="utf-8")
    assert count_cells_in_profile(bad_file) == 0

    non_dict_file = tmp_path / "list.json"
    non_dict_file.write_text("[]", encoding="utf-8")
    assert count_cells_in_profile(non_dict_file) == 0


def test_pathing_controller_save_load_reset(tmp_path: Path) -> None:
    odometer = MirrorOdometer(MovementModel())
    controller = PathingController(odometer=odometer)
    state = WorldState(
        observed_at_seconds=10.0,
        position=Position(0, 0),
        nearby_mob_count=1,
        inventory=(),
        progress_marker=0,
        visible_mobs=(VisibleMob(0, "Flame", 0.9, 50, 50, 20, 20),),
        viewport=Viewport(100, 100),
    )
    controller.observe(state)
    odometer.command(0x57, duration_seconds=1.0)  # the client moves forward
    controller.integrate_movement(0x57, duration_seconds=1.0)  # Move W
    controller.observe(replace(state, observed_at_seconds=11.0))

    assert len(controller.spatial_map.known_cells()) > 0
    assert controller.position != WorldPoint(0.0, 0.0)

    save_path = tmp_path / "saved_camp.json"
    controller.save_map(save_path)
    assert save_path.is_file()

    # Reset
    controller.reset()
    assert len(controller.spatial_map.known_cells()) == 0
    assert controller.position == WorldPoint(0.0, 0.0)
    assert controller.waypoints == ()

    # Load back
    controller.load_map(save_path)
    assert len(controller.spatial_map.known_cells()) > 0
    assert controller.position == WorldPoint(0.0, 0.0)


def test_orchestrator_profile_management_lifecycle(tmp_path: Path) -> None:
    pipeline = MagicMock()
    adapter = MagicMock()
    adapter.is_aborted.return_value = False
    adapter.is_foreground.return_value = True

    pathing = PathingController()
    pathing.spatial_map.record_visit(WorldPoint(15.0, 15.0), at_seconds=1.0)

    orchestrator = FarmingOrchestrator(
        pipeline,
        adapter,
        window_handle=123,
        config=FarmingConfig(),
        pathing=pathing,
    )

    save_path = tmp_path / "orch_profile.json"
    orchestrator.save_navigation_profile(save_path)
    assert save_path.is_file()

    orchestrator.reset_navigation_map()
    assert len(pathing.spatial_map.known_cells()) == 0

    orchestrator.load_navigation_profile(save_path)
    assert len(pathing.spatial_map.known_cells()) == 1

    # Disallowed when farming is active
    orchestrator.start()
    assert orchestrator.mode == FarmingMode.SEARCHING
    with pytest.raises(RuntimeError, match="only be saved while farming is paused"):
        orchestrator.save_navigation_profile(save_path)
    with pytest.raises(RuntimeError, match="only be loaded while farming is paused"):
        orchestrator.load_navigation_profile(save_path)
    with pytest.raises(RuntimeError, match="only be reset while farming is paused"):
        orchestrator.reset_navigation_map()
