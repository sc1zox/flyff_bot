"""Minimal localized desktop presentation for automation state."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow

from flyff_bot.features.automation.models import WorldState
from flyff_bot.i18n import Message, Translator


class MainWindow(QMainWindow):
    """Present the latest simulated or observed world-state summary."""

    def __init__(self, translator: Translator) -> None:
        super().__init__()
        self._translator = translator
        self.setWindowTitle(translator.text(Message.UI_TITLE))
        self._status_label = QLabel()
        self.setCentralWidget(self._status_label)
        self.set_status(mob_count=0)

    def set_status(self, mob_count: int) -> None:
        """Show one localized summary from a state feed."""

        self._status_label.setText(
            self._translator.text(Message.UI_WORLD_STATUS, mob_count=mob_count)
        )

    def update_state(self, state: WorldState) -> None:
        """Update the presentation from an immutable world-state snapshot."""

        self.set_status(state.nearby_mob_count)
