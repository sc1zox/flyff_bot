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
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.constants import (
    DEFAULT_CLIENT_WORLD_ROOT,
    DEFAULT_QUEST_DATABASE_PATH,
    DEFAULT_QUEST_NPC_POSITIONS_PATH,
    DEFAULT_WORLD_MAP_DIRECTORY,
    DEFAULT_WORLD_MONSTER_IDS_PATH,
)
from flyff_bot.features.automation.camera_alignment import DEFAULT_AUTO_ALIGN_CAMERA
from flyff_bot.features.automation.controllers import (
    DEFAULT_COMBAT_CLASS_PROFILE,
    MELEE_ENGAGEMENT_DISTANCE_UNITS,
    RANGED_ENGAGEMENT_DISTANCE_UNITS,
    CombatClassProfile,
    EngagementBreakReason,
)
from flyff_bot.features.automation.emergency_persistence import (
    DEFAULT_EMERGENCY_CONFIG_PATH,
    load_emergency_config,
    save_emergency_config,
)
from flyff_bot.features.automation.emergency_recovery import (
    MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    EmergencyRecoveryConfig,
)
from flyff_bot.features.automation.kill_goals import KillGoalConfig, MobKillProgress
from flyff_bot.features.automation.models import (
    MonsterStatsMetrics,
    MonsterStatsSource,
    MonsterStatsStatus,
    SelectedTarget,
    TargetNameStatus,
    TargetState,
    WorldState,
)
from flyff_bot.features.automation.powerup_controller import PowerUpConfig
from flyff_bot.features.automation.powerup_persistence import (
    DEFAULT_POWERUP_CONFIG_PATH,
    load_powerup_config,
    save_powerup_config,
)
from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerConfig,
    VitalTriggerRule,
    VitalTriggerType,
)
from flyff_bot.features.automation.vitals_persistence import (
    DEFAULT_VITALS_CONFIG_PATH,
    load_vitals_config,
    save_vitals_config,
)
from flyff_bot.features.input_control import parse_virtual_key
from flyff_bot.features.navigation.live_camera import CameraReadErrorCode
from flyff_bot.features.navigation.live_position import PositionReadErrorCode, PositionSource
from flyff_bot.features.quests.goals import QuestNpc
from flyff_bot.features.quests.persistence import (
    QuestDatabaseError,
    load_quest_database,
    load_quest_npc_positions,
)
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.features.vision.target_verification import (
    DEFAULT_ANCHOR_MATCH_THRESHOLD,
    MAXIMUM_MATCH_THRESHOLD,
    MINIMUM_MATCH_THRESHOLD,
)
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import BotStatus, DashboardUpdate, FarmingGoal, WindowStatus
from flyff_bot.ui.debug_overlay import DebugOverlayWidget, render_debug_overlay
from flyff_bot.ui.dungeon_panel import DungeonCooldownPanel
from flyff_bot.ui.event_log_panel import EventLogPanel
from flyff_bot.ui.navigation_window import NavigationMapWindow
from flyff_bot.ui.path_inspector import PathInspectorWidget
from flyff_bot.ui.placement_overlay import ClientGeometryProvider, PlacementOverlayWindow
from flyff_bot.ui.powerup_panel import PowerUpPanel
from flyff_bot.ui.quest_panel import QuestGoalPanel
from flyff_bot.ui.target_panel import TargetSelectionPanel
from flyff_bot.ui.theme import apply_theme
from flyff_bot.ui.world_data_dialog import WorldDataDialog

MATCH_THRESHOLD_STEP = 0.05
MATCH_THRESHOLD_DECIMALS = 2

HOTKEY_CHOICES = [
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "F8",
    "F9",
    "F10",
    "F11",
    "F12",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
    "C",
    "Space",
]

