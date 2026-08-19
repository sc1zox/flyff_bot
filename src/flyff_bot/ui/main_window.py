"""Localized native dashboard for observed automation state."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.constants import (
    DEFAULT_CLIENT_WORLD_ROOT,
    DEFAULT_WORLD_MAP_DIRECTORY,
    DEFAULT_WORLD_MONSTER_IDS_PATH,
)
from flyff_bot.features.automation.camera_alignment import DEFAULT_AUTO_ALIGN_CAMERA
from flyff_bot.features.automation.controllers import CombatConfig, EngagementBreakReason
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
from flyff_bot.features.automation.kill_goals import KillGoalConfig
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
from flyff_bot.features.navigation.anchoring import ProfileAnchorState
from flyff_bot.features.navigation.persistence import (
    DEFAULT_NAVIGATION_DIR,
    list_navigation_profiles,
    sanitize_profile_name,
)
from flyff_bot.features.navigation.tracking import TrackingQuality
from flyff_bot.features.vision.monster_stats import MonsterStatsConfig
from flyff_bot.features.vision.target_verification import (
    DEFAULT_ANCHOR_MATCH_THRESHOLD,
    MAXIMUM_MATCH_THRESHOLD,
    MINIMUM_MATCH_THRESHOLD,
)
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import BotStatus, DashboardUpdate, FarmingGoal, WindowStatus
from flyff_bot.ui.debug_overlay import DebugOverlayWidget, render_debug_overlay
from flyff_bot.ui.navigation_window import NavigationMapWindow
from flyff_bot.ui.path_inspector import PathInspectorWidget
from flyff_bot.ui.placement_overlay import ClientGeometryProvider, PlacementOverlayWindow
from flyff_bot.ui.powerup_panel import PowerUpPanel
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

# The teleport item or skill can sit on any quickslot, so the emergency hotkey offers the
# full supported physical range rather than the combat subset (US-040).
EMERGENCY_HOTKEY_CHOICES = [
    *(f"F{number}" for number in range(1, 13)),
    *(str(digit) for digit in range(10)),
    *(chr(code) for code in range(ord("A"), ord("Z") + 1)),
]
STUCK_TIMEOUT_STEP_SECONDS = 5.0
STUCK_TIMEOUT_DECIMALS = 1
SPAWN_POINT_DECIMALS = 1


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
    set_spawn_point_requested = Signal()
    combat_grace_changed = Signal(float)
    kill_verification_changed = Signal(bool)
    anchor_threshold_changed = Signal(float)
    target_selection_changed = Signal(object)
    save_profile_requested = Signal(Path)
    load_profile_requested = Signal(Path)
    reset_navigation_requested = Signal()
    vector_navigation_requested = Signal(object)
    vector_navigation_cleared = Signal()

    def __init__(
        self,
        translator: Translator,
        *,
        navigation_dir: Path | None = None,
        vitals_config_path: Path | None = None,
        powerup_config_path: Path | None = None,
        emergency_config_path: Path | None = None,
        client_world_root: Path | None = None,
        world_map_dir: Path | None = None,
        monster_names_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._translator = translator
        self._navigation_dir = navigation_dir or DEFAULT_NAVIGATION_DIR
        self._client_world_root = client_world_root or Path(DEFAULT_CLIENT_WORLD_ROOT)
        self._world_map_dir = world_map_dir or Path(DEFAULT_WORLD_MAP_DIRECTORY)
        self._monster_names_path = monster_names_path or Path(DEFAULT_WORLD_MONSTER_IDS_PATH)
        self._world_data_dialog: WorldDataDialog | None = None
        self._vitals_config_path = vitals_config_path or DEFAULT_VITALS_CONFIG_PATH
        self._powerup_config_path = powerup_config_path or DEFAULT_POWERUP_CONFIG_PATH
        self._emergency_config_path = emergency_config_path or DEFAULT_EMERGENCY_CONFIG_PATH
        self._latest_update: DashboardUpdate | None = None

        # Card Panels
        self._status_card = QGroupBox()
        self._status_card.setObjectName("CardPanel")
        self._controls_card = QGroupBox()
        self._controls_card.setObjectName("CardPanel")
        self._profile_card = QGroupBox()
        self._profile_card.setObjectName("CardPanel")
        self._profile_card.setVisible(False)
        self._profile_bar = self._profile_card
        self._telemetry_card = QGroupBox()
        self._telemetry_card.setObjectName("CardPanel")

        # Status & Metrics
        self._status_label = QLabel()
        self._status_label.setObjectName("StatusBadge")
        self._window_label = QLabel()
        self._window_label.setObjectName("StatChip")
        self._window_status = WindowStatus.NOT_FOUND
        self._tracking_label = QLabel()
        self._tracking_label.setObjectName("StatChip")
        self._tracking_quality = TrackingQuality.DEGRADED
        self._mob_label = QLabel()
        self._mob_label.setObjectName("StatChip")
        self._target_label = QLabel()
        self._target_label.setObjectName("StatChip")
        self._goal_label = QLabel()
        self._goal_label.setObjectName("StatChip")
        self._vitals_label = QLabel()
        self._vitals_label.setObjectName("StatChip")

        # Debug Overlay Viewport
        self._overlay_label = DebugOverlayWidget()
        self._overlay_label.setVisible(False)

        # Transparent in-game placement guide overlay
        self._placement_overlay = PlacementOverlayWindow(self._translator)

        # Navigation Map & Inspector
        self._path_inspector = PathInspectorWidget(self._translator)
        self._path_inspector.setVisible(False)
        self._map_container = QWidget()
        self._map_container_layout = QVBoxLayout(self._map_container)
        self._map_container_layout.setContentsMargins(0, 0, 0, 0)
        self._map_container_layout.addWidget(self._path_inspector)
        self._map_container.setVisible(False)
        self._map_window = NavigationMapWindow(self._translator)
        self._popout_map_button = QPushButton()
        self._is_map_popped_out = False
        self._teardowns: list[Callable[[], None]] = []

        # Profile Controls
        self._profile_selector = QComboBox()
        self._profile_name_input = QLineEdit()
        self._save_profile_button = QPushButton()
        self._load_profile_button = QPushButton()
        self._reset_map_button = QPushButton()
        self._reset_map_button.setObjectName("ActionDanger")
        self._world_data_button = QPushButton()
        self._spawn_point_button = QPushButton()
        self._spawn_point_label = QLabel()
        self._spawn_point_label.setObjectName("StatChip")
        self._profile_anchor_label = QLabel()
        self._profile_anchor_label.setObjectName("StatChip")
        self._profile_anchor_state = ProfileAnchorState.SESSION

        # Primary Action Controls
        self._start_button = QPushButton()
        self._start_button.setObjectName("ActionStart")
        self._pause_button = QPushButton()
        self._pause_button.setObjectName("ActionPause")
        self._emergency_stop_button = QPushButton()
        self._emergency_stop_button.setObjectName("ActionEmergencyStop")
        self._attack_key_label = QLabel()
        self._attack_key_button = QPushButton()
        self._align_camera_button = QPushButton()
        self._auto_align_toggle = QCheckBox()
        self._auto_align_toggle.setChecked(DEFAULT_AUTO_ALIGN_CAMERA)
        self._attack_virtual_key = parse_virtual_key("F3")
        self._attack_key_name = "F3"
        self._is_recording_attack_key = False
        self._language_selector = QComboBox()

        # Telemetry & Diagnostics Toggles
        self._debug_toggle = QCheckBox()
        self._placements_toggle = QCheckBox()
        self._path_toggle = QCheckBox()
        self._vitals_toggle = QCheckBox()
        self._powerups_toggle = QCheckBox()
        self._combat_toggle = QCheckBox()
        self._target_debug_toggle = QCheckBox()
        self._monster_stats_toggle = QCheckBox()
        self._recovery_toggle = QCheckBox()

        # Unrecoverable stuck recovery panel (US-040)
        self._recovery_panel = QGroupBox()
        self._recovery_panel.setObjectName("CardPanel")
        self._recovery_panel.setVisible(False)
        self._recovery_timeout_label = QLabel()
        self._recovery_timeout_spin = QDoubleSpinBox()
        self._recovery_hotkey_label = QLabel()
        self._recovery_hotkey_combo = QComboBox()

        # Combat settings panel
        self._combat_panel = QGroupBox()
        self._combat_panel.setObjectName("CardPanel")
        self._combat_panel.setVisible(False)
        self._target_grace_label = QLabel()
        self._target_grace_spin = QDoubleSpinBox()
        self._target_grace_spin.setRange(0.1, 5.0)
        self._target_grace_spin.setSingleStep(0.1)
        self._target_grace_spin.setDecimals(1)
        self._target_grace_spin.setValue(0.8)
        self._target_grace_spin.setSuffix(" s")
        self._kill_verification_label = QLabel()
        self._kill_verification_toggle = QCheckBox()
        self._kill_verification_toggle.setChecked(CombatConfig().kill_verification_enabled)
        self._anchor_threshold_label = QLabel()
        self._anchor_threshold_spin = _match_threshold_spin(DEFAULT_ANCHOR_MATCH_THRESHOLD)

        # Target verification debug panel
        self._target_debug_panel = QGroupBox()
        self._target_debug_panel.setObjectName("CardPanel")
        self._target_debug_panel.setVisible(False)
        self._target_anchor_label = QLabel()
        self._target_anchor_value = QLabel()
        self._target_hp_label = QLabel()
        self._target_hp_value = QLabel()
        self._target_name_label = QLabel()
        self._target_name_value = QLabel()
        # The row carries raw OCR output, which is untrusted text rather than markup.
        self._target_name_value.setTextFormat(Qt.TextFormat.PlainText)
        self._target_state_label = QLabel()
        self._target_state_value = QLabel()
        self._target_reason_label = QLabel()
        self._target_reason_value = QLabel()
        self._target_break_label = QLabel()
        self._target_break_value = QLabel()

        # Monster stats OCR debug panel
        self._monster_stats_panel = QGroupBox()
        self._monster_stats_panel.setObjectName("CardPanel")
        self._monster_stats_panel.setVisible(False)
        self._monster_anchor_label = QLabel()
        self._monster_anchor_value = QLabel()
        self._monster_roi_label = QLabel()
        self._monster_roi_value = QLabel()
        self._monster_source_label = QLabel()
        self._monster_source_value = QLabel()
        self._monster_kills_label = QLabel()
        self._monster_kills_value = QLabel()
        self._monster_text_label = QLabel()
        self._monster_text_value = QLabel()
        # OCR output is untrusted text; rendering it as rich text would swallow markup.
        self._monster_text_value.setTextFormat(Qt.TextFormat.PlainText)
        self._monster_status_label = QLabel()
        self._monster_status_value = QLabel()

        # Power-up / timed hotkey configuration panel
        self._powerup_panel = PowerUpPanel(self._translator)
        self._powerup_panel.setVisible(False)

        # Target monster selection and per-monster kill quotas
        self._targets_toggle = QCheckBox()
        self._target_panel = TargetSelectionPanel(self._translator)
        self._target_panel.setVisible(False)

        # Vitals configuration panel
        self._vitals_panel = QGroupBox()
        self._vitals_panel.setObjectName("CardPanel")
        self._vitals_panel.setVisible(False)
        self._vitals_col_type = QLabel()
        self._vitals_col_active = QLabel()
        self._vitals_col_threshold = QLabel()
        self._vitals_col_hotkey = QLabel()
        self._vitals_col_debounce = QLabel()

        self._hp_label = QLabel()
        self._hp_enabled = QCheckBox()
        self._hp_threshold_spin = QSpinBox()
        self._hp_key_combo = QComboBox()
        self._hp_debounce_spin = QSpinBox()

        self._mp_label = QLabel()
        self._mp_enabled = QCheckBox()
        self._mp_threshold_spin = QSpinBox()
        self._mp_key_combo = QComboBox()
        self._mp_debounce_spin = QSpinBox()

        self._fp_label = QLabel()
        self._fp_enabled = QCheckBox()
        self._fp_threshold_spin = QSpinBox()
        self._fp_key_combo = QComboBox()
        self._fp_debounce_spin = QSpinBox()

        apply_theme(self)
        self._init_vitals_widgets()
        self._init_recovery_widgets()
        self._init_target_debug_widgets()
        self._init_monster_stats_widgets()
        self._build_layout()
        self._connect_controls()
        self._load_vitals_config_to_ui()
        self._powerup_panel.set_config(load_powerup_config(self._powerup_config_path))
        self._load_emergency_config_to_ui()
        self._retranslate()
        self.set_status(mob_count=0)
        self._adapt_window_geometry()

    @property
    def start_button(self) -> QPushButton:
        """Expose the Start control for application-service wiring."""

        return self._start_button

    @property
    def pause_button(self) -> QPushButton:
        """Expose the Pause control for application-service wiring."""

        return self._pause_button

    @property
    def emergency_stop_button(self) -> QPushButton:
        """Expose the emergency-stop control for application-service wiring."""

        return self._emergency_stop_button

    @property
    def status_label(self) -> QLabel:
        """Expose current operator status for lightweight integrations."""

        return self._status_label

    @property
    def goal_label(self) -> QLabel:
        """Expose current goal progress for lightweight integrations."""

        return self._goal_label

    @property
    def window_label(self) -> QLabel:
        """Expose the game-window condition chip for lightweight integrations."""

        return self._window_label

    @property
    def tracking_label(self) -> QLabel:
        """Expose the navigation tracking-quality chip for lightweight integrations."""

        return self._tracking_label

    @property
    def mob_label(self) -> QLabel:
        """Expose the visible-mob count chip for lightweight integrations."""

        return self._mob_label

    @property
    def target_label(self) -> QLabel:
        """Expose the target-state chip for lightweight integrations."""

        return self._target_label

    @property
    def overlay_label(self) -> DebugOverlayWidget:
        """Expose the optional viewport for deterministic UI tests."""

        return self._overlay_label

    @property
    def path_inspector(self) -> PathInspectorWidget:
        """Expose the path inspector widget for testing and inspection."""

        return self._path_inspector

    @property
    def path_toggle(self) -> QCheckBox:
        """Expose the path toggle checkbox for testing."""

        return self._path_toggle

    @property
    def placements_toggle(self) -> QCheckBox:
        """Expose the Placements visual guide toggle checkbox for testing."""

        return self._placements_toggle

    @property
    def placement_overlay(self) -> PlacementOverlayWindow:
        """Expose the transparent in-game guide overlay for testing."""

        return self._placement_overlay

    def attach_placement_target(self, provider: ClientGeometryProvider, window_handle: int) -> None:
        """Bind the placement guide overlay to the discovered game window."""

        self._placement_overlay.attach_target(provider, window_handle)

    @property
    def profile_bar(self) -> QWidget:
        """Expose the profile bar widget for testing."""

        return self._profile_bar

    @property
    def profile_selector(self) -> QComboBox:
        """Expose the profile selector dropdown for testing."""

        return self._profile_selector

    @property
    def profile_name_input(self) -> QLineEdit:
        """Expose the profile name input field for testing."""

        return self._profile_name_input

    @property
    def save_profile_button(self) -> QPushButton:
        """Expose the profile save button for testing."""

        return self._save_profile_button

    @property
    def load_profile_button(self) -> QPushButton:
        """Expose the profile load button for testing."""

        return self._load_profile_button

    @property
    def reset_map_button(self) -> QPushButton:
        """Expose the reset map button for testing."""

        return self._reset_map_button

    @property
    def spawn_point_button(self) -> QPushButton:
        """Expose the Set Spawn Point control for application-service wiring."""

        return self._spawn_point_button

    @property
    def spawn_point_label(self) -> QLabel:
        """Expose the chip naming this map's mapped spawn anchor."""

        return self._spawn_point_label

    @property
    def recovery_toggle(self) -> QCheckBox:
        """Expose the stuck-recovery panel toggle."""

        return self._recovery_toggle

    @property
    def recovery_panel(self) -> QGroupBox:
        """Expose the unrecoverable stuck recovery settings panel."""

        return self._recovery_panel

    @property
    def recovery_timeout_spin(self) -> QDoubleSpinBox:
        """Expose the configurable unrecoverable stuck timeout control."""

        return self._recovery_timeout_spin

    @property
    def recovery_hotkey_combo(self) -> QComboBox:
        """Expose the configurable emergency teleport hotkey control."""

        return self._recovery_hotkey_combo

    @property
    def attack_key_button(self) -> QPushButton:
        """Expose the key-capture control for the desktop application and tests."""

        return self._attack_key_button

    @property
    def align_camera_button(self) -> QPushButton:
        """Expose the on-demand camera alignment control for wiring and tests."""

        return self._align_camera_button

    @property
    def auto_align_toggle(self) -> QCheckBox:
        """Expose the pre-flight camera alignment toggle for wiring and tests."""

        return self._auto_align_toggle

    @property
    def attack_virtual_key(self) -> int:
        """Return the currently selected Windows virtual-key code."""

        return self._attack_virtual_key

    @property
    def vitals_label(self) -> QLabel:
        """Expose the vitals readout label for testing and verification."""

        return self._vitals_label

    @property
    def vitals_toggle(self) -> QCheckBox:
        """Expose the vitals panel toggle control."""

        return self._vitals_toggle

    @property
    def vitals_panel(self) -> QGroupBox:
        """Expose the vitals configuration panel."""

        return self._vitals_panel

    @property
    def hp_enabled_checkbox(self) -> QCheckBox:
        return self._hp_enabled

    @property
    def hp_threshold_spin(self) -> QSpinBox:
        return self._hp_threshold_spin

    @property
    def hp_key_combo(self) -> QComboBox:
        return self._hp_key_combo

    @property
    def hp_debounce_spin(self) -> QSpinBox:
        return self._hp_debounce_spin

    @property
    def mp_enabled_checkbox(self) -> QCheckBox:
        return self._mp_enabled

    @property
    def mp_threshold_spin(self) -> QSpinBox:
        return self._mp_threshold_spin

    @property
    def mp_key_combo(self) -> QComboBox:
        return self._mp_key_combo

    @property
    def mp_debounce_spin(self) -> QSpinBox:
        return self._mp_debounce_spin

    @property
    def fp_enabled_checkbox(self) -> QCheckBox:
        return self._fp_enabled

    @property
    def fp_threshold_spin(self) -> QSpinBox:
        return self._fp_threshold_spin

    @property
    def fp_key_combo(self) -> QComboBox:
        return self._fp_key_combo

    @property
    def fp_debounce_spin(self) -> QSpinBox:
        return self._fp_debounce_spin

    @property
    def powerups_toggle(self) -> QCheckBox:
        """Expose the power-up panel toggle control."""

        return self._powerups_toggle

    @property
    def powerup_panel(self) -> PowerUpPanel:
        """Expose the dynamic power-up configuration panel."""

        return self._powerup_panel

    @property
    def combat_toggle(self) -> QCheckBox:
        """Expose the combat settings panel toggle control."""

        return self._combat_toggle

    @property
    def combat_panel(self) -> QGroupBox:
        """Expose the combat configuration panel."""

        return self._combat_panel

    @property
    def target_panel(self) -> TargetSelectionPanel:
        """Expose the monster selection and kill-quota panel."""

        return self._target_panel

    @property
    def targets_toggle(self) -> QCheckBox:
        """Expose the toggle that reveals the monster selection panel."""

        return self._targets_toggle

    @property
    def target_selection(self) -> KillGoalConfig:
        """Return the monster selection and quotas the operator configured."""

        return self._target_panel.get_config()

    @property
    def target_grace_spin(self) -> QDoubleSpinBox:
        """Expose the target click grace period spin box."""

        return self._target_grace_spin

    @property
    def kill_verification_toggle(self) -> QCheckBox:
        """Expose the kill verification toggle checkbox."""

        return self._kill_verification_toggle

    @property
    def anchor_threshold_spin(self) -> QDoubleSpinBox:
        """Expose the header-anchor match threshold spin box."""

        return self._anchor_threshold_spin

    @property
    def target_debug_toggle(self) -> QCheckBox:
        """Expose the target verification debug panel toggle control."""

        return self._target_debug_toggle

    @property
    def target_debug_panel(self) -> QGroupBox:
        """Expose the target verification debug panel."""

        return self._target_debug_panel

    @property
    def target_anchor_value(self) -> QLabel:
        """Expose the header-anchor debug readout for testing."""

        return self._target_anchor_value

    @property
    def target_hp_value(self) -> QLabel:
        """Expose the HP-bar debug readout for testing."""

        return self._target_hp_value

    @property
    def target_name_value(self) -> QLabel:
        """Expose the name-match debug readout for testing."""

        return self._target_name_value

    @property
    def target_state_value(self) -> QLabel:
        """Expose the overall target-state debug readout for testing."""

        return self._target_state_value

    @property
    def target_reason_value(self) -> QLabel:
        """Expose the target-failure-reason debug readout for testing."""

        return self._target_reason_value

    @property
    def monster_stats_toggle(self) -> QCheckBox:
        """Expose the monster stats debug panel toggle control."""

        return self._monster_stats_toggle

    @property
    def monster_stats_panel(self) -> QGroupBox:
        """Expose the monster stats OCR debug panel."""

        return self._monster_stats_panel

    @property
    def monster_anchor_value(self) -> QLabel:
        """Expose the monster stats anchor debug readout for testing."""

        return self._monster_anchor_value

    @property
    def monster_source_value(self) -> QLabel:
        """Expose the monster stats region-source debug readout for testing."""

        return self._monster_source_value

    @property
    def monster_roi_value(self) -> QLabel:
        """Expose the monster stats region debug readout for testing."""

        return self._monster_roi_value

    @property
    def monster_kills_value(self) -> QLabel:
        """Expose the parsed monster kill count debug readout for testing."""

        return self._monster_kills_value

    @property
    def monster_text_value(self) -> QLabel:
        """Expose the raw monster stats OCR text readout for testing."""

        return self._monster_text_value

    @property
    def monster_status_value(self) -> QLabel:
        """Expose the monster stats feed status readout for testing."""

        return self._monster_status_value

    @property
    def status_card(self) -> QGroupBox:
        """Expose the status and metrics card panel."""

        return self._status_card

    @property
    def controls_card(self) -> QGroupBox:
        """Expose the action controls card panel."""

        return self._controls_card

    @property
    def profile_card(self) -> QGroupBox:
        """Expose the navigation and profiles card panel."""

        return self._profile_card

    @property
    def telemetry_card(self) -> QGroupBox:
        """Expose the diagnostics and views toolbar card panel."""

        return self._telemetry_card

    @property
    def popout_map_button(self) -> QPushButton:
        """Expose the pop-out map button."""

        return self._popout_map_button

    @property
    def map_window(self) -> NavigationMapWindow:
        """Expose the secondary map window."""

        return self._map_window

    @property
    def is_map_popped_out(self) -> bool:
        """Return whether the navigation map is currently popped out."""

        return self._is_map_popped_out

    def _init_vitals_widgets(self) -> None:
        for spin in (self._hp_threshold_spin, self._mp_threshold_spin, self._fp_threshold_spin):
            spin.setRange(1, 100)
            spin.setSuffix("%")
        self._hp_threshold_spin.setValue(70)
        self._mp_threshold_spin.setValue(30)
        self._fp_threshold_spin.setValue(20)

        for spin in (self._hp_debounce_spin, self._mp_debounce_spin, self._fp_debounce_spin):
            spin.setRange(100, 10000)
            spin.setSingleStep(100)
            spin.setSuffix(" ms")
            spin.setValue(800)

        for combo in (self._hp_key_combo, self._mp_key_combo, self._fp_key_combo):
            combo.addItems(HOTKEY_CHOICES)

        self._hp_key_combo.setCurrentText("F1")
        self._mp_key_combo.setCurrentText("F2")
        self._fp_key_combo.setCurrentText("F3")

        self._hp_enabled.setChecked(True)
        self._mp_enabled.setChecked(True)
        self._fp_enabled.setChecked(True)

        vitals_layout = QGridLayout()
        vitals_layout.addWidget(self._vitals_col_type, 0, 0)
        vitals_layout.addWidget(self._vitals_col_active, 0, 1)
        vitals_layout.addWidget(self._vitals_col_threshold, 0, 2)
        vitals_layout.addWidget(self._vitals_col_hotkey, 0, 3)
        vitals_layout.addWidget(self._vitals_col_debounce, 0, 4)

        vitals_layout.addWidget(self._hp_label, 1, 0)
        vitals_layout.addWidget(self._hp_enabled, 1, 1)
        vitals_layout.addWidget(self._hp_threshold_spin, 1, 2)
        vitals_layout.addWidget(self._hp_key_combo, 1, 3)
        vitals_layout.addWidget(self._hp_debounce_spin, 1, 4)

        vitals_layout.addWidget(self._mp_label, 2, 0)
        vitals_layout.addWidget(self._mp_enabled, 2, 1)
        vitals_layout.addWidget(self._mp_threshold_spin, 2, 2)
        vitals_layout.addWidget(self._mp_key_combo, 2, 3)
        vitals_layout.addWidget(self._mp_debounce_spin, 2, 4)

        vitals_layout.addWidget(self._fp_label, 3, 0)
        vitals_layout.addWidget(self._fp_enabled, 3, 1)
        vitals_layout.addWidget(self._fp_threshold_spin, 3, 2)
        vitals_layout.addWidget(self._fp_key_combo, 3, 3)
        vitals_layout.addWidget(self._fp_debounce_spin, 3, 4)

        self._vitals_panel.setLayout(vitals_layout)

        combat_layout = QVBoxLayout()
        grace_row = QHBoxLayout()
        grace_row.addWidget(self._target_grace_label)
        grace_row.addWidget(self._target_grace_spin)
        combat_layout.addLayout(grace_row)
        kill_row = QHBoxLayout()
        kill_row.addWidget(self._kill_verification_label)
        kill_row.addWidget(self._kill_verification_toggle)
        combat_layout.addLayout(kill_row)
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(self._anchor_threshold_label)
        threshold_row.addWidget(self._anchor_threshold_spin)
        combat_layout.addLayout(threshold_row)
        self._combat_panel.setLayout(combat_layout)

    def _init_recovery_widgets(self) -> None:
        """Build the unrecoverable stuck timeout and emergency teleport controls (US-040)."""

        self._recovery_timeout_spin.setRange(
            MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
            MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
        )
        self._recovery_timeout_spin.setSingleStep(STUCK_TIMEOUT_STEP_SECONDS)
        self._recovery_timeout_spin.setDecimals(STUCK_TIMEOUT_DECIMALS)
        self._recovery_timeout_spin.setSuffix(" s")
        # The unassigned entry carries ``None`` so the refusal case is a stored value rather
        # than a magic label the reader has to recognize.
        self._recovery_hotkey_combo.addItem("", None)
        for choice in EMERGENCY_HOTKEY_CHOICES:
            self._recovery_hotkey_combo.addItem(choice, choice)

        recovery_layout = QVBoxLayout()
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(self._recovery_timeout_label)
        timeout_row.addWidget(self._recovery_timeout_spin)
        recovery_layout.addLayout(timeout_row)
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self._recovery_hotkey_label)
        hotkey_row.addWidget(self._recovery_hotkey_combo)
        recovery_layout.addLayout(hotkey_row)
        self._recovery_panel.setLayout(recovery_layout)

    def _load_emergency_config_to_ui(self) -> None:
        config = load_emergency_config(self._emergency_config_path)
        self._recovery_timeout_spin.blockSignals(True)
        self._recovery_hotkey_combo.blockSignals(True)
        self._recovery_timeout_spin.setValue(config.stuck_timeout_seconds)
        stored_key = (
            None
            if config.teleport_virtual_key is None
            else _virtual_key_name(config.teleport_virtual_key)
        )
        index = self._recovery_hotkey_combo.findData(stored_key)
        self._recovery_hotkey_combo.setCurrentIndex(max(0, index))
        self._recovery_timeout_spin.blockSignals(False)
        self._recovery_hotkey_combo.blockSignals(False)

    def get_emergency_config(self) -> EmergencyRecoveryConfig:
        """Return the unrecoverable stuck recovery settings defined by UI inputs."""

        selected = self._recovery_hotkey_combo.currentData()
        return EmergencyRecoveryConfig(
            teleport_virtual_key=(
                parse_virtual_key(selected) if isinstance(selected, str) else None
            ),
            stuck_timeout_seconds=self._recovery_timeout_spin.value(),
        )

    def _on_emergency_inputs_changed(self) -> None:
        config = self.get_emergency_config()
        save_emergency_config(config, self._emergency_config_path)
        self.emergency_config_changed.emit(config)

    def _init_target_debug_widgets(self) -> None:
        target_debug_layout = QVBoxLayout()
        for label, value in (
            (self._target_anchor_label, self._target_anchor_value),
            (self._target_hp_label, self._target_hp_value),
            (self._target_name_label, self._target_name_value),
            (self._target_state_label, self._target_state_value),
            (self._target_reason_label, self._target_reason_value),
            (self._target_break_label, self._target_break_value),
        ):
            row = QHBoxLayout()
            row.addWidget(label)
            row.addWidget(value)
            target_debug_layout.addLayout(row)
        self._target_debug_panel.setLayout(target_debug_layout)

    def _init_monster_stats_widgets(self) -> None:
        monster_stats_layout = QVBoxLayout()
        for label, value in (
            (self._monster_anchor_label, self._monster_anchor_value),
            (self._monster_roi_label, self._monster_roi_value),
            (self._monster_source_label, self._monster_source_value),
            (self._monster_kills_label, self._monster_kills_value),
            (self._monster_text_label, self._monster_text_value),
            (self._monster_status_label, self._monster_status_value),
        ):
            row = QHBoxLayout()
            row.addWidget(label)
            row.addWidget(value)
            monster_stats_layout.addLayout(row)
        self._monster_stats_panel.setLayout(monster_stats_layout)

    def _load_vitals_config_to_ui(self) -> None:
        config = load_vitals_config(self._vitals_config_path)
        self._block_vitals_signals(True)
        hp = config.rule_for(VitalTriggerType.HP)
        if hp is not None:
            self._hp_enabled.setChecked(hp.enabled)
            self._hp_threshold_spin.setValue(round(hp.threshold_percentage))
            self._hp_key_combo.setCurrentText(_virtual_key_name(hp.virtual_key))
            self._hp_debounce_spin.setValue(round(hp.debounce_seconds * 1000))

        mp = config.rule_for(VitalTriggerType.MP)
        if mp is not None:
            self._mp_enabled.setChecked(mp.enabled)
            self._mp_threshold_spin.setValue(round(mp.threshold_percentage))
            self._mp_key_combo.setCurrentText(_virtual_key_name(mp.virtual_key))
            self._mp_debounce_spin.setValue(round(mp.debounce_seconds * 1000))

        fp = config.rule_for(VitalTriggerType.FP)
        if fp is not None:
            self._fp_enabled.setChecked(fp.enabled)
            self._fp_threshold_spin.setValue(round(fp.threshold_percentage))
            self._fp_key_combo.setCurrentText(_virtual_key_name(fp.virtual_key))
            self._fp_debounce_spin.setValue(round(fp.debounce_seconds * 1000))
        self._block_vitals_signals(False)

    def _block_vitals_signals(self, blocked: bool) -> None:
        for widget in (
            self._hp_enabled,
            self._hp_threshold_spin,
            self._hp_key_combo,
            self._hp_debounce_spin,
            self._mp_enabled,
            self._mp_threshold_spin,
            self._mp_key_combo,
            self._mp_debounce_spin,
            self._fp_enabled,
            self._fp_threshold_spin,
            self._fp_key_combo,
            self._fp_debounce_spin,
        ):
            widget.blockSignals(blocked)

    def get_vitals_config(self) -> VitalsTriggerConfig:
        """Return the current vitals trigger configuration as defined by UI inputs."""

        hp_rule = VitalTriggerRule(
            vital_type=VitalTriggerType.HP,
            threshold_percentage=float(self._hp_threshold_spin.value()),
            virtual_key=parse_virtual_key(self._hp_key_combo.currentText()),
            debounce_seconds=self._hp_debounce_spin.value() / 1000.0,
            enabled=self._hp_enabled.isChecked(),
        )
        mp_rule = VitalTriggerRule(
            vital_type=VitalTriggerType.MP,
            threshold_percentage=float(self._mp_threshold_spin.value()),
            virtual_key=parse_virtual_key(self._mp_key_combo.currentText()),
            debounce_seconds=self._mp_debounce_spin.value() / 1000.0,
            enabled=self._mp_enabled.isChecked(),
        )
        fp_rule = VitalTriggerRule(
            vital_type=VitalTriggerType.FP,
            threshold_percentage=float(self._fp_threshold_spin.value()),
            virtual_key=parse_virtual_key(self._fp_key_combo.currentText()),
            debounce_seconds=self._fp_debounce_spin.value() / 1000.0,
            enabled=self._fp_enabled.isChecked(),
        )
        return VitalsTriggerConfig(rules=(hp_rule, mp_rule, fp_rule))

    def _on_vitals_inputs_changed(self) -> None:
        config = self.get_vitals_config()
        save_vitals_config(config, self._vitals_config_path)
        self.vitals_config_changed.emit(config)

    def get_powerup_config(self) -> PowerUpConfig:
        """Return the timed power-up configuration currently defined by UI inputs."""

        return self._powerup_panel.get_config()

    @Slot(object)
    def _on_powerup_config_changed(self, config: object) -> None:
        if not isinstance(config, PowerUpConfig):
            raise TypeError("Power-up panel must publish PowerUpConfig values.")
        save_powerup_config(config, self._powerup_config_path)
        self.powerup_config_changed.emit(config)

    def set_status(self, mob_count: int) -> None:
        """Retain the bootstrap summary API for callers without a full update."""

        self._render_status_badge(BotStatus.PAUSED)
        self._mob_label.setText(self._translator.text(Message.UI_WORLD_STATUS, mob_count=mob_count))
        self._target_label.setText(self._translator.text(Message.UI_TARGET_NONE))
        self._goal_label.setText(self._translator.text(Message.UI_NO_GOAL))
        self._vitals_label.setText(
            self._translator.text(
                Message.UI_VITALS_STATUS,
                hp="100.0",
                mp="100.0",
                fp="100.0",
            )
        )
        self._render_window_status()
        self._render_tracking_quality()

    def set_window_status(self, status: WindowStatus) -> None:
        """Display a game-window condition observed outside the perception pipeline."""

        self._window_status = status
        self._render_window_status()

    def update_state(self, state: WorldState) -> None:
        """Update the display from a state feed without a configured goal."""

        self.update_dashboard(DashboardUpdate(state, BotStatus.PAUSED))

    @Slot(DashboardUpdate)
    def update_dashboard(self, update: DashboardUpdate) -> None:
        """Receive a worker-safe immutable update on the Qt main thread."""

        self._latest_update = update
        self._render_update()

    @Slot()
    def _request_start(self) -> None:
        self._set_local_status(BotStatus.ACTIVE)
        self.start_requested.emit()

    @Slot()
    def _request_pause(self) -> None:
        self._set_local_status(BotStatus.PAUSED)
        self.pause_requested.emit()

    @Slot()
    def _request_emergency_stop(self) -> None:
        self._set_local_status(BotStatus.EMERGENCY_STOPPED)
        self.emergency_stop_requested.emit()

    @Slot(int)
    def _switch_language(self, index: int) -> None:
        language_value = self._language_selector.itemData(index)
        if not isinstance(language_value, str):
            raise TypeError("Language selector must contain Language values.")
        self._translator = Translator(Language(language_value))
        self._placement_overlay.set_translator(self._translator)
        self._retranslate()
        if self._latest_update is not None:
            self._render_update()
        else:
            self.set_status(mob_count=0)

    @Slot(bool)
    def _update_overlay_visibility(self, visible: bool) -> None:
        self._overlay_label.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_path_visibility(self, visible: bool) -> None:
        self._profile_card.setVisible(visible)
        if self._is_map_popped_out:
            self._map_window.setVisible(visible)
        else:
            self._map_container.setVisible(visible)
            self._path_inspector.setVisible(visible)
        self._adapt_window_geometry()

    @Slot()
    def _toggle_map_popout(self) -> None:
        if not self._is_map_popped_out:
            self._is_map_popped_out = True
            if not self._path_toggle.isChecked():
                self._path_toggle.setChecked(True)
            self._map_container_layout.removeWidget(self._path_inspector)
            self._path_inspector.setVisible(True)
            self._map_window.set_inspector(self._path_inspector)
            self._map_container.setVisible(False)
            self._map_window.show()
            self._map_window.raise_()
            self._map_window.activateWindow()
            self._popout_map_button.setText(self._translator.text(Message.UI_DOCK_MAP))
        else:
            self._dock_map()
        self._adapt_window_geometry()

    def _dock_map(self) -> None:
        if not self._is_map_popped_out:
            return
        self._is_map_popped_out = False
        inspector = self._map_window.take_inspector()
        self._map_window.hide()
        if inspector is not None:
            self._map_container_layout.addWidget(inspector)
            inspector.setVisible(self._path_toggle.isChecked())
        self._map_container.setVisible(self._path_toggle.isChecked())
        self._popout_map_button.setText(self._translator.text(Message.UI_POPOUT_MAP))
        self._adapt_window_geometry()

    @Slot()
    def _on_map_window_closed(self) -> None:
        self._dock_map()

    @Slot(bool)
    def _on_placements_toggled(self, checked: bool) -> None:
        self._placement_overlay.set_guides_visible(checked)
        if self._latest_update is not None:
            self._render_update()

    @Slot(bool)
    def _update_vitals_visibility(self, visible: bool) -> None:
        self._vitals_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_powerups_visibility(self, visible: bool) -> None:
        self._powerup_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot()
    def _on_powerup_rows_changed(self) -> None:
        # Added and removed rows change the panel's height, and the window sizes
        # itself with adjustSize(), so a new row would otherwise be clipped.
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_combat_visibility(self, visible: bool) -> None:
        self._combat_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_recovery_visibility(self, visible: bool) -> None:
        self._recovery_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_target_debug_visibility(self, visible: bool) -> None:
        self._target_debug_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_monster_stats_visibility(self, visible: bool) -> None:
        self._monster_stats_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot()
    def _on_combat_grace_changed(self) -> None:
        self.combat_grace_changed.emit(self._target_grace_spin.value())

    @Slot(bool)
    def _on_kill_verification_changed(self, enabled: bool) -> None:
        self.kill_verification_changed.emit(enabled)

    @Slot(float)
    def _on_anchor_threshold_changed(self, threshold: float) -> None:
        self.anchor_threshold_changed.emit(threshold)

    @Slot(bool)
    def _update_targets_visibility(self, visible: bool) -> None:
        self._target_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(object)
    def _on_target_selection_changed(self, config: object) -> None:
        self.target_selection_changed.emit(config)

    def set_target_mob_options(self, class_names: Sequence[str]) -> None:
        """List the monster classes the active detection model reports."""

        self._target_panel.set_class_names(class_names)
        self._adapt_window_geometry()

    def _adapt_window_geometry(self) -> None:
        central = self.centralWidget()
        if central is not None:
            layout = central.layout()
            if layout is not None:
                layout.activate()
        self.adjustSize()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Trigger emergency stop immediately upon Escape keypress."""

        if event.key() == Qt.Key.Key_Escape:
            self._request_emergency_stop()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Record one supported physical key while the attack-key button is active."""

        if (
            watched is self._attack_key_button
            and self._is_recording_attack_key
            and event.type() is QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
        ):
            self._record_attack_key(event)
            return True
        return super().eventFilter(watched, event)

    def _build_layout(self) -> None:
        # Status & Metrics Card
        status_layout = QVBoxLayout()
        status_top = QHBoxLayout()
        status_top.addWidget(self._status_label)
        status_top.addWidget(self._window_label)
        status_top.addWidget(self._tracking_label)
        status_top.addStretch()
        status_layout.addLayout(status_top)

        metrics_row = QHBoxLayout()
        metrics_row.addWidget(self._mob_label)
        metrics_row.addWidget(self._target_label)
        metrics_row.addWidget(self._vitals_label)
        metrics_row.addWidget(self._goal_label)
        status_layout.addLayout(metrics_row)
        self._status_card.setLayout(status_layout)

        # Action Controls Card
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self._start_button)
        controls_layout.addWidget(self._pause_button)
        controls_layout.addWidget(self._emergency_stop_button)
        controls_layout.addWidget(self._attack_key_label)
        controls_layout.addWidget(self._attack_key_button)
        controls_layout.addWidget(self._align_camera_button)
        controls_layout.addWidget(self._auto_align_toggle)
        controls_layout.addWidget(self._language_selector)
        self._controls_card.setLayout(controls_layout)

        # Navigation & Profiles Card
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(self._profile_selector)
        profile_layout.addWidget(self._profile_name_input)
        profile_layout.addWidget(self._save_profile_button)
        profile_layout.addWidget(self._load_profile_button)
        profile_layout.addWidget(self._reset_map_button)
        profile_layout.addWidget(self._world_data_button)
        profile_layout.addWidget(self._spawn_point_button)
        profile_layout.addWidget(self._spawn_point_label)
        profile_layout.addWidget(self._profile_anchor_label)
        self._profile_card.setLayout(profile_layout)

        # Telemetry & Diagnostics Toolbar Card
        telemetry_layout = QHBoxLayout()
        telemetry_layout.addWidget(self._debug_toggle)
        telemetry_layout.addWidget(self._placements_toggle)
        telemetry_layout.addWidget(self._path_toggle)
        telemetry_layout.addWidget(self._popout_map_button)
        telemetry_layout.addWidget(self._vitals_toggle)
        telemetry_layout.addWidget(self._powerups_toggle)
        telemetry_layout.addWidget(self._targets_toggle)
        telemetry_layout.addWidget(self._combat_toggle)
        telemetry_layout.addWidget(self._recovery_toggle)
        telemetry_layout.addWidget(self._target_debug_toggle)
        telemetry_layout.addWidget(self._monster_stats_toggle)
        self._telemetry_card.setLayout(telemetry_layout)

        content = QVBoxLayout()
        content.addWidget(self._status_card)
        content.addWidget(self._controls_card)
        content.addWidget(self._telemetry_card)
        content.addWidget(self._overlay_label)
        content.addWidget(self._vitals_panel)
        content.addWidget(self._powerup_panel)
        content.addWidget(self._target_panel)
        content.addWidget(self._combat_panel)
        content.addWidget(self._recovery_panel)
        content.addWidget(self._target_debug_panel)
        content.addWidget(self._monster_stats_panel)
        content.addWidget(self._profile_card)
        content.addWidget(self._map_container)

        container = QWidget()
        container.setLayout(content)
        self.setCentralWidget(container)

    def _connect_controls(self) -> None:
        self._start_button.clicked.connect(self._request_start)
        self._pause_button.clicked.connect(self._request_pause)
        self._emergency_stop_button.clicked.connect(self._request_emergency_stop)
        self._attack_key_button.clicked.connect(self._begin_attack_key_recording)
        self._align_camera_button.clicked.connect(self._request_camera_alignment)
        self._auto_align_toggle.toggled.connect(self.auto_align_changed)
        self._attack_key_button.installEventFilter(self)
        self._debug_toggle.toggled.connect(self._update_overlay_visibility)
        self._path_toggle.toggled.connect(self._update_path_visibility)
        self._popout_map_button.clicked.connect(self._toggle_map_popout)
        self._map_window.closed.connect(self._on_map_window_closed)
        self._map_window.emergency_stop_requested.connect(self._request_emergency_stop)
        self._vitals_toggle.toggled.connect(self._update_vitals_visibility)
        self._powerups_toggle.toggled.connect(self._update_powerups_visibility)
        self._powerup_panel.config_changed.connect(self._on_powerup_config_changed)
        self._powerup_panel.rows_changed.connect(self._on_powerup_rows_changed)
        self._placements_toggle.toggled.connect(self._on_placements_toggled)
        self._language_selector.currentIndexChanged.connect(self._switch_language)
        self._save_profile_button.clicked.connect(self._on_save_profile_clicked)
        self._load_profile_button.clicked.connect(self._on_load_profile_clicked)
        self._reset_map_button.clicked.connect(self._on_reset_map_clicked)
        self._world_data_button.clicked.connect(self._on_world_data_clicked)
        self._spawn_point_button.clicked.connect(self.set_spawn_point_requested)
        self._recovery_toggle.toggled.connect(self._update_recovery_visibility)
        self._recovery_timeout_spin.valueChanged.connect(self._on_emergency_inputs_changed)
        self._recovery_hotkey_combo.currentIndexChanged.connect(self._on_emergency_inputs_changed)

        for check in (self._hp_enabled, self._mp_enabled, self._fp_enabled):
            check.toggled.connect(self._on_vitals_inputs_changed)
        for spin in (
            self._hp_threshold_spin,
            self._mp_threshold_spin,
            self._fp_threshold_spin,
            self._hp_debounce_spin,
            self._mp_debounce_spin,
            self._fp_debounce_spin,
        ):
            spin.valueChanged.connect(self._on_vitals_inputs_changed)
        for combo in (self._hp_key_combo, self._mp_key_combo, self._fp_key_combo):
            combo.currentTextChanged.connect(self._on_vitals_inputs_changed)
        self._combat_toggle.toggled.connect(self._update_combat_visibility)
        self._target_grace_spin.valueChanged.connect(self._on_combat_grace_changed)
        self._kill_verification_toggle.toggled.connect(self._on_kill_verification_changed)
        self._anchor_threshold_spin.valueChanged.connect(self._on_anchor_threshold_changed)
        self._targets_toggle.toggled.connect(self._update_targets_visibility)
        self._target_panel.selection_changed.connect(self._on_target_selection_changed)
        self._target_debug_toggle.toggled.connect(self._update_target_debug_visibility)
        self._monster_stats_toggle.toggled.connect(self._update_monster_stats_visibility)

    def refresh_profiles(self, select_path: Path | None = None) -> None:
        """Scan the navigation profiles directory and populate the selector."""

        current_path = select_path or self._profile_selector.currentData()
        self._profile_selector.blockSignals(True)
        self._profile_selector.clear()
        profiles = list_navigation_profiles(self._navigation_dir)
        selected_index = -1
        for idx, profile in enumerate(profiles):
            label = self._translator.text(
                Message.UI_PROFILE_CELLS_COUNT,
                name=profile.name,
                count=profile.cell_count,
            )
            self._profile_selector.addItem(label, profile.path)
            if current_path is not None and profile.path == current_path:
                selected_index = idx

        if selected_index >= 0:
            self._profile_selector.setCurrentIndex(selected_index)
        elif self._profile_selector.count() > 0:
            self._profile_selector.setCurrentIndex(0)
        self._profile_selector.blockSignals(False)

    @Slot()
    def _on_save_profile_clicked(self) -> None:
        raw_text = self._profile_name_input.text()
        cleaned = sanitize_profile_name(raw_text)
        if not cleaned:
            selected_data = self._profile_selector.currentData()
            if isinstance(selected_data, Path):
                cleaned = sanitize_profile_name(selected_data.stem)
        if not cleaned:
            return
        target_path = self._navigation_dir / f"{cleaned}.json"
        self.save_profile_requested.emit(target_path)
        self.refresh_profiles(select_path=target_path)

    @Slot()
    def _on_load_profile_clicked(self) -> None:
        selected = self._profile_selector.currentData()
        if isinstance(selected, Path) and selected.is_file():
            self.load_profile_requested.emit(selected)

    @Slot()
    def _on_reset_map_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            self._translator.text(Message.UI_PROFILE_RESET_TITLE),
            self._translator.text(Message.UI_PROFILE_RESET_PROMPT),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.reset_navigation_requested.emit()

    def show_error_dialog(self, title: str, message: str) -> None:
        """Display a warning/error dialog to the operator."""

        QMessageBox.warning(self, title, message)

    def confirm_read_only_profile(self) -> bool:
        """Offer the two defined outcomes for a profile that could not be re-anchored.

        Exactly two are offered, and cancelling is the default: a silently shifted map is
        worse than no map at all (US-036).
        """

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self._translator.text(Message.UI_PROFILE_UNMATCHED_TITLE))
        box.setText(self._translator.text(Message.UI_PROFILE_UNMATCHED_PROMPT))
        read_only = box.addButton(
            self._translator.text(Message.UI_PROFILE_UNMATCHED_READ_ONLY),
            QMessageBox.ButtonRole.AcceptRole,
        )
        cancel = box.addButton(
            self._translator.text(Message.UI_PROFILE_UNMATCHED_CANCEL),
            QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is read_only

    @property
    def world_data_button(self) -> QPushButton:
        """Expose the world data manager trigger for testing."""

        return self._world_data_button

    @property
    def world_data_dialog(self) -> WorldDataDialog | None:
        """Return the world data dialog once the operator has opened it."""

        return self._world_data_dialog

    @Slot()
    def _on_world_data_clicked(self) -> None:
        """Open the world data manager, creating it on first use."""

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

    @property
    def profile_anchor_label(self) -> QLabel:
        """Expose the profile anchor-state chip for testing."""

        return self._profile_anchor_label

    def _retranslate(self) -> None:
        self.setWindowTitle(self._translator.text(Message.UI_TITLE))
        self._status_card.setTitle(self._translator.text(Message.UI_CARD_STATUS))
        self._controls_card.setTitle(self._translator.text(Message.UI_CARD_CONTROLS))
        self._profile_card.setTitle(self._translator.text(Message.UI_CARD_PROFILES))
        self._telemetry_card.setTitle(self._translator.text(Message.UI_CARD_TELEMETRY))
        self._popout_map_button.setText(
            self._translator.text(
                Message.UI_DOCK_MAP if self._is_map_popped_out else Message.UI_POPOUT_MAP
            )
        )
        self._map_window.set_translator(self._translator)

        self._start_button.setText(self._translator.text(Message.UI_START))
        self._pause_button.setText(self._translator.text(Message.UI_PAUSE))
        self._emergency_stop_button.setText(self._translator.text(Message.UI_EMERGENCY_STOP))
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
        self._debug_toggle.setText(self._translator.text(Message.UI_DEBUG_OVERLAY))
        self._path_toggle.setText(self._translator.text(Message.UI_PATH_INSPECTOR))
        self._vitals_toggle.setText(self._translator.text(Message.UI_VITALS_TOGGLE))
        self._powerups_toggle.setText(self._translator.text(Message.UI_POWERUPS_TOGGLE))
        self._powerup_panel.set_translator(self._translator)
        self._placements_toggle.setText(self._translator.text(Message.UI_PLACEMENTS_TOGGLE))
        self._combat_toggle.setText(self._translator.text(Message.UI_COMBAT_SETTINGS))
        self._combat_panel.setTitle(self._translator.text(Message.UI_COMBAT_SETTINGS))
        self._retranslate_recovery()
        self._targets_toggle.setText(self._translator.text(Message.UI_TARGETS_TOGGLE))
        self._target_panel.set_translator(self._translator)
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
        self._target_debug_toggle.setText(self._translator.text(Message.UI_TARGET_DEBUG_TOGGLE))
        self._target_debug_panel.setTitle(self._translator.text(Message.UI_TARGET_DEBUG_TITLE))
        self._target_anchor_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_ANCHOR))
        self._target_hp_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_HP))
        self._target_name_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_NAME))
        self._target_state_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_STATE))
        self._target_reason_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_REASON))
        self._target_break_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_BREAK))
        self._monster_stats_toggle.setText(
            self._translator.text(Message.UI_MONSTER_STATS_DEBUG_TOGGLE)
        )
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
        self._render_profile_anchor_state()
        self._save_profile_button.setText(self._translator.text(Message.UI_PROFILE_SAVE))
        self._load_profile_button.setText(self._translator.text(Message.UI_PROFILE_LOAD))
        self._reset_map_button.setText(self._translator.text(Message.UI_PROFILE_RESET))
        self._world_data_button.setText(self._translator.text(Message.UI_WORLD_DATA))
        self._world_data_button.setToolTip(self._translator.text(Message.UI_WORLD_DATA_TOOLTIP))
        self._spawn_point_button.setText(self._translator.text(Message.UI_RECOVERY_SPAWN_POINT))
        self._spawn_point_button.setToolTip(
            self._translator.text(Message.UI_RECOVERY_SPAWN_POINT_TOOLTIP)
        )
        self._render_spawn_point()
        if self._world_data_dialog is not None:
            self._world_data_dialog.set_translator(self._translator)
        self._profile_name_input.setPlaceholderText(
            self._translator.text(Message.UI_PROFILE_NAME_PLACEHOLDER)
        )
        self.refresh_profiles()
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

    def _retranslate_recovery(self) -> None:
        """Re-label the stuck recovery controls, keeping the selected hotkey selected."""

        self._recovery_toggle.setText(self._translator.text(Message.UI_RECOVERY_TOGGLE))
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

    def _render_spawn_point(self) -> None:
        """Show the spawn anchor the active map would teleport back to, if one is mapped."""

        navigation = self._latest_update.navigation if self._latest_update is not None else None
        spawn = navigation.spawn_point if navigation is not None else None
        if spawn is None:
            self._spawn_point_label.setText(
                self._translator.text(Message.UI_RECOVERY_SPAWN_POINT_NONE)
            )
            return
        self._spawn_point_label.setText(
            self._translator.text(
                Message.UI_RECOVERY_SPAWN_POINT_VALUE,
                x=f"{spawn[0]:.{SPAWN_POINT_DECIMALS}f}",
                y=f"{spawn[1]:.{SPAWN_POINT_DECIMALS}f}",
            )
        )

    def show_spawn_point_refused(self) -> None:
        """Tell the operator why the current position could not become the spawn anchor."""

        self.show_error_dialog(
            self._translator.text(Message.UI_RECOVERY_SPAWN_POINT_REFUSED_TITLE),
            self._translator.text(Message.UI_RECOVERY_SPAWN_POINT_REFUSED_PROMPT),
        )

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
        else:
            self._attack_virtual_key = parse_virtual_key(label)
            self._attack_key_name = label.upper() if len(label) == 1 else label
            self.attack_key_changed.emit(self._attack_virtual_key)
        self._attack_key_button.setText(self._attack_key_name)

    def _set_local_status(self, status: BotStatus) -> None:
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

    def _render_tracking_quality(self) -> None:
        self._tracking_label.setText(
            self._translator.text(_tracking_quality_message(self._tracking_quality))
        )

    def _render_profile_anchor_state(self) -> None:
        self._profile_anchor_label.setText(
            self._translator.text(_profile_anchor_message(self._profile_anchor_state))
        )

    def _render_update(self) -> None:
        if self._latest_update is None:
            return
        update = self._latest_update
        self._render_status_badge(update.status)
        self._window_status = update.window
        self._render_window_status()
        self._tracking_quality = (
            update.navigation.tracking_quality
            if update.navigation is not None
            else TrackingQuality.DEGRADED
        )
        self._render_tracking_quality()
        self._profile_anchor_state = (
            update.navigation.profile_anchor_state
            if update.navigation is not None
            else ProfileAnchorState.SESSION
        )
        self._render_profile_anchor_state()
        self._render_spawn_point()
        self._mob_label.setText(
            self._translator.text(Message.UI_WORLD_STATUS, mob_count=update.state.nearby_mob_count)
        )
        self._target_label.setText(
            self._translator.text(_target_state_message(update.state.selected_target.state))
        )
        self._goal_label.setText(_goal_text(self._translator, update.state, update.goal))
        vitals = update.state.player_vitals
        self._vitals_label.setText(
            self._translator.text(
                Message.UI_VITALS_STATUS,
                hp=f"{vitals.hp_percentage:.1f}",
                mp=f"{vitals.mp_percentage:.1f}",
                fp=f"{vitals.fp_percentage:.1f}",
            )
        )
        if update.frame is not None:
            self._overlay_label.setPixmap(
                render_debug_overlay(
                    update.frame,
                    update.state.visible_mobs,
                    update.state.selected_target,
                    self._translator,
                    vitals=vitals,
                    monster_stats_config=MonsterStatsConfig(),
                    show_placements=self._placements_toggle.isChecked(),
                )
            )
        if update.navigation is not None:
            self._path_inspector.set_navigation(update.navigation)
        self._render_target_debug(update.state.selected_target)
        self._target_break_value.setText(
            self._translator.text(_engagement_break_message(update.engagement_break))
        )
        self._render_monster_stats_debug(update.state.monster_stats)
        self._target_panel.set_progress(update.kill_progress)
        self._update_overlay_visibility(self._debug_toggle.isChecked())
        is_active = update.status in {
            BotStatus.ACTIVE,
            BotStatus.RECONCILING,
            BotStatus.SEARCH_ROTATING,
            BotStatus.SEARCH_ROAMING,
            BotStatus.REPOSITIONING,
        }
        profile_controls_enabled = not is_active
        # Alignment drives the camera by hand, so it is offered only while the session is
        # idle and never while it is already moving the camera or latched in an emergency stop.
        self._align_camera_button.setEnabled(
            update.status
            in {
                BotStatus.PAUSED,
                BotStatus.STANDBY,
                BotStatus.COMPLETED,
                BotStatus.ALIGNMENT_FAILED,
            }
        )
        self._profile_selector.setEnabled(profile_controls_enabled)
        self._profile_name_input.setEnabled(profile_controls_enabled)
        self._save_profile_button.setEnabled(profile_controls_enabled)
        self._load_profile_button.setEnabled(profile_controls_enabled)
        self._reset_map_button.setEnabled(profile_controls_enabled)

    def _render_target_debug(self, target: SelectedTarget) -> None:
        metrics = target.metrics
        self._target_anchor_value.setText(
            self._translator.text(
                Message.UI_TARGET_DEBUG_ANCHOR_VALUE,
                status=_pass_fail_text(self._translator, metrics.anchor_passed),
                score=f"{metrics.anchor_score:.2f}",
                threshold=f"{metrics.anchor_threshold:.2f}",
            )
        )
        self._target_hp_value.setText(
            self._translator.text(
                Message.UI_TARGET_DEBUG_HP_VALUE,
                status=_pass_fail_text(self._translator, metrics.hp_passed),
                pixels=metrics.hp_pixel_count,
                percentage=f"{metrics.hp_percentage:.1f}",
            )
        )
        self._target_name_value.setText(
            self._translator.text(Message.UI_TARGET_DEBUG_NAME_NOT_EVALUATED)
            if metrics.name_status is TargetNameStatus.NOT_EVALUATED
            else self._translator.text(
                Message.UI_TARGET_DEBUG_NAME_VALUE,
                status=_pass_fail_text(self._translator, metrics.name_passed),
                text=metrics.name_text,
                name=metrics.name_candidate or self._translator.text(Message.UI_NO_TARGET_NAME),
            )
        )
        self._target_state_value.setText(self._translator.text(_target_state_message(target.state)))
        self._target_reason_value.setText(
            self._translator.text(_target_failure_reason_message(target))
        )

    def _render_monster_stats_debug(self, metrics: MonsterStatsMetrics) -> None:
        self._monster_anchor_value.setText(
            self._translator.text(
                Message.UI_MONSTER_STATS_DEBUG_ANCHOR_VALUE,
                status=_pass_fail_text(self._translator, metrics.anchor_passed),
                score=f"{metrics.anchor_score:.2f}",
                threshold=f"{metrics.anchor_threshold:.2f}",
            )
            if metrics.anchor_configured
            else self._translator.text(Message.UI_MONSTER_STATS_DEBUG_ANCHOR_FIXED_REGION)
        )
        self._monster_roi_value.setText(
            self._translator.text(
                Message.UI_MONSTER_STATS_DEBUG_ROI_VALUE,
                width=metrics.roi_width,
                height=metrics.roi_height,
            )
        )
        self._monster_source_value.setText(
            self._translator.text(_monster_stats_source_message(metrics.source))
        )
        self._monster_kills_value.setText(
            str(metrics.parsed_count)
            if metrics.parsed_count is not None
            else self._translator.text(Message.UI_MONSTER_STATS_DEBUG_NO_COUNT)
        )
        self._monster_text_value.setText(
            metrics.raw_text
            if metrics.raw_text
            else self._translator.text(Message.UI_MONSTER_STATS_DEBUG_NO_TEXT)
        )
        self._monster_status_value.setText(
            self._translator.text(_monster_stats_status_message(metrics.status))
        )

    def register_teardown(self, teardown: Callable[[], None]) -> None:
        """Register a worker shutdown callback to run before the window closes."""

        self._teardowns.append(teardown)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure the session is paused, secondary windows closed, and navigation data persisted."""

        self.pause_requested.emit()
        # Worker threads are stopped before the widgets go away, so no background tick can
        # publish into a half-destroyed window.
        for teardown in self._teardowns:
            teardown()
        if self._map_window is not None:
            self._map_window.close()
        if self._world_data_dialog is not None:
            self._world_data_dialog.close()
        self._placement_overlay.stop()
        super().closeEvent(event)


def _match_threshold_spin(default_value: float) -> QDoubleSpinBox:
    """Build one template-match threshold control over the supported score range."""

    spin = QDoubleSpinBox()
    spin.setRange(MINIMUM_MATCH_THRESHOLD, MAXIMUM_MATCH_THRESHOLD)
    spin.setSingleStep(MATCH_THRESHOLD_STEP)
    spin.setDecimals(MATCH_THRESHOLD_DECIMALS)
    spin.setValue(default_value)
    return spin


def _key_label(key: int) -> str | None:
    """Translate the subset of Qt key codes supported by combat bindings."""

    if key == Qt.Key.Key_Space:
        return "space"
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9 or Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return chr(key)
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        return f"F{key - Qt.Key.Key_F1 + 1}"
    return None


def _virtual_key_name(virtual_key: int) -> str:
    """Format a virtual-key code as a human-readable key string."""

    if 0x70 <= virtual_key <= 0x7B:
        return f"F{virtual_key - 0x70 + 1}"
    if 0x30 <= virtual_key <= 0x39:
        return chr(virtual_key)
    if 0x41 <= virtual_key <= 0x5A:
        return chr(virtual_key)
    if virtual_key == 0x20:
        return "Space"
    return f"0x{virtual_key:02X}"


def _status_message(status: BotStatus) -> Message:
    return {
        BotStatus.ACTIVE: Message.UI_STATUS_ACTIVE,
        BotStatus.STANDBY: Message.UI_STATUS_STANDBY,
        BotStatus.COMPLETED: Message.UI_STATUS_COMPLETED,
        BotStatus.COMBAT: Message.UI_STATUS_COMBAT,
        BotStatus.PAUSED: Message.UI_STATUS_PAUSED,
        BotStatus.EMERGENCY_STOPPED: Message.UI_STATUS_EMERGENCY_STOPPED,
        BotStatus.RECONCILING: Message.UI_STATUS_RECONCILING,
        BotStatus.SEARCH_ROTATING: Message.UI_STATUS_SEARCH_ROTATING,
        BotStatus.SEARCH_ROAMING: Message.UI_STATUS_SEARCH_ROAMING,
        BotStatus.REPOSITIONING: Message.UI_STATUS_REPOSITIONING,
        BotStatus.ALIGNING: Message.UI_STATUS_ALIGNING,
        BotStatus.ALIGNMENT_FAILED: Message.UI_STATUS_ALIGNMENT_FAILED,
        BotStatus.EMERGENCY_TELEPORT: Message.UI_STATUS_EMERGENCY_TELEPORT,
        BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE: (
            Message.UI_STATUS_EMERGENCY_TELEPORT_UNAVAILABLE
        ),
    }[status]


def _tracking_quality_message(quality: TrackingQuality) -> Message:
    return {
        TrackingQuality.MEASURED: Message.UI_TRACKING_MEASURED,
        TrackingQuality.PREDICTED: Message.UI_TRACKING_PREDICTED,
        TrackingQuality.DEGRADED: Message.UI_TRACKING_DEGRADED,
    }[quality]


def _profile_anchor_message(state: ProfileAnchorState) -> Message:
    return {
        ProfileAnchorState.SESSION: Message.UI_PROFILE_ANCHOR_SESSION,
        ProfileAnchorState.ANCHORED: Message.UI_PROFILE_ANCHOR_ANCHORED,
        ProfileAnchorState.READ_ONLY: Message.UI_PROFILE_ANCHOR_READ_ONLY,
        ProfileAnchorState.UNANCHORED: Message.UI_PROFILE_ANCHOR_UNANCHORED,
    }[state]


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
    """Explain a rejected nameplate reading, distinguishing a missing OCR engine."""

    return {
        TargetNameStatus.NOT_EVALUATED: Message.UI_TARGET_DEBUG_REASON_ANCHOR,
        TargetNameStatus.MATCHED: Message.UI_TARGET_DEBUG_REASON_OK,
        TargetNameStatus.NO_MATCH: Message.UI_TARGET_DEBUG_REASON_NAME,
        TargetNameStatus.UNREADABLE: Message.UI_TARGET_DEBUG_REASON_NAME_UNREADABLE,
        TargetNameStatus.OCR_FAILED: Message.UI_TARGET_DEBUG_REASON_NAME_OCR_FAILED,
        TargetNameStatus.ENGINE_UNAVAILABLE: Message.UI_TARGET_DEBUG_REASON_NAME_ENGINE,
    }[status]


def _goal_text(translator: Translator, state: WorldState, goal: FarmingGoal | None) -> str:
    if goal is None:
        return translator.text(Message.UI_NO_GOAL)
    quantities = {entry.item: entry.quantity for entry in state.inventory}
    return translator.text(
        Message.UI_GOAL_PROGRESS,
        current=quantities.get(goal.item_name, 0),
        required=goal.required_quantity,
        item_name=goal.item_name,
    )
