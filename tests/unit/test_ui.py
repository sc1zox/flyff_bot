"""Smoke tests for the localized Qt presentation."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.main_window import MainWindow


def test_main_window_displays_localized_world_status() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.set_status(3)

    status = window.centralWidget()
    assert isinstance(status, QLabel)
    assert application is not None
    assert window.windowTitle() == "Flyff Bot"
    assert status.text() == "Visible mobs: 3"
