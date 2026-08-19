"""Tests for the localized Qt dashboard and queued update bridge."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

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
from flyff_bot.features.automation.orchestrator import (
    FarmingInputAdapter,
    FarmingMode,
    FarmingOrchestrator,
)
from flyff_bot.features.automation.powerup_controller import PowerUpConfig, PowerUpEntry
from flyff_bot.features.automation.powerup_persistence import (
    load_powerup_config,
    save_powerup_config,
)
from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerConfig,
    VitalTriggerType,
)
from flyff_bot.features.input_control import (
    InputControlError,
    InputErrorCode,
    ScreenRect,
    parse_virtual_key,
)
from flyff_bot.features.navigation.anchoring import ProfileAnchorState
from flyff_bot.features.navigation.pathing import (
    PathingController,
    ProfileLoadOutcome,
    ProfileLoadResult,
)
from flyff_bot.features.navigation.spatial import SpatialMap, WorldPoint
from flyff_bot.features.perception.pipeline import PerceptionPipeline
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
    CellSnapshot,
    DashboardFeed,
    DashboardUpdate,
    EdgeSnapshot,
    FarmingGoal,
    NavigationSnapshot,
    WindowStatus,
)
from flyff_bot.ui.debug_overlay import DebugOverlayWidget, render_debug_overlay
from flyff_bot.ui.main_window import MainWindow
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

        def load_navigation_profile(
            self, path: Path, *, accept_unmatched: bool = False
        ) -> ProfileLoadResult:
            self.requests.append(f"load:{path.name}")
            return ProfileLoadResult(ProfileLoadOutcome.ANCHORED)

        def reset_navigation_map(self) -> None:
            self.requests.append("reset")

        def configure_vitals(self, config: VitalsTriggerConfig) -> None:
            self.requests.append("vitals")

        def configure_powerups(self, config: PowerUpConfig) -> None:
            self.requests.append("powerups")

        def request_camera_alignment(self) -> None:
            self.requests.append("align")

        def configure_auto_align(self, enabled: bool) -> None:
            self.requests.append(f"auto_align:{enabled}")

    session = Session()
    connect_farming_controls(window, session)
    window.start_button.click()
    window.pause_button.click()
    window.emergency_stop_button.click()
    window.align_camera_button.click()
    window.auto_align_toggle.setChecked(False)
    window.save_profile_requested.emit(Path("spot.json"))
    window.load_profile_requested.emit(Path("spot.json"))
    window.reset_navigation_requested.emit()
    application.processEvents()

    assert session.requests == [
        "start",
        "pause",
        "stop",
        "align",
        "auto_align:False",
        "save:spot.json",
        "load:spot.json",
        "reset",
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
        cell_size_pixels=40.0,
        leash_radius_pixels=80.0,
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


class _ProfileSession:
    """A farming session that only records how a profile load was attempted."""

    def __init__(self, outcome: ProfileLoadOutcome) -> None:
        self._outcome = outcome
        self.load_attempts: list[bool] = []

    def start(self) -> None: ...

    def pause(self) -> None: ...

    def emergency_stop(self) -> None: ...

    def save_navigation_profile(self, path: Path) -> None: ...

    def load_navigation_profile(
        self, path: Path, *, accept_unmatched: bool = False
    ) -> ProfileLoadResult:
        self.load_attempts.append(accept_unmatched)
        return ProfileLoadResult(
            self._outcome, stored_zoom_signature=110.7, live_zoom_signature=88.5
        )

    def reset_navigation_map(self) -> None: ...

    def configure_vitals(self, config: VitalsTriggerConfig) -> None: ...

    def configure_powerups(self, config: PowerUpConfig) -> None: ...

    def request_camera_alignment(self) -> None: ...

    def configure_auto_align(self, enabled: bool) -> None: ...


@pytest.mark.parametrize(
    ("accepted", "expected_attempts"),
    [(True, [False, True]), (False, [False])],
)
def test_refused_anchor_only_loads_read_only_when_the_operator_accepts(
    monkeypatch: pytest.MonkeyPatch, accepted: bool, expected_attempts: list[bool]
) -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    session = _ProfileSession(ProfileLoadOutcome.UNMATCHED)
    connect_farming_controls(window, session)
    monkeypatch.setattr(MainWindow, "confirm_read_only_profile", lambda _self: accepted)

    window.load_profile_requested.emit(Path("spot.json"))
    application.processEvents()

    assert session.load_attempts == expected_attempts


def test_a_scale_mismatch_is_reported_and_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    application = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    window = MainWindow(translator)
    session = _ProfileSession(ProfileLoadOutcome.SCALE_MISMATCH)
    connect_farming_controls(window, session)
    dialogs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        MainWindow,
        "show_error_dialog",
        lambda _self, title, message: dialogs.append((title, message)),
    )

    window.load_profile_requested.emit(Path("spot.json"))
    application.processEvents()

    assert session.load_attempts == [False]
    assert dialogs[0][0] == translator.text(Message.UI_PROFILE_SCALE_MISMATCH_TITLE)
    assert "110.7" in dialogs[0][1]
    assert "88.5" in dialogs[0][1]


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (ProfileAnchorState.SESSION, Message.UI_PROFILE_ANCHOR_SESSION),
        (ProfileAnchorState.ANCHORED, Message.UI_PROFILE_ANCHOR_ANCHORED),
        (ProfileAnchorState.READ_ONLY, Message.UI_PROFILE_ANCHOR_READ_ONLY),
        (ProfileAnchorState.UNANCHORED, Message.UI_PROFILE_ANCHOR_UNANCHORED),
    ],
)
def test_main_window_shows_the_profile_anchor_state(
    state: ProfileAnchorState, message: Message
) -> None:
    application = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    window = MainWindow(translator)
    snapshot = NavigationSnapshot(
        player_x=0.0,
        player_y=0.0,
        heading_degrees=90.0,
        cells=(),
        edges=(),
        profile_anchor_state=state,
    )

    window.update_dashboard(DashboardUpdate(_world_state(), BotStatus.PAUSED, navigation=snapshot))
    application.processEvents()

    assert window.profile_anchor_label.text() == translator.text(message)


def test_unanchored_profile_prompt_offers_read_only_or_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _application = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    window = MainWindow(translator)
    prompts: list[QMessageBox] = []

    def _decline(box: QMessageBox) -> int:
        prompts.append(box)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _decline)

    assert window.confirm_read_only_profile() is False

    prompt = prompts[0]
    assert len(prompt.buttons()) == 2
    assert prompt.defaultButton() is not None
    assert prompt.defaultButton().text() == translator.text(Message.UI_PROFILE_UNMATCHED_CANCEL)

    def _accept(box: QMessageBox) -> int:
        for button in box.buttons():
            if box.buttonRole(button) is QMessageBox.ButtonRole.AcceptRole:
                button.click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _accept)

    assert window.confirm_read_only_profile() is True


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


def test_main_window_close_event_pauses_and_persists_the_navigation_map(tmp_path: Path) -> None:
    """BUG-004: closing the window must not drop map updates learned since the last save."""

    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    spatial_map = SpatialMap()
    spatial_map.record_visit(WorldPoint(0.0, 0.0), CLOSE_EVENT_VISIT_TIME_SECONDS)
    map_path = tmp_path / "spatial_map.json"
    orchestrator = FarmingOrchestrator(
        # Neither collaborator is exercised: closing only pauses and flushes the map to disk.
        cast(PerceptionPipeline, object()),
        cast(FarmingInputAdapter, object()),
        CLOSE_EVENT_WINDOW_HANDLE,
        pathing=PathingController(spatial_map, map_path=map_path),
    )
    orchestrator.start()
    connect_farming_controls(window, orchestrator)

    window.closeEvent(QCloseEvent())
    application.processEvents()

    assert orchestrator.mode is FarmingMode.PAUSED
    assert map_path.is_file()
    persisted = json.loads(map_path.read_text(encoding="utf-8"))
    assert persisted["cells"]


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


def test_main_window_vitals_panel_toggle_and_config_signals(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH), vitals_config_path=tmp_path / "vitals.json")

    assert window.vitals_panel.isHidden()
    window.vitals_toggle.setChecked(True)
    assert not window.vitals_panel.isHidden()

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


def test_main_window_combat_panel_toggle_and_config_signals() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.combat_panel.isHidden()
    window.combat_toggle.setChecked(True)
    assert not window.combat_panel.isHidden()

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


def test_main_window_target_debug_panel_toggle_and_renders_failure_metrics() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.target_debug_panel.isHidden()
    window.target_debug_toggle.setChecked(True)
    assert not window.target_debug_panel.isHidden()

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


def test_main_window_monster_stats_panel_toggle_and_renders_a_successful_reading() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.monster_stats_panel.isHidden()
    window.monster_stats_toggle.setChecked(True)
    assert not window.monster_stats_panel.isHidden()

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

    window.monster_stats_toggle.setChecked(False)
    assert window.monster_stats_panel.isHidden()


def test_main_window_monster_stats_panel_reports_a_failed_reading_and_stays_updated() -> None:
    """The panel renders even while hidden, so it is current the moment it is opened."""

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

    assert window.monster_stats_panel.isHidden()
    assert window.monster_anchor_value.text() == "FAIL 0.42 / 0.85"
    assert window.monster_kills_value.text() == "Not recognized"
    assert window.monster_text_value.text() == "No text recognized"
    assert window.monster_status_value.text() == "No kill counter found in the text"
    # A missed anchor still reads, so the panel must name which crop produced the number.
    assert window.monster_source_value.text() == "Predefined placement region"


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

    assert window.monster_stats_toggle.text() == "Monster-Stats-Debug"
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
    assert "#ActionEmergencyStop" in stylesheet
    assert "#StatusBadge" in stylesheet

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


def test_main_window_card_hierarchy_and_object_names() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.start_button.objectName() == "ActionStart"
    assert window.pause_button.objectName() == "ActionPause"
    assert window.emergency_stop_button.objectName() == "ActionEmergencyStop"
    assert window.reset_map_button.objectName() == "ActionDanger"
    assert window.status_label.objectName() == "StatusBadge"
    assert window.goal_label.objectName() == "StatChip"
    assert window.vitals_label.objectName() == "StatChip"

    assert window.status_card.title() == "Status & Telemetry"
    assert window.controls_card.title() == "Controls"
    assert window.profile_card.title() == "Navigation & Profiles"
    assert window.telemetry_card.title() == "Diagnostics & Views"


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

    assert panel.isHidden()
    window.powerups_toggle.setChecked(True)
    assert not panel.isHidden()
    assert panel.rows == ()

    configs: list[PowerUpConfig] = []
    window.powerup_config_changed.connect(configs.append)

    panel.add_button.click()
    panel.add_button.click()
    application.processEvents()
    assert len(panel.rows) == 2

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
    assert window_en.powerups_toggle.text() == "Power-ups"
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


def test_main_window_target_panel_toggle_reveals_the_selection() -> None:
    _application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))

    assert not window.target_panel.isVisible()
    window.targets_toggle.setChecked(True)

    assert window.target_panel.isVisibleTo(window)


def test_main_window_target_panel_labels_are_localized() -> None:
    _application = QApplication.instance() or QApplication([])

    window_en = MainWindow(Translator(Language.ENGLISH))
    window_de = MainWindow(Translator(Language.GERMAN))

    assert window_en.target_panel.title() == "Target Monsters & Kill Quotas"
    assert window_de.target_panel.title() == "Zielmonster & Abschussvorgaben"
    assert window_de.target_panel.close_client_check.text().startswith("Spiel-Client")


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
