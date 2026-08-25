"""The world data manager dialog and its extraction worker (US-045)."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from world_fixtures import (
    flat_heights,
    raise_vertex,
    respawn_record,
    write_world_directory,
)

from flyff_bot.features.navigation.navmesh import NavMeshBaker
from flyff_bot.features.navigation.navmesh_persistence import (
    save_baked_navmesh,
    world_navmesh_path,
)
from flyff_bot.features.navigation.vector_navigation import VectorNavigationRequest, ZoneGoal
from flyff_bot.features.navigation.world_extractor import (
    WorldExtractionSummary,
    load_world_map,
)
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex
from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.world_data_dialog import (
    ALL_TARGET_MOBS,
    WorldDataDialog,
    WorldExtractionWorker,
)

MONSTER_IDS_PATH = Path("data/assets/world/monster_ids.json")


@pytest.fixture(scope="module", autouse=True)
def _application() -> None:
    """Ensure one Qt application exists for the widgets these tests build."""

    if QApplication.instance() is None:
        QApplication([])


@pytest.fixture
def client_root(tmp_path: Path) -> Path:
    """Return a client world root holding one synthetic Eden-like region."""

    root = tmp_path / "client"
    write_world_directory(
        root,
        "wdtest",
        region_records=[
            respawn_record(1453, (100.0, 92.0, 200.0), (80, 180, 120, 220), 26, 30),
            respawn_record(1458, (300.0, 92.0, 400.0), (280, 380, 320, 420), 12, 60),
        ],
        blocks=[(0, 0, raise_vertex(flat_heights(100.0), 5, 5, 500.0))],
    )
    (root / "notaregion").mkdir()
    return root


def _dialog(
    client_root: Path, tmp_path: Path, *, settings: QSettings | None = None
) -> WorldDataDialog:
    resolved_settings = settings or QSettings(
        str(tmp_path / "world_data_dialog.ini"), QSettings.Format.IniFormat
    )
    return WorldDataDialog(
        Translator(Language.ENGLISH),
        client_root,
        tmp_path / "worlds",
        monster_names_path=MONSTER_IDS_PATH,
        settings=resolved_settings,
    )


def _set_checked(dialog: WorldDataDialog, row: int, checked: bool) -> None:
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    dialog.zone_list.item(row).setCheckState(state)


def _check_only(dialog: WorldDataDialog, row: int) -> None:
    for index in range(dialog.zone_list.count()):
        _set_checked(dialog, index, index == row)


def _extract(dialog: WorldDataDialog, output_directory: Path) -> None:
    """Run the extraction the dialog would start, synchronously and in-process.

    The worker reports through Qt signals queued across threads, which needs a running event
    loop, so the tests drive the same worker body directly and hand its summary to the same
    completion slot the signal would have reached.
    """

    directory = dialog.region_selector.currentData()
    assert isinstance(directory, Path)
    worker = WorldExtractionWorker(output_directory, MONSTER_IDS_PATH)
    captured: list[WorldExtractionSummary] = []
    worker.completed.connect(captured.append)
    worker._run(directory)
    dialog._on_extraction_completed(captured[0])


def test_only_client_directories_holding_a_world_script_are_listed(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)

    assert [
        dialog.region_selector.itemText(index) for index in range(dialog.region_selector.count())
    ] == ["wdtest"]
    assert dialog.extract_button.isEnabled()


def test_a_client_root_without_regions_says_so_instead_of_offering_nothing(
    tmp_path: Path,
) -> None:
    dialog = _dialog(tmp_path / "missing", tmp_path)

    assert dialog.region_selector.count() == 0
    assert not dialog.extract_button.isEnabled()
    assert str(tmp_path / "missing") in dialog.status_label.text()


def test_extraction_writes_the_map_and_reports_what_it_found(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)

    _extract(dialog, tmp_path / "worlds")

    saved = tmp_path / "worlds" / "wdtest.json"
    assert saved.is_file()
    world_map = load_world_map(saved)
    assert len(world_map.zones) == 2
    status = dialog.status_label.text()
    assert "2 spawn zones" in status
    assert "Flame" in status and "Rapra" in status
    assert str(saved) in status


def test_a_failed_extraction_reports_its_reason(client_root: Path, tmp_path: Path) -> None:
    dialog = _dialog(client_root, tmp_path)

    dialog._on_extraction_failed("terrain block is too short")

    assert "terrain block is too short" in dialog.status_label.text()
    assert dialog.extract_button.isEnabled()


def test_an_extracted_map_offers_its_zones_as_the_standing_position(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)

    _extract(dialog, tmp_path / "worlds")

    assert dialog.loaded_map is not None
    assert dialog.zone_list.count() == 2
    assert dialog.zone_list.item(0).text() == "Flame — 26 mobs at (100, 200)"
    assert dialog.activate_button.isEnabled()


def test_activation_requests_a_navigator_anchored_at_the_selected_zone(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)
    _extract(dialog, tmp_path / "worlds")
    dialog.quota_spin.setValue(7)
    requests: list[object] = []
    dialog.vector_navigation_requested.connect(requests.append)

    _check_only(dialog, 1)
    dialog._on_activate_clicked()

    request = requests[0]
    assert isinstance(request, VectorNavigationRequest)
    assert request.anchor_zone is not None
    assert request.anchor_zone.monster_name == "Rapra"
    assert [zone.monster_name for zone in request.active_zones] == ["Rapra"]
    assert request.goals == (ZoneGoal("Flame", 7), ZoneGoal("Rapra", 7))
    assert "Rapra" in dialog.status_label.text()


def test_several_checked_zones_are_all_armed_for_sequential_farming(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)
    _extract(dialog, tmp_path / "worlds")
    requests: list[object] = []
    dialog.vector_navigation_requested.connect(requests.append)

    _set_checked(dialog, 0, True)
    _set_checked(dialog, 1, True)
    dialog._on_activate_clicked()

    request = requests[0]
    assert isinstance(request, VectorNavigationRequest)
    assert [zone.monster_name for zone in request.active_zones] == ["Flame", "Rapra"]
    assert request.anchor_zone is not None
    assert request.anchor_zone.monster_name == "Flame"
    assert "2" in dialog.status_label.text()


def test_map_click_makes_that_camp_first_without_dropping_other_checked_zones(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)
    _extract(dialog, tmp_path / "worlds")
    _set_checked(dialog, 0, True)
    _set_checked(dialog, 1, True)
    requests: list[object] = []
    dialog.vector_navigation_requested.connect(requests.append)
    assert dialog.loaded_map is not None

    dialog.activate_zone(dialog.loaded_map.zones[1])

    request = requests[0]
    assert isinstance(request, VectorNavigationRequest)
    assert [zone.monster_name for zone in request.active_zones] == ["Rapra", "Flame"]
    assert request.anchor_zone is not None
    assert request.anchor_zone.monster_name == "Rapra"
    assert "Rapra" in dialog.status_label.text()


def test_selected_world_map_loads_its_sibling_navmesh_for_visualization(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)
    _extract(dialog, tmp_path / "worlds")
    mesh = NavMeshBaker().bake(
        (
            WorldTriangle(
                WorldVertex(0.0, 100.0, 0.0),
                WorldVertex(0.0, 100.0, 20.0),
                WorldVertex(20.0, 100.0, 0.0),
                "ground",
            ),
        )
    )
    save_baked_navmesh(mesh, world_navmesh_path(tmp_path / "worlds", "wdtest"))
    scenes: list[tuple[object, object]] = []
    dialog.world_map_changed.connect(lambda world_map, navmesh: scenes.append((world_map, navmesh)))

    dialog.refresh()

    assert dialog.map_selector.count() == 1
    assert dialog.loaded_navmesh is not None
    assert len(dialog.loaded_navmesh.polygons) == 1
    assert scenes[-1] == (dialog.loaded_map, dialog.loaded_navmesh)


def test_activation_is_refused_while_no_zone_is_checked(client_root: Path, tmp_path: Path) -> None:
    dialog = _dialog(client_root, tmp_path)
    _extract(dialog, tmp_path / "worlds")
    requests: list[object] = []
    dialog.vector_navigation_requested.connect(requests.append)

    _set_checked(dialog, 0, False)
    dialog._on_activate_clicked()

    assert not dialog.activate_button.isEnabled()
    assert requests == []


def test_refresh_and_reopened_dialog_restore_region_map_zone_and_quota(
    client_root: Path, tmp_path: Path
) -> None:
    write_world_directory(
        client_root,
        "wdother",
        region_records=[respawn_record(1453, (10.0, 92.0, 20.0), (0, 0, 20, 40), 1, 30)],
        blocks=[],
    )
    settings = QSettings(str(tmp_path / "world_data_dialog.ini"), QSettings.Format.IniFormat)
    dialog = _dialog(client_root, tmp_path, settings=settings)
    dialog.region_selector.setCurrentText("wdtest")
    _extract(dialog, tmp_path / "worlds")
    dialog.region_selector.setCurrentText("wdother")
    _check_only(dialog, 1)
    dialog.quota_spin.setValue(17)

    dialog.refresh()

    assert dialog.region_selector.currentText() == "wdother"
    assert dialog.map_selector.currentText() == "wdtest"
    assert [zone.monster_name for zone in dialog.active_zones] == ["Rapra"]
    assert dialog.quota_spin.value() == 17

    reopened = _dialog(client_root, tmp_path, settings=settings)

    assert reopened.region_selector.currentText() == "wdother"
    assert reopened.map_selector.currentText() == "wdtest"
    assert [zone.monster_name for zone in reopened.active_zones] == ["Rapra"]
    assert reopened.quota_spin.value() == 17


def test_a_selected_monster_narrows_the_goals_to_that_class(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)
    _extract(dialog, tmp_path / "worlds")
    dialog.set_target_mob("Rapra")
    requests: list[object] = []
    dialog.vector_navigation_requested.connect(requests.append)

    dialog._on_activate_clicked()

    request = requests[0]
    assert isinstance(request, VectorNavigationRequest)
    assert request.goals == (ZoneGoal("Rapra"),)


def test_an_unrestricted_selection_farms_every_extracted_class_in_turn(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)
    _extract(dialog, tmp_path / "worlds")
    dialog.set_target_mob(ALL_TARGET_MOBS)
    requests: list[object] = []
    dialog.vector_navigation_requested.connect(requests.append)

    dialog._on_activate_clicked()

    request = requests[0]
    assert isinstance(request, VectorNavigationRequest)
    assert [goal.monster_name for goal in request.goals] == ["Flame", "Rapra"]
    assert all(goal.kill_quota is None for goal in request.goals)


def test_deactivation_stops_dispatching_any_route(client_root: Path, tmp_path: Path) -> None:
    dialog = _dialog(client_root, tmp_path)
    cleared: list[bool] = []
    dialog.vector_navigation_cleared.connect(lambda: cleared.append(True))

    dialog._on_deactivate_clicked()

    assert cleared == [True]
    assert "no route" in dialog.status_label.text()


def test_switching_language_retranslates_every_label(client_root: Path, tmp_path: Path) -> None:
    dialog = _dialog(client_root, tmp_path)
    english = dialog.extract_button.text()

    dialog.set_translator(Translator(Language.GERMAN))

    assert dialog.extract_button.text() != english
    assert dialog.extract_button.text() == "Extrahieren"
    assert dialog.windowTitle() == "Weltdaten & Karten"


def test_clicking_extract_starts_the_worker_and_announces_the_region(
    client_root: Path, tmp_path: Path
) -> None:
    dialog = _dialog(client_root, tmp_path)

    dialog._on_extract_clicked()

    assert "wdtest" in dialog.status_label.text()
    assert not dialog.extract_button.isEnabled()
    dialog.close()


def test_a_second_extraction_is_refused_while_one_is_still_running(tmp_path: Path) -> None:
    """One region at a time keeps the output directory from being written twice at once."""

    worker = WorldExtractionWorker(tmp_path / "worlds")
    blocker = threading.Event()
    worker._thread = threading.Thread(target=blocker.wait, daemon=True)
    worker._thread.start()

    try:
        assert not worker.start(tmp_path)
    finally:
        blocker.set()
        worker.join(timeout_seconds=5.0)
