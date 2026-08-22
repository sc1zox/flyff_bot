"""Localized dashboard panel for extracted dungeons and live cooldown state."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.dungeons.models import DungeonStateSnapshot, DungeonStatus, format_cooldown
from flyff_bot.i18n import Message, Translator

_STATUS_MESSAGES = {
    DungeonStatus.READY: Message.UI_DUNGEON_STATUS_READY,
    DungeonStatus.ON_COOLDOWN: Message.UI_DUNGEON_STATUS_ON_COOLDOWN,
    DungeonStatus.ENTRY_LIMIT_REACHED: Message.UI_DUNGEON_STATUS_ENTRY_LIMIT_REACHED,
    DungeonStatus.UNKNOWN: Message.UI_DUNGEON_STATUS_UNKNOWN,
}


class DungeonCooldownPanel(QGroupBox):
    """Render one immutable snapshot list without mutating domain objects."""

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._table = QTableWidget(0, 4, self)
        self._table.setObjectName("DungeonCooldownTable")
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._status_label = QLabel()
        self._status_label.setObjectName("StatChip")
        status_layout = QHBoxLayout()
        status_layout.addWidget(self._status_label)
        status_layout.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(status_layout)
        self.set_translator(translator)

    @property
    def table(self) -> QTableWidget:
        """Expose the row renderer for focused UI assertions."""

        return self._table

    def set_translator(self, translator: Translator) -> None:
        """Retranslate every stable label while preserving the current rows."""

        self._translator = translator
        self.setTitle(translator.text(Message.UI_DUNGEON_PANEL_TITLE))
        for column, message in enumerate(
            (
                Message.UI_DUNGEON_COLUMN_NAME,
                Message.UI_DUNGEON_COLUMN_LEVEL,
                Message.UI_DUNGEON_COLUMN_STATUS,
                Message.UI_DUNGEON_COLUMN_COOLDOWN,
            )
        ):
            self._table.setHorizontalHeaderItem(column, QTableWidgetItem(translator.text(message)))
        if not self._table.rowCount():
            self._render_status(Message.UI_DUNGEON_UNAVAILABLE)

    def set_snapshots(self, snapshots: Sequence[DungeonStateSnapshot] | None) -> None:
        """Replace all rows from one live-reader poll or extraction-only state."""

        self._table.setRowCount(0)
        if snapshots is None:
            self._render_status(Message.UI_DUNGEON_UNAVAILABLE)
            return
        for snapshot in snapshots:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(snapshot.definition.name))
            self._table.setItem(
                row,
                1,
                QTableWidgetItem(
                    f"{snapshot.definition.minimum_level}-{snapshot.definition.maximum_level}"
                ),
            )
            self._table.setItem(row, 2, QTableWidgetItem(self._status_text(snapshot)))
            cooldown = format_cooldown(snapshot.remaining_cooldown_seconds)
            tooltip = self._translator.text(
                Message.UI_DUNGEON_ENTRY_COUNT,
                used=snapshot.entries_used if snapshot.entries_used is not None else "—",
                limit=snapshot.daily_entry_limit if snapshot.daily_entry_limit is not None else "∞",
            )
            item = QTableWidgetItem(cooldown)
            item.setToolTip(tooltip)
            self._table.setItem(row, 3, item)
        self._render_status(None)

    def _status_text(self, snapshot: DungeonStateSnapshot) -> str:
        text = self._translator.text(_STATUS_MESSAGES[snapshot.status])
        return f"{text} ({snapshot.diagnostic_code})" if snapshot.diagnostic_code else text

    def _render_status(self, message: Message | None) -> None:
        self._status_label.setText("" if message is None else self._translator.text(message))
        self._status_label.setVisible(message is not None)
