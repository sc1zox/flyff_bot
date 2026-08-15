"""Localized native dashboard for observed automation state."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.automation.models import WorldState
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import BotStatus, DashboardUpdate, FarmingGoal
from flyff_bot.ui.debug_overlay import render_debug_overlay


class MainWindow(QMainWindow):
    """Render immutable dashboard updates and emit operator intent signals."""

    start_requested = Signal()
    pause_requested = Signal()
    emergency_stop_requested = Signal()

    def __init__(self, translator: Translator) -> None:
        super().__init__()
        self._translator = translator
        self._latest_update: DashboardUpdate | None = None
        self._status_label = QLabel()
        self._goal_label = QLabel()
        self._overlay_label = QLabel()
        self._overlay_label.setVisible(False)
        self._start_button = QPushButton()
        self._pause_button = QPushButton()
        self._emergency_stop_button = QPushButton()
        self._debug_toggle = QCheckBox()
        self._language_selector = QComboBox()
        self._build_layout()
        self._connect_controls()
        self._retranslate()
        self.set_status(mob_count=0)

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
    def overlay_label(self) -> QLabel:
        """Expose the optional viewport for deterministic UI tests."""

        return self._overlay_label

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
        self._overlay_label.setVisible(visible and self._overlay_label.pixmap() is not None)

    def _build_layout(self) -> None:
        controls = QHBoxLayout()
        controls.addWidget(self._start_button)
        controls.addWidget(self._pause_button)
        controls.addWidget(self._emergency_stop_button)
        controls.addWidget(self._debug_toggle)
        controls.addWidget(self._language_selector)
        content = QVBoxLayout()
        content.addWidget(self._status_label)
        content.addWidget(self._goal_label)
        content.addLayout(controls)
        content.addWidget(self._overlay_label)
        container = QWidget()
        container.setLayout(content)
        self.setCentralWidget(container)

    def _connect_controls(self) -> None:
        self._start_button.clicked.connect(self._request_start)
        self._pause_button.clicked.connect(self._request_pause)
        self._emergency_stop_button.clicked.connect(self._request_emergency_stop)
        self._debug_toggle.toggled.connect(self._update_overlay_visibility)
        self._language_selector.currentIndexChanged.connect(self._switch_language)

    def _retranslate(self) -> None:
        self.setWindowTitle(self._translator.text(Message.UI_TITLE))
        self._start_button.setText(self._translator.text(Message.UI_START))
        self._pause_button.setText(self._translator.text(Message.UI_PAUSE))
        self._emergency_stop_button.setText(self._translator.text(Message.UI_EMERGENCY_STOP))
        self._debug_toggle.setText(self._translator.text(Message.UI_DEBUG_OVERLAY))
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

    def _set_local_status(self, status: BotStatus) -> None:
        if self._latest_update is None:
            return
        self.update_dashboard(
            DashboardUpdate(
                self._latest_update.state,
                status,
                self._latest_update.goal,
                self._latest_update.frame,
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
        self._update_overlay_visibility(self._debug_toggle.isChecked())


def _status_message(status: BotStatus) -> Message:
    return {
        BotStatus.ACTIVE: Message.UI_STATUS_ACTIVE,
        BotStatus.PAUSED: Message.UI_STATUS_PAUSED,
        BotStatus.EMERGENCY_STOPPED: Message.UI_STATUS_EMERGENCY_STOPPED,
        BotStatus.RECONCILING: Message.UI_STATUS_RECONCILING,
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
