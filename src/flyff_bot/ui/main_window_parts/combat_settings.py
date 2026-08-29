from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from flyff_bot.constants import DEFAULT_POLICY_MODEL_DIRECTORY
from flyff_bot.features.automation.controllers import (
    DEFAULT_COMBAT_CLASS_PROFILE,
    MELEE_ENGAGEMENT_DISTANCE_UNITS,
    CombatClassProfile,
)
from flyff_bot.features.policy.contract import ContractIncompatibility
from flyff_bot.features.policy.models import (
    DEFAULT_POLICY_RUNTIME_MODE,
    PolicyRuntimeMode,
)
from flyff_bot.features.policy.runner import PolicyFault
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
    """Combat profile, policy artifacts, targeting thresholds, and verification controls."""

    policy_model_directory_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        # Filled by ``retranslate``; every user-visible string comes from the locale bundle.
        self._policy_model_dialog_title = ""

        self._class_label = QLabel()
        self.class_selector = QComboBox()
        for profile in CombatClassProfile:
            self.class_selector.addItem("", userData=profile)
        self.class_selector.setCurrentIndex(
            list(CombatClassProfile).index(DEFAULT_COMBAT_CLASS_PROFILE)
        )

        self._policy_label = QLabel()
        self.policy_mode_selector = QComboBox()
        for mode in PolicyRuntimeMode:
            self.policy_mode_selector.addItem("", userData=mode)
        self.policy_mode_selector.setCurrentIndex(
            list(PolicyRuntimeMode).index(DEFAULT_POLICY_RUNTIME_MODE)
        )

        self._policy_model_label = QLabel()
        self.policy_model_directory_edit = QLineEdit(DEFAULT_POLICY_MODEL_DIRECTORY)
        self.policy_model_browse_button = QPushButton()
        self.policy_diagnostic_label = QLabel()
        self.policy_diagnostic_label.setWordWrap(True)
        self.policy_diagnostic_label.setVisible(False)
        self._policy_model_row = QWidget()
        policy_model_layout = QHBoxLayout(self._policy_model_row)
        policy_model_layout.setContentsMargins(0, 0, 0, 0)
        policy_model_layout.addWidget(self.policy_model_directory_edit)
        policy_model_layout.addWidget(self.policy_model_browse_button)
        self.policy_model_browse_button.clicked.connect(self._browse_policy_model_directory)
        self.policy_model_directory_edit.editingFinished.connect(self._emit_policy_model_directory)

        self._engagement_label = QLabel()
        self.engagement_distance_spin = QDoubleSpinBox()
        self.engagement_distance_spin.setRange(0.1, 100.0)
        self.engagement_distance_spin.setSingleStep(0.5)
        self.engagement_distance_spin.setDecimals(1)
        self.engagement_distance_spin.setValue(MELEE_ENGAGEMENT_DISTANCE_UNITS)

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
        layout.addWidget(self._class_label, 0, 0)
        layout.addWidget(self.class_selector, 0, 1)
        layout.addWidget(self._policy_label, 1, 0)
        layout.addWidget(self.policy_mode_selector, 1, 1)
        layout.addWidget(self._policy_model_label, 2, 0)
        layout.addWidget(self._policy_model_row, 2, 1)
        layout.addWidget(self.policy_diagnostic_label, 3, 0, 1, 2)
        layout.addWidget(self._engagement_label, 4, 0)
        layout.addWidget(self.engagement_distance_spin, 4, 1)
        layout.addWidget(self._grace_label, 5, 0)
        layout.addWidget(self.grace_spin, 5, 1)
        layout.addWidget(self._verification_label, 6, 0)
        layout.addWidget(self.verification_toggle, 6, 1)
        layout.addWidget(self._anchor_label, 7, 0)
        layout.addWidget(self.anchor_spin, 7, 1)

    def set_policy_diagnostic(self, translator: Translator, fault: PolicyFault | None) -> None:
        """Show why learned automation stopped, or hide the diagnostic when it is running.

        An artifact refused because it was produced under another decision contract is reported
        as its own complete sentence naming both versions, never as a raw code pasted into a
        sentence (US-079).
        """

        self.policy_diagnostic_label.setVisible(fault is not None)
        self.policy_diagnostic_label.setText(
            "" if fault is None else policy_fault_text(translator, fault)
        )

    def _browse_policy_model_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self._policy_model_dialog_title, self.policy_model_directory_edit.text()
        )
        if directory:
            self.policy_model_directory_edit.setText(directory)
            self._emit_policy_model_directory()

    def _emit_policy_model_directory(self) -> None:
        self.policy_model_directory_changed.emit(self.policy_model_directory_edit.text().strip())

    def retranslate(self, translator: Translator) -> None:
        self.setTitle(translator.text(Message.UI_COMBAT_SETTINGS))
        self._class_label.setText(translator.text(Message.UI_COMBAT_CLASS))
        self.class_selector.setToolTip(translator.text(Message.UI_COMBAT_CLASS_TOOLTIP))
        for profile in CombatClassProfile:
            index = self.class_selector.findData(profile)
            if index >= 0:
                key = (
                    Message.UI_COMBAT_CLASS_MELEE
                    if profile is CombatClassProfile.MELEE
                    else Message.UI_COMBAT_CLASS_RANGED
                    if profile is CombatClassProfile.RANGED
                    else Message.UI_COMBAT_CLASS_CUSTOM
                )
                self.class_selector.setItemText(index, translator.text(key))
        self._policy_label.setText(translator.text(Message.UI_POLICY_MODE))
        self.policy_mode_selector.setToolTip(translator.text(Message.UI_POLICY_MODE_TOOLTIP))
        for mode in PolicyRuntimeMode:
            index = self.policy_mode_selector.findData(mode)
            if index >= 0:
                key = (
                    Message.UI_POLICY_MODE_HEURISTIC
                    if mode is PolicyRuntimeMode.HEURISTIC
                    else Message.UI_POLICY_MODE_SHADOW
                    if mode is PolicyRuntimeMode.ML_SHADOW
                    else Message.UI_POLICY_MODE_ACTIVE
                )
                self.policy_mode_selector.setItemText(index, translator.text(key))
        self._policy_model_label.setText(translator.text(Message.UI_POLICY_MODEL_DIRECTORY))
        self.policy_model_directory_edit.setToolTip(
            translator.text(Message.UI_POLICY_MODEL_DIRECTORY_TOOLTIP)
        )
        self.policy_model_browse_button.setText(translator.text(Message.UI_POLICY_MODEL_BROWSE))
        self._policy_model_dialog_title = translator.text(Message.UI_POLICY_MODEL_DIALOG)
        self._engagement_label.setText(translator.text(Message.UI_ENGAGEMENT_DISTANCE))
        self.engagement_distance_spin.setToolTip(
            translator.text(Message.UI_ENGAGEMENT_DISTANCE_TOOLTIP)
        )
        self._grace_label.setText(translator.text(Message.UI_TARGET_GRACE_PERIOD))
        self.grace_spin.setToolTip(translator.text(Message.UI_TARGET_GRACE_TOOLTIP))
        self._verification_label.setText(translator.text(Message.UI_KILL_VERIFICATION))
        self.verification_toggle.setToolTip(translator.text(Message.UI_KILL_VERIFICATION_TOOLTIP))
        self._anchor_label.setText(translator.text(Message.UI_ANCHOR_THRESHOLD))
        self.anchor_spin.setToolTip(translator.text(Message.UI_ANCHOR_THRESHOLD_TOOLTIP))


