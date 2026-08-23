from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
)

from flyff_bot.features.automation.camera_alignment import DEFAULT_AUTO_ALIGN_CAMERA
from flyff_bot.features.input_control import parse_virtual_key
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.main_window_parts.controls import DEFAULT_ATTACK_KEY_NAME, key_label


class WindowControlsCard(QGroupBox):
    """Primary operator actions and language selection."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self.start_button = QPushButton()
        self.start_button.setObjectName("ActionStart")
        self.pause_button = QPushButton()
        self.pause_button.setObjectName("ActionPause")
        self.attack_key_label = QLabel()
        self.attack_key_button = QPushButton()
        self.align_camera_button = QPushButton()
        self.auto_align_toggle = QCheckBox()
        self.auto_align_toggle.setObjectName("Switch")
        self.auto_align_toggle.setChecked(DEFAULT_AUTO_ALIGN_CAMERA)
        self.language_label = QLabel()
        self.language_selector = QComboBox()

        self._attack_virtual_key = parse_virtual_key(DEFAULT_ATTACK_KEY_NAME)
        self._attack_key_name = DEFAULT_ATTACK_KEY_NAME
        self._is_recording_attack_key = False

        layout = QGridLayout(self)
        layout.addWidget(self.start_button, 0, 0)
        layout.addWidget(self.pause_button, 0, 1)
        layout.addWidget(self.attack_key_label, 0, 2)
        layout.addWidget(self.attack_key_button, 0, 3)
        layout.addWidget(self.align_camera_button, 1, 0)
        layout.addWidget(self.auto_align_toggle, 1, 1, 1, 2)
        layout.addWidget(self.language_label, 1, 3)
        layout.addWidget(self.language_selector, 1, 4)
        layout.setColumnStretch(5, 1)

    @property
    def attack_virtual_key(self) -> int:
        return self._attack_virtual_key

    def begin_attack_key_recording(self, translator: Translator) -> None:
        self._is_recording_attack_key = True
        self.attack_key_button.setText(translator.text(Message.UI_ATTACK_KEY_RECORDING))
        self.attack_key_button.setFocus()

    def record_attack_key(self, key_code: int, translator: Translator) -> bool:
        label = key_label(key_code)
        self._is_recording_attack_key = False
        if label is None:
            self.attack_key_button.setToolTip(translator.text(Message.UI_ATTACK_KEY_UNSUPPORTED))
            self.attack_key_button.setText(self._attack_key_name)
            return False
        self._attack_virtual_key = parse_virtual_key(label)
        self._attack_key_name = label
        self.attack_key_button.setToolTip(translator.text(Message.UI_ATTACK_KEY_TOOLTIP))
        self.attack_key_button.setText(label)
        return True

    def retranslate(self, translator: Translator) -> None:
        self.setTitle(translator.text(Message.UI_CARD_CONTROLS))
        self.start_button.setText(translator.text(Message.UI_START))
        self.pause_button.setText(translator.text(Message.UI_PAUSE))
        self.attack_key_label.setText(translator.text(Message.UI_ATTACK_KEY))
        self.attack_key_button.setToolTip(translator.text(Message.UI_ATTACK_KEY_TOOLTIP))
        self.attack_key_button.setText(
            translator.text(Message.UI_ATTACK_KEY_RECORDING)
            if self._is_recording_attack_key
            else self._attack_key_name
        )
        self.align_camera_button.setText(translator.text(Message.UI_ALIGN_CAMERA))
        self.align_camera_button.setToolTip(translator.text(Message.UI_ALIGN_CAMERA_TOOLTIP))
        self.auto_align_toggle.setText(translator.text(Message.UI_AUTO_ALIGN_CAMERA))
        self.auto_align_toggle.setToolTip(translator.text(Message.UI_AUTO_ALIGN_CAMERA_TOOLTIP))
        self.language_label.setText(translator.text(Message.UI_LANGUAGE))
