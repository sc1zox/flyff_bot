from __future__ import annotations

from pathlib import Path

from flyff_bot.features.quests.persistence import QuestDatabaseError, load_quest_database
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.quest_panel import QuestGoalPanel


class QuestDatabaseController:
    """Loads the extracted quest database without coupling it to window layout."""

    def __init__(self, panel: QuestGoalPanel, translator: Translator) -> None:
        self.panel = panel
        self.translator = translator

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.panel.set_translator(translator)

    def load(self, path: Path) -> None:
        if not path.is_file():
            self.panel.set_status_text(
                self.translator.text(Message.UI_QUEST_DATABASE_MISSING, path=path)
            )
            return
        try:
            database = load_quest_database(path)
        except QuestDatabaseError as error:
            self.panel.set_status_text(
                self.translator.text(Message.QUEST_EXTRACTION_FAILED, reason=error)
            )
            return
        self.panel.set_database(
            database,
            self.translator.text(
                Message.UI_QUEST_DATABASE_LOADED,
                count=len(database.quests),
                path=path,
            ),
        )
