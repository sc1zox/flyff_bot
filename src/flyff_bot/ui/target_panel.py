"""Monster selection table with per-monster kill quotas and live progress."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.automation.kill_goals import (
    UNLIMITED_KILL_QUOTA,
    KillGoalConfig,
    MobKillProgress,
    MobKillQuota,
)
from flyff_bot.i18n import Message, Translator

MAXIMUM_KILL_QUOTA = 9999
NAME_COLUMN_STRETCH = 2


@dataclass(frozen=True, slots=True)
class TargetRow:
    """The widgets backing one selectable monster class."""

    class_name: str
    container: QWidget
    name_label: QLabel
    enabled_check: QCheckBox
    quota_spin: QSpinBox
    progress_label: QLabel


class TargetSelectionPanel(QGroupBox):
    """Select any number of monster classes and the kills each one still owes."""

    selection_changed = Signal(object)

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardPanel")
        self._translator = translator
        self._rows: list[TargetRow] = []

        self._monster_header = QLabel()
        self._active_header = QLabel()
        self._quota_header = QLabel()
        self._progress_header = QLabel()
        self._empty_hint = QLabel()
        self._close_client_check = QCheckBox()

        header_row = QHBoxLayout()
        header_row.addWidget(self._monster_header, NAME_COLUMN_STRETCH)
        header_row.addWidget(self._active_header)
        header_row.addWidget(self._quota_header)
        header_row.addWidget(self._progress_header)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)

        panel_layout = QVBoxLayout()
        panel_layout.addLayout(header_row)
        panel_layout.addLayout(self._rows_layout)
        panel_layout.addWidget(self._empty_hint)
        panel_layout.addWidget(self._close_client_check)
        self.setLayout(panel_layout)

        self._close_client_check.toggled.connect(self._emit_selection_changed)
        self._retranslate()

    @property
    def rows(self) -> tuple[TargetRow, ...]:
        """Expose the monster rows for wiring and verification."""

        return tuple(self._rows)

    @property
    def close_client_check(self) -> QCheckBox:
        """Expose the optional shutdown toggle applied once every quota is reached."""

        return self._close_client_check

    def set_translator(self, translator: Translator) -> None:
        """Switch the displayed language without discarding the current selection."""

        self._translator = translator
        self._retranslate()

    def set_class_names(self, class_names: Sequence[str]) -> None:
        """Rebuild the table from the classes the active detection model reports.

        A selection made for a class the new model still knows is preserved, and
        repopulating never re-emits: the caller supplies the classes before the session
        is wired up.
        """

        previous = {
            row.class_name: (row.enabled_check.isChecked(), row.quota_spin.value())
            for row in self._rows
        }
        while self._rows:
            self._discard_row(self._rows[-1])
        for class_name in class_names:
            enabled, quota = previous.get(class_name, (False, UNLIMITED_KILL_QUOTA))
            self._append_row(class_name, enabled=enabled, required_kills=quota)
        self._render_empty_hint()

    def get_config(self) -> KillGoalConfig:
        """Return the monster selection and quotas currently defined by the table."""

        return KillGoalConfig(
            quotas=tuple(
                MobKillQuota(row.class_name, row.quota_spin.value())
                for row in self._rows
                if row.enabled_check.isChecked()
            ),
            close_client_on_completion=self._close_client_check.isChecked(),
        )

    def set_progress(self, progress: Sequence[MobKillProgress]) -> None:
        """Render the live kill counters published by the running session."""

        counters = {entry.class_name: entry for entry in progress}
        for row in self._rows:
            row.progress_label.setText(self._progress_text(counters.get(row.class_name)))

    def _progress_text(self, entry: MobKillProgress | None) -> str:
        if entry is None:
            return self._translator.text(Message.UI_TARGETS_PROGRESS_INACTIVE)
        if entry.is_unlimited:
            return self._translator.text(Message.UI_TARGETS_PROGRESS_UNLIMITED, current=entry.kills)
        return self._translator.text(
            Message.UI_TARGETS_PROGRESS_VALUE,
            current=entry.kills,
            required=entry.required_kills,
        )

    def _append_row(self, class_name: str, *, enabled: bool, required_kills: int) -> TargetRow:
        container = QWidget()
        name_label = QLabel(class_name)
        enabled_check = QCheckBox()
        enabled_check.setChecked(enabled)
        quota_spin = QSpinBox()
        quota_spin.setRange(UNLIMITED_KILL_QUOTA, MAXIMUM_KILL_QUOTA)
        quota_spin.setValue(required_kills)
        progress_label = QLabel()

        row_layout = QHBoxLayout(container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(name_label, NAME_COLUMN_STRETCH)
        row_layout.addWidget(enabled_check)
        row_layout.addWidget(quota_spin)
        row_layout.addWidget(progress_label)

        row = TargetRow(
            class_name=class_name,
            container=container,
            name_label=name_label,
            enabled_check=enabled_check,
            quota_spin=quota_spin,
            progress_label=progress_label,
        )
        self._rows.append(row)
        self._rows_layout.addWidget(container)
        self._translate_row(row)

        enabled_check.toggled.connect(self._emit_selection_changed)
        quota_spin.valueChanged.connect(self._emit_selection_changed)
        return row

    def _discard_row(self, row: TargetRow) -> None:
        self._rows.remove(row)
        self._rows_layout.removeWidget(row.container)
        row.container.setParent(None)
        row.container.deleteLater()

    @Slot()
    def _emit_selection_changed(self) -> None:
        self.selection_changed.emit(self.get_config())

    def _render_empty_hint(self) -> None:
        self._empty_hint.setVisible(not self._rows)

    def _retranslate(self) -> None:
        self.setTitle(self._translator.text(Message.UI_TARGETS_TITLE))
        self._monster_header.setText(self._translator.text(Message.UI_TARGETS_MONSTER))
        self._active_header.setText(self._translator.text(Message.UI_TARGETS_ACTIVE))
        self._quota_header.setText(self._translator.text(Message.UI_TARGETS_QUOTA))
        self._progress_header.setText(self._translator.text(Message.UI_TARGETS_PROGRESS))
        self._empty_hint.setText(self._translator.text(Message.UI_TARGETS_EMPTY))
        self._close_client_check.setText(self._translator.text(Message.UI_TARGETS_CLOSE_CLIENT))
        self._close_client_check.setToolTip(
            self._translator.text(Message.UI_TARGETS_CLOSE_CLIENT_TOOLTIP)
        )
        for row in self._rows:
            self._translate_row(row)
        self._render_empty_hint()

    def _translate_row(self, row: TargetRow) -> None:
        row.enabled_check.setToolTip(self._translator.text(Message.UI_TARGETS_ACTIVE_TOOLTIP))
        row.quota_spin.setToolTip(self._translator.text(Message.UI_TARGETS_QUOTA_TOOLTIP))
        row.quota_spin.setSpecialValueText(
            self._translator.text(Message.UI_TARGETS_QUOTA_UNLIMITED)
        )
        row.progress_label.setText(
            row.progress_label.text() or self._translator.text(Message.UI_TARGETS_PROGRESS_INACTIVE)
        )
