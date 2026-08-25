"""Tests for the localized Qt dashboard and queued update bridge."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QScrollArea,
    QTableWidgetItem,
)

from flyff_bot.features.automation.controllers import CombatClassProfile
from flyff_bot.features.automation.emergency_recovery import EmergencyRecoveryConfig
from flyff_bot.features.automation.kill_goals import (
    KillGoalConfig,
    MobKillProgress,
    MobKillQuota,
)
from flyff_bot.features.automation.models import (
    InventoryEntry,
    MonsterStatsMetrics,
    MonsterStatsSource,
    MonsterStatsStatus,
    PlayerVitals,
    Position,
    SelectedTarget,
    TargetNameStatus,
    TargetState,
    TargetVerificationMetrics,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import PolicyRuntimeMode
from flyff_bot.features.automation.powerup_controller import PowerUpConfig, PowerUpEntry
from flyff_bot.features.automation.powerup_persistence import (
    load_powerup_config,
    save_powerup_config,
)
from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerConfig,
    VitalTriggerType,
)
from flyff_bot.features.diagnostics import SessionEvent, SessionEventKind
from flyff_bot.features.dungeons.models import (
    DungeonDefinition,
    DungeonStateSnapshot,
    DungeonStatus,
)
from flyff_bot.features.input_control import (
    InputControlError,
    InputErrorCode,
    ScreenRect,
    parse_virtual_key,
)
from flyff_bot.features.navigation.live_camera import CameraReadErrorCode
from flyff_bot.features.navigation.live_position import (
    PositionReadErrorCode,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.teleporter_extraction import save_teleporter_catalog
from flyff_bot.features.navigation.teleporter_models import (
    TeleporterCatalog,
    TeleporterDestination,
)
from flyff_bot.features.navigation.vector_navigation import VectorNavigationRequest
from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldDimensions,
    WorldVectorMap,
    save_world_map,
)
from flyff_bot.features.vision.models import CapturedFrame, ClientSize
from flyff_bot.features.vision.monster_stats import MonsterStatsConfig, compute_monster_stats_roi
from flyff_bot.features.vision.target_verification import TargetVerifier
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.app import (
    connect_farming_controls,
    connect_target_selection,
    start_farming,
    target_class_applier,
)
from flyff_bot.ui.dashboard import (
    BotStatus,
    DashboardFeed,
    DashboardUpdate,
    FarmingGoal,
    NavigationSnapshot,
    VectorZoneSnapshot,
    WindowStatus,
)
from flyff_bot.ui.debug_overlay import DebugOverlayWidget, render_debug_overlay
from flyff_bot.ui.main_window import DashboardTab, MainWindow
from flyff_bot.ui.navigation_window import NavigationMapWindow
from flyff_bot.ui.path_inspector import PathInspectorWidget
from flyff_bot.ui.placement_overlay import (
    GuideStyle,
    PlacementOverlayWindow,
    compute_placement_guides,
    logical_geometry,
)
from flyff_bot.ui.theme import apply_theme, load_theme_stylesheet

CLOSE_EVENT_WINDOW_HANDLE = 4711
CLOSE_EVENT_VISIT_TIME_SECONDS = 1.0

RESET_DESTINATION = TeleporterDestination(
    destination_id=7,
    name="Eden",
    search_text="Eden",
    world_id=2,
    anchor_x=100.0,
    anchor_z=200.0,
)
TELEPORTER_CATALOG = TeleporterCatalog((RESET_DESTINATION,))


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

    window.camera_preview_toggle.setChecked(True)
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
    QTest.keyClick(window, Qt.Key.Key_Escape)
    application.processEvents()

    assert requested == ["start", "pause", "emergency"]
    assert window.status_label.text() == "Bot status: Emergency Stopped"


def test_switching_tabs_does_not_emit_operator_or_configuration_intent() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    emitted: list[str] = []
    window.start_requested.connect(lambda: emitted.append("start"))
    window.pause_requested.connect(lambda: emitted.append("pause"))
    window.emergency_stop_requested.connect(lambda: emitted.append("stop"))
    window.auto_align_changed.connect(lambda _enabled: emitted.append("auto-align"))
    window.kill_verification_changed.connect(lambda _enabled: emitted.append("kill-check"))

    for tab in DashboardTab:
        window.tab_widget.setCurrentIndex(tab)
        application.processEvents()

    assert emitted == []


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

        def configure_policy_mode(self, mode: PolicyRuntimeMode) -> None:
            self.requests.append(f"policy:{mode.value}")

        def start(self) -> None:
            self.requests.append("start")

        def pause(self) -> None:
            self.requests.append("pause")

        def emergency_stop(self) -> None:
            self.requests.append("stop")

        def configure_vitals(self, config: VitalsTriggerConfig) -> None:
            self.requests.append("vitals")

        def configure_powerups(self, config: PowerUpConfig) -> None:
            self.requests.append("powerups")

        def configure_emergency_recovery(self, config: EmergencyRecoveryConfig) -> None:
            self.requests.append("emergency")

        def request_camera_alignment(self) -> None:
            self.requests.append("align")

        def configure_auto_align(self, enabled: bool) -> None:
            self.requests.append(f"auto_align:{enabled}")

    session = Session()
    connect_farming_controls(window, session)
    window.start_button.click()
    window.pause_button.click()
    window.tab_widget.setCurrentIndex(DashboardTab.DIAGNOSTICS_LOGS)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    window.align_camera_button.click()
    window.auto_align_toggle.setChecked(False)
    application.processEvents()

    assert session.requests == [
        "start",
        "pause",
        "stop",
        "align",
        "auto_align:False",
    ]


def test_main_window_align_camera_button_is_gated_on_an_idle_session() -> None:
    """US-042: the camera is only realigned while the session is not driving it."""

    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.PAUSED))
    assert window.align_camera_button.isEnabled()

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.SEARCH_ROTATING))
    assert not window.align_camera_button.isEnabled()

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ALIGNING))
    assert not window.align_camera_button.isEnabled()

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.EMERGENCY_STOPPED))
    assert not window.align_camera_button.isEnabled()

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ALIGNMENT_FAILED))
    assert window.align_camera_button.isEnabled()


def test_main_window_renders_localized_alignment_states() -> None:
    """US-042: alignment progress and failure are localized status badges."""

    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ALIGNING))
    assert "Aligning camera" in window.status_label.text()
    assert window.align_camera_button.text() == "Align Camera"
    assert window.auto_align_toggle.isChecked()

    german = MainWindow(Translator(Language.GERMAN))
    german.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ALIGNMENT_FAILED))
    assert "Kameraausrichtung" in german.status_label.text()
    assert german.align_camera_button.text() == "Kamera ausrichten"


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
    vzone = VectorZoneSnapshot(
        monster_name="Aibatt",
        center_x=20.0,
        center_y=20.0,
        half_width_pixels=20.0,
        half_depth_pixels=20.0,
        capacity=5,
    )
    snapshot = NavigationSnapshot(
        player_x=15.0,
        player_y=25.0,
        heading_degrees=45.0,
        position_source=PositionSource.LIVE,
        world_position=WorldPosition(15.0, 10.0, 25.0),
        world_waypoints=(WorldPosition(20.0, 10.0, 20.0),),
        vector_zones=(vzone,),
    )
    widget.set_navigation(snapshot)
    assert widget.snapshot == snapshot
    widget.render(widget)

    # Retranslate
    widget.set_translator(Translator(Language.GERMAN))
    widget.render(widget)


def test_main_window_path_inspector_stays_current_before_navigation_tab_is_selected() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    feed = DashboardFeed()
    feed.update_available.connect(window.update_dashboard)

    snapshot = NavigationSnapshot(
        player_x=0.0,
        player_y=0.0,
        heading_degrees=90.0,
        position_source=PositionSource.LIVE,
        world_position=WorldPosition(0.0, 10.0, 0.0),
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
    assert not window.path_inspector.isHidden()

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.NAVIGATION_WORLD)
    application.processEvents()
    assert window.path_inspector.isVisibleTo(window)


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
        monster_stats_config=MonsterStatsConfig(),
    )
    widget.setPixmap(pixmap)
    assert widget.pixmap() is pixmap
    assert widget.sizeHint().width() > 0
    assert widget.sizeHint().height() > 0
    widget.render(widget)


def test_debug_overlay_draws_monster_stats_calibration_guide_box() -> None:
    _application = QApplication.instance() or QApplication([])
    config = MonsterStatsConfig()
    frame = CapturedFrame(np.zeros((900, 1600, 3), dtype=np.uint8), ClientSize(1600, 900))

    pixmap = render_debug_overlay(
        frame,
        (),
        SelectedTarget(TargetState.NONE, None, 0),
        Translator(Language.ENGLISH),
        monster_stats_config=config,
        show_placements=True,
    )
    left, top, right, bottom = compute_monster_stats_roi(
        frame.client_size.width, frame.client_size.height, config
    )

    assert not pixmap.isNull()
    assert 0 <= left < right <= frame.client_size.width
    assert 0 <= top < bottom <= frame.client_size.height

    without_guide = render_debug_overlay(
        frame,
        (),
        SelectedTarget(TargetState.NONE, None, 0),
        Translator(Language.ENGLISH),
    )
    assert not without_guide.isNull()


def test_debug_overlay_placements_toggle_draws_vitals_and_target_guide_boxes() -> None:
    _application = QApplication.instance() or QApplication([])
    frame = CapturedFrame(np.zeros((300, 400, 3), dtype=np.uint8), ClientSize(400, 300))

    with_placements = render_debug_overlay(
        frame,
        (),
        SelectedTarget(TargetState.NONE, None, 0),
        Translator(Language.ENGLISH),
        monster_stats_config=MonsterStatsConfig(),
        show_placements=True,
    )
    without_placements = render_debug_overlay(
        frame,
        (),
        SelectedTarget(TargetState.NONE, None, 0),
        Translator(Language.ENGLISH),
        monster_stats_config=MonsterStatsConfig(),
        show_placements=False,
    )

    assert not with_placements.isNull()
    assert with_placements.toImage() != without_placements.toImage()


def test_main_window_camera_preview_does_not_resize_the_window() -> None:
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
    initial_size = window.size()

    window.camera_preview_toggle.setChecked(True)
    application.processEvents()
    assert not window.overlay_label.isHidden()
    assert window.size() == initial_size

    window.camera_preview_toggle.setChecked(False)
    application.processEvents()
    assert window.overlay_label.isHidden()
    assert window.size() == initial_size


def test_main_window_switching_functional_tabs_does_not_resize_the_window() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    snapshot = NavigationSnapshot(
        player_x=0.0,
        player_y=0.0,
        heading_degrees=90.0,
        waypoints=(),
    )
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE, navigation=snapshot))
    window.show()
    application.processEvents()
    initial_size = window.size()

    for tab in DashboardTab:
        window.tab_widget.setCurrentIndex(tab)
        application.processEvents()
        assert window.size() == initial_size


def test_main_window_navigation_tab_controls() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.NAVIGATION_WORLD)
    application.processEvents()
    assert window.world_data_button.isVisibleTo(window)
    assert window.path_inspector.isVisibleTo(window)


def test_navigation_map_follow_and_fit_controls_are_localized() -> None:
    _application = QApplication.instance() or QApplication([])
    window_en = MainWindow(Translator(Language.ENGLISH))
    window_de = MainWindow(Translator(Language.GERMAN))

    assert window_en.follow_player_button.text() == "Follow Player"
    assert window_en.fit_world_button.text() == "Fit World"
    assert window_de.follow_player_button.text() == "Spieler folgen"
    assert "Pos1" in window_de.follow_player_button.toolTip()


def test_navigation_tab_lazily_loads_the_restored_world_scene_and_map_click_activates_camp(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication([])
    zone = VectorSpawnZone(
        1453,
        50.0,
        10.0,
        60.0,
        40.0,
        50.0,
        60.0,
        70.0,
        12,
        30,
        "Flame",
    )
    save_world_map(
        WorldVectorMap("WdTest", WorldDimensions(1, 1, 1.0), zones=(zone,)),
        tmp_path / "worlds",
    )
    window = MainWindow(
        Translator(Language.ENGLISH),
        client_world_root=tmp_path / "client",
        world_map_dir=tmp_path / "worlds",
    )
    requests: list[object] = []
    window.vector_navigation_requested.connect(requests.append)
    assert window.world_data_dialog is None

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.NAVIGATION_WORLD)
    application.processEvents()

    assert window.world_data_dialog is not None
    assert window.path_inspector.world_map is not None
    assert window.path_inspector.world_map.world_name == "WdTest"
    point = window.path_inspector.world_to_screen(zone.centroid).toPoint()
    QTest.mouseClick(window.path_inspector, Qt.MouseButton.LeftButton, pos=point)
    application.processEvents()

    assert len(requests) == 1
    request = requests[0]
    assert isinstance(request, VectorNavigationRequest)
    assert request.anchor_zone == zone
    assert request.active_zones == (zone,)


def test_follow_player_control_centers_on_each_live_navigation_update() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.follow_player_button.click()

    for x, z in ((10.0, 20.0), (90.0, 120.0)):
        window.update_dashboard(
            DashboardUpdate(
                _world_state(),
                BotStatus.ACTIVE,
                navigation=NavigationSnapshot(
                    x,
                    z,
                    45.0,
                    position_source=PositionSource.LIVE,
                    world_position=WorldPosition(x, 5.0, z),
                ),
            )
        )
        application.processEvents()
        assert window.path_inspector.view_center.x == pytest.approx(x)
        assert window.path_inspector.view_center.z == pytest.approx(z)


def test_main_window_shows_live_gps_and_world_coordinates() -> None:
    application = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    window = MainWindow(translator)
    snapshot = NavigationSnapshot(
        player_x=123.0,
        player_y=789.0,
        heading_degrees=90.0,
        position_source=PositionSource.LIVE,
        world_position=WorldPosition(123.0, 45.0, 789.0),
    )

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE, navigation=snapshot))
    application.processEvents()

    assert window.gps_label.text() == translator.text(Message.UI_GPS_LIVE)
    assert window.gps_label.property("gps") == "live"
    assert "123.00" in window.gps_label.toolTip()
    assert "45.00" in window.gps_label.toolTip()
    assert "789.00" in window.gps_label.toolTip()

    fallback = replace(
        snapshot,
        position_source=PositionSource.UNAVAILABLE,
        position_error_code=PositionReadErrorCode.UNSUPPORTED_BUILD,
        world_position=None,
    )
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE, navigation=fallback))
    application.processEvents()

    assert window.gps_label.text() == translator.text(
        Message.UI_GPS_OFFLINE,
        reason=translator.text(Message.UI_GPS_ERROR_UNSUPPORTED_BUILD),
    )
    assert window.gps_label.property("gps") == "offline"
    assert "not fingerprinted" in window.gps_label.toolTip()
    assert window.camera_label.text() == translator.text(
        Message.UI_CAMERA_OFFLINE,
        reason=translator.text(Message.UI_GPS_UNAVAILABLE),
    )

    camera_fallback = replace(
        fallback,
        camera_error_code=CameraReadErrorCode.UNSUPPORTED_BUILD,
    )
    window.update_dashboard(
        DashboardUpdate(_world_state(), BotStatus.ACTIVE, navigation=camera_fallback)
    )
    application.processEvents()

    assert window.camera_label.text() == translator.text(
        Message.UI_CAMERA_OFFLINE,
        reason=translator.text(Message.UI_CAMERA_ERROR_UNSUPPORTED_BUILD),
    )
    assert window.camera_label.property("camera") == "offline"


def test_main_window_close_event_emits_pause_requested() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    pause_calls: list[bool] = []
    window.pause_requested.connect(lambda: pause_calls.append(True))

    event = QCloseEvent()
    window.closeEvent(event)
    assert pause_calls == [True]


def test_main_window_renders_live_vitals() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    state = replace(
        _world_state(),
        player_vitals=PlayerVitals(hp_percentage=85.5, mp_percentage=60.0, fp_percentage=42.3),
    )
    window.update_dashboard(DashboardUpdate(state, BotStatus.ACTIVE))
    application.processEvents()

    assert "HP 85.5%" in window.vitals_label.text()
    assert "MP 60.0%" in window.vitals_label.text()
    assert "FP 42.3%" in window.vitals_label.text()


def test_main_window_vitals_panel_in_tab_and_config_signals(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH), vitals_config_path=tmp_path / "vitals.json")

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.VITALS_BUFFS)
    application.processEvents()
    assert window.vitals_panel.isVisibleTo(window)

    configs: list[VitalsTriggerConfig] = []
    window.vitals_config_changed.connect(configs.append)

    window.hp_threshold_spin.setValue(85)
    application.processEvents()

    assert len(configs) >= 1
    latest = configs[-1]
    hp_rule = latest.rule_for(VitalTriggerType.HP)
    assert hp_rule is not None
    assert hp_rule.threshold_percentage == 85.0


def test_main_window_placements_toggle_renders_guide_boxes_immediately() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    frame = CapturedFrame(np.zeros((300, 400, 3), dtype=np.uint8), ClientSize(400, 300))
    window.update_dashboard(
        DashboardUpdate(_world_state(), BotStatus.ACTIVE, FarmingGoal("Sunstones", 500), frame)
    )
    application.processEvents()
    before = window.overlay_label.pixmap()
    assert before is not None
    image_before = before.toImage()

    window.placements_toggle.setChecked(True)
    application.processEvents()

    after = window.overlay_label.pixmap()
    assert after is not None
    assert after.toImage() != image_before


def test_main_window_placements_toggle_label_localized() -> None:
    _application = QApplication.instance() or QApplication([])
    window_en = MainWindow(Translator(Language.ENGLISH))
    assert window_en.placements_toggle.text() == "Placements"

    window_de = MainWindow(Translator(Language.GERMAN))
    assert window_de.placements_toggle.text() == "Platzierungshilfen"


def test_main_window_combat_panel_in_tab_and_config_signals() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.COMBAT_TARGETS)
    application.processEvents()
    assert window.combat_panel.isVisibleTo(window)

    grace_values: list[float] = []
    kill_verification_values: list[bool] = []
    window.combat_grace_changed.connect(grace_values.append)
    window.kill_verification_changed.connect(kill_verification_values.append)

    window.target_grace_spin.setValue(1.5)
    # Kill verification is on by default, so toggling it off is the observable change.
    window.kill_verification_toggle.setChecked(False)
    application.processEvents()

    assert grace_values[-1] == pytest.approx(1.5)
    assert kill_verification_values == [False]


def test_main_window_combat_class_and_distance_signals_are_wired(tmp_path: Path) -> None:
    del tmp_path
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.COMBAT_TARGETS)
    application.processEvents()

    class_values: list[object] = []
    distance_values: list[float] = []
    window.combat_class_changed.connect(class_values.append)
    window.engagement_distance_changed.connect(distance_values.append)

    window.combat_class_selector.setCurrentIndex(
        list(CombatClassProfile).index(CombatClassProfile.RANGED)
    )
    application.processEvents()
    assert class_values == [CombatClassProfile.RANGED]
    assert window.engagement_distance_spin.value() == pytest.approx(15.0)
    assert distance_values == [pytest.approx(15.0)]

    window.combat_class_selector.setCurrentIndex(
        list(CombatClassProfile).index(CombatClassProfile.CUSTOM)
    )
    application.processEvents()
    window.engagement_distance_spin.setValue(8.5)
    application.processEvents()
    assert class_values[-1] is CombatClassProfile.CUSTOM
    assert distance_values[-1] == pytest.approx(8.5)


def test_main_window_target_debug_panel_in_tab_and_renders_failure_metrics() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.DIAGNOSTICS_LOGS)
    application.processEvents()
    assert window.target_debug_panel.isVisibleTo(window)

    target = SelectedTarget(
        TargetState.WRONG,
        None,
        3,
        15.0,
        TargetVerificationMetrics(
            anchor_score=0.95,
            anchor_threshold=0.9,
            anchor_passed=True,
            minimum_hp_pixel_count=10,
            hp_pixel_count=3,
            hp_percentage=15.0,
            hp_passed=False,
            name_candidate=None,
            name_text="Flame <Lvl 175>",
            name_status=TargetNameStatus.MATCHED,
            name_passed=True,
        ),
    )
    window.update_dashboard(
        DashboardUpdate(replace(_world_state(), selected_target=target), BotStatus.ACTIVE)
    )
    application.processEvents()

    assert window.target_anchor_value.text() == "PASS 0.95 / 0.90"
    assert window.target_hp_value.text() == "FAIL 3 px (15.0%)"
    assert window.target_name_value.text() == "PASS 'Flame <Lvl 175>' → none"
    assert window.target_state_value.text() == "Wrong target"
    assert window.target_reason_value.text() == "HP bar below minimum pixel threshold"


def test_main_window_monster_stats_panel_in_tab_and_renders_a_successful_reading() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.DIAGNOSTICS_LOGS)
    application.processEvents()
    assert window.monster_stats_panel.isVisibleTo(window)

    metrics = MonsterStatsMetrics(
        anchor_configured=True,
        anchor_score=0.93,
        anchor_threshold=0.85,
        anchor_passed=True,
        roi_width=145,
        roi_height=20,
        raw_text="Monster Kills: 12",
        parsed_count=12,
        status=MonsterStatsStatus.OK,
    )
    window.update_dashboard(
        DashboardUpdate(replace(_world_state(), monster_stats=metrics), BotStatus.ACTIVE)
    )
    application.processEvents()

    assert window.monster_anchor_value.text() == "PASS 0.93 / 0.85"
    assert window.monster_roi_value.text() == "145 x 20 px"
    assert window.monster_kills_value.text() == "12"
    assert window.monster_text_value.text() == "Monster Kills: 12"
    assert window.monster_status_value.text() == "OK"


def test_main_window_monster_stats_panel_reports_a_failed_reading_and_stays_updated() -> None:
    """The panel renders off-tab, so it is current the moment Diagnostics opens."""

    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    metrics = MonsterStatsMetrics(
        anchor_configured=True,
        anchor_score=0.42,
        anchor_threshold=0.85,
        status=MonsterStatsStatus.NO_MATCH,
        source=MonsterStatsSource.FIXED_REGION,
    )
    window.update_dashboard(
        DashboardUpdate(replace(_world_state(), monster_stats=metrics), BotStatus.STANDBY)
    )
    application.processEvents()

    window.show()
    assert not window.monster_stats_panel.isVisibleTo(window)
    assert window.monster_anchor_value.text() == "FAIL 0.42 / 0.85"
    assert window.monster_kills_value.text() == "Not recognized"
    assert window.monster_text_value.text() == "No text recognized"
    assert window.monster_status_value.text() == "No kill counter found in the text"
    # A missed anchor still reads, so the panel must name which crop produced the number.
    assert window.monster_source_value.text() == "Predefined placement region"

    window.tab_widget.setCurrentIndex(DashboardTab.DIAGNOSTICS_LOGS)
    application.processEvents()
    assert window.monster_stats_panel.isVisibleTo(window)


def test_main_window_monster_stats_panel_marks_an_unconfigured_anchor() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    metrics = MonsterStatsMetrics(
        anchor_configured=False,
        roi_width=174,
        roi_height=90,
        raw_text="Level 42",
        status=MonsterStatsStatus.NO_MATCH,
    )
    window.update_dashboard(
        DashboardUpdate(replace(_world_state(), monster_stats=metrics), BotStatus.STANDBY)
    )
    application.processEvents()

    assert "predefined placement region" in window.monster_anchor_value.text()
    assert "No anchor template configured" not in window.monster_anchor_value.text()
    assert window.monster_status_value.text() == "No kill counter found in the text"


def test_main_window_monster_stats_panel_names_an_unavailable_ocr_engine() -> None:
    """A missing Tesseract install must not read as a generic recognition failure."""

    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.update_dashboard(
        DashboardUpdate(
            replace(
                _world_state(),
                monster_stats=MonsterStatsMetrics(
                    status=MonsterStatsStatus.ENGINE_UNAVAILABLE, roi_width=145, roi_height=20
                ),
            ),
            BotStatus.STANDBY,
        )
    )
    application.processEvents()

    engine_unavailable = window.monster_status_value.text()
    window.update_dashboard(
        DashboardUpdate(
            replace(
                _world_state(),
                monster_stats=MonsterStatsMetrics(status=MonsterStatsStatus.OCR_FAILED),
            ),
            BotStatus.STANDBY,
        )
    )
    application.processEvents()

    assert engine_unavailable.strip()
    assert engine_unavailable != window.monster_status_value.text()


def test_main_window_monster_stats_panel_renders_in_german_locale() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.GERMAN))

    window.update_dashboard(
        DashboardUpdate(
            replace(
                _world_state(),
                monster_stats=MonsterStatsMetrics(status=MonsterStatsStatus.OCR_FAILED),
            ),
            BotStatus.STANDBY,
        )
    )
    application.processEvents()

    assert window.monster_stats_panel.title() == "Monster-Stats-Debug"
    assert window.monster_status_value.text() == "OCR fehlgeschlagen"
    assert window.monster_kills_value.text() == "Nicht erkannt"


def test_main_window_target_threshold_controls_emit_live_configuration() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.anchor_threshold_spin.value() == pytest.approx(0.75)
    assert window.anchor_threshold_spin.minimum() == pytest.approx(0.3)
    assert window.anchor_threshold_spin.maximum() == pytest.approx(1.0)

    thresholds: list[float] = []
    window.anchor_threshold_changed.connect(thresholds.append)

    window.anchor_threshold_spin.setValue(0.6)
    application.processEvents()

    assert thresholds[-1] == pytest.approx(0.6)


def test_target_threshold_controls_reconfigure_a_running_verifier() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    template = np.full((2, 2, 3), 7, dtype=np.uint8)
    verifier = TargetVerifier(("Flame",), template, _StubTextRecognizer())
    window.anchor_threshold_changed.connect(verifier.update_anchor_threshold)

    window.anchor_threshold_spin.setValue(0.55)
    application.processEvents()

    assert verifier.config.anchor_match_threshold == pytest.approx(0.55)


def test_main_window_target_threshold_labels_localized() -> None:
    _application = QApplication.instance() or QApplication([])

    window_en = MainWindow(Translator(Language.ENGLISH))
    window_de = MainWindow(Translator(Language.GERMAN))

    assert window_en.anchor_threshold_spin.toolTip().startswith("Minimum template match score")
    assert window_de.anchor_threshold_spin.toolTip().startswith("Mindestwert der Vorlagen")


def test_main_window_target_debug_shows_measured_metrics_without_an_accepted_anchor() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    target = SelectedTarget(
        TargetState.NONE,
        None,
        0,
        0.0,
        TargetVerificationMetrics(
            anchor_score=0.72,
            anchor_threshold=0.75,
            anchor_passed=False,
            minimum_hp_pixel_count=10,
            hp_pixel_count=1049,
            hp_percentage=100.0,
            hp_passed=True,
            name_candidate=None,
            name_status=TargetNameStatus.NOT_EVALUATED,
            name_passed=False,
        ),
    )
    window.update_dashboard(
        DashboardUpdate(replace(_world_state(), selected_target=target), BotStatus.ACTIVE)
    )
    application.processEvents()

    assert window.target_anchor_value.text() == "FAIL 0.72 / 0.75"
    assert window.target_hp_value.text() == "PASS 1049 px (100.0%)"
    assert window.target_name_value.text() == "Not evaluated without a target header"
    assert window.target_reason_value.text() == "Header anchor not detected"


def test_main_window_target_debug_renders_valid_target_criteria_met() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    target = SelectedTarget(
        TargetState.VALID,
        "Flame",
        45,
        100.0,
        TargetVerificationMetrics(
            anchor_score=0.95,
            anchor_threshold=0.9,
            anchor_passed=True,
            minimum_hp_pixel_count=10,
            hp_passed=True,
            name_candidate="Flame",
            name_text="Flame <Lvl 175>",
            name_status=TargetNameStatus.MATCHED,
            name_passed=True,
        ),
    )
    window.update_dashboard(
        DashboardUpdate(replace(_world_state(), selected_target=target), BotStatus.ACTIVE)
    )
    application.processEvents()

    assert window.target_name_value.text() == "PASS 'Flame <Lvl 175>' → Flame"
    assert window.target_state_value.text() == "Valid target"
    assert window.target_reason_value.text() == "Criteria met"


def test_main_window_target_debug_renders_cleanly_in_german_locale() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.GERMAN))

    target = SelectedTarget(
        TargetState.NONE,
        None,
        0,
        0.0,
        TargetVerificationMetrics(anchor_score=0.2, anchor_threshold=0.9, anchor_passed=False),
    )
    window.update_dashboard(
        DashboardUpdate(replace(_world_state(), selected_target=target), BotStatus.ACTIVE)
    )

    assert window.target_state_value.text() == "Kein Ziel"
    assert window.target_reason_value.text() == "Kopf-Anker nicht erkannt"
    assert "FEHLGESCHLAGEN" in window.target_anchor_value.text()


def test_theme_stylesheet_loading_and_fallback(tmp_path: Path) -> None:
    # Valid stylesheet contains core action selectors
    stylesheet = load_theme_stylesheet()
    assert "#ActionStart" in stylesheet
    assert "#ActionPause" in stylesheet
    assert "#StatusBadge" in stylesheet
    assert "QTabWidget::pane" in stylesheet
    assert "QTabBar::tab:selected" in stylesheet
    assert "QScrollArea" in stylesheet
    assert "QCheckBox#Switch::indicator" in stylesheet

    # Fallback safely when path does not exist
    invalid_path = tmp_path / "non_existent.qss"
    assert load_theme_stylesheet(invalid_path) == ""

    # apply_theme works without error on QApplication or widgets
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(Translator(Language.ENGLISH))
    apply_theme(window)


def test_main_window_escape_key_triggers_emergency_stop() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE))

    stopped: list[bool] = []
    window.emergency_stop_requested.connect(lambda: stopped.append(True))

    QTest.keyClick(window, Qt.Key.Key_Escape)
    application.processEvents()

    assert stopped == [True]
    assert window.status_label.text() == "Bot status: Emergency Stopped"
    assert window.status_label.property("status") == "emergency_stopped"


def test_navigation_map_window_escape_key_triggers_emergency_stop() -> None:
    application = QApplication.instance() or QApplication([])
    map_window = NavigationMapWindow(Translator(Language.ENGLISH))

    stopped: list[bool] = []
    map_window.emergency_stop_requested.connect(lambda: stopped.append(True))

    QTest.keyClick(map_window, Qt.Key.Key_Escape)
    application.processEvents()

    assert stopped == [True]


def test_navigation_map_popout_and_dock_lifecycle() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert not window.is_map_popped_out
    assert window.map_window.isHidden()
    assert window.popout_map_button.text() == "Pop-out Map"

    # Pop-out map
    window.popout_map_button.click()
    application.processEvents()

    assert window.is_map_popped_out
    assert not window.map_window.isHidden()
    assert window.map_window.inspector is window.path_inspector
    assert window.popout_map_button.text() == "Dock Map"

    # Dock map back
    window.popout_map_button.click()
    application.processEvents()

    assert not window.is_map_popped_out
    assert window.map_window.isHidden()
    assert window.map_window.inspector is None
    assert window.popout_map_button.text() == "Pop-out Map"

    # Pop-out again and test window close docking
    window.popout_map_button.click()
    application.processEvents()
    assert window.is_map_popped_out

    window.map_window.close()
    application.processEvents()
    assert not window.is_map_popped_out
    assert window.popout_map_button.text() == "Pop-out Map"


def test_main_window_tab_hierarchy_and_object_names() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.start_button.objectName() == "ActionStart"
    assert window.pause_button.objectName() == "ActionPause"
    assert window.status_label.objectName() == "StatusBadge"
    assert window.goal_label.objectName() == "StatChip"
    assert window.vitals_label.objectName() == "StatChip"
    assert window.camera_preview_toggle.objectName() == "Switch"
    assert window.auto_align_toggle.objectName() == "Switch"
    assert window.kill_verification_toggle.objectName() == "Switch"

    assert window.status_card.title() == "Status & Telemetry"
    assert window.controls_card.title() == "Controls"
    assert not window.tab_widget.isAncestorOf(window.status_card)
    assert not window.tab_widget.isAncestorOf(window.controls_card)
    assert not hasattr(window, "emergency_stop_button")

    expected_labels = [
        "Dashboard",
        "Combat & Targets",
        "Vitals & Buffs",
        "Quest Goals",
        "Dungeons & Cooldowns",
        "Navigation & World",
        "Diagnostics & Logs",
    ]
    assert window.tab_widget.count() == len(DashboardTab)
    assert [window.tab_widget.tabText(index) for index in range(window.tab_widget.count())] == (
        expected_labels
    )
    assert all(window.tab_widget.tabToolTip(index) for index in range(window.tab_widget.count()))

    for tab in DashboardTab:
        scroll_area = window.tab_scroll_area(tab)
        assert isinstance(scroll_area, QScrollArea)
        assert scroll_area.widgetResizable()
        assert scroll_area.sizeAdjustPolicy() is QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored

    combat_page = window.tab_scroll_area(DashboardTab.COMBAT_TARGETS).widget()
    vitals_page = window.tab_scroll_area(DashboardTab.VITALS_BUFFS).widget()
    navigation_page = window.tab_scroll_area(DashboardTab.NAVIGATION_WORLD).widget()
    diagnostics_page = window.tab_scroll_area(DashboardTab.DIAGNOSTICS_LOGS).widget()
    assert combat_page is not None
    assert vitals_page is not None
    assert navigation_page is not None
    assert diagnostics_page is not None
    assert combat_page.isAncestorOf(window.target_panel)
    assert vitals_page.isAncestorOf(window.powerup_panel)
    assert navigation_page.isAncestorOf(window.world_data_button)
    assert diagnostics_page.isAncestorOf(window.event_log_panel)
    quest_page = window.tab_scroll_area(DashboardTab.QUEST_GOALS).widget()
    assert quest_page is not None
    assert quest_page.isAncestorOf(window.quest_panel)
    dungeon_page = window.tab_scroll_area(DashboardTab.DUNGEONS_COOLDOWNS).widget()
    assert dungeon_page is not None
    assert dungeon_page.isAncestorOf(window.dungeon_panel)


def test_main_window_dungeon_panel_renders_extracted_and_live_rows() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.tab_widget.setCurrentIndex(DashboardTab.DUNGEONS_COOLDOWNS)
    definition = DungeonDefinition(101, "Ominous", 60, 300, 3600)

    window.update_dashboard(
        DashboardUpdate(
            _world_state(),
            BotStatus.ACTIVE,
            dungeons=(
                DungeonStateSnapshot(definition, DungeonStatus.ON_COOLDOWN, 3661.0, 2, 3),
                DungeonStateSnapshot(
                    definition, DungeonStatus.UNKNOWN, diagnostic_code="unconfigured_profile"
                ),
            ),
        )
    )
    application.processEvents()

    table = window.dungeon_panel.table
    assert window.dungeon_panel.title() == "Dungeons & Cooldowns"
    status_items = [table.item(row, 2) for row in range(table.rowCount())]
    assert all(item is not None for item in status_items)
    assert all(isinstance(item, QTableWidgetItem) for item in status_items)
    status_texts = [item.text() if item is not None else "" for item in status_items]
    assert status_texts == [
        "On cooldown",
        "Unknown (unconfigured_profile)",
    ]
    cooldown_item = table.item(0, 3)
    assert cooldown_item is not None
    cooldown_text = cooldown_item.text() if cooldown_item is not None else ""
    assert cooldown_text == "01:01:01"


def test_main_window_tab_labels_and_tooltips_retranslate_in_place() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    original_scroll_area = window.tab_scroll_area(DashboardTab.NAVIGATION_WORLD)
    window.tab_widget.setCurrentIndex(DashboardTab.NAVIGATION_WORLD)

    window._language_selector.setCurrentIndex(0)
    application.processEvents()

    assert [window.tab_widget.tabText(index) for index in range(window.tab_widget.count())] == [
        "Übersicht",
        "Kampf & Ziele",
        "Vitals & Buffs",
        "Quest-Ziele",
        "Dungeons & Abklingzeiten",
        "Navigation & Karte",
        "Diagnose & Tools",
    ]
    assert all(window.tab_widget.tabToolTip(index) for index in range(window.tab_widget.count()))
    assert window.tab_widget.currentIndex() == DashboardTab.NAVIGATION_WORLD
    assert window.tab_scroll_area(DashboardTab.NAVIGATION_WORLD) is original_scroll_area


def test_main_window_status_badge_dynamic_property() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE))
    assert window.status_label.property("status") == "active"

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.PAUSED))
    assert window.status_label.property("status") == "paused"

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.EMERGENCY_STOPPED))
    assert window.status_label.property("status") == "emergency_stopped"

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.RECONCILING))
    assert window.status_label.property("status") == "reconciling"

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.SEARCH_ROTATING))
    assert window.status_label.property("status") == "search"

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.STANDBY))
    assert window.status_label.property("status") == "standby"

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.COMBAT))
    assert window.status_label.property("status") == "combat"


def test_main_window_separates_bot_status_from_mob_and_target_telemetry() -> None:
    """Regression for BUG-007: the badge must not be overwritten by the mob count."""

    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.status_label.text() == "Bot status: Paused"
    assert window.mob_label.text() == "Visible mobs: 0"

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.STANDBY))

    assert window.status_label.text() == "Bot status: Ready (live preview)"
    assert window.mob_label.text() == "Visible mobs: 1"
    assert window.target_label.text() == "Valid target"
    assert window.goal_label.text() == "Goal: none configured"


def test_main_window_reports_the_game_window_state() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.window_label.text() == "Game window not found"

    window.set_window_status(WindowStatus.MINIMIZED)
    assert window.window_label.text() == "Game window minimized"

    window.update_dashboard(
        DashboardUpdate(_world_state(), BotStatus.STANDBY, window=WindowStatus.NOT_FOREGROUND)
    )
    assert window.window_label.text() == "Game window: not in foreground"

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.ACTIVE))
    assert window.window_label.text() == "Game window: in foreground"


def test_main_window_keeps_the_window_state_across_local_status_changes() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.update_dashboard(
        DashboardUpdate(_world_state(), BotStatus.STANDBY, window=WindowStatus.NOT_FOREGROUND)
    )

    window.start_button.click()

    assert window.window_label.text() == "Game window: not in foreground"


def test_main_window_localizes_the_window_state_for_german_operators() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.GERMAN))

    window.set_window_status(WindowStatus.NOT_FOUND)

    assert window.window_label.text() == "Spielfenster nicht gefunden"
    assert window.status_label.text() == "Bot-Status: Pausiert"


def test_placement_guides_cover_the_vitals_gauges_target_and_monster_stats_regions() -> None:
    client_size = ClientSize(1920, 1080)

    guides = compute_placement_guides(
        client_size, Translator(Language.ENGLISH), MonsterStatsConfig()
    )

    assert len(guides) == 6
    labeled = [guide for guide in guides if guide.label is not None]
    assert len(labeled) == 3
    assert all(guide.style is GuideStyle.DASHED for guide in labeled)
    assert all(guide.style is GuideStyle.SOLID for guide in guides if guide.label is None)
    for guide in guides:
        assert 0 <= guide.left < guide.right <= client_size.width
        assert 0 <= guide.top < guide.bottom <= client_size.height


def test_placement_guides_omit_the_monster_stats_box_without_a_configuration() -> None:
    guides = compute_placement_guides(ClientSize(1920, 1080), Translator(Language.ENGLISH))

    assert len(guides) == 5
    assert [guide.label for guide in guides].count(None) == 3


def test_logical_geometry_converts_physical_pixels_for_scaled_displays() -> None:
    bounds = ScreenRect(left=100, top=200, width=1920, height=1080)

    assert logical_geometry(bounds, 1.0) == (100, 200, 1920, 1080)
    assert logical_geometry(bounds, 1.5) == (67, 133, 1280, 720)
    assert logical_geometry(bounds, 2.0) == (50, 100, 960, 540)
    assert logical_geometry(bounds, 0.0) == (100, 200, 1920, 1080)


def test_placement_overlay_tracks_client_geometry_and_hides_when_unavailable() -> None:
    _application = QApplication.instance() or QApplication([])
    provider = _FakeGeometryProvider(ScreenRect(left=40, top=60, width=800, height=600))
    overlay = PlacementOverlayWindow(Translator(Language.ENGLISH))

    overlay.attach_target(provider, 4242)
    assert overlay.isHidden()

    overlay.set_guides_visible(True)
    assert provider.requested_handles == [4242]
    assert overlay.isVisible()
    assert overlay.geometry().left() == 40
    assert overlay.geometry().top() == 60
    assert overlay.client_size == ClientSize(800, 600)
    overlay.render(overlay)

    provider.bounds = None
    overlay.refresh_geometry()
    assert overlay.isHidden()

    provider.bounds = ScreenRect(left=0, top=0, width=1024, height=768)
    overlay.refresh_geometry()
    assert overlay.isVisible()

    overlay.set_guides_visible(False)
    assert overlay.isHidden()
    overlay.stop()


def test_placement_overlay_never_takes_focus_from_the_game_window() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PlacementOverlayWindow(Translator(Language.ENGLISH))

    flags = overlay.windowFlags()

    assert flags & Qt.WindowType.WindowTransparentForInput
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.FramelessWindowHint
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    overlay.stop()


def test_main_window_placements_toggle_drives_the_desktop_guide_overlay() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    provider = _FakeGeometryProvider(ScreenRect(left=10, top=20, width=1280, height=720))
    window.attach_placement_target(provider, 77)

    window.placements_toggle.setChecked(True)
    application.processEvents()
    assert window.placement_overlay.isVisible()
    assert window.placement_overlay.client_size == ClientSize(1280, 720)

    window.placements_toggle.setChecked(False)
    application.processEvents()
    assert window.placement_overlay.isHidden()

    window.close()


def test_main_window_close_event_stops_the_placement_overlay() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    provider = _FakeGeometryProvider(ScreenRect(left=0, top=0, width=640, height=480))
    window.attach_placement_target(provider, 5)
    window.placements_toggle.setChecked(True)

    window.closeEvent(QCloseEvent())

    assert window.placement_overlay.isHidden()


class _StubTextRecognizer:
    """A recognizer stand-in for tests that never reach the OCR boundary."""

    def recognize(self, image: npt.NDArray[np.uint8]) -> tuple[str, ...]:
        return ()


class _FakeGeometryProvider:
    """Deterministic client-geometry source standing in for the Win32 adapter."""

    def __init__(self, bounds: ScreenRect | None) -> None:
        self.bounds = bounds
        self.requested_handles: list[int] = []

    def client_screen_bounds(self, window_handle: int) -> ScreenRect | None:
        self.requested_handles.append(window_handle)
        return self.bounds


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


def test_main_window_powerup_panel_adds_edits_and_removes_rows(tmp_path: Path) -> None:
    """US-016: the panel manages an arbitrary number of persisted timed hotkeys."""

    application = QApplication.instance() or QApplication([])
    config_path = tmp_path / "powerups.json"
    window = MainWindow(Translator(Language.ENGLISH), powerup_config_path=config_path)
    panel = window.powerup_panel

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.VITALS_BUFFS)
    application.processEvents()
    assert panel.isVisibleTo(window)
    assert panel.rows == ()
    initial_size = window.size()

    configs: list[PowerUpConfig] = []
    window.powerup_config_changed.connect(configs.append)

    panel.add_button.click()
    panel.add_button.click()
    application.processEvents()
    assert len(panel.rows) == 2
    assert window.size() == initial_size

    first_row = panel.rows[0]
    first_row.name_input.setText("Grilled Eel")
    first_row.key_combo.setCurrentText("F5")
    first_row.interval_spin.setValue(300)
    panel.rows[1].enabled_check.setChecked(False)
    application.processEvents()

    latest = configs[-1]
    assert latest.entries[0].label == "Grilled Eel"
    assert latest.entries[0].virtual_key == parse_virtual_key("F5")
    assert latest.entries[0].interval_seconds == 300
    assert latest.entries[1].enabled is False
    assert load_powerup_config(config_path).entries == latest.entries

    panel.rows[1].remove_button.click()
    application.processEvents()

    assert len(panel.rows) == 1
    assert len(load_powerup_config(config_path).entries) == 1


def test_main_window_restores_persisted_powerups_on_construction(tmp_path: Path) -> None:
    """US-016: configured entries survive an application restart."""

    _application = QApplication.instance() or QApplication([])
    config_path = tmp_path / "powerups.json"
    save_powerup_config(
        PowerUpConfig(
            entries=(
                PowerUpEntry(
                    virtual_key=parse_virtual_key("F7"),
                    interval_seconds=45,
                    label="Upcut Stone",
                    enabled=False,
                ),
            )
        ),
        config_path,
    )

    window = MainWindow(Translator(Language.ENGLISH), powerup_config_path=config_path)

    assert len(window.powerup_panel.rows) == 1
    row = window.powerup_panel.rows[0]
    assert row.name_input.text() == "Upcut Stone"
    assert row.key_combo.currentText() == "F7"
    assert row.interval_spin.value() == 45
    assert row.enabled_check.isChecked() is False
    assert window.get_powerup_config().entries[0].label == "Upcut Stone"


def test_main_window_skips_out_of_range_persisted_powerup_intervals(tmp_path: Path) -> None:
    """A hand-edited interval must be dropped by the loader, never reach the panel."""

    _application = QApplication.instance() or QApplication([])
    config_path = tmp_path / "powerups.json"
    config_path.write_text(
        json.dumps(
            {"entries": [{"virtual_key": parse_virtual_key("F4"), "interval_seconds": 999999}]}
        ),
        encoding="utf-8",
    )

    window = MainWindow(Translator(Language.ENGLISH), powerup_config_path=config_path)

    assert window.powerup_panel.rows == ()


def test_main_window_powerup_labels_are_localized() -> None:
    _application = QApplication.instance() or QApplication([])

    window_en = MainWindow(Translator(Language.ENGLISH))
    assert window_en.powerup_panel.title() == "Power-ups & Timed Hotkeys"

    window_de = MainWindow(Translator(Language.GERMAN))
    assert window_de.powerup_panel.title() == "Power-ups & Zeitgesteuerte Tasten"


class _RecordingDetector:
    """Records the class filters pushed into the perception boundary."""

    def __init__(self) -> None:
        self.allowed_class_names: list[frozenset[str]] = []

    def update_allowed_class_names(self, allowed_class_names: frozenset[str]) -> None:
        self.allowed_class_names.append(allowed_class_names)


class _RecordingSession:
    """Records the monster selections pushed into the session boundary."""

    def __init__(self) -> None:
        self.configs: list[KillGoalConfig] = []

    def configure_kill_goals(self, config: KillGoalConfig) -> None:
        self.configs.append(config)


def test_main_window_target_panel_lists_every_model_class_unselected() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.set_target_mob_options(("Flame", "Rapra"))

    rows = window.target_panel.rows
    assert [row.class_name for row in rows] == ["Flame", "Rapra"]
    assert [row.enabled_check.isChecked() for row in rows] == [False, False]
    assert window.target_selection == KillGoalConfig()


def test_main_window_target_panel_emits_activated_monsters_and_quotas() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.set_target_mob_options(("Flame", "Rapra"))

    selections: list[KillGoalConfig] = []
    window.target_selection_changed.connect(selections.append)

    window.target_panel.rows[1].enabled_check.setChecked(True)
    window.target_panel.rows[1].quota_spin.setValue(3)
    application.processEvents()

    assert selections[-1].quotas == (MobKillQuota("Rapra", 3),)
    assert window.target_selection.quotas == (MobKillQuota("Rapra", 3),)


def test_main_window_target_panel_keeps_the_selection_across_repopulation() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.set_target_mob_options(("Flame", "Rapra"))
    window.target_panel.rows[0].enabled_check.setChecked(True)
    window.target_panel.rows[0].quota_spin.setValue(7)
    application.processEvents()

    selections: list[KillGoalConfig] = []
    window.target_selection_changed.connect(selections.append)
    window.set_target_mob_options(("Rapra", "Flame"))

    assert window.target_selection.quotas == (MobKillQuota("Flame", 7),)
    assert selections == []


def test_main_window_target_panel_renders_live_quota_progress() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.set_target_mob_options(("Flame", "Rapra"))

    window.update_dashboard(
        DashboardUpdate(
            _world_state(),
            BotStatus.COMBAT,
            kill_progress=(
                MobKillProgress("Flame", 14, 20),
                MobKillProgress("Rapra", 5, 0),
            ),
        )
    )

    assert window.target_panel.rows[0].progress_label.text() == "14 / 20"
    assert window.target_panel.rows[1].progress_label.text() == "5"
    assert window.kill_progress_label.text() == "Kills: Flame 14/20, Rapra 5"


def test_main_window_target_panel_is_available_on_combat_tab() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.show()

    assert not window.target_panel.isVisible()
    window.tab_widget.setCurrentIndex(DashboardTab.COMBAT_TARGETS)
    application.processEvents()

    assert window.target_panel.isVisibleTo(window)


def test_main_window_target_panel_labels_are_localized() -> None:
    _application = QApplication.instance() or QApplication([])

    window_en = MainWindow(Translator(Language.ENGLISH))
    window_de = MainWindow(Translator(Language.GERMAN))

    assert window_en.target_panel.title() == "Target Monsters & Kill Quotas"
    assert window_de.target_panel.title() == "Zielmonster & Abschussvorgaben"
    assert window_de.target_panel.close_client_check.text().startswith("Spiel-Client")


def test_main_window_event_log_panel_is_available_on_diagnostics_tab() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.show()

    assert not window.event_log_panel.isVisible()
    window.tab_widget.setCurrentIndex(DashboardTab.DIAGNOSTICS_LOGS)
    application.processEvents()

    assert window.event_log_panel.isVisibleTo(window)


def test_main_window_event_log_panel_labels_are_localized() -> None:
    _application = QApplication.instance() or QApplication([])

    window_en = MainWindow(Translator(Language.ENGLISH))
    window_de = MainWindow(Translator(Language.GERMAN))

    assert window_en.event_log_panel.title() == "Diagnostic Event Log"
    assert window_de.event_log_panel.title() == "Diagnose-Ereignisprotokoll"


def test_main_window_event_log_panel_renders_recent_events_most_recent_first() -> None:
    """US-049: the dashboard event log view mirrors the session logger's own ordering."""

    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.update_dashboard(
        DashboardUpdate(
            _world_state(),
            BotStatus.STANDBY,
            events=(
                SessionEvent(
                    timestamp="2026-08-19T12:00:05+00:00",
                    kind=SessionEventKind.FOCUS_LOST,
                    previous_mode="searching",
                    new_mode="paused",
                    reason="focus_lost",
                    foreground_window_title="Notepad",
                    foreground_window_process="notepad.exe",
                ),
                SessionEvent(
                    timestamp="2026-08-19T12:00:00+00:00",
                    kind=SessionEventKind.MODE_TRANSITION,
                    previous_mode="paused",
                    new_mode="searching",
                    reason="session_start",
                ),
            ),
        )
    )

    list_widget = window.event_log_panel.list_widget
    assert list_widget.count() == 2
    assert "Focus lost" in list_widget.item(0).text()
    assert "Notepad" in list_widget.item(0).text()
    assert "Searching" in list_widget.item(0).text()
    assert "Mode change" in list_widget.item(1).text()


