from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QPushButton, QWidget

from flyff_bot.features.navigation.test_navigation import NavigationTestRequest
from flyff_bot.i18n import Translator
from flyff_bot.ui.main_window_parts.navigation import NavigationSection
from flyff_bot.ui.world_data_dialog import WorldDataDialog


class NavigationController:
    """Coordinate the navigation section and its lazily created world-data dialog."""

    def __init__(
        self,
        *,
        translator: Translator,
        navigation: NavigationSection,
        parent_window: QWidget,
        world_root: Path,
        map_dir: Path,
        monster_names_path: Path,
    ) -> None:
        self.translator = translator
        self.navigation = navigation
        self.dialog = WorldDataDialog(
            translator,
            world_root,
            map_dir,
            monster_names_path=monster_names_path,
            parent=parent_window,
        )
        self.dialog.world_map_changed.connect(self.navigation.inspector.set_world_data)
        self.navigation.inspector.zone_selected.connect(self.dialog.activate_zone)
        self.navigation.inspector.set_world_data(
            self.dialog.loaded_map,
            self.dialog.loaded_navmesh,
        )

    def connect_test_navigation(self, callback: Callable[[NavigationTestRequest], None]) -> None:
        """Forward the map's typed test-navigation request to the main window facade."""

        self.navigation.inspector.test_navigation_requested.connect(callback)

    @property
    def world_data_button(self) -> QPushButton:
        return self.navigation.world_data_button

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.dialog.set_translator(translator)

    def show_world_data(self) -> None:
        self.dialog.refresh()
        self.dialog.show()
        self.dialog.raise_()

    def close(self) -> None:
        self.dialog.close()
