from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import NavigationSnapshot
from flyff_bot.ui.navigation_window import NavigationMapWindow
from flyff_bot.ui.path_inspector import PathInspectorWidget


class NavigationSection(QWidget):
    """Dockable navigation inspector and world-data entry point."""

    def __init__(self, translator: Translator) -> None:
        super().__init__()
        self.translator = translator
        self.inspector = PathInspectorWidget(translator)
        self.map_window = NavigationMapWindow(translator)
        self.world_data_button = QPushButton()
        self.popout_button = QPushButton()
        self.map_container = QWidget()
        self.map_layout = QVBoxLayout(self.map_container)
        self.is_popped_out = False

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(self.world_data_button)
        controls_layout.addWidget(self.popout_button)
        controls_layout.addStretch()

        self.map_layout.setContentsMargins(0, 0, 0, 0)
        self.map_layout.addWidget(self.inspector)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(controls)
        layout.addWidget(self.map_container)

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.inspector.set_translator(translator)
        self.map_window.set_translator(translator)
        self._update_popout_text()

    def render_navigation(self, navigation: NavigationSnapshot | None) -> None:
        self.inspector.set_navigation(navigation)

    def toggle_popout(self) -> None:
        if self.is_popped_out:
            self.dock()
        else:
            self.popout()

    def popout(self) -> None:
        item = self.map_layout.takeAt(0)
        if item is not None and isinstance(item.widget(), PathInspectorWidget):
            self.map_window.set_inspector(self.inspector)
            self.map_window.show()
            self.is_popped_out = True
            self._update_popout_text()

    def dock(self) -> None:
        inspector = self.map_window.take_inspector()
        if inspector is not None:
            self.map_layout.addWidget(inspector)
            self.map_window.hide()
            self.is_popped_out = False
            self._update_popout_text()

    def _update_popout_text(self) -> None:
        message = Message.UI_DOCK_MAP if self.is_popped_out else Message.UI_POPOUT_MAP
        self.popout_button.setText(self.translator.text(message))
