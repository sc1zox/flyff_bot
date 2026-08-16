"""Localized native dashboard for observed automation state."""

from __future__ import annotations

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

from flyff_bot.features.automation.models import SelectedTarget, TargetState, WorldState
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
from flyff_bot.features.navigation.persistence import (
    DEFAULT_NAVIGATION_DIR,
    list_navigation_profiles,
    sanitize_profile_name,
)
from flyff_bot.features.vision.monster_stats import MonsterStatsConfig
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import BotStatus, DashboardUpdate, FarmingGoal
from flyff_bot.ui.debug_overlay import DebugOverlayWidget, render_debug_overlay
from flyff_bot.ui.path_inspector import PathInspectorWidget

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


class MainWindow(QMainWindow):
    """Render immutable dashboard updates and emit operator intent signals."""

    start_requested = Signal()
    pause_requested = Signal()
    emergency_stop_requested = Signal()
    attack_key_changed = Signal(int)
    vitals_config_changed = Signal(object)
    combat_grace_changed = Signal(float)
    kill_verification_changed = Signal(bool)
    save_profile_requested = Signal(Path)
    load_profile_requested = Signal(Path)
    reset_navigation_requested = Signal()

    def __init__(
        self,
        translator: Translator,
        *,
        navigation_dir: Path | None = None,
        vitals_config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._translator = translator
        self._navigation_dir = navigation_dir or DEFAULT_NAVIGATION_DIR
        self._vitals_config_path = vitals_config_path or DEFAULT_VITALS_CONFIG_PATH
        self._latest_update: DashboardUpdate | None = None
        self._status_label = QLabel()
        self._goal_label = QLabel()
        self._vitals_label = QLabel()
        self._overlay_label = DebugOverlayWidget()
        self._overlay_label.setVisible(False)
        self._path_inspector = PathInspectorWidget(self._translator)
        self._path_inspector.setVisible(False)
        self._profile_bar = QWidget()
        self._profile_bar.setVisible(False)
        self._profile_selector = QComboBox()
        self._profile_name_input = QLineEdit()
        self._save_profile_button = QPushButton()
        self._load_profile_button = QPushButton()
        self._reset_map_button = QPushButton()
        self._start_button = QPushButton()
        self._pause_button = QPushButton()
        self._emergency_stop_button = QPushButton()
        self._attack_key_label = QLabel()
        self._attack_key_button = QPushButton()
        self._attack_virtual_key = parse_virtual_key("F3")
        self._attack_key_name = "F3"
        self._is_recording_attack_key = False
        self._debug_toggle = QCheckBox()
        self._path_toggle = QCheckBox()
        self._vitals_toggle = QCheckBox()
        self._placements_toggle = QCheckBox()
        self._language_selector = QComboBox()

        # Combat settings panel
        self._combat_panel = QGroupBox()
        self._combat_panel.setVisible(False)
        self._combat_toggle = QCheckBox()
        self._target_grace_label = QLabel()
        self._target_grace_spin = QDoubleSpinBox()
        self._target_grace_spin.setRange(0.1, 5.0)
        self._target_grace_spin.setSingleStep(0.1)
        self._target_grace_spin.setDecimals(1)
        self._target_grace_spin.setValue(0.8)
        self._target_grace_spin.setSuffix(" s")
        self._kill_verification_label = QLabel()
        self._kill_verification_toggle = QCheckBox()

        # Target verification debug panel
        self._target_debug_toggle = QCheckBox()
        self._target_debug_panel = QGroupBox()
        self._target_debug_panel.setVisible(False)
        self._target_anchor_label = QLabel()
        self._target_anchor_value = QLabel()
        self._target_hp_label = QLabel()
        self._target_hp_value = QLabel()
        self._target_name_label = QLabel()
        self._target_name_value = QLabel()
        self._target_state_label = QLabel()
        self._target_state_value = QLabel()
        self._target_reason_label = QLabel()
        self._target_reason_value = QLabel()

        # Vitals configuration panel
        self._vitals_panel = QGroupBox()
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

        self._init_vitals_widgets()
        self._init_target_debug_widgets()
        self._build_layout()
        self._connect_controls()
        self._load_vitals_config_to_ui()
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
    def attack_key_button(self) -> QPushButton:
        """Expose the key-capture control for the desktop application and tests."""

        return self._attack_key_button

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
    def combat_toggle(self) -> QCheckBox:
        """Expose the combat settings panel toggle control."""

        return self._combat_toggle

    @property
    def combat_panel(self) -> QGroupBox:
        """Expose the combat configuration panel."""

        return self._combat_panel

    @property
    def target_grace_spin(self) -> QDoubleSpinBox:
        """Expose the target click grace period spin box."""

        return self._target_grace_spin

    @property
    def kill_verification_toggle(self) -> QCheckBox:
        """Expose the kill verification toggle checkbox."""

        return self._kill_verification_toggle

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
        self._combat_panel.setLayout(combat_layout)

    def _init_target_debug_widgets(self) -> None:
        target_debug_layout = QVBoxLayout()
        for label, value in (
            (self._target_anchor_label, self._target_anchor_value),
            (self._target_hp_label, self._target_hp_value),
            (self._target_name_label, self._target_name_value),
            (self._target_state_label, self._target_state_value),
            (self._target_reason_label, self._target_reason_value),
        ):
            row = QHBoxLayout()
            row.addWidget(label)
            row.addWidget(value)
            target_debug_layout.addLayout(row)
        self._target_debug_panel.setLayout(target_debug_layout)

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

    def set_status(self, mob_count: int) -> None:
        """Retain the bootstrap summary API for callers without a full update."""

        self._status_label.setText(
            self._translator.text(Message.UI_WORLD_STATUS, mob_count=mob_count)
        )
        self._goal_label.setText(self._translator.text(Message.UI_NO_GOAL))
        self._vitals_label.setText(
            self._translator.text(
                Message.UI_VITALS_STATUS,
                hp="100.0",
                mp="100.0",
                fp="100.0",
            )
        )

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
        self._retranslate()
        if self._latest_update is not None:
            self._render_update()

    @Slot(bool)
    def _update_overlay_visibility(self, visible: bool) -> None:
        self._overlay_label.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_path_visibility(self, visible: bool) -> None:
        self._profile_bar.setVisible(visible)
        self._path_inspector.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_vitals_visibility(self, visible: bool) -> None:
        self._vitals_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _on_placements_toggled(self, _checked: bool) -> None:
        if self._latest_update is not None:
            self._render_update()

    @Slot(bool)
    def _update_combat_visibility(self, visible: bool) -> None:
        self._combat_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot(bool)
    def _update_target_debug_visibility(self, visible: bool) -> None:
        self._target_debug_panel.setVisible(visible)
        self._adapt_window_geometry()

    @Slot()
    def _on_combat_grace_changed(self) -> None:
        self.combat_grace_changed.emit(self._target_grace_spin.value())

    @Slot(bool)
    def _on_kill_verification_changed(self, enabled: bool) -> None:
        self.kill_verification_changed.emit(enabled)

    def _adapt_window_geometry(self) -> None:
        central = self.centralWidget()
        if central is not None:
            layout = central.layout()
            if layout is not None:
                layout.activate()
        self.adjustSize()

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
        controls = QHBoxLayout()
        controls.addWidget(self._start_button)
        controls.addWidget(self._pause_button)
        controls.addWidget(self._emergency_stop_button)
        controls.addWidget(self._attack_key_label)
        controls.addWidget(self._attack_key_button)
        controls.addWidget(self._debug_toggle)
        controls.addWidget(self._path_toggle)
        controls.addWidget(self._vitals_toggle)
        controls.addWidget(self._placements_toggle)
        controls.addWidget(self._combat_toggle)
        controls.addWidget(self._target_debug_toggle)
        controls.addWidget(self._language_selector)

        profile_layout = QHBoxLayout()
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(self._profile_selector)
        profile_layout.addWidget(self._profile_name_input)
        profile_layout.addWidget(self._save_profile_button)
        profile_layout.addWidget(self._load_profile_button)
        profile_layout.addWidget(self._reset_map_button)
        self._profile_bar.setLayout(profile_layout)

        content = QVBoxLayout()
        content.addWidget(self._status_label)
        content.addWidget(self._goal_label)
        content.addWidget(self._vitals_label)
        content.addLayout(controls)
        content.addWidget(self._overlay_label)
        content.addWidget(self._vitals_panel)
        content.addWidget(self._combat_panel)
        content.addWidget(self._target_debug_panel)
        content.addWidget(self._profile_bar)
        content.addWidget(self._path_inspector)
        container = QWidget()
        container.setLayout(content)
        self.setCentralWidget(container)

    def _connect_controls(self) -> None:
        self._start_button.clicked.connect(self._request_start)
        self._pause_button.clicked.connect(self._request_pause)
        self._emergency_stop_button.clicked.connect(self._request_emergency_stop)
        self._attack_key_button.clicked.connect(self._begin_attack_key_recording)
        self._attack_key_button.installEventFilter(self)
        self._debug_toggle.toggled.connect(self._update_overlay_visibility)
        self._path_toggle.toggled.connect(self._update_path_visibility)
        self._vitals_toggle.toggled.connect(self._update_vitals_visibility)
        self._placements_toggle.toggled.connect(self._on_placements_toggled)
        self._language_selector.currentIndexChanged.connect(self._switch_language)
        self._save_profile_button.clicked.connect(self._on_save_profile_clicked)
        self._load_profile_button.clicked.connect(self._on_load_profile_clicked)
        self._reset_map_button.clicked.connect(self._on_reset_map_clicked)

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
        self._target_debug_toggle.toggled.connect(self._update_target_debug_visibility)

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

    def _retranslate(self) -> None:
        self.setWindowTitle(self._translator.text(Message.UI_TITLE))
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
        self._debug_toggle.setText(self._translator.text(Message.UI_DEBUG_OVERLAY))
        self._path_toggle.setText(self._translator.text(Message.UI_PATH_INSPECTOR))
        self._vitals_toggle.setText(self._translator.text(Message.UI_VITALS_TOGGLE))
        self._placements_toggle.setText(self._translator.text(Message.UI_PLACEMENTS_TOGGLE))
        self._combat_toggle.setText(self._translator.text(Message.UI_COMBAT_SETTINGS))
        self._combat_panel.setTitle(self._translator.text(Message.UI_COMBAT_SETTINGS))
        self._target_grace_label.setText(self._translator.text(Message.UI_TARGET_GRACE_PERIOD))
        self._target_grace_spin.setToolTip(self._translator.text(Message.UI_TARGET_GRACE_TOOLTIP))
        self._kill_verification_label.setText(self._translator.text(Message.UI_KILL_VERIFICATION))
        self._kill_verification_toggle.setToolTip(
            self._translator.text(Message.UI_KILL_VERIFICATION_TOOLTIP)
        )
        self._target_debug_toggle.setText(self._translator.text(Message.UI_TARGET_DEBUG_TOGGLE))
        self._target_debug_panel.setTitle(self._translator.text(Message.UI_TARGET_DEBUG_TITLE))
        self._target_anchor_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_ANCHOR))
        self._target_hp_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_HP))
        self._target_name_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_NAME))
        self._target_state_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_STATE))
        self._target_reason_label.setText(self._translator.text(Message.UI_TARGET_DEBUG_REASON))
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
        self._save_profile_button.setText(self._translator.text(Message.UI_PROFILE_SAVE))
        self._load_profile_button.setText(self._translator.text(Message.UI_PROFILE_LOAD))
        self._reset_map_button.setText(self._translator.text(Message.UI_PROFILE_RESET))
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
            )
        )

    def _render_update(self) -> None:
        if self._latest_update is None:
            return
        update = self._latest_update
        self._status_label.setText(
            self._translator.text(
                Message.UI_BOT_STATUS,
                status=self._translator.text(_status_message(update.status)),
            )
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
        self._update_overlay_visibility(self._debug_toggle.isChecked())
        is_active = update.status in {
            BotStatus.ACTIVE,
            BotStatus.RECONCILING,
            BotStatus.SEARCH_ROTATING,
            BotStatus.SEARCH_TILTING,
            BotStatus.SEARCH_ROAMING,
            BotStatus.SEARCH_MINIMAP,
        }
        profile_controls_enabled = not is_active
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
                pixels=target.hp_pixel_count,
                percentage=f"{target.hp_percentage:.1f}",
            )
        )
        self._target_name_value.setText(
            self._translator.text(
                Message.UI_TARGET_DEBUG_NAME_VALUE,
                status=_pass_fail_text(self._translator, metrics.name_passed),
                name=metrics.name_candidate or self._translator.text(Message.UI_NO_TARGET_NAME),
                score=f"{metrics.name_score:.2f}",
                threshold=f"{metrics.name_threshold:.2f}",
            )
        )
        self._target_state_value.setText(self._translator.text(_target_state_message(target.state)))
        self._target_reason_value.setText(
            self._translator.text(_target_failure_reason_message(target))
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure the session is paused and navigation data is persisted upon window close."""

        self.pause_requested.emit()
        super().closeEvent(event)


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
        BotStatus.PAUSED: Message.UI_STATUS_PAUSED,
        BotStatus.EMERGENCY_STOPPED: Message.UI_STATUS_EMERGENCY_STOPPED,
        BotStatus.RECONCILING: Message.UI_STATUS_RECONCILING,
        BotStatus.SEARCH_ROTATING: Message.UI_STATUS_SEARCH_ROTATING,
        BotStatus.SEARCH_TILTING: Message.UI_STATUS_SEARCH_TILTING,
        BotStatus.SEARCH_ROAMING: Message.UI_STATUS_SEARCH_ROAMING,
        BotStatus.SEARCH_MINIMAP: Message.UI_STATUS_SEARCH_MINIMAP,
    }[status]


def _pass_fail_text(translator: Translator, passed: bool) -> str:
    return translator.text(Message.UI_TARGET_DEBUG_PASS if passed else Message.UI_TARGET_DEBUG_FAIL)


def _target_state_message(state: TargetState) -> Message:
    return {
        TargetState.VALID: Message.UI_TARGET_VALID,
        TargetState.WRONG: Message.UI_TARGET_WRONG,
        TargetState.NONE: Message.UI_TARGET_NONE,
    }[state]


def _target_failure_reason_message(target: SelectedTarget) -> Message:
    metrics = target.metrics
    if target.state is TargetState.VALID:
        return Message.UI_TARGET_DEBUG_REASON_OK
    if not metrics.anchor_passed:
        return Message.UI_TARGET_DEBUG_REASON_ANCHOR
    if not metrics.hp_passed:
        return Message.UI_TARGET_DEBUG_REASON_HP
    return Message.UI_TARGET_DEBUG_REASON_NAME


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
