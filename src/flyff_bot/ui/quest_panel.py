"""Searchable quest browser that queues extracted client quests as farming goals."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.quests.goals import QuestResolutionIssue
from flyff_bot.features.quests.models import (
    UNBOUNDED_LEVEL,
    QuestCollection,
    QuestDatabase,
    QuestDefinition,
    QuestObjectiveProgress,
)
from flyff_bot.i18n import Message, Translator

# The level filter is inclusive of both bounds and disabled at its minimum.
MINIMUM_CHARACTER_LEVEL = 0
MAXIMUM_CHARACTER_LEVEL = 999
# The list is rebuilt on every keystroke, so it is bounded to keep the Qt event loop
# responsive. The bound sits above the farmable quest count of the shipped client, so it
# only ever truncates a database far larger than that; the match counter states when it did.
MAXIMUM_RENDERED_QUESTS = 1000
# Selection round-trips through the item's user data rather than its displayed label.
QUEST_ID_ROLE = int(Qt.ItemDataRole.UserRole)

COLLECTION_LABELS = {
    QuestCollection.GENERAL: Message.UI_QUEST_COLLECTION_GENERAL,
    QuestCollection.SCENARIO: Message.UI_QUEST_COLLECTION_SCENARIO,
    QuestCollection.OFFICE: Message.UI_QUEST_COLLECTION_OFFICE,
    QuestCollection.DUNGEON: Message.UI_QUEST_COLLECTION_DUNGEON,
}
ISSUE_MESSAGES = {
    QuestResolutionIssue.NO_FARMABLE_OBJECTIVE: Message.UI_QUEST_ISSUE_NO_OBJECTIVE,
    QuestResolutionIssue.NO_WORLD_MAP: Message.UI_QUEST_ISSUE_NO_WORLD_MAP,
    QuestResolutionIssue.NO_SPAWN_ZONE: Message.UI_QUEST_ISSUE_NO_SPAWN_ZONE,
}


class QuestGoalPanel(QGroupBox):
    """Browse the extracted quest database and queue quests as farming goals.

    The panel owns presentation only: it filters the loaded database, keeps the operator's
    ordered selection, and renders the progress a running session publishes. Resolving a
    quest to spawn zones and steering a session are someone else's job.
    """

    selection_changed = Signal(object)

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardPanel")
        self._translator = translator
        self._database = QuestDatabase()
        self._selected_ids: list[str] = []
        self._status_text = ""

        self._search_edit = QLineEdit()
        self._collection_combo = QComboBox()
        self._group_combo = QComboBox()
        self._level_label = QLabel()
        self._level_spin = QSpinBox()
        self._level_spin.setRange(MINIMUM_CHARACTER_LEVEL, MAXIMUM_CHARACTER_LEVEL)
        self._quest_list = QListWidget()
        self._quest_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._clear_button = QPushButton()
        self._match_label = QLabel()
        self._selected_label = QLabel()
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._active_label = QLabel()
        self._progress_label = QLabel()
        self._progress_label.setWordWrap(True)

        filter_row = QHBoxLayout()
        filter_row.addWidget(self._search_edit, 2)
        filter_row.addWidget(self._collection_combo)
        filter_row.addWidget(self._group_combo)
        filter_row.addWidget(self._level_label)
        filter_row.addWidget(self._level_spin)

        footer_row = QHBoxLayout()
        footer_row.addWidget(self._match_label)
        footer_row.addWidget(self._selected_label)
        footer_row.addWidget(self._clear_button)

        panel_layout = QVBoxLayout()
        panel_layout.addLayout(filter_row)
        panel_layout.addWidget(self._quest_list)
        panel_layout.addLayout(footer_row)
        panel_layout.addWidget(self._status_label)
        panel_layout.addWidget(self._active_label)
        panel_layout.addWidget(self._progress_label)
        self.setLayout(panel_layout)

        self._search_edit.textChanged.connect(self._render_quests)
        self._collection_combo.currentIndexChanged.connect(self._render_quests)
        self._group_combo.currentIndexChanged.connect(self._render_quests)
        self._level_spin.valueChanged.connect(self._render_quests)
        self._quest_list.itemChanged.connect(self._on_item_changed)
        self._clear_button.clicked.connect(self._clear_selection)
        self._retranslate()

    @property
    def quest_list(self) -> QListWidget:
        """Expose the quest list for wiring and verification."""

        return self._quest_list

    @property
    def search_edit(self) -> QLineEdit:
        """Expose the free-text search field for wiring and verification."""

        return self._search_edit

    @property
    def level_spin(self) -> QSpinBox:
        """Expose the character-level filter for wiring and verification."""

        return self._level_spin

    @property
    def collection_combo(self) -> QComboBox:
        """Expose the category filter for wiring and verification."""

        return self._collection_combo

    @property
    def database(self) -> QuestDatabase:
        """Return the quest database this panel is browsing."""

        return self._database

    @property
    def selected_quest_ids(self) -> tuple[str, ...]:
        """Return the queued quest identifiers, in the order they were selected."""

        return tuple(self._selected_ids)

    def selected_quests(self) -> tuple[QuestDefinition, ...]:
        """Return the queued quests in selection order."""

        return self._database.select(self._selected_ids)

    def set_translator(self, translator: Translator) -> None:
        """Switch the displayed language without discarding the current selection."""

        self._translator = translator
        self._retranslate()

    def set_database(self, database: QuestDatabase, status_text: str = "") -> None:
        """Adopt an extracted quest database and rebuild the filters around it."""

        self._database = database
        self._selected_ids = [
            quest_id for quest_id in self._selected_ids if database.get(quest_id) is not None
        ]
        self._status_text = status_text
        self._rebuild_group_filter()
        self._render_quests()
        self._render_status()

    def set_status_text(self, text: str) -> None:
        """Render one diagnostic line under the quest list."""

        self._status_text = text
        self._render_status()

    def set_progress(
        self, active_title: str, progress: Sequence[QuestObjectiveProgress], completed: bool
    ) -> None:
        """Render the active quest and its objective counters for a running session."""

        if completed:
            self._active_label.setText(self._translator.text(Message.UI_QUEST_QUEUE_COMPLETED))
            self._progress_label.setText("")
            return
        self._active_label.setText(
            self._translator.text(Message.UI_QUEST_ACTIVE, title=active_title)
            if active_title
            else ""
        )
        self._progress_label.setText(
            "  ".join(
                self._translator.text(
                    Message.UI_QUEST_PROGRESS,
                    monster=entry.monster_name,
                    kills=entry.kills,
                    required=entry.required_kills,
                )
                for entry in progress
            )
        )

    def issue_text(self, issue: QuestResolutionIssue, title: str, monsters: str) -> str:
        """Return the localized diagnostic for one unfarmable quest resolution."""

        return self._translator.text(ISSUE_MESSAGES[issue], title=title, monsters=monsters)

    def visible_quests(self) -> tuple[QuestDefinition, ...]:
        """Return the quests the current filters select, in database order."""

        query = self._search_edit.text()
        # Qt hands enum item data back as its plain string value, so the filter compares
        # the collection by value rather than by identity.
        collection = self._collection_combo.currentData()
        collection = None if collection is None else str(collection)
        group = self._group_combo.currentData()
        level = self._level_spin.value()
        matches: list[QuestDefinition] = []
        for quest in self._database.farmable:
            if collection is not None and str(quest.collection) != collection:
                continue
            if group is not None and quest.group != group:
                continue
            if not _matches_level(quest, level):
                continue
            if not quest.matches(query):
                continue
            matches.append(quest)
        return tuple(matches)

    @Slot()
    def _render_quests(self) -> None:
        matches = self.visible_quests()
        rendered = matches[:MAXIMUM_RENDERED_QUESTS]
        self._quest_list.blockSignals(True)
        self._quest_list.clear()
        for quest in rendered:
            item = QListWidgetItem(self._quest_label(quest))
            item.setData(QUEST_ID_ROLE, quest.quest_id)
            item.setToolTip(
                self._translator.text(
                    Message.UI_QUEST_ENTRY_TOOLTIP,
                    identifier=quest.quest_id,
                    group=quest.group,
                    objective=quest.objective or quest.description,
                )
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if quest.quest_id in self._selected_ids
                else Qt.CheckState.Unchecked
            )
            self._quest_list.addItem(item)
        self._quest_list.blockSignals(False)
        self._match_label.setText(
            self._translator.text(
                Message.UI_QUEST_MATCH_COUNT,
                count=len(rendered),
                total=len(self._database.farmable),
            )
        )
        self._render_selection_count()

    @Slot(QListWidgetItem)
    def _on_item_changed(self, item: QListWidgetItem) -> None:
        quest_id = str(item.data(QUEST_ID_ROLE) or "")
        if not quest_id:
            return
        checked = item.checkState() is Qt.CheckState.Checked
        if checked and quest_id not in self._selected_ids:
            self._selected_ids.append(quest_id)
        elif not checked and quest_id in self._selected_ids:
            self._selected_ids.remove(quest_id)
        else:
            return
        self._render_selection_count()
        self.selection_changed.emit(self.selected_quests())

    @Slot()
    def _clear_selection(self) -> None:
        if not self._selected_ids:
            return
        self._selected_ids.clear()
        self._render_quests()
        self.selection_changed.emit(())

    def _render_selection_count(self) -> None:
        self._selected_label.setText(
            self._translator.text(Message.UI_QUEST_SELECTED_COUNT, count=len(self._selected_ids))
        )

    def _render_status(self) -> None:
        self._status_label.setText(self._status_text)
        self._status_label.setVisible(bool(self._status_text))

    def _quest_label(self, quest: QuestDefinition) -> str:
        return self._translator.text(
            Message.UI_QUEST_ENTRY,
            title=quest.display_title,
            levels=_level_range(quest),
            monsters=", ".join(quest.monster_names()),
        )

    def _rebuild_group_filter(self) -> None:
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        self._group_combo.addItem(self._translator.text(Message.UI_QUEST_FILTER_ALL), None)
        for group in self._database.groups:
            self._group_combo.addItem(group, group)
        self._group_combo.blockSignals(False)

    def _rebuild_collection_filter(self) -> None:
        previous = self._collection_combo.currentData()
        self._collection_combo.blockSignals(True)
        self._collection_combo.clear()
        self._collection_combo.addItem(self._translator.text(Message.UI_QUEST_FILTER_ALL), None)
        for collection, message in COLLECTION_LABELS.items():
            self._collection_combo.addItem(self._translator.text(message), str(collection))
        index = self._collection_combo.findData(previous)
        self._collection_combo.setCurrentIndex(max(0, index))
        self._collection_combo.blockSignals(False)

    def _retranslate(self) -> None:
        self.setTitle(self._translator.text(Message.UI_QUEST_PANEL_TITLE))
        self._search_edit.setPlaceholderText(
            self._translator.text(Message.UI_QUEST_SEARCH_PLACEHOLDER)
        )
        self._level_label.setText(self._translator.text(Message.UI_QUEST_FILTER_LEVEL))
        self._clear_button.setText(self._translator.text(Message.UI_QUEST_CLEAR_SELECTION))
        self._collection_combo.setToolTip(self._translator.text(Message.UI_QUEST_FILTER_COLLECTION))
        self._group_combo.setToolTip(self._translator.text(Message.UI_QUEST_FILTER_GROUP))
        self._rebuild_collection_filter()
        self._rebuild_group_filter()
        self._render_quests()
        self._render_status()


def _level_range(quest: QuestDefinition) -> str:
    if quest.minimum_level == UNBOUNDED_LEVEL and quest.maximum_level == UNBOUNDED_LEVEL:
        return "-"
    return f"{quest.minimum_level}-{quest.maximum_level}"


def _matches_level(quest: QuestDefinition, level: int) -> bool:
    """Return whether a character level falls inside a quest's begin-level window."""

    if level == MINIMUM_CHARACTER_LEVEL:
        return True
    if quest.minimum_level != UNBOUNDED_LEVEL and level < quest.minimum_level:
        return False
    return not (quest.maximum_level != UNBOUNDED_LEVEL and level > quest.maximum_level)