def test_main_window_event_log_panel_shows_empty_hint_without_events() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.STANDBY))

    list_widget = window.event_log_panel.list_widget
    assert list_widget.count() == 1
    assert list_widget.item(0).text() == "No session events recorded yet."


def test_target_selection_reaches_the_session_and_narrows_perception() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.set_target_mob_options(("Flame", "Rapra"))
    detector = _RecordingDetector()
    template = np.full((2, 2, 3), 7, dtype=np.uint8)
    verifier = TargetVerifier(("Flame", "Rapra"), template, _StubTextRecognizer())
    session = _RecordingSession()

    apply_classes = target_class_applier(
        detector, verifier, ("Flame", "Rapra"), default_anchor_path=None
    )
    connect_target_selection(window, session)

    window.target_panel.rows[1].enabled_check.setChecked(True)
    application.processEvents()

    assert session.configs[-1].quotas == (MobKillQuota("Rapra", 0),)

    apply_classes(frozenset({"Rapra"}))
    assert detector.allowed_class_names[-1] == frozenset({"Rapra"})
    assert list(verifier.allowed_names) == ["Rapra"]

    apply_classes(frozenset())
    assert detector.allowed_class_names[-1] == frozenset()
    assert list(verifier.allowed_names) == ["Flame", "Rapra"]


