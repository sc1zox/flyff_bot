"""Localized runtime-mode UI wiring coverage for US-067."""

from pathlib import Path

from PySide6.QtWidgets import QApplication

from flyff_bot.features.policy.models import PolicyRuntimeMode
from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.main_window import MainWindow


def test_runtime_mode_selector_is_wired_and_localized(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(Translator(Language.ENGLISH))
    window.show()
    del tmp_path
    values: list[object] = []
    window.policy_mode_changed.connect(values.append)

    assert PolicyRuntimeMode(window.policy_mode_selector.currentData()) is (
        PolicyRuntimeMode.HEURISTIC
    )
    window.policy_mode_changed.emit(PolicyRuntimeMode.ML_SHADOW)
    window.policy_mode_selector.setCurrentIndex(-1)
    application.processEvents()
    window.policy_mode_selector.setCurrentIndex(
        list(PolicyRuntimeMode).index(PolicyRuntimeMode.ML_SHADOW)
    )
    application.processEvents()

    assert values[-1] == PolicyRuntimeMode.ML_SHADOW
    assert window.policy_mode_selector.itemText(0) == "Heuristic"
