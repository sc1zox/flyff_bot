from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel

from flyff_bot.features.automation.emergency_recovery import (
    MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    EmergencyRecoveryConfig,
)
from flyff_bot.features.navigation.teleporter_models import TeleporterDestination
from flyff_bot.i18n import Message, Translator

STUCK_TIMEOUT_STEP_SECONDS = 5.0
STUCK_TIMEOUT_DECIMALS = 1


class RecoverySettingsPanel(QGroupBox):
    """Operator-configurable timeout and built-in teleporter reset destination."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self._destinations: tuple[TeleporterDestination, ...] = ()

        self._timeout_label = QLabel()
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(
            MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
            MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
        )
        self.timeout_spin.setSingleStep(STUCK_TIMEOUT_STEP_SECONDS)
        self.timeout_spin.setDecimals(STUCK_TIMEOUT_DECIMALS)

        self._destination_label = QLabel()
        self.destination_combo = QComboBox()
        self.destination_combo.addItem("", userData=None)

        layout = QGridLayout(self)
        layout.addWidget(self._timeout_label, 0, 0)
        layout.addWidget(self.timeout_spin, 0, 1)
        layout.addWidget(self._destination_label, 1, 0)
        layout.addWidget(self.destination_combo, 1, 1)

    def set_destinations(self, destinations: tuple[TeleporterDestination, ...]) -> None:
        """Populate the selector with client-declared destinations only."""

        selected_id = self.destination_combo.currentData()
        self._destinations = destinations
        self.destination_combo.blockSignals(True)
        self.destination_combo.clear()
        self.destination_combo.addItem("", userData=None)
        for destination in destinations:
            self.destination_combo.addItem(
                destination.name,
                userData=destination.destination_id,
            )
        index = self.destination_combo.findData(selected_id)
        self.destination_combo.setCurrentIndex(index if index >= 0 else 0)
        self.destination_combo.blockSignals(False)

    def load_config(self, config: EmergencyRecoveryConfig) -> None:
        self.timeout_spin.setValue(config.stuck_timeout_seconds)
        destination_id = None if config.destination is None else config.destination.destination_id
        index = self.destination_combo.findData(destination_id)
        self.destination_combo.setCurrentIndex(index if index >= 0 else 0)

    def get_config(self) -> EmergencyRecoveryConfig:
        destination_id = self.destination_combo.currentData()
        destination = next(
            (
                candidate
                for candidate in self._destinations
                if candidate.destination_id == destination_id
            ),
            None,
        )
        return EmergencyRecoveryConfig(
            stuck_timeout_seconds=self.timeout_spin.value(),
            destination=destination,
        )

    def retranslate(self, translator: Translator) -> None:
        self.setTitle(translator.text(Message.UI_RECOVERY_TITLE))
        self._timeout_label.setText(translator.text(Message.UI_RECOVERY_TIMEOUT))
        self.timeout_spin.setToolTip(translator.text(Message.UI_RECOVERY_TIMEOUT_TOOLTIP))
        self._destination_label.setText(translator.text(Message.UI_RECOVERY_DESTINATION))
        self.destination_combo.setToolTip(translator.text(Message.UI_RECOVERY_DESTINATION_TOOLTIP))
        self.destination_combo.blockSignals(True)
        self.destination_combo.setItemText(
            0,
            translator.text(Message.UI_RECOVERY_DESTINATION_UNASSIGNED),
        )
        self.destination_combo.blockSignals(False)