def test_the_world_data_manager_opens_and_reuses_one_dialog(tmp_path: Path) -> None:
    """The dialog is created on first use and kept, so its extraction survives reopening."""

    application = QApplication.instance() or QApplication([])
    assert application is not None
    window = MainWindow(
        Translator(Language.ENGLISH),
        client_world_root=tmp_path / "client",
        world_map_dir=tmp_path / "worlds",
    )
    requests: list[object] = []
    window.vector_navigation_requested.connect(requests.append)

    assert window.world_data_dialog is None
    window.world_data_button.click()
    dialog = window.world_data_dialog
    window.world_data_button.click()

    assert dialog is not None
    assert window.world_data_dialog is dialog
    # The dialog's request signal is re-emitted by the window, which is what `run_desktop`
    # connects the session's vector navigation to.
    dialog.vector_navigation_requested.emit("request")
    assert requests == ["request"]
    window.close()


def test_the_world_data_button_is_localized() -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    window = MainWindow(Translator(Language.GERMAN))

    assert window.world_data_button.text() == "Weltdaten & Karten"


def test_the_recovery_panel_persists_the_timeout_and_reset_destination(
    tmp_path: Path,
) -> None:
    """US-051: the operator's stuck timeout and teleporter reset target survive a restart."""

    application = QApplication.instance() or QApplication([])
    config_path = tmp_path / "emergency.json"
    destination_path = tmp_path / "teleporters.json"
    save_teleporter_catalog(TELEPORTER_CATALOG, destination_path)
    window = MainWindow(Translator(Language.ENGLISH), emergency_config_path=config_path)
    window.set_teleporter_destinations(TELEPORTER_CATALOG.destinations)

    window.show()
    window.tab_widget.setCurrentIndex(DashboardTab.COMBAT_TARGETS)
    application.processEvents()
    assert window.recovery_panel.isVisibleTo(window)

    configs: list[EmergencyRecoveryConfig] = []
    window.emergency_config_changed.connect(configs.append)

    window.recovery_timeout_spin.setValue(90.0)
    window.recovery_destination_combo.setCurrentIndex(
        window.recovery_destination_combo.findData(RESET_DESTINATION.destination_id)
    )
    application.processEvents()

    assert configs[-1].stuck_timeout_seconds == pytest.approx(90.0)
    assert configs[-1].destination is RESET_DESTINATION

    restored = MainWindow(
        Translator(Language.ENGLISH),
        emergency_config_path=config_path,
        teleporter_database_path=destination_path,
    )
    assert restored.get_emergency_config() == configs[-1]


def test_an_unselected_teleporter_destination_is_stored_and_restored(tmp_path: Path) -> None:
    """US-051: selecting no reset target is a choice, not a missing setting."""

    application = QApplication.instance() or QApplication([])
    config_path = tmp_path / "emergency.json"
    destination_path = tmp_path / "teleporters.json"
    save_teleporter_catalog(TELEPORTER_CATALOG, destination_path)
    window = MainWindow(Translator(Language.ENGLISH), emergency_config_path=config_path)
    window.set_teleporter_destinations(TELEPORTER_CATALOG.destinations)

    window.recovery_destination_combo.setCurrentIndex(
        window.recovery_destination_combo.findData(None)
    )
    application.processEvents()

    assert window.get_emergency_config().destination is None
    restored = MainWindow(
        Translator(Language.ENGLISH),
        emergency_config_path=config_path,
        teleporter_database_path=destination_path,
    )
    assert restored.get_emergency_config().destination is None
