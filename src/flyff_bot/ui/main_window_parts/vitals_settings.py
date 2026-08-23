from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
)

from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerConfig,
    VitalTriggerRule,
    VitalTriggerType,
)
from flyff_bot.features.input_control import parse_virtual_key
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.main_window_parts.controls import HOTKEY_CHOICES

THRESHOLD_MIN_PERCENT = 1
THRESHOLD_MAX_PERCENT = 99
DEBOUNCE_MIN_SECONDS = 0.1
DEBOUNCE_MAX_SECONDS = 30.0
DEBOUNCE_STEP_SECONDS = 0.5
DEBOUNCE_DECIMALS = 1


class VitalsSettingsPanel(QGroupBox):
    """Configurable HP, MP, and FP trigger rules."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")

        self._type_column = QLabel()
        self._active_column = QLabel()
        self._threshold_column = QLabel()
        self._hotkey_column = QLabel()
        self._debounce_column = QLabel()

        self._rows: dict[VitalTriggerType, _VitalRow] = {}
        for vital_type in (VitalTriggerType.HP, VitalTriggerType.MP, VitalTriggerType.FP):
            self._rows[vital_type] = _VitalRow()

        layout = QGridLayout(self)
        for column, label in enumerate(
            (
                self._type_column,
                self._active_column,
                self._threshold_column,
                self._hotkey_column,
                self._debounce_column,
            )
        ):
            layout.addWidget(label, 0, column)
        for row, vital_type in enumerate(self._rows, start=1):
            controls = self._rows[vital_type]
            layout.addWidget(controls.label, row, 0)
            layout.addWidget(controls.enabled, row, 1)
            layout.addWidget(controls.threshold, row, 2)
            layout.addWidget(controls.hotkey, row, 3)
            layout.addWidget(controls.debounce, row, 4)

    @property
    def hp_threshold_spin(self) -> QSpinBox:
        return self._rows[VitalTriggerType.HP].threshold

    @property
    def mp_threshold_spin(self) -> QSpinBox:
        return self._rows[VitalTriggerType.MP].threshold

    @property
    def fp_threshold_spin(self) -> QSpinBox:
        return self._rows[VitalTriggerType.FP].threshold

    @property
    def rows(self) -> tuple[_VitalRow, ...]:
        """Expose row controls for signal wiring without leaking the mutable map."""

        return tuple(self._rows.values())

    def load_config(self, config: VitalsTriggerConfig) -> None:
        for rule in config.rules:
            key_name = ""
            for candidate in HOTKEY_CHOICES:
                try:
                    if parse_virtual_key(candidate) == rule.virtual_key:
                        key_name = candidate
                        break
                except ValueError:
                    continue
            controls = self._rows.get(rule.vital_type)
            if controls is None:
                continue
            controls.enabled.setChecked(rule.enabled)
            controls.threshold.setValue(round(rule.threshold_percentage))
            controls.hotkey.setCurrentText(key_name)
            controls.debounce.setValue(rule.debounce_seconds)

    def get_config(self) -> VitalsTriggerConfig:
        rules: list[VitalTriggerRule] = []
        for vital_type, controls in self._rows.items():
            try:
                virtual_key = parse_virtual_key(controls.hotkey.currentText().strip())
            except ValueError:
                # An unreadable hotkey is an unusable rule rather than a silently
                # re-assigned one, so the entry is dropped instead of guessed.
                continue
            rules.append(
                VitalTriggerRule(
                    vital_type=vital_type,
                    threshold_percentage=controls.threshold.value(),
                    virtual_key=virtual_key,
                    debounce_seconds=controls.debounce.value(),
                    enabled=controls.enabled.isChecked(),
                )
            )
        return VitalsTriggerConfig(rules=tuple(rules))

    def retranslate(self, translator: Translator) -> None:
        self.setTitle(translator.text(Message.UI_VITALS_TITLE))
        self._type_column.setText(translator.text(Message.UI_VITALS_HP)[:2])
        self._active_column.setText(translator.text(Message.UI_VITALS_ACTIVE))
        self._threshold_column.setText(translator.text(Message.UI_VITALS_THRESHOLD))
        self._hotkey_column.setText(translator.text(Message.UI_VITALS_HOTKEY))
        self._debounce_column.setText(translator.text(Message.UI_VITALS_DEBOUNCE))
        labels = {
            VitalTriggerType.HP: Message.UI_VITALS_HP,
            VitalTriggerType.MP: Message.UI_VITALS_MP,
            VitalTriggerType.FP: Message.UI_VITALS_FP,
        }
        for vital_type, controls in self._rows.items():
            controls.label.setText(translator.text(labels[vital_type]))


class _VitalRow:
    def __init__(self) -> None:
        self.label = QLabel()
        self.enabled = QCheckBox()
        self.enabled.setObjectName("Switch")
        self.threshold = QSpinBox()
        self.threshold.setRange(THRESHOLD_MIN_PERCENT, THRESHOLD_MAX_PERCENT)
        self.hotkey = QComboBox()
        self.hotkey.addItems(HOTKEY_CHOICES)
        self.debounce = QDoubleSpinBox()
        self.debounce.setRange(DEBOUNCE_MIN_SECONDS, DEBOUNCE_MAX_SECONDS)
        self.debounce.setSingleStep(DEBOUNCE_STEP_SECONDS)
        self.debounce.setDecimals(DEBOUNCE_DECIMALS)
