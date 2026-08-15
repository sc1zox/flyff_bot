"""Localized native dashboard for observed automation state."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.input_control import parse_virtual_key
from flyff_bot.features.navigation.persistence import (
    DEFAULT_NAVIGATION_DIR,
    list_navigation_profiles,
    sanitize_profile_name,
)
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import BotStatus, DashboardUpdate, FarmingGoal
from flyff_bot.ui.debug_overlay import DebugOverlayWidget, render_debug_overlay
from flyff_bot.ui.path_inspector import PathInspectorWidget


class MainWindow(QMainWindow):
    """Render immutable dashboard updates and emit operator intent signals."""

    start_requested = Signal()
    pause_requested = Signal()
    emergency_stop_requested = Signal()
    attack_key_changed = Signal(int)
    save_profile_requested = Signal(Path)
    load_profile_requested = Signal(Path)
    reset_navigation_requested = Signal()

    def __init__(self, translator: Translator, *, navigation_dir: Path | None = None) -> None:
        super().__init__()
        self._translator = translator
        self._navigation_dir = navigation_dir or DEFAULT_NAVIGATION_DIR
        self._latest_update: DashboardUpdate | None = None
        self._status_label = QLabel()
        self._goal_label = QLabel()
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
        self._language_selector = QComboBox()
        self._build_layout()
        self._connect_controls()
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

    def set_status(self, mob_count: int) -> None:
        """Retain the bootstrap summary API for callers without a full update."""

        self._status_label.setText(
            self._translator.text(Message.UI_WORLD_STATUS, mob_count=mob_count)
        )
        self._goal_label.setText(self._translator.text(Message.UI_NO_GOAL))

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
        content.addLayout(controls)
        content.addWidget(self._overlay_label)
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
        self._language_selector.currentIndexChanged.connect(self._switch_language)
        self._save_profile_button.clicked.connect(self._on_save_profile_clicked)
        self._load_profile_button.clicked.connect(self._on_load_profile_clicked)
        self._reset_map_button.clicked.connect(self._on_reset_map_clicked)

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
        if update.frame is not None:
            self._overlay_label.setPixmap(
                render_debug_overlay(
                    update.frame,
                    update.state.visible_mobs,
                    update.state.selected_target,
                    self._translator,
                )
            )
        if update.navigation is not None:
            self._path_inspector.set_navigation(update.navigation)
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