# One complete localized sentence per way an artifact can disagree with the running contract.
_CONTRACT_MESSAGES = {
    ContractIncompatibility.CONTRACT_MISSING: Message.POLICY_CONTRACT_STAMP_MISSING,
    ContractIncompatibility.CONTRACT_VERSION: Message.POLICY_CONTRACT_VERSION_MISMATCH,
    ContractIncompatibility.OBSERVATION_SCHEMA: Message.POLICY_CONTRACT_OBSERVATION_SCHEMA,
    ContractIncompatibility.OBSERVATION_WIDTH: Message.POLICY_CONTRACT_OBSERVATION_WIDTH,
    ContractIncompatibility.GOAL_VOCABULARY: Message.POLICY_CONTRACT_GOAL_VOCABULARY,
    ContractIncompatibility.ACTION_VOCABULARY: Message.POLICY_CONTRACT_ACTION_VOCABULARY,
    ContractIncompatibility.REWARD_CONFIG: Message.POLICY_CONTRACT_REWARD_CONFIG,
    ContractIncompatibility.TACTICAL_PARAMETERS: Message.POLICY_CONTRACT_TACTICAL_PARAMETERS,
}


def policy_fault_text(translator: Translator, fault: PolicyFault) -> str:
    """Return the complete localized sentence one halted learned session is reported with."""

    if fault.incompatibility is None:
        return translator.text(Message.POLICY_MODEL_UNAVAILABLE, reason=fault.reason)
    return translator.text(
        _CONTRACT_MESSAGES[fault.incompatibility], expected=fault.expected, found=fault.found
    )
