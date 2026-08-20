"""Dynamic power-up table for adding, editing, and removing timed hotkeys."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.automation.powerup_controller import (
    DEFAULT_POWERUP_INTERVAL_SECONDS,
    MAXIMUM_POWERUP_INTERVAL_SECONDS,
    MINIMUM_POWERUP_INTERVAL_SECONDS,
    PowerUpConfig,
    PowerUpEntry,
)
from flyff_bot.features.input_control import parse_virtual_key
from flyff_bot.i18n import Message, Translator

DEFAULT_POWERUP_HOTKEY = "F4"
INTERVAL_STEP_SECONDS = 5
NAME_COLUMN_STRETCH = 2

POWERUP_HOTKEY_CHOICES: tuple[str, ...] = (
    *(f"F{number}" for number in range(1, 13)),
    *(str(digit) for digit in range(10)),
    *(chr(code) for code in range(ord("A"), ord("Z") + 1)),
    "Space",
)


@dataclass(frozen=True, slots=True)
class PowerUpRow:
    """The editable widgets backing one configured power-up entry."""

    container: QWidget
    name_input: QLineEdit
    key_combo: QComboBox
    interval_spin: QSpinBox
    enabled_check: QCheckBox
    remove_button: QPushButton


class PowerUpPanel(QGroupBox):
    """Render an arbitrary number of timed-hotkey rows and publish their configuration."""

    config_changed = Signal(object)
    rows_changed = Signal()

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardPanel")
        self._translator = translator
        self._rows: list[PowerUpRow] = []
        self._stagger_seconds = PowerUpConfig().stagger_seconds

        self._name_header = QLabel()
        self._key_header = QLabel()
        self._interval_header = QLabel()
        self._active_header = QLabel()
        self._remove_header = QLabel()
        self._empty_hint = QLabel()
        self._add_button = QPushButton()

        header_row = QHBoxLayout()
        header_row.addWidget(self._name_header, NAME_COLUMN_STRETCH)
        header_row.addWidget(self._key_header)
        header_row.addWidget(self._interval_header)
        header_row.addWidget(self._active_header)
        header_row.addWidget(self._remove_header)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)

        footer_row = QHBoxLayout()
        footer_row.addWidget(self._add_button)
        footer_row.addStretch()

        panel_layout = QVBoxLayout()
        panel_layout.addLayout(header_row)
        panel_layout.addLayout(self._rows_layout)
        panel_layout.addWidget(self._empty_hint)
        panel_layout.addLayout(footer_row)
        self.setLayout(panel_layout)

        self._add_button.clicked.connect(self._on_add_clicked)
        self._retranslate()

    @property
    def rows(self) -> tuple[PowerUpRow, ...]:
        """Expose the current editor rows for wiring and verification."""

        return tuple(self._rows)

    @property
    def add_button(self) -> QPushButton:
        """Expose the add-row control."""

        return self._add_button

    def set_translator(self, translator: Translator) -> None:
        """Switch the displayed language without discarding configured entries."""

        self._translator = translator
        self._retranslate()

    @property
    def config(self) -> PowerUpConfig:
        return self.get_config()

    def get_config(self) -> PowerUpConfig:
        """Return the power-up configuration currently defined by the editor rows."""

        entries = tuple(
            PowerUpEntry(
                virtual_key=parse_virtual_key(row.key_combo.currentText()),
                interval_seconds=row.interval_spin.value(),
                label=row.name_input.text().strip(),
                enabled=row.enabled_check.isChecked(),
            )
            for row in self._rows
        )
        return PowerUpConfig(entries=entries, stagger_seconds=self._stagger_seconds)

    def set_config(self, config: PowerUpConfig) -> None:
        """Replace every editor row with the supplied configuration without re-emitting."""

        self._stagger_seconds = config.stagger_seconds
        while self._rows:
            self._discard_row(self._rows[-1])
        for entry in config.entries:
            self._append_row(entry)
        self._render_empty_hint()
        self.rows_changed.emit()

    def _append_row(self, entry: PowerUpEntry) -> PowerUpRow:
        container = QWidget()
        name_input = QLineEdit(entry.label)
        key_combo = QComboBox()
        key_combo.addItems(POWERUP_HOTKEY_CHOICES)
        key_combo.setCurrentText(_virtual_key_choice(entry.virtual_key))
        interval_spin = QSpinBox()
        interval_spin.setRange(MINIMUM_POWERUP_INTERVAL_SECONDS, MAXIMUM_POWERUP_INTERVAL_SECONDS)
        interval_spin.setSingleStep(INTERVAL_STEP_SECONDS)
        interval_spin.setValue(entry.interval_seconds)
        enabled_check = QCheckBox()
        enabled_check.setChecked(entry.enabled)
        remove_button = QPushButton()
        remove_button.setObjectName("ActionDanger")

        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(name_input, NAME_COLUMN_STRETCH)
        row_layout.addWidget(key_combo)
        row_layout.addWidget(interval_spin)
        row_layout.addWidget(enabled_check)
        row_layout.addWidget(remove_button)

        row = PowerUpRow(
            container=container,
            name_input=name_input,
            key_combo=key_combo,
            interval_spin=interval_spin,
            enabled_check=enabled_check,
            remove_button=remove_button,
        )
        self._rows.append(row)
        self._rows_layout.addWidget(container)
        self._translate_row(row)

        # editingFinished rather than textChanged: a label is typed one character at
        # a time, and every emission persists the file and re-pushes the config.
        name_input.editingFinished.connect(self._emit_config_changed)
        key_combo.currentTextChanged.connect(self._emit_config_changed)
        interval_spin.valueChanged.connect(self._emit_config_changed)
        enabled_check.toggled.connect(self._emit_config_changed)
        remove_button.clicked.connect(lambda: self._on_remove_clicked(row))
        return row

    def _discard_row(self, row: PowerUpRow) -> None:
        self._rows.remove(row)
        self._rows_layout.removeWidget(row.container)
        row.container.setParent(None)
        row.container.deleteLater()

    @Slot()
    def _on_add_clicked(self) -> None:
        self._append_row(
            PowerUpEntry(
                virtual_key=parse_virtual_key(DEFAULT_POWERUP_HOTKEY),
                interval_seconds=DEFAULT_POWERUP_INTERVAL_SECONDS,
            )
        )
        self._render_empty_hint()
        self.rows_changed.emit()
        self._emit_config_changed()

    def _on_remove_clicked(self, row: PowerUpRow) -> None:
        if row not in self._rows:
            return
        self._discard_row(row)
        self._render_empty_hint()
        self.rows_changed.emit()
        self._emit_config_changed()

    @Slot()
    def _emit_config_changed(self) -> None:
        self.config_changed.emit(self.get_config())

    def _render_empty_hint(self) -> None:
        self._empty_hint.setVisible(not self._rows)

    def _retranslate(self) -> None:
        self.setTitle(self._translator.text(Message.UI_POWERUPS_TITLE))
        self._name_header.setText(self._translator.text(Message.UI_POWERUPS_NAME))
        self._key_header.setText(self._translator.text(Message.UI_POWERUPS_HOTKEY))
        self._interval_header.setText(self._translator.text(Message.UI_POWERUPS_INTERVAL))
        self._active_header.setText(self._translator.text(Message.UI_POWERUPS_ACTIVE))
        self._remove_header.setText(self._translator.text(Message.UI_POWERUPS_REMOVE_COLUMN))
        self._empty_hint.setText(self._translator.text(Message.UI_POWERUPS_EMPTY))
        self._add_button.setText(self._translator.text(Message.UI_POWERUPS_ADD))
        self._add_button.setToolTip(self._translator.text(Message.UI_POWERUPS_ADD_TOOLTIP))
        for row in self._rows:
            self._translate_row(row)
        self._render_empty_hint()

    def _translate_row(self, row: PowerUpRow) -> None:
        row.name_input.setPlaceholderText(
            self._translator.text(Message.UI_POWERUPS_NAME_PLACEHOLDER)
        )
        row.interval_spin.setSuffix(self._translator.text(Message.UI_POWERUPS_INTERVAL_SUFFIX))
        row.interval_spin.setToolTip(self._translator.text(Message.UI_POWERUPS_INTERVAL_TOOLTIP))
        row.key_combo.setToolTip(self._translator.text(Message.UI_POWERUPS_HOTKEY_TOOLTIP))
        row.enabled_check.setToolTip(self._translator.text(Message.UI_POWERUPS_ACTIVE_TOOLTIP))
        row.remove_button.setText(self._translator.text(Message.UI_POWERUPS_REMOVE))
        row.remove_button.setToolTip(self._translator.text(Message.UI_POWERUPS_REMOVE_TOOLTIP))


def _virtual_key_choice(virtual_key: int) -> str:
    """Return the choice label matching a virtual key, falling back to the default."""

    for choice in POWERUP_HOTKEY_CHOICES:
        if parse_virtual_key(choice) == virtual_key:
            return choice
    return DEFAULT_POWERUP_HOTKEY