EMERGENCY_HOTKEY_CHOICES = [
    *(f"F{number}" for number in range(1, 13)),
    *(str(digit) for digit in range(10)),
    *(chr(code) for code in range(ord("A"), ord("Z") + 1)),
]
STUCK_TIMEOUT_STEP_SECONDS = 5.0
STUCK_TIMEOUT_DECIMALS = 1
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
        self._world_data_dialog: WorldDataDialog | None = None
        self._vitals_config_path = vitals_config_path or DEFAULT_VITALS_CONFIG_PATH
        self._powerup_config_path = powerup_config_path or DEFAULT_POWERUP_CONFIG_PATH
        self._emergency_config_path = emergency_config_path or DEFAULT_EMERGENCY_CONFIG_PATH
        self._latest_update: DashboardUpdate | None = None

        # Persistent header cards
        self._status_card = QGroupBox()
        self._status_card.setObjectName("CardPanel")
        self._controls_card = QGroupBox()
        self._controls_card.setObjectName("CardPanel")

        # Functional view cards
        self._summary_card = QGroupBox()
        self._summary_card.setObjectName("CardPanel")

        # Status & Metrics
        self._status_label = QLabel()
        self._status_label.setObjectName("StatusBadge")
        self._window_label = QLabel()
        self._window_label.setObjectName("StatChip")
        self._window_status = WindowStatus.NOT_FOUND
        self._gps_label = QLabel()
        self._gps_label.setObjectName("StatChip")
        self._camera_label = QLabel()
        self._camera_label.setObjectName("StatChip")
        self._position_source = PositionSource.UNAVAILABLE
        self._mob_label = QLabel()
        self._mob_label.setObjectName("StatChip")
        self._target_label = QLabel()
        self._target_label.setObjectName("StatChip")
        self._goal_label = QLabel()
        self._goal_label.setObjectName("StatChip")
        self._vitals_label = QLabel()
        self._vitals_label.setObjectName("StatChip")
        self._kill_progress_label = QLabel()
        self._kill_progress_label.setObjectName("StatChip")

        # Debug Overlay Viewport
        self._overlay_label = DebugOverlayWidget()
        self._overlay_label.setVisible(False)

        # Transparent in-game placement guide overlay
        self._placement_overlay = PlacementOverlayWindow(self._translator)

        # Navigation Map & Inspector
        self._path_inspector = PathInspectorWidget(self._translator)
        self._map_container = QWidget()
        self._map_container_layout = QVBoxLayout(self._map_container)
        self._map_container_layout.setContentsMargins(0, 0, 0, 0)
        self._map_container_layout.addWidget(self._path_inspector)
        self._map_window = NavigationMapWindow(self._translator)
        self._popout_map_button = QPushButton()
        self._world_data_button = QPushButton()
        self._is_map_popped_out = False
        self._teardowns: list[Callable[[], None]] = []

        # Primary Action Controls
        self._start_button = QPushButton()
        self._start_button.setObjectName("ActionStart")
        self._pause_button = QPushButton()
        self._pause_button.setObjectName("ActionPause")
        self._attack_key_label = QLabel()
        self._attack_key_button = QPushButton()
        self._align_camera_button = QPushButton()
        self._auto_align_toggle = QCheckBox()
        self._auto_align_toggle.setObjectName("Switch")
        self._auto_align_toggle.setChecked(DEFAULT_AUTO_ALIGN_CAMERA)
        self._attack_virtual_key = parse_virtual_key("F3")
        self._attack_key_name = "F3"
        self._is_recording_attack_key = False
        self._language_label = QLabel()
        self._language_selector = QComboBox()

        # Display settings
        self._camera_preview_toggle = QCheckBox()
        self._camera_preview_toggle.setObjectName("Switch")
        self._placements_toggle = QCheckBox()
        self._placements_toggle.setObjectName("Switch")

        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("FunctionalTabs")
        self._tab_scroll_areas: dict[DashboardTab, QScrollArea] = {}

        # Sub-panels
        self._combat_panel = QGroupBox()
        self._combat_panel.setObjectName("CardPanel")
        self._combat_class_label = QLabel()
        self._combat_class_selector = QComboBox()
        for profile in CombatClassProfile:
            self._combat_class_selector.addItem("", userData=profile.value)
        self._combat_class_selector.setCurrentIndex(
            list(CombatClassProfile).index(DEFAULT_COMBAT_CLASS_PROFILE)
        )
        self._engagement_distance_label = QLabel()
        self._engagement_distance_spin = QDoubleSpinBox()
        self._engagement_distance_spin.setRange(0.1, 100.0)
        self._engagement_distance_spin.setSingleStep(0.5)
        self._engagement_distance_spin.setDecimals(1)
        self._engagement_distance_spin.setValue(MELEE_ENGAGEMENT_DISTANCE_UNITS)
        self._target_grace_label = QLabel()
        self._target_grace_spin = QDoubleSpinBox()
        self._target_grace_spin.setRange(0.0, 10.0)
        self._target_grace_spin.setSingleStep(0.1)
        self._target_grace_spin.setDecimals(1)
        self._target_grace_spin.setValue(0.8)
        self._kill_verification_label = QLabel()
        self._kill_verification_toggle = QCheckBox()
        self._kill_verification_toggle.setObjectName("Switch")
        self._kill_verification_toggle.setChecked(True)
        self._anchor_threshold_label = QLabel()
        self._anchor_threshold_spin = QDoubleSpinBox()
        self._anchor_threshold_spin.setRange(MINIMUM_MATCH_THRESHOLD, MAXIMUM_MATCH_THRESHOLD)
        self._anchor_threshold_spin.setSingleStep(MATCH_THRESHOLD_STEP)
        self._anchor_threshold_spin.setDecimals(MATCH_THRESHOLD_DECIMALS)
        self._anchor_threshold_spin.setValue(DEFAULT_ANCHOR_MATCH_THRESHOLD)

        self._recovery_panel = QGroupBox()
        self._recovery_panel.setObjectName("CardPanel")
        self._recovery_timeout_label = QLabel()
        self._recovery_timeout_spin = QDoubleSpinBox()
        self._recovery_timeout_spin.setRange(
            MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
            MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
        )
        self._recovery_timeout_spin.setSingleStep(STUCK_TIMEOUT_STEP_SECONDS)
        self._recovery_timeout_spin.setDecimals(STUCK_TIMEOUT_DECIMALS)
        self._recovery_hotkey_label = QLabel()
        self._recovery_hotkey_combo = QComboBox()
        self._recovery_hotkey_combo.addItem("", userData=None)
        for key_name in EMERGENCY_HOTKEY_CHOICES:
            self._recovery_hotkey_combo.addItem(key_name, userData=key_name)
        self._load_emergency_settings()

        self._target_panel = TargetSelectionPanel(self._translator)
        self._quest_panel = QuestGoalPanel(self._translator)
        self._dungeon_panel = DungeonCooldownPanel(self._translator)

        self._target_debug_panel = QGroupBox()
        self._target_debug_panel.setObjectName("CardPanel")
        self._target_anchor_label = QLabel()
        self._target_anchor_val = QLabel()
        self._target_anchor_val.setObjectName("StatChip")
        self._target_hp_label = QLabel()
        self._target_hp_val = QLabel()
        self._target_hp_val.setObjectName("StatChip")
        self._target_name_label = QLabel()
        self._target_name_val = QLabel()
        self._target_name_val.setObjectName("StatChip")
        self._target_state_label = QLabel()
        self._target_state_val = QLabel()
        self._target_state_val.setObjectName("StatChip")
        self._target_reason_label = QLabel()
        self._target_reason_val = QLabel()
        self._target_reason_val.setObjectName("StatChip")
        self._target_break_label = QLabel()
        self._target_break_val = QLabel()
        self._target_break_val.setObjectName("StatChip")

        self._monster_stats_panel = QGroupBox()
        self._monster_stats_panel.setObjectName("CardPanel")
        self._monster_anchor_label = QLabel()
        self._monster_anchor_val = QLabel()
        self._monster_anchor_val.setObjectName("StatChip")
        self._monster_roi_label = QLabel()
        self._monster_roi_val = QLabel()
        self._monster_roi_val.setObjectName("StatChip")
        self._monster_source_label = QLabel()
        self._monster_source_val = QLabel()
        self._monster_source_val.setObjectName("StatChip")
        self._monster_kills_label = QLabel()
        self._monster_kills_val = QLabel()
        self._monster_kills_val.setObjectName("StatChip")
        self._monster_text_label = QLabel()
        self._monster_text_val = QLabel()
        self._monster_text_val.setObjectName("StatChip")
        self._monster_status_label = QLabel()
        self._monster_status_val = QLabel()
        self._monster_status_val.setObjectName("StatChip")

        self._event_log_panel = EventLogPanel(self._translator)

        self._vitals_panel = QGroupBox()
        self._vitals_panel.setObjectName("CardPanel")
        self._vitals_col_type = QLabel()
        self._vitals_col_active = QLabel()
        self._vitals_col_threshold = QLabel()
        self._vitals_col_hotkey = QLabel()
        self._vitals_col_debounce = QLabel()
        self._hp_label = QLabel()
        self._hp_check = QCheckBox()
        self._hp_check.setObjectName("Switch")
        self._hp_spin = QSpinBox()
        self._hp_spin.setRange(1, 99)
        self._hp_combo = QComboBox()
        self._hp_combo.addItems(HOTKEY_CHOICES)
        self._hp_debounce_spin = QDoubleSpinBox()
        self._hp_debounce_spin.setRange(0.1, 30.0)
        self._hp_debounce_spin.setSingleStep(0.5)
        self._hp_debounce_spin.setDecimals(1)
        self._mp_label = QLabel()
        self._mp_check = QCheckBox()
        self._mp_check.setObjectName("Switch")
        self._mp_spin = QSpinBox()
        self._mp_spin.setRange(1, 99)
        self._mp_combo = QComboBox()
        self._mp_combo.addItems(HOTKEY_CHOICES)
        self._mp_debounce_spin = QDoubleSpinBox()
        self._mp_debounce_spin.setRange(0.1, 30.0)
        self._mp_debounce_spin.setSingleStep(0.5)
        self._mp_debounce_spin.setDecimals(1)
        self._fp_label = QLabel()
        self._fp_check = QCheckBox()
        self._fp_check.setObjectName("Switch")
        self._fp_spin = QSpinBox()
        self._fp_spin.setRange(1, 99)
        self._fp_combo = QComboBox()
        self._fp_combo.addItems(HOTKEY_CHOICES)
        self._fp_debounce_spin = QDoubleSpinBox()
        self._fp_debounce_spin.setRange(0.1, 30.0)
        self._fp_debounce_spin.setSingleStep(0.5)
        self._fp_debounce_spin.setDecimals(1)
        self._load_vitals_settings()

        self._powerup_panel = PowerUpPanel(self._translator)
        self._load_powerup_settings()

        self._build_layout()
        self._connect_controls()
        self._retranslate()
        self._render_status_badge(BotStatus.PAUSED)
        self._render_window_status()
        self._render_gps()
        self._render_camera()
        self._render_mob_count(0)
        self._render_vitals()
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
        return self._world_data_dialog

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
        return self._attack_virtual_key

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
        return self._combat_class_selector

    @property
    def engagement_distance_spin(self) -> QDoubleSpinBox:
        return self._engagement_distance_spin

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
        return self._is_map_popped_out

    @property
    def popout_map_button(self) -> QPushButton:
        return self._popout_map_button

    @property
    def kill_progress_label(self) -> QLabel:
        return self._kill_progress_label

    def set_window_status(self, status: WindowStatus) -> None:
        self._window_status = status
        self._render_window_status()

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
        return self._recovery_timeout_spin

    @property
    def recovery_hotkey_combo(self) -> QComboBox:
        return self._recovery_hotkey_combo

    def _build_layout(self) -> None:
        status_top = QHBoxLayout()
        status_top.addWidget(self._status_label)
        status_top.addWidget(self._window_label)
        status_top.addWidget(self._gps_label)
        status_top.addWidget(self._camera_label)
        status_top.addStretch()
        self._status_card.setLayout(status_top)

        metrics_layout = QGridLayout()
        metrics_layout.addWidget(self._mob_label, 0, 0)
        metrics_layout.addWidget(self._target_label, 0, 1)
        metrics_layout.addWidget(self._kill_progress_label, 0, 2)
        metrics_layout.addWidget(self._vitals_label, 1, 0, 1, 2)
        metrics_layout.addWidget(self._goal_label, 1, 2)
        self._summary_card.setLayout(metrics_layout)

        controls_layout = QGridLayout()
        controls_layout.addWidget(self._start_button, 0, 0)
        controls_layout.addWidget(self._pause_button, 0, 1)
        controls_layout.addWidget(self._attack_key_label, 0, 2)
        controls_layout.addWidget(self._attack_key_button, 0, 3)
        controls_layout.addWidget(self._align_camera_button, 1, 0)
        controls_layout.addWidget(self._auto_align_toggle, 1, 1, 1, 2)
        controls_layout.addWidget(self._language_label, 1, 3)
        controls_layout.addWidget(self._language_selector, 1, 4)
        self._controls_card.setLayout(controls_layout)

        combat_layout = QGridLayout()
        combat_layout.addWidget(self._combat_class_label, 0, 0)
        combat_layout.addWidget(self._combat_class_selector, 0, 1)
        combat_layout.addWidget(self._engagement_distance_label, 1, 0)
        combat_layout.addWidget(self._engagement_distance_spin, 1, 1)
        combat_layout.addWidget(self._target_grace_label, 2, 0)
        combat_layout.addWidget(self._target_grace_spin, 2, 1)
        combat_layout.addWidget(self._kill_verification_toggle, 3, 0, 1, 2)
        combat_layout.addWidget(self._anchor_threshold_label, 4, 0)
        combat_layout.addWidget(self._anchor_threshold_spin, 4, 1)
        self._combat_panel.setLayout(combat_layout)

        controls_layout.setColumnStretch(5, 1)

        preview_controls = QWidget()
        preview_controls_layout = QHBoxLayout(preview_controls)
        preview_controls_layout.setContentsMargins(0, 0, 0, 0)
        preview_controls_layout.addWidget(self._camera_preview_toggle)
        preview_controls_layout.addStretch()

        nav_controls = QWidget()
        nav_controls_layout = QHBoxLayout(nav_controls)
        nav_controls_layout.setContentsMargins(0, 0, 0, 0)
        nav_controls_layout.addWidget(self._world_data_button)
        nav_controls_layout.addWidget(self._popout_map_button)
        nav_controls_layout.addStretch()

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
            nav_controls,
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
        self._target_grace_spin.valueChanged.connect(self.combat_grace_changed)
        self._combat_class_selector.currentIndexChanged.connect(self._on_combat_class_changed)
        self._engagement_distance_spin.valueChanged.connect(self.engagement_distance_changed)
        self._engagement_distance_spin.valueChanged.connect(self._on_engagement_distance_changed)
        self._kill_verification_toggle.toggled.connect(self._on_kill_verification_changed)
        self._anchor_threshold_spin.valueChanged.connect(self._on_anchor_threshold_changed)
        self._target_panel.selection_changed.connect(self._on_target_selection_changed)
        self._quest_panel.selection_changed.connect(self.quest_selection_changed)
        self._recovery_timeout_spin.valueChanged.connect(self._on_emergency_changed)
        self._recovery_hotkey_combo.currentIndexChanged.connect(self._on_emergency_changed)
        for check, spin, combo, debounce in (
            (self._hp_check, self._hp_spin, self._hp_combo, self._hp_debounce_spin),
            (self._mp_check, self._mp_spin, self._mp_combo, self._mp_debounce_spin),
            (self._fp_check, self._fp_spin, self._fp_combo, self._fp_debounce_spin),
        ):
            check.toggled.connect(self._on_vitals_changed)
            spin.valueChanged.connect(self._on_vitals_changed)
            combo.currentIndexChanged.connect(self._on_vitals_changed)
            debounce.valueChanged.connect(self._on_vitals_changed)

    @Slot()
    def _on_vitals_changed(self) -> None:
        config = self.get_vitals_config()
        save_vitals_config(config, self._vitals_config_path)
        self.vitals_config_changed.emit(config)

    @Slot()
    def _on_combat_class_changed(self) -> None:
        profile = self._combat_class_selector.currentData()
        if isinstance(profile, CombatClassProfile):
            selected_profile = profile
        elif profile in {item.value for item in CombatClassProfile}:
            selected_profile = CombatClassProfile(profile)
        else:
            return
        if selected_profile is CombatClassProfile.MELEE:
            distance = MELEE_ENGAGEMENT_DISTANCE_UNITS
        elif selected_profile is CombatClassProfile.RANGED:
            distance = RANGED_ENGAGEMENT_DISTANCE_UNITS
        else:
            distance = self._engagement_distance_spin.value()
        self._engagement_distance_spin.setValue(distance)
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
        current = self._combat_class_selector.currentData()
        current_profile = (
            current if isinstance(current, CombatClassProfile) else CombatClassProfile(current)
        )
        if profile is not current_profile:
            self._combat_class_selector.setCurrentIndex(list(CombatClassProfile).index(profile))

    def show_error_dialog(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    @Slot()
    def _on_world_data_clicked(self) -> None:
        dialog = self._world_data_dialog
        if dialog is None:
            dialog = WorldDataDialog(
                self._translator,
                self._client_world_root,
                self._world_map_dir,
                monster_names_path=self._monster_names_path,
                parent=self,
            )
            dialog.vector_navigation_requested.connect(self.vector_navigation_requested)
            dialog.vector_navigation_cleared.connect(self.vector_navigation_cleared)
            self._world_data_dialog = dialog
        dialog.refresh()
        dialog.show()
        dialog.raise_()

    def _retranslate(self) -> None:
        self.setWindowTitle(self._translator.text(Message.UI_TITLE))
        self._status_card.setTitle(self._translator.text(Message.UI_CARD_STATUS))
        self._controls_card.setTitle(self._translator.text(Message.UI_CARD_CONTROLS))
        self._summary_card.setTitle(self._translator.text(Message.UI_DASHBOARD_SUMMARY))
        self._retranslate_tabs()
        self._popout_map_button.setText(
            self._translator.text(
                Message.UI_DOCK_MAP if self._is_map_popped_out else Message.UI_POPOUT_MAP
            )
        )
        self._map_window.set_translator(self._translator)

        self._start_button.setText(self._translator.text(Message.UI_START))
        self._pause_button.setText(self._translator.text(Message.UI_PAUSE))
        self._attack_key_label.setText(self._translator.text(Message.UI_ATTACK_KEY))
        self._attack_key_button.setToolTip(self._translator.text(Message.UI_ATTACK_KEY_TOOLTIP))
        self._attack_key_button.setText(
            self._translator.text(Message.UI_ATTACK_KEY_RECORDING)
            if self._is_recording_attack_key
            else self._attack_key_name
        )
        self._align_camera_button.setText(self._translator.text(Message.UI_ALIGN_CAMERA))
        self._align_camera_button.setToolTip(self._translator.text(Message.UI_ALIGN_CAMERA_TOOLTIP))
        self._auto_align_toggle.setText(self._translator.text(Message.UI_AUTO_ALIGN_CAMERA))
        self._auto_align_toggle.setToolTip(
            self._translator.text(Message.UI_AUTO_ALIGN_CAMERA_TOOLTIP)
        )
        self._language_label.setText(self._translator.text(Message.UI_LANGUAGE))
        self._camera_preview_toggle.setText(self._translator.text(Message.UI_CAMERA_PREVIEW))
        self._camera_preview_toggle.setToolTip(
            self._translator.text(Message.UI_CAMERA_PREVIEW_TOOLTIP)
        )
        self._powerup_panel.set_translator(self._translator)
        self._placements_toggle.setText(self._translator.text(Message.UI_PLACEMENTS_TOGGLE))
        self._placements_toggle.setToolTip(self._translator.text(Message.UI_PLACEMENTS_TOOLTIP))
        self._combat_panel.setTitle(self._translator.text(Message.UI_COMBAT_SETTINGS))
        self._combat_class_label.setText(self._translator.text(Message.UI_COMBAT_CLASS))
        self._combat_class_selector.setToolTip(
            self._translator.text(Message.UI_COMBAT_CLASS_TOOLTIP)
        )
        for profile in CombatClassProfile:
            index = self._combat_class_selector.findData(profile)
            if index >= 0:
                key = (
                    Message.UI_COMBAT_CLASS_MELEE
                    if profile is CombatClassProfile.MELEE
                    else Message.UI_COMBAT_CLASS_RANGED
                    if profile is CombatClassProfile.RANGED
                    else Message.UI_COMBAT_CLASS_CUSTOM
                )
                self._combat_class_selector.setItemText(index, self._translator.text(key))
        self._engagement_distance_label.setText(
            self._translator.text(Message.UI_ENGAGEMENT_DISTANCE)
        )
        self._engagement_distance_spin.setToolTip(
            self._translator.text(Message.UI_ENGAGEMENT_DISTANCE_TOOLTIP)
        )
        self._retranslate_recovery()
        self._target_panel.set_translator(self._translator)
        self._quest_panel.set_translator(self._translator)
        self._dungeon_panel.set_translator(self._translator)
        self._target_grace_label.setText(self._translator.text(Message.UI_TARGET_GRACE_PERIOD))
        self._target_grace_spin.setToolTip(self._translator.text(Message.UI_TARGET_GRACE_TOOLTIP))
        self._kill_verification_label.setText(self._translator.text(Message.UI_KILL_VERIFICATION))
        self._kill_verification_toggle.setToolTip(
            self._translator.text(Message.UI_KILL_VERIFICATION_TOOLTIP)
        )
        self._anchor_threshold_label.setText(self._translator.text(Message.UI_ANCHOR_THRESHOLD))
        self._anchor_threshold_spin.setToolTip(
            self._translator.text(Message.UI_ANCHOR_THRESHOLD_TOOLTIP)
        )
        self._target_debug_panel.setTitle(self._translator.text(Message.UI_TARGET_DEBUG_TITLE))
        self._target_anchor_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_ANCHOR))
        self._target_hp_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_HP))
        self._target_name_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_NAME))
        self._target_state_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_STATE))
        self._target_reason_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_REASON))
        self._target_break_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_BREAK))
        self._monster_stats_panel.setTitle(
            self._translator.text(Message.UI_MONSTER_STATS_DEBUG_TITLE)
        )
        self._monster_anchor_label.setText(
            self._translator.text(Message.UI_MONSTER_STATS_DEBUG_ANCHOR)
        )
        self._monster_roi_label.setText(self._translator.text(Message.UI_MONSTER_STATS_DEBUG_ROI))
        self._monster_source_label.setText(
            self._translator.text(Message.UI_MONSTER_STATS_DEBUG_SOURCE)
        )
        self._monster_kills_label.setText(
            self._translator.text(Message.UI_MONSTER_STATS_DEBUG_KILLS)
        )
        self._monster_text_label.setText(self._translator.text(Message.UI_MONSTER_STATS_DEBUG_TEXT))
        self._monster_status_label.setText(
            self._translator.text(Message.UI_MONSTER_STATS_DEBUG_STATUS)
        )
        self._render_monster_stats_debug(
            self._latest_update.state.monster_stats
            if self._latest_update is not None
            else MonsterStatsMetrics()
        )
        self._event_log_panel.set_translator(self._translator)
        self._vitals_panel.setTitle(self._translator.text(Message.UI_VITALS_TITLE))
        self._vitals_col_type.setText(self._translator.text(Message.UI_VITALS_HP)[:2])
        self._vitals_col_active.setText(self._translator.text(Message.UI_VITALS_ACTIVE))
        self._vitals_col_threshold.setText(self._translator.text(Message.UI_VITALS_THRESHOLD))
        self._vitals_col_hotkey.setText(self._translator.text(Message.UI_VITALS_HOTKEY))
        self._vitals_col_debounce.setText(self._translator.text(Message.UI_VITALS_DEBOUNCE))
        self._hp_label.setText(self._translator.text(Message.UI_VITALS_HP))
        self._mp_label.setText(self._translator.text(Message.UI_VITALS_MP))
        self._fp_label.setText(self._translator.text(Message.UI_VITALS_FP))
        self._path_inspector.set_translator(self._translator)
        self._world_data_button.setText(self._translator.text(Message.UI_WORLD_DATA))
        self._world_data_button.setToolTip(self._translator.text(Message.UI_WORLD_DATA_TOOLTIP))
        if self._world_data_dialog is not None:
            self._world_data_dialog.set_translator(self._translator)
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
            self._render_status_badge(BotStatus.PAUSED)
            self._render_window_status()
            self._render_gps()
            self._render_camera()
            self._render_mob_count(0)
            self._render_vitals()

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

    def _retranslate_recovery(self) -> None:
        self._recovery_panel.setTitle(self._translator.text(Message.UI_RECOVERY_TITLE))
        self._recovery_timeout_label.setText(self._translator.text(Message.UI_RECOVERY_TIMEOUT))
        self._recovery_timeout_spin.setToolTip(
            self._translator.text(Message.UI_RECOVERY_TIMEOUT_TOOLTIP)
        )
        self._recovery_hotkey_label.setText(self._translator.text(Message.UI_RECOVERY_HOTKEY))
        self._recovery_hotkey_combo.setToolTip(
            self._translator.text(Message.UI_RECOVERY_HOTKEY_TOOLTIP)
        )
        self._recovery_hotkey_combo.blockSignals(True)
        self._recovery_hotkey_combo.setItemText(
            0, self._translator.text(Message.UI_RECOVERY_HOTKEY_UNASSIGNED)
        )
        self._recovery_hotkey_combo.blockSignals(False)

    @Slot()
    def _request_camera_alignment(self) -> None:
        self.align_camera_requested.emit()

    @Slot()
    def _begin_attack_key_recording(self) -> None:
        self._is_recording_attack_key = True
        self._attack_key_button.setText(self._translator.text(Message.UI_ATTACK_KEY_RECORDING))
        self._attack_key_button.setFocus(Qt.FocusReason.MouseFocusReason)

    def _record_attack_key(self, event: QKeyEvent) -> None:
        label = _key_label(event.key())
        self._is_recording_attack_key = False
        if label is None:
            self._attack_key_button.setToolTip(
                self._translator.text(Message.UI_ATTACK_KEY_UNSUPPORTED)
            )
            self._attack_key_button.setText(self._attack_key_name)
            return
        self._attack_virtual_key = parse_virtual_key(label)
        self._attack_key_name = label
        self._attack_key_button.setToolTip(self._translator.text(Message.UI_ATTACK_KEY_TOOLTIP))
        self._attack_key_button.setText(label)
        self.attack_key_changed.emit(self._attack_virtual_key)

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
        self._status_label.setText(
            self._translator.text(
                Message.UI_BOT_STATUS,
                status=self._translator.text(_status_message(status)),
            )
        )
        self._status_label.setProperty("status", _status_category(status))
        style = self._status_label.style()
        if style is not None:
            style.unpolish(self._status_label)
            style.polish(self._status_label)

    def _render_window_status(self) -> None:
        self._window_label.setText(
            self._translator.text(_window_status_message(self._window_status))
        )

    def _render_gps(self) -> None:
        live = self._position_source is PositionSource.LIVE
        navigation = self._latest_update.navigation if self._latest_update is not None else None
        position = navigation.world_position if navigation is not None else None
        error_code = navigation.position_error_code if navigation is not None else None
        reason = self._translator.text(
            Message.UI_GPS_UNAVAILABLE if error_code is None else _gps_error_message(error_code)
        )
        self._gps_label.setText(
            self._translator.text(Message.UI_GPS_LIVE)
            if live
            else self._translator.text(Message.UI_GPS_OFFLINE, reason=reason)
        )
        self._gps_label.setProperty("gps", "live" if live else "offline")
        self._gps_label.setToolTip(
            self._translator.text(
                Message.UI_GPS_COORDINATES,
                x=f"{position.x:.2f}",
                y=f"{position.y:.2f}",
                z=f"{position.z:.2f}",
            )
            if position is not None
            else self._translator.text(Message.UI_GPS_OFFLINE, reason=reason)
        )
        style = self._gps_label.style()
        if style is not None:
            style.unpolish(self._gps_label)
            style.polish(self._gps_label)

    def _render_camera(self) -> None:
        navigation = self._latest_update.navigation if self._latest_update is not None else None
        state = navigation.camera_state if navigation is not None else None
        error_code = navigation.camera_error_code if navigation is not None else None
        reason = self._translator.text(
            Message.UI_GPS_UNAVAILABLE if error_code is None else _camera_error_message(error_code)
        )
        self._camera_label.setText(
            self._translator.text(Message.UI_CAMERA_LIVE)
            if state is not None
            else self._translator.text(Message.UI_CAMERA_OFFLINE, reason=reason)
        )
        self._camera_label.setProperty("camera", "live" if state is not None else "offline")
        style = self._camera_label.style()
        if style is not None:
            style.unpolish(self._camera_label)
            style.polish(self._camera_label)

    def _render_update(self) -> None:
        if self._latest_update is None:
            return
        update = self._latest_update
        self._render_status_badge(update.status)
        self._window_status = update.window
        self._render_window_status()
        self._position_source = (
            update.navigation.position_source
            if update.navigation is not None
            else PositionSource.UNAVAILABLE
        )
        self._render_gps()
        self._render_camera()
        self._render_mob_count(update.state.nearby_mob_count)
        self._render_target(update.state.selected_target)
        self._render_goal(update.goal, update.state.inventory)
        self._render_vitals(update.state)
        self._render_kill_progress(update.kill_progress)
        self._target_panel.set_progress(update.kill_progress)
        self._quest_panel.set_progress(
            update.quest_title, update.quest_progress, update.quest_queue_completed
        )
        self._dungeon_panel.set_snapshots(update.dungeons)
        self._event_log_panel.set_events(update.events)
        self._render_target_debug(update.state.selected_target, update.engagement_break)
        self._render_monster_stats_debug(update.state.monster_stats)
        self._path_inspector.set_navigation(update.navigation)
        self._align_camera_button.setEnabled(
            update.status in {BotStatus.PAUSED, BotStatus.STANDBY, BotStatus.ALIGNMENT_FAILED}
        )
        if update.frame is not None:
            self._render_overlay_frame(update.frame, update.state)

    def _render_mob_count(self, count: int) -> None:
        self._mob_label.setText(self._translator.text(Message.UI_MOBS_COUNT, count=count))

    def _render_target(self, target: SelectedTarget) -> None:
        msg = (
            Message.UI_TARGET_VALID
            if target.state is TargetState.VALID
            else Message.UI_TARGET_WRONG
            if target.state is TargetState.WRONG
            else Message.UI_TARGET_NONE
        )
        self._target_label.setText(self._translator.text(msg))

    def _render_goal(self, goal: FarmingGoal | None, inventory: Sequence[object]) -> None:
        state = self._latest_update.state if self._latest_update is not None else None
        self._goal_label.setText(_goal_text(self._translator, state, goal))

    def _render_vitals(self, state: WorldState | None = None) -> None:
        vitals = state.player_vitals if state is not None else None
        hp = (
            f"{vitals.hp_percentage:.1f}"
            if vitals is not None and vitals.hp_percentage is not None
            else "--"
        )
        mp = (
            f"{vitals.mp_percentage:.1f}"
            if vitals is not None and vitals.mp_percentage is not None
            else "--"
        )
        fp = (
            f"{vitals.fp_percentage:.1f}"
            if vitals is not None and vitals.fp_percentage is not None
            else "--"
        )
        self._vitals_label.setText(
            self._translator.text(Message.UI_VITALS_STATUS, hp=hp, mp=mp, fp=fp)
        )

    def _render_kill_progress(self, progress: tuple[MobKillProgress, ...]) -> None:
        self._kill_progress_label.setText(_kill_progress_text(self._translator, progress))

    def _render_target_debug(
        self, target: SelectedTarget, break_reason: EngagementBreakReason | None
    ) -> None:
        metrics = target.metrics
        self._target_anchor_val.setText(
            self._translator.text(
                Message.UI_TARGET_DEBUG_ANCHOR_VALUE,
                status=_pass_fail_text(self._translator, metrics.anchor_passed),
                score=f"{metrics.anchor_score:.2f}",
                threshold=f"{metrics.anchor_threshold:.2f}",
            )
        )
        self._target_hp_val.setText(
            self._translator.text(
                Message.UI_TARGET_DEBUG_HP_VALUE,
                status=_pass_fail_text(self._translator, metrics.hp_passed),
                pixels=metrics.hp_pixel_count,
                percentage=f"{metrics.hp_percentage:.1f}",
            )
        )
        self._target_name_val.setText(
            self._translator.text(Message.UI_TARGET_DEBUG_NAME_NOT_EVALUATED)
            if metrics.name_status is TargetNameStatus.NOT_EVALUATED
            else self._translator.text(
                Message.UI_TARGET_DEBUG_NAME_VALUE,
                status=_pass_fail_text(self._translator, metrics.name_passed),
                text=metrics.name_text,
                name=metrics.name_candidate or self._translator.text(Message.UI_NO_TARGET_NAME),
            )
        )

        self._target_state_val.setText(self._translator.text(_target_state_message(target.state)))
        self._target_reason_val.setText(
            self._translator.text(_target_failure_reason_message(target))
        )
        self._target_break_val.setText(
            self._translator.text(_engagement_break_message(break_reason))
        )

    def _render_monster_stats_debug(self, metrics: MonsterStatsMetrics) -> None:
        if not metrics.anchor_configured:
            anchor_text = self._translator.text(Message.UI_MONSTER_STATS_DEBUG_ANCHOR_FIXED_REGION)
        else:
            anchor_text = self._translator.text(
                Message.UI_MONSTER_STATS_DEBUG_ANCHOR_VALUE,
                status=_pass_fail_text(self._translator, metrics.anchor_passed),
                score=f"{metrics.anchor_score:.2f}",
                threshold=f"{metrics.anchor_threshold:.2f}",
            )
        self._monster_anchor_val.setText(anchor_text)

        if metrics.roi_width > 0 and metrics.roi_height > 0:
            self._monster_roi_val.setText(
                self._translator.text(
                    Message.UI_MONSTER_STATS_DEBUG_ROI_VALUE,
                    width=metrics.roi_width,
                    height=metrics.roi_height,
                )
            )
        else:
            self._monster_roi_val.setText(
                self._translator.text(Message.UI_MONSTER_STATS_DEBUG_STATUS_ROI_UNAVAILABLE)
            )

        self._monster_source_val.setText(
            self._translator.text(_monster_stats_source_message(metrics.source))
        )
        self._monster_kills_val.setText(
            str(metrics.parsed_count)
            if metrics.parsed_count is not None
            else self._translator.text(Message.UI_MONSTER_STATS_DEBUG_NO_COUNT)
        )
        self._monster_text_val.setText(
            metrics.raw_text
            if metrics.raw_text
            else self._translator.text(Message.UI_MONSTER_STATS_DEBUG_NO_TEXT)
        )
        self._monster_status_val.setText(
            self._translator.text(_monster_stats_status_message(metrics.status))
        )

    def _render_overlay_frame(
        self, frame: CapturedFrame | None, state: WorldState | None = None
    ) -> None:
        if frame is None:
            self._overlay_label.clear()
            return
        mobs = state.visible_mobs if state is not None else ()
        target = (
            state.selected_target
            if state is not None
            else SelectedTarget(TargetState.NONE, None, 0)
        )
        vitals = state.player_vitals if state is not None else None
        pixmap = render_debug_overlay(
            frame,
            mobs,
            target,
            self._translator,
            vitals=vitals,
            show_placements=self._placements_toggle.isChecked(),
        )
        self._overlay_label.setPixmap(pixmap)

    @Slot(bool)
    def _update_overlay_visibility(self, visible: bool) -> None:
        self._overlay_label.setVisible(visible)
        if visible and self._latest_update is not None:
            self._render_overlay_frame(self._latest_update.frame, self._latest_update.state)

    @Slot()
    def _toggle_map_popout(self) -> None:
        if self._is_map_popped_out:
            self._dock_map()
        else:
            self._popout_map()

    def _popout_map(self) -> None:
        item = self._map_container_layout.takeAt(0)
        if item is not None:
            inspector = item.widget()
            if isinstance(inspector, PathInspectorWidget):
                self._map_window.set_inspector(inspector)
                self._map_window.show()
                self._is_map_popped_out = True
                self._popout_map_button.setText(self._translator.text(Message.UI_DOCK_MAP))

    def _dock_map(self) -> None:
        inspector = self._map_window.take_inspector()
        if inspector is not None:
            self._map_container_layout.addWidget(inspector)
            self._map_window.hide()
            self._is_map_popped_out = False
            self._popout_map_button.setText(self._translator.text(Message.UI_POPOUT_MAP))

    @Slot()
    def _on_map_window_closed(self) -> None:
        self._dock_map()

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
        if isinstance(config, PowerUpConfig):
            save_powerup_config(config, self._powerup_config_path)
            self.powerup_config_changed.emit(config)

    def _load_vitals_settings(self) -> None:
        config = load_vitals_config(self._vitals_config_path)
        for rule in config.rules:
            key_name = ""
            for name in HOTKEY_CHOICES:
                try:
                    if parse_virtual_key(name) == rule.virtual_key:
                        key_name = name
                        break
                except ValueError:
                    continue
            if rule.vital_type is VitalTriggerType.HP:
                self._hp_check.setChecked(rule.enabled)
                self._hp_spin.setValue(round(rule.threshold_percentage))
                self._hp_combo.setCurrentText(key_name)
                self._hp_debounce_spin.setValue(rule.debounce_seconds)
            elif rule.vital_type is VitalTriggerType.MP:
                self._mp_check.setChecked(rule.enabled)
                self._mp_spin.setValue(round(rule.threshold_percentage))
                self._mp_combo.setCurrentText(key_name)
                self._mp_debounce_spin.setValue(rule.debounce_seconds)
            elif rule.vital_type is VitalTriggerType.FP:
                self._fp_check.setChecked(rule.enabled)
                self._fp_spin.setValue(round(rule.threshold_percentage))
                self._fp_combo.setCurrentText(key_name)
                self._fp_debounce_spin.setValue(rule.debounce_seconds)

    def get_vitals_config(self) -> VitalsTriggerConfig:
        rules = []
        for vital_type, check, spin, combo, debounce in (
            (
                VitalTriggerType.HP,
                self._hp_check,
                self._hp_spin,
                self._hp_combo,
                self._hp_debounce_spin,
            ),
            (
                VitalTriggerType.MP,
                self._mp_check,
                self._mp_spin,
                self._mp_combo,
                self._mp_debounce_spin,
            ),
            (
                VitalTriggerType.FP,
                self._fp_check,
                self._fp_spin,
                self._fp_combo,
                self._fp_debounce_spin,
            ),
        ):
            try:
                vk = parse_virtual_key(combo.currentText().strip())
            except ValueError:
                # An unreadable hotkey is an unusable rule rather than a silently
                # re-assigned one, so the entry is dropped instead of guessed.
                continue
            rules.append(
                VitalTriggerRule(
                    vital_type=vital_type,
                    threshold_percentage=spin.value(),
                    virtual_key=vk,
                    debounce_seconds=debounce.value(),
                    enabled=check.isChecked(),
                )
            )
        return VitalsTriggerConfig(rules=tuple(rules))

    def _load_powerup_settings(self) -> None:
        config = load_powerup_config(self._powerup_config_path)
        self._powerup_panel.set_config(config)

    def get_powerup_config(self) -> PowerUpConfig:
        return self._powerup_panel.config

    def set_target_mob_options(self, options: tuple[str, ...] | Sequence[str]) -> None:
        self._target_panel.set_class_names(options)

    @Slot()
    def _on_emergency_changed(self) -> None:
        config = self.get_emergency_config()
        save_emergency_config(config, self._emergency_config_path)
        self.emergency_config_changed.emit(config)

    def _load_emergency_settings(self) -> None:
        config = load_emergency_config(self._emergency_config_path)
        self._recovery_timeout_spin.setValue(config.stuck_timeout_seconds)
        key_name = None
        if config.teleport_virtual_key is not None:
            for name in EMERGENCY_HOTKEY_CHOICES:
                try:
                    if parse_virtual_key(name) == config.teleport_virtual_key:
                        key_name = name
                        break
                except ValueError:
                    continue
        index = self._recovery_hotkey_combo.findData(key_name)
        if index >= 0:
            self._recovery_hotkey_combo.setCurrentIndex(index)

    def get_emergency_config(self) -> EmergencyRecoveryConfig:
        hotkey_data = self._recovery_hotkey_combo.currentData()
        virtual_key: int | None = None
        if hotkey_data:
            try:
                virtual_key = parse_virtual_key(str(hotkey_data))
            except ValueError:
                virtual_key = None
        return EmergencyRecoveryConfig(
            stuck_timeout_seconds=self._recovery_timeout_spin.value(),
            teleport_virtual_key=virtual_key,
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._attack_key_button
            and self._is_recording_attack_key
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
        self._map_window.close()
        self._placement_overlay.close()
        if self._world_data_dialog is not None:
            self._world_data_dialog.close()
        save_vitals_config(self.get_vitals_config(), self._vitals_config_path)
        save_emergency_config(self.get_emergency_config(), self._emergency_config_path)
        super().closeEvent(event)


def _key_label(key_code: int) -> str | None:
    if Qt.Key.Key_F1 <= key_code <= Qt.Key.Key_F12:
        return f"F{key_code - int(Qt.Key.Key_F1) + 1}"
    if Qt.Key.Key_0 <= key_code <= Qt.Key.Key_9:
        return chr(key_code)
    if Qt.Key.Key_A <= key_code <= Qt.Key.Key_Z:
        return chr(key_code)
    if key_code == Qt.Key.Key_Space:
        return "Space"
    return None


def _status_message(status: BotStatus) -> Message:
    return {
        BotStatus.ACTIVE: Message.UI_STATUS_ACTIVE,
        BotStatus.STANDBY: Message.UI_STATUS_STANDBY,
        BotStatus.COMPLETED: Message.UI_STATUS_COMPLETED,
        BotStatus.PAUSED: Message.UI_STATUS_PAUSED,
        BotStatus.EMERGENCY_STOPPED: Message.UI_STATUS_EMERGENCY_STOPPED,
        BotStatus.COMBAT: Message.UI_STATUS_COMBAT,
        BotStatus.RECONCILING: Message.UI_STATUS_RECONCILING,
        BotStatus.SEARCH_ROTATING: Message.UI_STATUS_SEARCH_ROTATING,
        BotStatus.SEARCH_ROAMING: Message.UI_STATUS_SEARCH_ROAMING,
        BotStatus.REPOSITIONING: Message.UI_STATUS_REPOSITIONING,
        BotStatus.APPROACHING: Message.UI_STATUS_APPROACHING,
        BotStatus.ALIGNING: Message.UI_STATUS_ALIGNING,
        BotStatus.ALIGNMENT_FAILED: Message.UI_STATUS_ALIGNMENT_FAILED,
        BotStatus.EMERGENCY_TELEPORT: Message.UI_STATUS_EMERGENCY_TELEPORT,
        BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE: Message.UI_STATUS_EMERGENCY_TELEPORT_UNAVAILABLE,
    }[status]


def _gps_error_message(code: PositionReadErrorCode) -> Message:
    return {
        PositionReadErrorCode.UNSUPPORTED_PLATFORM: Message.UI_GPS_ERROR_UNSUPPORTED_PLATFORM,
        PositionReadErrorCode.WINDOW_NOT_FOREGROUND: Message.UI_GPS_ERROR_WINDOW_NOT_FOREGROUND,
        PositionReadErrorCode.PROCESS_UNAVAILABLE: Message.UI_GPS_ERROR_PROCESS_UNAVAILABLE,
        PositionReadErrorCode.WRONG_PROCESS: Message.UI_GPS_ERROR_WRONG_PROCESS,
        PositionReadErrorCode.UNSUPPORTED_BUILD: Message.UI_GPS_ERROR_UNSUPPORTED_BUILD,
        PositionReadErrorCode.HANDLE_LOST: Message.UI_GPS_ERROR_HANDLE_LOST,
        PositionReadErrorCode.MALFORMED_READ: Message.UI_GPS_ERROR_MALFORMED_READ,
        PositionReadErrorCode.INVALID_PROFILE_CONFIGURATION: (
            Message.UI_GPS_ERROR_INVALID_PROFILE_CONFIGURATION
        ),
    }[code]


def _camera_error_message(code: CameraReadErrorCode) -> Message:
    return {
        CameraReadErrorCode.UNSUPPORTED_PLATFORM: Message.UI_CAMERA_ERROR_UNSUPPORTED_PLATFORM,
        CameraReadErrorCode.WINDOW_NOT_FOREGROUND: Message.UI_CAMERA_ERROR_WINDOW_NOT_FOREGROUND,
        CameraReadErrorCode.PROCESS_UNAVAILABLE: Message.UI_CAMERA_ERROR_PROCESS_UNAVAILABLE,
        CameraReadErrorCode.WRONG_PROCESS: Message.UI_CAMERA_ERROR_WRONG_PROCESS,
        CameraReadErrorCode.UNSUPPORTED_BUILD: Message.UI_CAMERA_ERROR_UNSUPPORTED_BUILD,
        CameraReadErrorCode.HANDLE_LOST: Message.UI_CAMERA_ERROR_HANDLE_LOST,
        CameraReadErrorCode.MALFORMED_READ: Message.UI_CAMERA_ERROR_MALFORMED_READ,
        CameraReadErrorCode.INVALID_PROFILE_CONFIGURATION: (
            Message.UI_CAMERA_ERROR_INVALID_PROFILE_CONFIGURATION
        ),
    }[code]


def _window_status_message(status: WindowStatus) -> Message:
    return {
        WindowStatus.OK: Message.UI_WINDOW_OK,
        WindowStatus.NOT_FOREGROUND: Message.UI_WINDOW_NOT_FOREGROUND,
        WindowStatus.MINIMIZED: Message.UI_WINDOW_MINIMIZED,
        WindowStatus.NOT_FOUND: Message.UI_WINDOW_NOT_FOUND,
        WindowStatus.CAPTURE_FAILED: Message.UI_WINDOW_CAPTURE_FAILED,
    }[status]


def _status_category(status: BotStatus) -> str:
    if status == BotStatus.ACTIVE:
        return "active"
    if status in {BotStatus.STANDBY, BotStatus.COMPLETED}:
        return "standby"
    if status == BotStatus.COMBAT:
        return "combat"
    if status == BotStatus.PAUSED:
        return "paused"
    if status == BotStatus.EMERGENCY_STOPPED:
        return "emergency_stopped"
    if status in {BotStatus.RECONCILING, BotStatus.ALIGNING}:
        return "reconciling"
    if status in {BotStatus.ALIGNMENT_FAILED, BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE}:
        return "emergency_stopped"
    if status == BotStatus.EMERGENCY_TELEPORT:
        return "reconciling"
    return "search"


def _pass_fail_text(translator: Translator, passed: bool) -> str:
    return translator.text(Message.UI_TARGET_DEBUG_PASS if passed else Message.UI_TARGET_DEBUG_FAIL)


def _target_state_message(state: TargetState) -> Message:
    return {
        TargetState.VALID: Message.UI_TARGET_VALID,
        TargetState.WRONG: Message.UI_TARGET_WRONG,
        TargetState.NONE: Message.UI_TARGET_NONE,
    }[state]


def _monster_stats_status_message(status: MonsterStatsStatus) -> Message:
    return {
        MonsterStatsStatus.IDLE: Message.UI_MONSTER_STATS_DEBUG_STATUS_IDLE,
        MonsterStatsStatus.OK: Message.UI_MONSTER_STATS_DEBUG_STATUS_OK,
        MonsterStatsStatus.ROI_UNAVAILABLE: Message.UI_MONSTER_STATS_DEBUG_STATUS_ROI_UNAVAILABLE,
        MonsterStatsStatus.ENGINE_UNAVAILABLE: (
            Message.UI_MONSTER_STATS_DEBUG_STATUS_ENGINE_UNAVAILABLE
        ),
        MonsterStatsStatus.OCR_FAILED: Message.UI_MONSTER_STATS_DEBUG_STATUS_OCR_FAILED,
        MonsterStatsStatus.NO_MATCH: Message.UI_MONSTER_STATS_DEBUG_STATUS_NO_MATCH,
    }[status]


def _monster_stats_source_message(source: MonsterStatsSource) -> Message:
    return {
        MonsterStatsSource.ANCHORED: Message.UI_MONSTER_STATS_DEBUG_SOURCE_ANCHORED,
        MonsterStatsSource.FIXED_REGION: Message.UI_MONSTER_STATS_DEBUG_SOURCE_FIXED_REGION,
    }[source]


def _engagement_break_message(reason: EngagementBreakReason | None) -> Message:
    if reason is None:
        return Message.UI_TARGET_DEBUG_BREAK_NONE
    return {
        EngagementBreakReason.ACQUISITION_TIMEOUT: Message.UI_TARGET_DEBUG_BREAK_ACQUISITION,
        EngagementBreakReason.TARGET_UNVERIFIED: Message.UI_TARGET_DEBUG_BREAK_UNVERIFIED,
        EngagementBreakReason.ENGAGEMENT_TIMEOUT: Message.UI_TARGET_DEBUG_BREAK_TIMEOUT,
        EngagementBreakReason.OBSTACLE_STALL: Message.UI_TARGET_DEBUG_BREAK_OBSTACLE,
    }[reason]


def _target_failure_reason_message(target: SelectedTarget) -> Message:
    metrics = target.metrics
    if target.state is TargetState.VALID:
        return Message.UI_TARGET_DEBUG_REASON_OK
    if not metrics.anchor_passed:
        return Message.UI_TARGET_DEBUG_REASON_ANCHOR
    if not metrics.hp_passed:
        return Message.UI_TARGET_DEBUG_REASON_HP
    return _target_name_reason_message(metrics.name_status)


def _target_name_reason_message(status: TargetNameStatus) -> Message:
    return {
        TargetNameStatus.NOT_EVALUATED: Message.UI_TARGET_DEBUG_REASON_ANCHOR,
        TargetNameStatus.MATCHED: Message.UI_TARGET_DEBUG_REASON_OK,
        TargetNameStatus.NO_MATCH: Message.UI_TARGET_DEBUG_REASON_NAME,
        TargetNameStatus.UNREADABLE: Message.UI_TARGET_DEBUG_REASON_NAME_UNREADABLE,
        TargetNameStatus.OCR_FAILED: Message.UI_TARGET_DEBUG_REASON_NAME_OCR_FAILED,
        TargetNameStatus.ENGINE_UNAVAILABLE: Message.UI_TARGET_DEBUG_REASON_NAME_ENGINE,
    }[status]


def _goal_text(translator: Translator, state: WorldState | None, goal: FarmingGoal | None) -> str:
    if goal is None:
        return translator.text(Message.UI_NO_GOAL)
    quantities = (
        {entry.item: entry.quantity for entry in state.inventory} if state is not None else {}
    )
    return translator.text(
        Message.UI_GOAL_PROGRESS,
        current=quantities.get(goal.item_name, 0),
        required=goal.required_quantity,
        item_name=goal.item_name,
    )


def _kill_progress_text(translator: Translator, progress: tuple[MobKillProgress, ...]) -> str:
    if not progress:
        return translator.text(Message.UI_KILL_PROGRESS_NONE)
    entries = [
        translator.text(
            (
                Message.UI_KILL_PROGRESS_UNLIMITED_ENTRY
                if item.is_unlimited
                else Message.UI_KILL_PROGRESS_ENTRY
            ),
            name=item.class_name,
            kills=item.kills,
            required=item.required_kills,
        )
        for item in progress
    ]
    return translator.text(Message.UI_KILL_PROGRESS_SUMMARY, progress=", ".join(entries))
