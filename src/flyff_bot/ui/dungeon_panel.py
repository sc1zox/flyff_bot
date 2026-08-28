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

from flyff_bot.features.dungeons.models import (
    DungeonDefinition,
    DungeonStateSnapshot,
    DungeonStatus,
    format_cooldown,
)
from flyff_bot.i18n import Message, Translator

_STATUS_MESSAGES = {
    DungeonStatus.READY: Message.UI_DUNGEON_STATUS_READY,
    DungeonStatus.ON_COOLDOWN: Message.UI_DUNGEON_STATUS_ON_COOLDOWN,
    DungeonStatus.ENTRY_LIMIT_REACHED: Message.UI_DUNGEON_STATUS_ENTRY_LIMIT_REACHED,
    DungeonStatus.UNKNOWN: Message.UI_DUNGEON_STATUS_UNKNOWN,
}
# Placeholders for a field the client never declared and for an unbounded entry limit.
UNDECLARED_TEXT = "—"
UNLIMITED_TEXT = "∞"


class DungeonCooldownPanel(QGroupBox):
    """Render one immutable snapshot list without mutating domain objects.

    The panel keeps the extracted database and the live poll apart so its status line names
    the actual gap: no database on disk, a database declaring no dungeons, or a database
    whose rows cannot be enriched because the client is not connected (BUG-036).
    """

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._definitions: tuple[DungeonDefinition, ...] | None = None
        self._snapshots: tuple[DungeonStateSnapshot, ...] | None = None
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

    @property
    def status_text(self) -> str:
        """Expose the rendered status line for focused UI assertions."""

        return self._status_label.text()

    def set_translator(self, translator: Translator) -> None:
        """Retranslate every label, re-rendering the rows the current state describes."""

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
        self._render()

    def set_database(self, definitions: Sequence[DungeonDefinition] | None) -> None:
        """Bind the extracted dungeon database; ``None`` means none is readable on disk."""

        self._definitions = None if definitions is None else tuple(definitions)
        self._snapshots = None
        self._render()

    def set_snapshots(self, snapshots: Sequence[DungeonStateSnapshot] | None) -> None:
        """Replace all rows from one live-reader poll; ``None`` means no live state."""

        self._snapshots = None if snapshots is None else tuple(snapshots)
        self._render()

    def _render(self) -> None:
        rows, status = self._rows_and_status()
        self._table.setRowCount(0)
        for snapshot in rows:
            self._append_row(snapshot)
        self._render_status(status)

    def _rows_and_status(self) -> tuple[tuple[DungeonStateSnapshot, ...], Message | None]:
        if self._snapshots is not None:
            return self._snapshots, None
        if self._definitions is None:
            return (), Message.UI_DUNGEON_UNAVAILABLE
        if not self._definitions:
            return (), Message.UI_DUNGEON_DATABASE_EMPTY
        extracted = tuple(DungeonStateSnapshot(definition) for definition in self._definitions)
        return extracted, Message.UI_DUNGEON_LIVE_UNAVAILABLE

    def _append_row(self, snapshot: DungeonStateSnapshot) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(snapshot.definition.name))
        self._table.setItem(row, 1, QTableWidgetItem(_level_text(snapshot.definition)))
        self._table.setItem(row, 2, QTableWidgetItem(self._status_text(snapshot)))
        tooltip = self._translator.text(
            Message.UI_DUNGEON_ENTRY_COUNT,
            used=snapshot.entries_used if snapshot.entries_used is not None else UNDECLARED_TEXT,
            limit=(
                snapshot.daily_entry_limit
                if snapshot.daily_entry_limit is not None
                else UNLIMITED_TEXT
            ),
        )
        item = QTableWidgetItem(format_cooldown(snapshot.remaining_cooldown_seconds))
        item.setToolTip(tooltip)
        self._table.setItem(row, 3, item)

    def _status_text(self, snapshot: DungeonStateSnapshot) -> str:
        text = self._translator.text(_STATUS_MESSAGES[snapshot.status])
        return f"{text} ({snapshot.diagnostic_code})" if snapshot.diagnostic_code else text

    def _render_status(self, message: Message | None) -> None:
        self._status_label.setText("" if message is None else self._translator.text(message))
        self._status_label.setVisible(message is not None)


def _level_text(definition: DungeonDefinition) -> str:
    if not definition.has_declared_level_range:
        return UNDECLARED_TEXT
    return f"{definition.minimum_level}-{definition.maximum_level}"
