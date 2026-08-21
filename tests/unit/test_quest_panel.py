"""Tests for the quest goal browser panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from flyff_bot.features.quests.goals import QuestResolutionIssue
from flyff_bot.features.quests.models import (
    QuestCollection,
    QuestDatabase,
    QuestDefinition,
    QuestKillRequirement,
    QuestObjectiveProgress,
)
from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.quest_panel import QUEST_ID_ROLE, QuestGoalPanel


def _quest(
    quest_id: str,
    title: str,
    *,
    collection: QuestCollection = QuestCollection.GENERAL,
    group: str = "Flaris",
    monster: str = "Flame",
    minimum_level: int = 10,
    maximum_level: int = 20,
) -> QuestDefinition:
    return QuestDefinition(
        quest_id=quest_id,
        title=title,
        collection=collection,
        group=group,
        minimum_level=minimum_level,
        maximum_level=maximum_level,
        kill_requirements=(QuestKillRequirement(f"MI_{monster.upper()}", monster, 5),),
    )


def _database() -> QuestDatabase:
    return QuestDatabase(
        quests=(
            _quest("general:A", "Puppy Redemption"),
            _quest("general:B", "Bozman's Gems", group="Saintmorning", monster="Rapra"),
            _quest(
                "office:C",
                "Daily Hunt",
                collection=QuestCollection.OFFICE,
                minimum_level=60,
                maximum_level=80,
            ),
        ),
        language="English",
    )


def _panel() -> QuestGoalPanel:
    QApplication.instance() or QApplication([])
    panel = QuestGoalPanel(Translator(Language.ENGLISH))
    panel.set_database(_database())
    return panel


def test_panel_lists_every_farmable_quest_of_a_loaded_database() -> None:
    panel = _panel()

    assert panel.quest_list.count() == 3
    assert panel.quest_list.item(0).text().startswith("Puppy Redemption")


def test_panel_filters_by_free_text_search() -> None:
    panel = _panel()

    panel.search_edit.setText("rapra")

    assert [quest.quest_id for quest in panel.visible_quests()] == ["general:B"]


def test_panel_filters_by_category() -> None:
    panel = _panel()
    index = panel.collection_combo.findData(str(QuestCollection.OFFICE))
    panel.collection_combo.setCurrentIndex(index)

    assert [quest.quest_id for quest in panel.visible_quests()] == ["office:C"]


def test_panel_filters_by_character_level_and_ignores_the_disabled_bound() -> None:
    panel = _panel()

    panel.level_spin.setValue(65)
    assert [quest.quest_id for quest in panel.visible_quests()] == ["office:C"]

    panel.level_spin.setValue(0)
    assert len(panel.visible_quests()) == 3


def test_panel_queues_quests_in_the_order_they_were_checked() -> None:
    panel = _panel()
    emitted: list[object] = []
    panel.selection_changed.connect(emitted.append)

    panel.quest_list.item(1).setCheckState(Qt.CheckState.Checked)
    panel.quest_list.item(0).setCheckState(Qt.CheckState.Checked)

    assert panel.selected_quest_ids == ("general:B", "general:A")
    assert [quest.quest_id for quest in panel.selected_quests()] == ["general:B", "general:A"]
    assert len(emitted) == 2


def test_panel_unchecking_a_quest_removes_it_from_the_queue() -> None:
    panel = _panel()
    panel.quest_list.item(0).setCheckState(Qt.CheckState.Checked)

    panel.quest_list.item(0).setCheckState(Qt.CheckState.Unchecked)

    assert panel.selected_quest_ids == ()


def test_panel_clear_selection_empties_the_queue_and_reports_it() -> None:
    panel = _panel()
    emitted: list[object] = []
    panel.quest_list.item(0).setCheckState(Qt.CheckState.Checked)
    panel.selection_changed.connect(emitted.append)

    panel._clear_selection()

    assert panel.selected_quest_ids == ()
    assert emitted == [()]


def test_panel_keeps_a_selection_that_survives_a_reloaded_database() -> None:
    panel = _panel()
    panel.quest_list.item(0).setCheckState(Qt.CheckState.Checked)

    panel.set_database(QuestDatabase(quests=(_quest("general:A", "Puppy Redemption"),)))

    assert panel.selected_quest_ids == ("general:A",)
    assert panel.quest_list.item(0).data(QUEST_ID_ROLE) == "general:A"
    assert panel.quest_list.item(0).checkState() is Qt.CheckState.Checked


def test_panel_drops_a_selection_the_new_database_no_longer_holds() -> None:
    panel = _panel()
    panel.quest_list.item(0).setCheckState(Qt.CheckState.Checked)

    panel.set_database(QuestDatabase(quests=(_quest("general:Z", "Other"),)))

    assert panel.selected_quest_ids == ()


def test_panel_renders_active_quest_progress_and_completion() -> None:
    panel = _panel()

    panel.set_progress("Puppy Redemption", (QuestObjectiveProgress("Flame", 2, 5),), False)
    assert panel._active_label.text() == "Active quest: Puppy Redemption"
    assert panel._progress_label.text() == "Flame: 2/5"

    panel.set_progress("", (), True)
    assert panel._active_label.text() == "All queued quests are complete."
    assert panel._progress_label.text() == ""


def test_panel_reports_a_resolution_issue_in_the_active_language() -> None:
    panel = _panel()

    english = panel.issue_text(QuestResolutionIssue.NO_SPAWN_ZONE, "Daily Hunt", "Flame")
    panel.set_translator(Translator(Language.GERMAN))
    german = panel.issue_text(QuestResolutionIssue.NO_SPAWN_ZONE, "Daily Hunt", "Flame")

    assert "no spawn zone" in english
    assert "Spawn-Zone" in german
    assert english != german


def test_panel_status_line_is_hidden_until_there_is_something_to_say() -> None:
    panel = _panel()

    assert not panel._status_label.isVisible()

    panel.set_status_text("No quest database found.")
    assert panel._status_label.text() == "No quest database found."
