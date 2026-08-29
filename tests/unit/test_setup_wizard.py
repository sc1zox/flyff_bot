"""Qt integration coverage for manual setup wizard entry points."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.main_window import MainWindow
from flyff_bot.ui.setup_wizard import SetupWizard


def test_main_window_opens_manual_setup_wizard(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    window = MainWindow(Translator(Language.ENGLISH))

    assert window.menuBar().actions()
    assert window._setup_action.text() == "Initial Setup"
    window.show_setup_wizard()

    wizard = window._setup_wizard
    assert isinstance(wizard, SetupWizard)
    wizard.close()


def test_setup_wizard_rejects_missing_client_structure(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    wizard = SetupWizard(
        Translator(Language.ENGLISH),
        client_world_root=tmp_path / "Data" / "World",
        world_map_directory=tmp_path / "worlds",
    )
    wizard.path_edit.setText(str(tmp_path / "missing"))

    wizard.start_button.click()

    assert "Select the Entropia folder" in wizard._status_label.text()
    assert not wizard.is_running
    wizard.close()


def test_setup_wizard_exposes_a_localized_force_reextraction_toggle() -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    wizard = SetupWizard(
        Translator(Language.GERMAN),
        client_world_root=Path("client") / "Data" / "World",
        world_map_directory=Path("worlds"),
    )

    assert not wizard.force_checkbox.isChecked()
    assert wizard.force_checkbox.text() == Translator(Language.GERMAN).text(
        Message.UI_SETUP_FORCE_REEXTRACT
    )

    wizard.set_translator(Translator(Language.ENGLISH))
    assert wizard.force_checkbox.text() == "Force re-extraction"
    wizard.close()
