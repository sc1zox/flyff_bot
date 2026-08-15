"""Tests for the localized Qt dashboard and queued update bridge."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from flyff_bot.features.automation.models import (
    InventoryEntry,
    Position,
    SelectedTarget,
    TargetState,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.input_control import InputControlError, InputErrorCode
from flyff_bot.features.vision.models import CapturedFrame, ClientSize
from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.app import connect_farming_controls, start_farming
from flyff_bot.ui.dashboard import (
    BotStatus,
    CellSnapshot,
    DashboardFeed,
    DashboardUpdate,
    EdgeSnapshot,
    FarmingGoal,
    NavigationSnapshot,
)
from flyff_bot.ui.debug_overlay import DebugOverlayWidget, render_debug_overlay
from flyff_bot.ui.main_window import MainWindow
from flyff_bot.ui.path_inspector import PathInspectorWidget


def test_main_window_receives_dashboard_signal_and_renders_overlay() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    feed = DashboardFeed()
    feed.update_available.connect(window.update_dashboard)

    feed.publish(
        DashboardUpdate(
            _world_state(),
            BotStatus.RECONCILING,
            FarmingGoal("Sunstones", 500),
            _frame(),
        )
    )
    application.processEvents()

    assert window.windowTitle() == "Flyff Bot"
    assert window.status_label.text() == "Bot status: Healing / Reconciling"
    assert window.goal_label.text() == "Goal: 124/500 Sunstones"
    assert window.overlay_label.pixmap() is not None
    assert window.overlay_label.isHidden()

    window._debug_toggle.setChecked(True)
    assert not window.overlay_label.isHidden()


def test_controls_emit_intent_and_update_status() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.PAUSED))
    requested: list[str] = []
    window.start_requested.connect(lambda: requested.append("start"))
    window.pause_requested.connect(lambda: requested.append("pause"))
    window.emergency_stop_requested.connect(lambda: requested.append("emergency"))

    window.start_button.click()
    window.pause_button.click()
    window.emergency_stop_button.click()
    application.processEvents()

    assert requested == ["start", "pause", "emergency"]
    assert window.status_label.text() == "Bot status: Emergency Stopped"


def test_language_switch_retranslates_cached_dashboard() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE))

    window._language_selector.setCurrentIndex(0)
    application.processEvents()

    assert window.windowTitle() == "Flyff Bot"
    assert window.status_label.text() == "Bot-Status: Aktiv"
    assert window.start_button.text() == "Starten"


def test_attack_key_capture_defaults_to_f3_and_records_supported_keys() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    selected: list[int] = []
    window.attack_key_changed.connect(selected.append)

    assert window.attack_virtual_key == 0x72
    assert window.attack_key_button.text() == "F3"

    window.attack_key_button.click()
    QTest.keyClick(window.attack_key_button, Qt.Key.Key_F1)
    application.processEvents()

    assert window.attack_virtual_key == 0x70
    assert window.attack_key_button.text() == "F1"
    assert selected == [0x70]


def test_attack_key_capture_rejects_unsupported_key_without_changing_selection() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.attack_key_button.click()
    QTest.keyClick(window.attack_key_button, Qt.Key.Key_Shift)
    application.processEvents()

    assert window.attack_virtual_key == 0x72
    assert window.attack_key_button.text() == "F3"
    assert "Unsupported attack key" in window.attack_key_button.toolTip()


def test_farming_controls_connect_dashboard_intent() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    class Session:
        def __init__(self) -> None:
            self.requests: list[str] = []

        def start(self) -> None:
            self.requests.append("start")

        def pause(self) -> None:
            self.requests.append("pause")

        def emergency_stop(self) -> None:
            self.requests.append("stop")

        def save_navigation_profile(self, path: Path) -> None:
            self.requests.append(f"save:{path.name}")

        def load_navigation_profile(self, path: Path) -> None:
            self.requests.append(f"load:{path.name}")

        def reset_navigation_map(self) -> None:
            self.requests.append("reset")

    session = Session()
    connect_farming_controls(window, session)
    window.start_button.click()
    window.pause_button.click()
    window.emergency_stop_button.click()
    window.save_profile_requested.emit(Path("spot.json"))
    window.load_profile_requested.emit(Path("spot.json"))
    window.reset_navigation_requested.emit()
    application.processEvents()

    assert session.requests == [
        "start",
        "pause",
        "stop",
        "save:spot.json",
        "load:spot.json",
        "reset",
    ]


def test_start_farming_focuses_the_game_before_starting_the_session() -> None:
    calls: list[str] = []

    class Controller:
        def focus_window(self, window_handle: int) -> None:
            assert window_handle == 42
            calls.append("focus")

    class Session:
        def start(self) -> None:
            calls.append("start")

        def pause(self) -> None:
            calls.append("pause")

        def emergency_stop(self) -> None:
            return None

    start_farming(Controller(), 42, Session())

    assert calls == ["focus", "start"]


def test_start_farming_pauses_without_traceback_when_focus_fails() -> None:
    calls: list[str] = []

    class Controller:
        def focus_window(self, _window_handle: int) -> None:
            raise InputControlError(InputErrorCode.FOCUS_FAILED)

    class Session:
        def start(self) -> None:
            calls.append("start")

        def pause(self) -> None:
            calls.append("pause")

        def emergency_stop(self) -> None:
            return None

    start_farming(Controller(), 42, Session())

    assert calls == ["pause"]


def test_path_inspector_widget_renders_cleanly_with_populated_snapshot() -> None:
    _application = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    widget = PathInspectorWidget(translator)
    widget.resize(500, 350)

    # Render without snapshot
    widget.render(widget)

    # Render with populated snapshot
    cells = (
        CellSnapshot(x=0, y=0, center_x=20.0, center_y=20.0, visits=5, stalls=0, spawn_weight=2.5),
        CellSnapshot(x=1, y=0, center_x=60.0, center_y=20.0, visits=2, stalls=1, spawn_weight=0.0),
        CellSnapshot(x=1, y=1, center_x=60.0, center_y=60.0, visits=1, stalls=0, spawn_weight=5.0),
    )
    edges = (
        EdgeSnapshot(
            origin_x=20.0, origin_y=20.0, destination_x=60.0, destination_y=20.0, stalls=1
        ),
        EdgeSnapshot(
            origin_x=60.0, origin_y=20.0, destination_x=60.0, destination_y=60.0, stalls=0
        ),
    )
    snapshot = NavigationSnapshot(
        player_x=15.0,
        player_y=25.0,
        heading_degrees=45.0,
        cells=cells,
        edges=edges,
        waypoints=((60.0, 60.0),),
        safe_waypoint=(20.0, 20.0),
        cell_size_units=40.0,
        leash_radius_units=80.0,
    )
    widget.set_navigation(snapshot)
    assert widget.snapshot == snapshot
    widget.render(widget)

    # Retranslate
    widget.set_translator(Translator(Language.GERMAN))
    widget.render(widget)


def test_main_window_path_inspector_toggle_and_update() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    feed = DashboardFeed()
    feed.update_available.connect(window.update_dashboard)

    snapshot = NavigationSnapshot(
        player_x=0.0,
        player_y=0.0,
        heading_degrees=90.0,
        cells=(),
        edges=(),
        waypoints=(),
        safe_waypoint=None,
    )
    feed.publish(
        DashboardUpdate(
            _world_state(),
            BotStatus.ACTIVE,
            navigation=snapshot,
        )
    )
    application.processEvents()

    assert window.path_inspector.snapshot == snapshot
    assert window.path_inspector.isHidden()

    window.path_toggle.setChecked(True)
    assert not window.path_inspector.isHidden()

    window.path_toggle.setChecked(False)
    assert window.path_inspector.isHidden()


def test_debug_overlay_widget_renders_cleanly_with_aspect_scaling() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DebugOverlayWidget()
    widget.resize(400, 300)
    widget.render(widget)

    pixmap = render_debug_overlay(
        _frame(),
        (),
        SelectedTarget(TargetState.NONE, None, 0),
        Translator(Language.ENGLISH),
    )
    widget.setPixmap(pixmap)
    assert widget.pixmap() is pixmap
    assert widget.sizeHint().width() > 0
    assert widget.sizeHint().height() > 0
    widget.render(widget)


def test_main_window_debug_toggle_dynamically_adjusts_window_size() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.update_dashboard(
        DashboardUpdate(
            _world_state(),
            BotStatus.ACTIVE,
            FarmingGoal("Sunstones", 500),
            _frame(),
        )
    )
    window.show()
    application.processEvents()
    compact_height = window.height()

    window._debug_toggle.setChecked(True)
    application.processEvents()
    expanded_height = window.height()
    assert expanded_height > compact_height
    assert not window.overlay_label.isHidden()

    window._debug_toggle.setChecked(False)
    application.processEvents()
    assert window.overlay_label.isHidden()
    assert window.height() < expanded_height


def test_main_window_path_toggle_dynamically_adjusts_window_size() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    snapshot = NavigationSnapshot(
        player_x=0.0,
        player_y=0.0,
        heading_degrees=90.0,
        cells=(),
        edges=(),
        waypoints=(),
        safe_waypoint=None,
    )
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE, navigation=snapshot))
    window.show()
    application.processEvents()
    compact_height = window.height()

    window.path_toggle.setChecked(True)
    application.processEvents()
    expanded_height = window.height()
    assert expanded_height > compact_height
    assert not window.path_inspector.isHidden()

    window.path_toggle.setChecked(False)
    application.processEvents()
    assert window.path_inspector.isHidden()
    assert window.height() < expanded_height


def test_main_window_profile_bar_toggle_and_state_gating(tmp_path: Path) -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH), navigation_dir=tmp_path)
    assert window.profile_bar.isHidden()

    window.path_toggle.setChecked(True)
    assert not window.profile_bar.isHidden()

    # Active farming status disables profile controls
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE))
    assert not window.profile_selector.isEnabled()
    assert not window.profile_name_input.isEnabled()
    assert not window.save_profile_button.isEnabled()
    assert not window.load_profile_button.isEnabled()
    assert not window.reset_map_button.isEnabled()

    # Paused status enables profile controls
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.PAUSED))
    assert window.profile_selector.isEnabled()
    assert window.profile_name_input.isEnabled()
    assert window.save_profile_button.isEnabled()
    assert window.load_profile_button.isEnabled()
    assert window.reset_map_button.isEnabled()

    # Emergency stopped status enables profile controls
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.EMERGENCY_STOPPED))
    assert window.profile_selector.isEnabled()
    assert window.profile_name_input.isEnabled()
    assert window.save_profile_button.isEnabled()


def test_main_window_profile_save_and_load_signals(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH), navigation_dir=tmp_path)

    saved_paths: list[Path] = []
    loaded_paths: list[Path] = []
    window.save_profile_requested.connect(saved_paths.append)
    window.load_profile_requested.connect(loaded_paths.append)

    # Save
    window.profile_name_input.setText("flame_north")
    window.save_profile_button.click()
    application.processEvents()

    assert len(saved_paths) == 1
    assert saved_paths[0] == tmp_path / "flame_north.json"

    # Create dummy file so it exists for loading
    saved_paths[0].write_text("{}", encoding="utf-8")
    window.refresh_profiles(select_path=saved_paths[0])

    # Load
    window.load_profile_button.click()
    application.processEvents()

    assert loaded_paths == [saved_paths[0]]


def test_main_window_reset_map_dialog_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH), navigation_dir=tmp_path)

    reset_calls: list[bool] = []
    window.reset_navigation_requested.connect(lambda: reset_calls.append(True))

    # Reject / Cancel
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    window.reset_map_button.click()
    application.processEvents()
    assert reset_calls == []

    # Accept / Confirm
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    window.reset_map_button.click()
    application.processEvents()
    assert reset_calls == [True]


def test_main_window_close_event_emits_pause_requested() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    pause_calls: list[bool] = []
    window.pause_requested.connect(lambda: pause_calls.append(True))

    event = QCloseEvent()
    window.closeEvent(event)
    assert pause_calls == [True]


def _world_state() -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=1,
        inventory=(InventoryEntry("Sunstones", 124),),
        progress_marker=124,
        selected_target=SelectedTarget(TargetState.VALID, "Flame", 10),
        visible_mobs=(VisibleMob(0, "Flame", 0.9, 1, 1, 2, 2),),
    )


def _frame() -> CapturedFrame:
    pixels = np.zeros((10, 10, 3), dtype=np.uint8)
    return CapturedFrame(pixels, ClientSize(10, 10))
