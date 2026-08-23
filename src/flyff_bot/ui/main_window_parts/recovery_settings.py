from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel

from flyff_bot.features.automation.emergency_recovery import (
    MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
    EmergencyRecoveryConfig,
)
from flyff_bot.features.input_control import parse_virtual_key
from flyff_bot.i18n import Message, Translator

EMERGENCY_HOTKEY_CHOICES = [
    *(f"F{number}" for number in range(1, 13)),
    *(str(digit) for digit in range(10)),
    *(chr(code) for code in range(ord("A"), ord("Z") + 1)),
]
STUCK_TIMEOUT_STEP_SECONDS = 5.0
STUCK_TIMEOUT_DECIMALS = 1


class RecoverySettingsPanel(QGroupBox):
    """Operator-configurable stuck timeout and emergency teleport hotkey."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")

        self._timeout_label = QLabel()
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(
            MINIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
            MAXIMUM_UNRECOVERABLE_STUCK_TIMEOUT_SECONDS,
        )
        self.timeout_spin.setSingleStep(STUCK_TIMEOUT_STEP_SECONDS)
        self.timeout_spin.setDecimals(STUCK_TIMEOUT_DECIMALS)

        self._hotkey_label = QLabel()
        self.hotkey_combo = QComboBox()
        self.hotkey_combo.addItem("", userData=None)
        for key_name in EMERGENCY_HOTKEY_CHOICES:
            self.hotkey_combo.addItem(key_name, userData=key_name)

        layout = QGridLayout(self)
        layout.addWidget(self._timeout_label, 0, 0)
        layout.addWidget(self.timeout_spin, 0, 1)
        layout.addWidget(self._hotkey_label, 1, 0)
        layout.addWidget(self.hotkey_combo, 1, 1)

    def load_config(self, config: EmergencyRecoveryConfig) -> None:
        self.timeout_spin.setValue(config.stuck_timeout_seconds)
        key_name = None
        if config.teleport_virtual_key is not None:
            for candidate in EMERGENCY_HOTKEY_CHOICES:
                try:
                    if parse_virtual_key(candidate) == config.teleport_virtual_key:
                        key_name = candidate
                        break
                except ValueError:
                    continue
        index = self.hotkey_combo.findData(key_name)
        if index >= 0:
            self.hotkey_combo.setCurrentIndex(index)

    def get_config(self) -> EmergencyRecoveryConfig:
        hotkey_data = self.hotkey_combo.currentData()
        virtual_key: int | None = None
        if hotkey_data:
            try:
                virtual_key = parse_virtual_key(str(hotkey_data))
            except ValueError:
                virtual_key = None
        return EmergencyRecoveryConfig(
            stuck_timeout_seconds=self.timeout_spin.value(),
            teleport_virtual_key=virtual_key,
        )

    def retranslate(self, translator: Translator) -> None:
        self.setTitle(translator.text(Message.UI_RECOVERY_TITLE))
        self._timeout_label.setText(translator.text(Message.UI_RECOVERY_TIMEOUT))
        self.timeout_spin.setToolTip(translator.text(Message.UI_RECOVERY_TIMEOUT_TOOLTIP))
        self._hotkey_label.setText(translator.text(Message.UI_RECOVERY_HOTKEY))
        self.hotkey_combo.setToolTip(translator.text(Message.UI_RECOVERY_HOTKEY_TOOLTIP))
        self.hotkey_combo.blockSignals(True)
        self.hotkey_combo.setItemText(0, translator.text(Message.UI_RECOVERY_HOTKEY_UNASSIGNED))
        self.hotkey_combo.blockSignals(False)
