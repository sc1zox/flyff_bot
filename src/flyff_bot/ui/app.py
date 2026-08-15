"""Qt application entry point kept separate from the command-line adapter."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from flyff_bot.i18n import Translator
from flyff_bot.ui.dashboard import DashboardFeed
from flyff_bot.ui.main_window import MainWindow


def run_desktop(arguments: Sequence[str] | None = None) -> int:
    """Launch the native desktop window and return Qt's exit code."""

    application = QApplication(list(arguments or sys.argv))
    window = MainWindow(Translator.from_environment())
    feed = DashboardFeed(window)
    feed.update_available.connect(window.update_dashboard)
    window.show()
    return application.exec()
