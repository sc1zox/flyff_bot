from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel

from flyff_bot.features.vision.target_verification import (
    DEFAULT_ANCHOR_MATCH_THRESHOLD,
    MAXIMUM_MATCH_THRESHOLD,
    MINIMUM_MATCH_THRESHOLD,
)
from flyff_bot.i18n import Message, Translator

MATCH_THRESHOLD_STEP = 0.05
MATCH_THRESHOLD_DECIMALS = 2
DEFAULT_TARGET_GRACE_SECONDS = 0.8
TARGET_GRACE_STEP_SECONDS = 0.1
TARGET_GRACE_MAX_SECONDS = 10.0
TARGET_GRACE_DECIMALS = 1


class CombatSettingsPanel(QGroupBox):
    """Combat targeting thresholds and kill-verification controls."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")

        self._grace_label = QLabel()
        self.grace_spin = QDoubleSpinBox()
        self.grace_spin.setRange(0.0, TARGET_GRACE_MAX_SECONDS)
        self.grace_spin.setSingleStep(TARGET_GRACE_STEP_SECONDS)
        self.grace_spin.setDecimals(TARGET_GRACE_DECIMALS)
        self.grace_spin.setValue(DEFAULT_TARGET_GRACE_SECONDS)

        self._verification_label = QLabel()
        self.verification_toggle = QCheckBox()
        self.verification_toggle.setObjectName("Switch")
        self.verification_toggle.setChecked(True)

        self._anchor_label = QLabel()
        self.anchor_spin = QDoubleSpinBox()
        self.anchor_spin.setRange(MINIMUM_MATCH_THRESHOLD, MAXIMUM_MATCH_THRESHOLD)
        self.anchor_spin.setSingleStep(MATCH_THRESHOLD_STEP)
        self.anchor_spin.setDecimals(MATCH_THRESHOLD_DECIMALS)
        self.anchor_spin.setValue(DEFAULT_ANCHOR_MATCH_THRESHOLD)

        layout = QGridLayout(self)
        layout.addWidget(self._grace_label, 0, 0)
        layout.addWidget(self.grace_spin, 0, 1)
        layout.addWidget(self._verification_label, 1, 0)
        layout.addWidget(self.verification_toggle, 1, 1)
        layout.addWidget(self._anchor_label, 2, 0)
        layout.addWidget(self.anchor_spin, 2, 1)

    def retranslate(self, translator: Translator) -> None:
        self.setTitle(translator.text(Message.UI_COMBAT_SETTINGS))
        self._grace_label.setText(translator.text(Message.UI_TARGET_GRACE_PERIOD))
        self.grace_spin.setToolTip(translator.text(Message.UI_TARGET_GRACE_TOOLTIP))
        self._verification_label.setText(translator.text(Message.UI_KILL_VERIFICATION))
        self.verification_toggle.setToolTip(translator.text(Message.UI_KILL_VERIFICATION_TOOLTIP))
        self._anchor_label.setText(translator.text(Message.UI_ANCHOR_THRESHOLD))
        self.anchor_spin.setToolTip(translator.text(Message.UI_ANCHOR_THRESHOLD_TOOLTIP))
