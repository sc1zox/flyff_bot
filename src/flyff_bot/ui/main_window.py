"""Localized native dashboard for observed automation state."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.constants import (
    DEFAULT_CLIENT_PLAYER_STATS_PROFILES_PATH,
    DEFAULT_CLIENT_WORLD_ROOT,
    DEFAULT_DUNGEON_DATABASE_PATH,
    DEFAULT_QUEST_DATABASE_PATH,
    DEFAULT_QUEST_NPC_POSITIONS_PATH,
    DEFAULT_WORLD_MAP_DIRECTORY,
    DEFAULT_WORLD_MONSTER_IDS_PATH,
)
from flyff_bot.features.automation.controllers import (
    MELEE_ENGAGEMENT_DISTANCE_UNITS,
    RANGED_ENGAGEMENT_DISTANCE_UNITS,
    CombatClassProfile,
)
from flyff_bot.features.automation.emergency_recovery import EmergencyRecoveryConfig
from flyff_bot.features.automation.kill_goals import KillGoalConfig
from flyff_bot.features.automation.models import (
    MonsterStatsMetrics,
    WorldState,
)
from flyff_bot.features.automation.powerup_controller import PowerUpConfig
from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerConfig,
)
from flyff_bot.features.quests.goals import QuestNpc
from flyff_bot.features.quests.persistence import (
    QuestDatabaseError,
    load_quest_database,
    load_quest_npc_positions,
)
from flyff_bot.features.setup.extraction import UnifiedClientExtractor
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import (
    BotStatus,
    DashboardUpdate,
    WindowStatus,
)
from flyff_bot.ui.debug_overlay import DebugOverlayWidget
from flyff_bot.ui.dungeon_panel import DungeonCooldownPanel
from flyff_bot.ui.event_log_panel import EventLogPanel
from flyff_bot.ui.main_window_parts.combat_settings import CombatSettingsPanel
from flyff_bot.ui.main_window_parts.dashboard import DashboardSummary, StatusHeaderCard
from flyff_bot.ui.main_window_parts.dashboard_presenter import DashboardPresenter
from flyff_bot.ui.main_window_parts.diagnostics import (
    MonsterStatsDebugPanel,
    TargetDebugPanel,
)
from flyff_bot.ui.main_window_parts.navigation import NavigationSection
from flyff_bot.ui.main_window_parts.navigation_controller import NavigationController
from flyff_bot.ui.main_window_parts.overlay_presenter import OverlayPresenter
from flyff_bot.ui.main_window_parts.quests import QuestDatabaseController
from flyff_bot.ui.main_window_parts.recovery_settings import RecoverySettingsPanel
from flyff_bot.ui.main_window_parts.settings_controllers import SettingsController
from flyff_bot.ui.main_window_parts.status_presenter import StatusPresenter
from flyff_bot.ui.main_window_parts.vitals_settings import VitalsSettingsPanel
from flyff_bot.ui.main_window_parts.window_controls import WindowControlsCard
from flyff_bot.ui.navigation_window import NavigationMapWindow
from flyff_bot.ui.path_inspector import PathInspectorWidget
from flyff_bot.ui.placement_overlay import ClientGeometryProvider, PlacementOverlayWindow
from flyff_bot.ui.powerup_panel import PowerUpPanel
from flyff_bot.ui.quest_panel import QuestGoalPanel
from flyff_bot.ui.setup_wizard import SetupWizard
from flyff_bot.ui.target_panel import TargetSelectionPanel
from flyff_bot.ui.theme import apply_theme
from flyff_bot.ui.world_data_dialog import WorldDataDialog

DEFAULT_WINDOW_WIDTH = 1100
DEFAULT_WINDOW_HEIGHT = 760
MINIMUM_WINDOW_WIDTH = 760
MINIMUM_WINDOW_HEIGHT = 520


class DashboardTab(IntEnum):
    """Stable indices for the operator-facing dashboard views."""

    DASHBOARD = 0
    COMBAT_TARGETS = 1
    VITALS_BUFFS = 2
    QUEST_GOALS = 3
    DUNGEONS_COOLDOWNS = 4
    NAVIGATION_WORLD = 5
    DIAGNOSTICS_LOGS = 6


class MainWindow(QMainWindow):
    """Render immutable dashboard updates and emit operator intent signals."""

    start_requested = Signal()
    pause_requested = Signal()
    emergency_stop_requested = Signal()
    attack_key_changed = Signal(int)
    align_camera_requested = Signal()
    auto_align_changed = Signal(bool)
    vitals_config_changed = Signal(object)
    powerup_config_changed = Signal(object)
    emergency_config_changed = Signal(object)
    combat_grace_changed = Signal(float)
    combat_class_changed = Signal(object)
    engagement_distance_changed = Signal(float)
    kill_verification_changed = Signal(bool)
    anchor_threshold_changed = Signal(float)
    target_selection_changed = Signal(object)
    quest_selection_changed = Signal(object)
    vector_navigation_requested = Signal(object)
    vector_navigation_cleared = Signal()

    def __init__(
        self,
        translator: Translator,
        *,
        vitals_config_path: Path | None = None,
        powerup_config_path: Path | None = None,
        emergency_config_path: Path | None = None,
        client_world_root: Path | None = None,
        world_map_dir: Path | None = None,
        monster_names_path: Path | None = None,
        quest_database_path: Path | None = None,
        quest_npc_positions_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._translator = translator
        self._client_world_root = client_world_root or Path(DEFAULT_CLIENT_WORLD_ROOT)
        self._world_map_dir = world_map_dir or Path(DEFAULT_WORLD_MAP_DIRECTORY)
        self._monster_names_path = monster_names_path or Path(DEFAULT_WORLD_MONSTER_IDS_PATH)
        self._quest_database_path = quest_database_path or Path(DEFAULT_QUEST_DATABASE_PATH)
        self._quest_npc_positions_path = quest_npc_positions_path or Path(
            DEFAULT_QUEST_NPC_POSITIONS_PATH
        )
        self._latest_update: DashboardUpdate | None = None
        # Persistent header cards
        self._status_card = StatusHeaderCard()
        self._controls_card = WindowControlsCard()

        # Functional view cards
        self._summary_card = DashboardSummary()

        # Status & Metrics
        self._status_label = self._status_card.status_label
        self._window_label = self._status_card.window_label
        self._gps_label = self._status_card.gps_label
        self._camera_label = self._status_card.camera_label
        self._mob_label = self._summary_card.mob_label
        self._target_label = self._summary_card.target_label
        self._goal_label = self._summary_card.goal_label
        self._vitals_label = self._summary_card.vitals_label
        self._kill_progress_label = self._summary_card.kill_progress_label
        self._dashboard_presenter = DashboardPresenter(
            translator,
            mob_label=self._mob_label,
            target_label=self._target_label,
            goal_label=self._goal_label,
            vitals_label=self._vitals_label,
            kill_progress_label=self._kill_progress_label,
        )
        self._status_presenter = StatusPresenter(
            translator,
            self._status_label,
            self._status_card.window_label,
            self._gps_label,
            self._camera_label,
        )
        self._window_status = self._status_presenter.window_status

        # Display settings
        self._camera_preview_toggle = QCheckBox()
        self._camera_preview_toggle.setObjectName("Switch")
        self._placements_toggle = QCheckBox()
        self._placements_toggle.setObjectName("Switch")

        # Debug Overlay Viewport
        self._overlay = OverlayPresenter(self._translator, self._placements_toggle)
        self._overlay_label = self._overlay.preview

        # Transparent in-game placement guide overlay
        self._placement_overlay = PlacementOverlayWindow(self._translator)

        # Navigation Map & Inspector
        self._navigation = NavigationSection(self._translator)
        self._navigation_controller: NavigationController | None = None
        self._path_inspector = self._navigation.inspector
        self._map_container = self._navigation.map_container
        self._map_window = self._navigation.map_window
        self._popout_map_button = self._navigation.popout_button
        self._world_data_button = self._navigation.world_data_button
        self._teardowns: list[Callable[[], None]] = []
        self._setup_wizard: SetupWizard | None = None
        self._build_setup_menu()

        # Primary Action Controls
        self._start_button = self._controls_card.start_button
        self._pause_button = self._controls_card.pause_button
        self._attack_key_button = self._controls_card.attack_key_button
        self._align_camera_button = self._controls_card.align_camera_button
        self._auto_align_toggle = self._controls_card.auto_align_toggle
        self._language_selector = self._controls_card.language_selector

        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("FunctionalTabs")
        self._tab_scroll_areas: dict[DashboardTab, QScrollArea] = {}

        # Sub-panels
        self._combat_panel = CombatSettingsPanel()
        self._target_grace_spin = self._combat_panel.grace_spin
        self._kill_verification_toggle = self._combat_panel.verification_toggle
        self._anchor_threshold_spin = self._combat_panel.anchor_spin

        self._recovery_panel = RecoverySettingsPanel()
        self._target_panel = TargetSelectionPanel(self._translator)
        self._quest_panel = QuestGoalPanel(self._translator)
        self._quest_controller = QuestDatabaseController(self._quest_panel, self._translator)
        self._dungeon_panel = DungeonCooldownPanel(self._translator)

        self._target_debug_panel = TargetDebugPanel()
        self._target_anchor_val = self._target_debug_panel.anchor_value
        self._target_hp_val = self._target_debug_panel.hp_value
        self._target_name_val = self._target_debug_panel.name_value
        self._target_state_val = self._target_debug_panel.state_value
        self._target_reason_val = self._target_debug_panel.reason_value
        self._target_break_val = self._target_debug_panel.break_value

        self._monster_stats_panel = MonsterStatsDebugPanel()
        self._monster_anchor_val = self._monster_stats_panel.anchor_value
        self._monster_roi_val = self._monster_stats_panel.roi_value
        self._monster_source_val = self._monster_stats_panel.source_value
        self._monster_kills_val = self._monster_stats_panel.kills_value
        self._monster_text_val = self._monster_stats_panel.text_value
        self._monster_status_val = self._monster_stats_panel.status_value

        self._event_log_panel = EventLogPanel(self._translator)

        self._vitals_panel = VitalsSettingsPanel()
        self._hp_spin = self._vitals_panel.hp_threshold_spin
        self._mp_spin = self._vitals_panel.mp_threshold_spin
        self._fp_spin = self._vitals_panel.fp_threshold_spin

        self._powerup_panel = PowerUpPanel(self._translator)
        self._settings = SettingsController(
            translator,
            recovery_panel=self._recovery_panel,
            vitals_panel=self._vitals_panel,
            powerup_panel=self._powerup_panel,
            vitals_path=vitals_config_path,
            powerup_path=powerup_config_path,
            emergency_path=emergency_config_path,
        )

        self._build_layout()
        self._connect_controls()
        self._retranslate()
        self._render_status_badge(BotStatus.PAUSED)
        self._status_presenter.render_initial_state()
        self._dashboard_presenter.render_initial_state()
        apply_theme(self)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(MINIMUM_WINDOW_WIDTH, MINIMUM_WINDOW_HEIGHT)

    @property
    def start_button(self) -> QPushButton:
        return self._start_button

    @property
    def pause_button(self) -> QPushButton:
        return self._pause_button

    @property
    def status_label(self) -> QLabel:
        return self._status_label

    @property
    def window_label(self) -> QLabel:
        return self._window_label

    @property
    def gps_label(self) -> QLabel:
        return self._gps_label

    @property
    def camera_label(self) -> QLabel:
        return self._camera_label

    @property
    def mob_label(self) -> QLabel:
        return self._mob_label

    @property
    def target_label(self) -> QLabel:
        return self._target_label

    @property
    def overlay_label(self) -> DebugOverlayWidget:
        return self._overlay_label

    @property
    def path_inspector(self) -> PathInspectorWidget:
        return self._path_inspector

    @property
    def tab_widget(self) -> QTabWidget:
        return self._tab_widget

    def tab_scroll_area(self, tab: DashboardTab) -> QScrollArea:
        return self._tab_scroll_areas[tab]

    @property
    def camera_preview_toggle(self) -> QCheckBox:
        return self._camera_preview_toggle

    @property
    def placements_toggle(self) -> QCheckBox:
        return self._placements_toggle

    @property
    def placement_overlay(self) -> PlacementOverlayWindow:
        return self._placement_overlay

    def attach_placement_target(self, provider: ClientGeometryProvider, window_handle: int) -> None:
        self._placement_overlay.attach_target(provider, window_handle)

    @property
    def world_data_button(self) -> QPushButton:
        return self._world_data_button

    @property
    def world_data_dialog(self) -> WorldDataDialog | None:
        return self._navigation_controller.dialog if self._navigation_controller else None

    @property
    def target_grace_spin(self) -> QDoubleSpinBox:
        return self._target_grace_spin

    @property
    def kill_verification_toggle(self) -> QCheckBox:
        return self._kill_verification_toggle

    @property
    def anchor_threshold_spin(self) -> QDoubleSpinBox:
        return self._anchor_threshold_spin

    @property
    def target_selection(self) -> KillGoalConfig:
        return self._target_panel.get_config()

    @property
    def target_selection_panel(self) -> TargetSelectionPanel:
        return self._target_panel

    @property
    def attack_virtual_key(self) -> int:
        return self._controls_card.attack_virtual_key

    @property
    def attack_key_button(self) -> QPushButton:
        return self._attack_key_button

    @property
    def map_window(self) -> NavigationMapWindow:
        return self._map_window

    @property
    def auto_align_toggle(self) -> QCheckBox:
        return self._auto_align_toggle

    @property
    def combat_panel(self) -> QGroupBox:
        return self._combat_panel

    @property
    def combat_class_selector(self) -> QComboBox:
        return self._combat_panel.class_selector

    @property
    def engagement_distance_spin(self) -> QDoubleSpinBox:
        return self._combat_panel.engagement_distance_spin

    @property
    def vitals_panel(self) -> QGroupBox:
        return self._vitals_panel

    @property
    def hp_threshold_spin(self) -> QSpinBox:
        return self._hp_spin

    @property
    def mp_threshold_spin(self) -> QSpinBox:
        return self._mp_spin

    @property
    def fp_threshold_spin(self) -> QSpinBox:
        return self._fp_spin

    @property
    def is_map_popped_out(self) -> bool:
        return self._navigation.is_popped_out

    @property
    def popout_map_button(self) -> QPushButton:
        return self._popout_map_button

    @property
    def kill_progress_label(self) -> QLabel:
        return self._kill_progress_label

    def set_window_status(self, status: WindowStatus) -> None:
        self._status_presenter.render_window_status(status)

    @property
    def goal_label(self) -> QLabel:
        return self._goal_label

    @property
    def vitals_label(self) -> QLabel:
        return self._vitals_label

    @property
    def align_camera_button(self) -> QPushButton:
        return self._align_camera_button

    @property
    def target_panel(self) -> TargetSelectionPanel:
        return self._target_panel

    @property
    def translator(self) -> Translator:
        """Expose the active translator for composition-root wiring."""

        return self._translator

    @property
    def quest_panel(self) -> QuestGoalPanel:
        """Expose the quest goal browser for wiring and verification."""

        return self._quest_panel

    @property
    def dungeon_panel(self) -> DungeonCooldownPanel:
        """Expose the dungeon cooldown panel for wiring and verification."""

        return self._dungeon_panel

    def load_quest_database(self) -> None:
        """Load the extracted quest database into the quest panel, if one exists.

        A missing or malformed database is a localized status line on the panel rather than
        a failure: quest extraction is an offline step an operator may not have run yet.
        """

        path = self._quest_database_path
        if not path.is_file():
            self._quest_panel.set_status_text(
                self._translator.text(Message.UI_QUEST_DATABASE_MISSING, path=path)
            )
            return
        try:
            database = load_quest_database(path)
        except QuestDatabaseError as error:
            self._quest_panel.set_status_text(
                self._translator.text(Message.QUEST_EXTRACTION_FAILED, reason=error)
            )
            return
        self._quest_panel.set_database(
            database,
            self._translator.text(
                Message.UI_QUEST_DATABASE_LOADED, count=len(database.quests), path=path
            ),
        )

    @property
    def quest_npc_positions(self) -> dict[str, QuestNpc]:
        """Load explicit accept/turn-in locations, tolerating a missing optional file."""

        if not self._quest_npc_positions_path.is_file():
            return {}
        return load_quest_npc_positions(self._quest_npc_positions_path)

    @property
    def powerup_panel(self) -> PowerUpPanel:
        return self._powerup_panel

    @property
    def event_log_panel(self) -> EventLogPanel:
        return self._event_log_panel

    @property
    def target_debug_panel(self) -> QGroupBox:
        return self._target_debug_panel

    @property
    def monster_stats_panel(self) -> QGroupBox:
        return self._monster_stats_panel

    @property
    def status_card(self) -> QGroupBox:
        return self._status_card

    @property
    def controls_card(self) -> QGroupBox:
        return self._controls_card

    @property
    def recovery_panel(self) -> QGroupBox:
        return self._recovery_panel

    @property
    def target_anchor_value(self) -> QLabel:
        return self._target_anchor_val

    @property
    def target_hp_value(self) -> QLabel:
        return self._target_hp_val

    @property
    def target_name_value(self) -> QLabel:
        return self._target_name_val

    @property
    def target_state_value(self) -> QLabel:
        return self._target_state_val

    @property
    def target_reason_value(self) -> QLabel:
        return self._target_reason_val

    @property
    def monster_anchor_value(self) -> QLabel:
        return self._monster_anchor_val

    @property
    def monster_roi_value(self) -> QLabel:
        return self._monster_roi_val

    @property
    def monster_kills_value(self) -> QLabel:
        return self._monster_kills_val

    @property
    def monster_text_value(self) -> QLabel:
        return self._monster_text_val

    @property
    def monster_status_value(self) -> QLabel:
        return self._monster_status_val

    @property
    def monster_source_value(self) -> QLabel:
        return self._monster_source_val

    @property
    def recovery_timeout_spin(self) -> QDoubleSpinBox:
        return self._settings.recovery_panel.timeout_spin

    @property
    def recovery_hotkey_combo(self) -> QComboBox:
        return self._settings.recovery_panel.hotkey_combo

    def _build_layout(self) -> None:
        preview_controls = QWidget()
        preview_controls_layout = QHBoxLayout(preview_controls)
        preview_controls_layout.setContentsMargins(0, 0, 0, 0)
        preview_controls_layout.addWidget(self._camera_preview_toggle)
        preview_controls_layout.addStretch()

        diagnostics_controls = QWidget()
        diagnostics_controls_layout = QHBoxLayout(diagnostics_controls)
        diagnostics_controls_layout.setContentsMargins(0, 0, 0, 0)
        diagnostics_controls_layout.addWidget(self._placements_toggle)
        diagnostics_controls_layout.addStretch()

        self._add_scroll_tab(
            DashboardTab.DASHBOARD,
            self._summary_card,
            preview_controls,
            self._overlay_label,
        )
        self._add_scroll_tab(
            DashboardTab.COMBAT_TARGETS,
            self._target_panel,
            self._combat_panel,
            self._recovery_panel,
        )
        self._add_scroll_tab(
            DashboardTab.VITALS_BUFFS,
            self._vitals_panel,
            self._powerup_panel,
        )
        self._add_scroll_tab(
            DashboardTab.QUEST_GOALS,
            self._quest_panel,
        )
        self._add_scroll_tab(
            DashboardTab.DUNGEONS_COOLDOWNS,
            self._dungeon_panel,
        )
        self._add_scroll_tab(
            DashboardTab.NAVIGATION_WORLD,
            self._navigation,
            self._map_container,
        )
        self._add_scroll_tab(
            DashboardTab.DIAGNOSTICS_LOGS,
            diagnostics_controls,
            self._event_log_panel,
            self._target_debug_panel,
            self._monster_stats_panel,
        )

        content = QVBoxLayout()
        content.addWidget(self._status_card)
        content.addWidget(self._controls_card)
        content.addWidget(self._tab_widget, 1)

        container = QWidget()
        container.setLayout(content)
        self.setCentralWidget(container)

    def _add_scroll_tab(self, tab: DashboardTab, *widgets: QWidget) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for widget in widgets:
            page_layout.addWidget(widget)
        page_layout.addStretch()

        scroll_area = QScrollArea()
        scroll_area.setObjectName("FunctionalTabScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidget(page)
        index = self._tab_widget.addTab(scroll_area, "")
        if index != int(tab):
            raise RuntimeError("Functional dashboard tabs must be added in stable index order.")
        self._tab_scroll_areas[tab] = scroll_area

    def _connect_controls(self) -> None:
        self._start_button.clicked.connect(self._request_start)
        self._pause_button.clicked.connect(self._request_pause)
        self._attack_key_button.clicked.connect(self._begin_attack_key_recording)
        self._align_camera_button.clicked.connect(self._request_camera_alignment)
        self._auto_align_toggle.toggled.connect(self.auto_align_changed)
        self._attack_key_button.installEventFilter(self)
        self._camera_preview_toggle.toggled.connect(self._update_overlay_visibility)
        self._popout_map_button.clicked.connect(self._toggle_map_popout)
        self._world_data_button.clicked.connect(self._on_world_data_clicked)
        self._map_window.closed.connect(self._on_map_window_closed)
        self._map_window.emergency_stop_requested.connect(self._request_emergency_stop)
        self._powerup_panel.config_changed.connect(self._on_powerup_config_changed)
        self._placements_toggle.toggled.connect(self._on_placements_toggled)
        self._language_selector.currentIndexChanged.connect(self._switch_language)
        self._combat_panel.grace_spin.valueChanged.connect(self.combat_grace_changed)
        self._combat_panel.class_selector.currentIndexChanged.connect(self._on_combat_class_changed)
        self._combat_panel.engagement_distance_spin.valueChanged.connect(
            self.engagement_distance_changed
        )
        self._combat_panel.engagement_distance_spin.valueChanged.connect(
            self._on_engagement_distance_changed
        )
        self._combat_panel.verification_toggle.toggled.connect(self._on_kill_verification_changed)
        self._combat_panel.anchor_spin.valueChanged.connect(self._on_anchor_threshold_changed)
        self._target_panel.selection_changed.connect(self._on_target_selection_changed)
        self._quest_panel.selection_changed.connect(self.quest_selection_changed)
        self._recovery_panel.timeout_spin.valueChanged.connect(self._on_emergency_changed)
        self._recovery_panel.hotkey_combo.currentIndexChanged.connect(self._on_emergency_changed)
        for controls in self._vitals_panel.rows:
            controls.enabled.toggled.connect(self._on_vitals_changed)
            controls.threshold.valueChanged.connect(self._on_vitals_changed)
            controls.hotkey.currentIndexChanged.connect(self._on_vitals_changed)
            controls.debounce.valueChanged.connect(self._on_vitals_changed)

    @Slot()
    def _on_vitals_changed(self) -> None:
        config = self._settings.save_vitals()
        self.vitals_config_changed.emit(config)

    @Slot()
    def _on_combat_class_changed(self) -> None:
        selected_profile = self._combat_panel.class_selector.currentData()
        if not isinstance(selected_profile, CombatClassProfile) and not isinstance(
            selected_profile, str
        ):
            return
        if isinstance(selected_profile, str):
            selected_profile = CombatClassProfile(selected_profile)
        if selected_profile is CombatClassProfile.MELEE:
            distance = MELEE_ENGAGEMENT_DISTANCE_UNITS
        elif selected_profile is CombatClassProfile.RANGED:
            distance = RANGED_ENGAGEMENT_DISTANCE_UNITS
        else:
            distance = self._combat_panel.engagement_distance_spin.value()
        self._combat_panel.engagement_distance_spin.setValue(distance)
        self.combat_class_changed.emit(selected_profile)

    @Slot()
    def _on_engagement_distance_changed(self, distance_units: float) -> None:
        profile = (
            CombatClassProfile.MELEE
            if distance_units == MELEE_ENGAGEMENT_DISTANCE_UNITS
            else CombatClassProfile.RANGED
            if distance_units == RANGED_ENGAGEMENT_DISTANCE_UNITS
            else CombatClassProfile.CUSTOM
        )
        current_profile = self._combat_panel.class_selector.currentData()
        if not isinstance(current_profile, CombatClassProfile):
            return
        if profile is not current_profile:
            self._combat_panel.class_selector.setCurrentIndex(
                list(CombatClassProfile).index(profile)
            )

    def show_error_dialog(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    @Slot()
    def _on_world_data_clicked(self) -> None:
        if self._navigation_controller is None:
            controller = NavigationController(
                translator=self._translator,
                navigation=self._navigation,
                parent_window=self,
                world_root=self._client_world_root,
                map_dir=self._world_map_dir,
                monster_names_path=self._monster_names_path,
            )
            controller.dialog.vector_navigation_requested.connect(self.vector_navigation_requested)
            controller.dialog.vector_navigation_cleared.connect(self.vector_navigation_cleared)
            self._navigation_controller = controller
        self._navigation_controller.show_world_data()

    def _build_setup_menu(self) -> None:
        menu_bar = self.menuBar()
        setup_menu = QMenu(menu_bar)
        action = setup_menu.addAction("")
        action.triggered.connect(self.show_setup_wizard)
        self._setup_action = action
        self._setup_action.setText(self._translator.text(Message.UI_SETUP_TITLE))
        menu_bar.addMenu(setup_menu)

    @Slot()
    def show_setup_wizard(self) -> None:
        if self._setup_wizard is None:
            self._setup_wizard = SetupWizard(
                self._translator,
                client_world_root=self._client_world_root,
                world_map_directory=self._world_map_dir,
                monster_names_path=self._monster_names_path,
                parent=self,
            )
            self._setup_wizard.setup_completed.connect(lambda _result: self.load_quest_database())
        self._setup_wizard.show()
        self._setup_wizard.raise_()
        self._setup_wizard.activateWindow()

    @staticmethod
    def is_first_run_setup_required(
        *,
        world_map_directory: Path | None = None,
        quest_database: Path | None = None,
        dungeon_database: Path | None = None,
        player_profiles: Path | None = None,
    ) -> bool:
        return UnifiedClientExtractor.is_first_run_required(
            world_map_directory=world_map_directory or Path(DEFAULT_WORLD_MAP_DIRECTORY),
            quest_database=quest_database or Path(DEFAULT_QUEST_DATABASE_PATH),
            dungeon_database=dungeon_database or Path(DEFAULT_DUNGEON_DATABASE_PATH),
            player_profiles=player_profiles or Path(DEFAULT_CLIENT_PLAYER_STATS_PROFILES_PATH),
        )

    def _retranslate(self) -> None:
        self.setWindowTitle(self._translator.text(Message.UI_TITLE))
        self._status_presenter.set_translator(self._translator)
        self._status_card.retranslate(self._translator)
        self._controls_card.retranslate(self._translator)
        self._summary_card.retranslate(self._translator)
        self._retranslate_tabs()
        self._popout_map_button.setText(
            self._translator.text(
                Message.UI_DOCK_MAP if self._navigation.is_popped_out else Message.UI_POPOUT_MAP
            )
        )
        self._map_window.set_translator(self._translator)
        self._camera_preview_toggle.setText(self._translator.text(Message.UI_CAMERA_PREVIEW))
        self._camera_preview_toggle.setToolTip(
            self._translator.text(Message.UI_CAMERA_PREVIEW_TOOLTIP)
        )
        self._powerup_panel.set_translator(self._translator)
        self._placements_toggle.setText(self._translator.text(Message.UI_PLACEMENTS_TOGGLE))
        self._placements_toggle.setToolTip(self._translator.text(Message.UI_PLACEMENTS_TOOLTIP))
        self._combat_panel.retranslate(self._translator)
        self._recovery_panel.retranslate(self._translator)
        self._target_panel.set_translator(self._translator)
        self._quest_panel.set_translator(self._translator)
        self._dungeon_panel.set_translator(self._translator)
        self._target_debug_panel.retranslate(self._translator)
        self._monster_stats_panel.retranslate(self._translator)
        self._monster_stats_panel.render_metrics(
            self._translator,
            self._latest_update.state.monster_stats
            if self._latest_update is not None
            else MonsterStatsMetrics(),
        )
        self._event_log_panel.set_translator(self._translator)
        self._vitals_panel.retranslate(self._translator)
        self._navigation.set_translator(self._translator)
        if self._navigation_controller is not None:
            self._navigation_controller.set_translator(self._translator)
        self._dashboard_presenter.set_translator(self._translator)
        self._overlay.set_translator(self._translator)
        self._world_data_button.setText(self._translator.text(Message.UI_WORLD_DATA))
        self._world_data_button.setToolTip(self._translator.text(Message.UI_WORLD_DATA_TOOLTIP))
        previous_language = self._translator.language
        self._language_selector.blockSignals(True)
        self._language_selector.clear()
        self._language_selector.addItem(
            self._translator.text(Message.UI_LANGUAGE_GERMAN), Language.GERMAN
        )
        self._language_selector.addItem(
            self._translator.text(Message.UI_LANGUAGE_ENGLISH), Language.ENGLISH
        )
        self._language_selector.setCurrentIndex(self._language_selector.findData(previous_language))
        self._language_selector.blockSignals(False)

        if self._latest_update is not None:
            self._render_update()
        else:
            self._status_presenter.render_initial_state()
            self._dashboard_presenter.render_initial_state()

    def _retranslate_tabs(self) -> None:
        labels = {
            DashboardTab.DASHBOARD: (Message.UI_TAB_DASHBOARD, Message.UI_TAB_DASHBOARD_TOOLTIP),
            DashboardTab.COMBAT_TARGETS: (
                Message.UI_TAB_COMBAT_TARGETS,
                Message.UI_TAB_COMBAT_TARGETS_TOOLTIP,
            ),
            DashboardTab.VITALS_BUFFS: (
                Message.UI_TAB_VITALS_BUFFS,
                Message.UI_TAB_VITALS_BUFFS_TOOLTIP,
            ),
            DashboardTab.QUEST_GOALS: (
                Message.UI_TAB_QUESTS,
                Message.UI_TAB_QUESTS_TOOLTIP,
            ),
            DashboardTab.DUNGEONS_COOLDOWNS: (
                Message.UI_TAB_DUNGEONS,
                Message.UI_TAB_DUNGEONS_TOOLTIP,
            ),
            DashboardTab.NAVIGATION_WORLD: (
                Message.UI_TAB_NAVIGATION_WORLD,
                Message.UI_TAB_NAVIGATION_WORLD_TOOLTIP,
            ),
            DashboardTab.DIAGNOSTICS_LOGS: (
                Message.UI_TAB_DIAGNOSTICS_LOGS,
                Message.UI_TAB_DIAGNOSTICS_LOGS_TOOLTIP,
            ),
        }
        for tab, (label_key, tooltip_key) in labels.items():
            self._tab_widget.setTabText(int(tab), self._translator.text(label_key))
            self._tab_widget.setTabToolTip(int(tab), self._translator.text(tooltip_key))

    @Slot()
    def _request_camera_alignment(self) -> None:
        self.align_camera_requested.emit()

    @Slot()
    def _begin_attack_key_recording(self) -> None:
        self._controls_card.begin_attack_key_recording(self._translator)

    def _record_attack_key(self, event: QKeyEvent) -> None:
        if self._controls_card.record_attack_key(event.key(), self._translator):
            self.attack_key_changed.emit(self._controls_card.attack_virtual_key)

    @Slot(DashboardUpdate)
    def update_dashboard(self, update: DashboardUpdate) -> None:
        self._latest_update = update
        self._render_update()

    def update_status(self, status: BotStatus) -> None:
        if self._latest_update is None:
            return
        self.update_dashboard(
            DashboardUpdate(
                self._latest_update.state,
                status,
                self._latest_update.goal,
                self._latest_update.frame,
                self._latest_update.navigation,
                self._latest_update.window,
            )
        )

    def _render_status_badge(self, status: BotStatus) -> None:
        self._status_presenter.render_status(status)

    def _render_navigation_status(self) -> None:
        self._status_presenter.render_navigation_status(
            self._latest_update.navigation if self._latest_update is not None else None
        )

    def _render_dashboard(self, update: DashboardUpdate) -> None:
        self._dashboard_presenter.render_update(update)
        self._target_panel.set_progress(update.kill_progress)

    def _render_update(self) -> None:
        if self._latest_update is None:
            return
        update = self._latest_update
        self._render_status_badge(update.status)
        self._status_presenter.render_window_status(update.window)
        self._render_navigation_status()
        self._render_dashboard(update)
        self._navigation.render_navigation(update.navigation)
        self._quest_panel.set_progress(
            update.quest_title, update.quest_progress, update.quest_queue_completed
        )
        self._dungeon_panel.set_snapshots(update.dungeons)
        self._event_log_panel.set_events(update.events)
        self._target_debug_panel.render_target(
            self._translator,
            update.state.selected_target,
            update.engagement_break,
        )
        self._monster_stats_panel.render_metrics(self._translator, update.state.monster_stats)
        self._align_camera_button.setEnabled(
            update.status in {BotStatus.PAUSED, BotStatus.STANDBY, BotStatus.ALIGNMENT_FAILED}
        )
        if update.frame is not None:
            self._render_overlay_frame(update.frame, update.state)

    def _render_overlay_frame(
        self, frame: CapturedFrame | None, state: WorldState | None = None
    ) -> None:
        self._overlay.render_frame(frame, state)

    @Slot(bool)
    def _update_overlay_visibility(self, visible: bool) -> None:
        self._overlay.set_visible(visible)
        if visible and self._latest_update is not None:
            self._render_overlay_frame(self._latest_update.frame, self._latest_update.state)

    @Slot()
    def _toggle_map_popout(self) -> None:
        self._navigation.toggle_popout()

    @Slot()
    def _on_map_window_closed(self) -> None:
        self._navigation.dock()

    @Slot()
    def _request_start(self) -> None:
        self.start_requested.emit()

    @Slot()
    def _request_pause(self) -> None:
        self.pause_requested.emit()

    @Slot()
    def _request_emergency_stop(self) -> None:
        self._render_status_badge(BotStatus.EMERGENCY_STOPPED)
        self.emergency_stop_requested.emit()

    @Slot(int)
    def _switch_language(self, index: int) -> None:
        raw = self._language_selector.itemData(index)
        if raw is not None:
            try:
                language = Language(raw)
            except ValueError:
                return
            self._translator = Translator(language)
            self._retranslate()
            self._quest_controller.set_translator(self._translator)
            self._placement_overlay.set_translator(self._translator)

    @Slot(bool)
    def _on_placements_toggled(self, checked: bool) -> None:
        self._placement_overlay.set_guides_visible(checked)
        if self._latest_update is not None and self._latest_update.frame is not None:
            self._render_overlay_frame(self._latest_update.frame, self._latest_update.state)

    @Slot(float)
    def _on_anchor_threshold_changed(self, value: float) -> None:
        self.anchor_threshold_changed.emit(value)

    @Slot(bool)
    def _on_kill_verification_changed(self, enabled: bool) -> None:
        self.kill_verification_changed.emit(enabled)

    @Slot(object)
    def _on_target_selection_changed(self, config: object) -> None:
        self.target_selection_changed.emit(config)

    @Slot(object)
    def _on_powerup_config_changed(self, config: object) -> None:
        self._settings.handle_powerup_changed(config)
        self.powerup_config_changed.emit(self._settings.powerup_config)

    def _load_vitals_settings(self) -> None:
        self._settings.load_vitals()

    def get_vitals_config(self) -> VitalsTriggerConfig:
        return self._settings.vitals_config

    def _load_powerup_settings(self) -> None:
        self._settings.load_powerups()

    def get_powerup_config(self) -> PowerUpConfig:
        return self._settings.powerup_config

    def set_target_mob_options(self, options: tuple[str, ...] | Sequence[str]) -> None:
        self._target_panel.set_class_names(options)

    @Slot()
    def _on_emergency_changed(self) -> None:
        config = self._settings.save_emergency()
        self.emergency_config_changed.emit(config)

    def get_emergency_config(self) -> EmergencyRecoveryConfig:
        return self._settings.emergency_config

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._attack_key_button
            and self._controls_card.is_recording_attack_key
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
        ):
            self._record_attack_key(event)
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._request_emergency_stop()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.pause_requested.emit()
        self._placement_overlay.close()
        if self._navigation_controller is not None:
            self._navigation_controller.close()
        self._settings.save_vitals()
        self._settings.save_emergency()
        super().closeEvent(event)
