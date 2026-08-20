"""Operator dialog for extracting client world data and arming vector navigation (US-045, US-059).

Extraction reads a whole region directory and decodes megabytes of terrain, which is far too
slow for the Qt event loop, so it runs on a dedicated worker thread and reaches the widgets
only through this dialog's signals.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.navigation.vector_navigation import (
    VectorNavigationRequest,
    ZoneGoal,
)
from flyff_bot.features.navigation.world_extractor import (
    ExtractionDiagnostic,
    VectorSpawnZone,
    WorldExtractionSummary,
    WorldVectorMap,
    discover_world_directories,
    extract_world,
    load_monster_names,
    load_world_map,
    save_world_map,
    summarize,
)
from flyff_bot.i18n import Message, Translator

# A quota of zero is the unlimited case, which is what a session without quest goals wants.
UNLIMITED_KILL_QUOTA = 0
MAXIMUM_KILL_QUOTA = 9999
# The unrestricted monster selection shares the dashboard's empty-class-name convention.
ALL_TARGET_MOBS = ""

_EXTRACTION_THREAD_NAME = "flyff-bot-world-extraction"
_SETTINGS_ORGANIZATION = "FlyffBot"
_SETTINGS_APPLICATION = "WorldDataDialog"
_REGION_SETTING = "selected_region"
_MAP_SETTING = "selected_map"
_ZONE_SETTING = "selected_zone"
_QUOTA_SETTING = "kill_quota"


class WorldExtractionWorker(QObject):
    """Run one region extraction off the GUI thread and report the outcome by signal."""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        output_directory: Path,
        monster_names_path: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._output_directory = output_directory
        self._monster_names_path = monster_names_path
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Return whether an extraction is currently in flight."""

        return self._thread is not None and self._thread.is_alive()

    def start(self, world_directory: Path) -> bool:
        """Begin extracting one region; refuse while another extraction is still running."""

        if self.is_running:
            return False
        self._thread = threading.Thread(
            target=self._run,
            args=(world_directory,),
            name=_EXTRACTION_THREAD_NAME,
            daemon=True,
        )
        self._thread.start()
        return True

    def join(self, timeout_seconds: float | None = None) -> None:
        """Wait for a running extraction to finish, which keeps teardown deterministic."""

        thread = self._thread
        if thread is not None:
            thread.join(timeout_seconds)

    def _run(self, world_directory: Path) -> None:
        try:
            names = (
                load_monster_names(self._monster_names_path)
                if self._monster_names_path is not None and self._monster_names_path.is_file()
                else {}
            )
            diagnostics: list[ExtractionDiagnostic] = []
            world_map = extract_world(world_directory, monster_names=names, diagnostics=diagnostics)
            output_path = save_world_map(world_map, self._output_directory)
        except (OSError, ValueError) as error:
            self.failed.emit(str(error))
            return
        self.completed.emit(summarize(world_map, output_path, diagnostics))


class WorldDataDialog(QDialog):
    """Browse client regions, extract their vector data, and arm goal-driven navigation."""

    vector_navigation_requested = Signal(object)
    vector_navigation_cleared = Signal()

    def __init__(
        self,
        translator: Translator,
        client_world_root: Path,
        world_map_directory: Path,
        *,
        monster_names_path: Path | None = None,
        parent: QWidget | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator
        self._client_world_root = client_world_root
        self._world_map_directory = world_map_directory
        self._loaded_map: WorldVectorMap | None = None
        self._target_mob = ALL_TARGET_MOBS
        self._settings = settings or QSettings(_SETTINGS_ORGANIZATION, _SETTINGS_APPLICATION)

        self._region_selector = QComboBox()
        self._extract_button = QPushButton()
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._map_selector = QComboBox()
        self._zone_selector = QComboBox()
        self._quota_spin = QSpinBox()
        self._quota_spin.setRange(UNLIMITED_KILL_QUOTA, MAXIMUM_KILL_QUOTA)
        self._quota_spin.setValue(self._saved_quota())
        self._activate_button = QPushButton()
        self._deactivate_button = QPushButton()
        self._close_button = QPushButton()

        self._region_label = QLabel()
        self._map_label = QLabel()
        self._zone_label = QLabel()
        self._quota_label = QLabel()

        self._worker = WorldExtractionWorker(world_map_directory, monster_names_path, self)
        self._worker.completed.connect(self._on_extraction_completed)
        self._worker.failed.connect(self._on_extraction_failed)

        self._build_layout()
        self._connect_controls()
        self._retranslate()
        self.refresh()

    @property
    def region_selector(self) -> QComboBox:
        """Expose the client-region selector for testing."""

        return self._region_selector

    @property
    def map_selector(self) -> QComboBox:
        """Expose the extracted-map selector for testing."""

        return self._map_selector

    @property
    def zone_selector(self) -> QComboBox:
        """Expose the standing-zone selector for testing."""

        return self._zone_selector

    @property
    def extract_button(self) -> QPushButton:
        """Expose the extraction trigger for testing."""

        return self._extract_button

    @property
    def activate_button(self) -> QPushButton:
        """Expose the activation button for testing."""

        return self._activate_button

    @property
    def deactivate_button(self) -> QPushButton:
        """Expose the deactivation button for testing."""

        return self._deactivate_button

    @property
    def quota_spin(self) -> QSpinBox:
        """Expose the per-monster kill quota input for testing."""

        return self._quota_spin

    @property
    def status_label(self) -> QLabel:
        """Expose the progress and result line for testing."""

        return self._status_label

    @property
    def loaded_map(self) -> WorldVectorMap | None:
        """Return the extracted map currently selected, if one could be read."""

        return self._loaded_map

    def set_target_mob(self, class_name: str) -> None:
        """Follow the dashboard's monster selection, which decides the farming goals."""

        self._target_mob = class_name

    def set_translator(self, translator: Translator) -> None:
        """Adopt a new locale and re-render every label and list entry."""

        self._translator = translator
        self._retranslate()
        self.refresh()

    def refresh(self) -> None:
        """Re-scan client regions and already extracted maps."""

        self._refresh_regions()
        self._refresh_maps()
        self._persist_state()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Wait for a running extraction so no worker outlives the dialog."""

        self._persist_state()
        self._worker.join()
        super().closeEvent(event)

    def _build_layout(self) -> None:
        grid = QGridLayout()
        grid.addWidget(self._region_label, 0, 0)
        grid.addWidget(self._region_selector, 0, 1)
        grid.addWidget(self._extract_button, 0, 2)
        grid.addWidget(self._map_label, 1, 0)
        grid.addWidget(self._map_selector, 1, 1, 1, 2)
        grid.addWidget(self._zone_label, 2, 0)
        grid.addWidget(self._zone_selector, 2, 1, 1, 2)
        grid.addWidget(self._quota_label, 3, 0)
        grid.addWidget(self._quota_spin, 3, 1, 1, 2)

        actions = QHBoxLayout()
        actions.addWidget(self._activate_button)
        actions.addWidget(self._deactivate_button)
        actions.addStretch()
        actions.addWidget(self._close_button)

        layout = QVBoxLayout()
        layout.addLayout(grid)
        layout.addWidget(self._status_label)
        layout.addLayout(actions)
        self.setLayout(layout)

    def _connect_controls(self) -> None:
        self._extract_button.clicked.connect(self._on_extract_clicked)
        self._map_selector.currentIndexChanged.connect(self._on_map_selected)
        self._region_selector.currentIndexChanged.connect(self._persist_state)
        self._map_selector.currentIndexChanged.connect(self._persist_state)
        self._zone_selector.currentIndexChanged.connect(self._persist_state)
        self._quota_spin.valueChanged.connect(self._persist_state)
        self._activate_button.clicked.connect(self._on_activate_clicked)
        self._deactivate_button.clicked.connect(self._on_deactivate_clicked)
        self._close_button.clicked.connect(self.close)

    def _refresh_regions(self) -> None:
        selected = self._region_selector.currentText() or self._saved_text(_REGION_SETTING)
        self._region_selector.blockSignals(True)
        self._region_selector.clear()
        for directory in discover_world_directories(self._client_world_root):
            self._region_selector.addItem(directory.name, directory)
        index = self._region_selector.findText(selected)
        if index >= 0:
            self._region_selector.setCurrentIndex(index)
        self._region_selector.blockSignals(False)
        has_regions = self._region_selector.count() > 0
        self._extract_button.setEnabled(has_regions)
        if not has_regions:
            self._status_label.setText(
                self._translator.text(
                    Message.UI_WORLD_DATA_NO_REGIONS, path=str(self._client_world_root)
                )
            )

    def _refresh_maps(self) -> None:
        current = self._map_selector.currentData()
        selected_name = (
            current.name if isinstance(current, Path) else self._saved_text(_MAP_SETTING)
        )
        self._map_selector.blockSignals(True)
        self._map_selector.clear()
        for path in _extracted_map_paths(self._world_map_directory):
            self._map_selector.addItem(path.stem, path)
        selected = next(
            (
                index
                for index in range(self._map_selector.count())
                if isinstance(self._map_selector.itemData(index), Path)
                and self._map_selector.itemData(index).name == selected_name
            ),
            -1,
        )
        if selected >= 0:
            self._map_selector.setCurrentIndex(selected)
        self._map_selector.blockSignals(False)
        self._on_map_selected()

    @Slot()
    def _on_extract_clicked(self) -> None:
        directory = self._region_selector.currentData()
        if not isinstance(directory, Path):
            return
        if not self._worker.start(directory):
            return
        self._extract_button.setEnabled(False)
        self._status_label.setText(
            self._translator.text(Message.UI_WORLD_DATA_EXTRACTING, region=directory.name)
        )

    @Slot(object)
    def _on_extraction_completed(self, summary: object) -> None:
        self._extract_button.setEnabled(True)
        if not isinstance(summary, WorldExtractionSummary):
            return
        result = self._translator.text(
            Message.UI_WORLD_DATA_RESULT,
            world=summary.world_name,
            zones=summary.zone_count,
            obstacles=summary.obstacle_count,
            blocks=summary.terrain_block_count,
            monsters=", ".join(summary.monster_names),
            path=str(summary.output_path),
        )
        if summary.diagnostics:
            warning = self._translator.text(
                Message.UI_WORLD_DATA_WARNINGS, count=len(summary.diagnostics)
            )
            result = "\n".join((result, warning))
        self._status_label.setText(result)
        self._refresh_maps()
        index = self._map_selector.findData(summary.output_path)
        if index >= 0:
            self._map_selector.setCurrentIndex(index)

    @Slot(str)
    def _on_extraction_failed(self, reason: str) -> None:
        self._extract_button.setEnabled(True)
        self._status_label.setText(
            self._translator.text(Message.UI_WORLD_DATA_FAILED, reason=reason)
        )

    @Slot()
    def _on_map_selected(self) -> None:
        path = self._map_selector.currentData()
        self._loaded_map = None
        if isinstance(path, Path) and path.is_file():
            try:
                self._loaded_map = load_world_map(path)
            except (OSError, ValueError) as error:
                self._status_label.setText(
                    self._translator.text(Message.UI_WORLD_DATA_FAILED, reason=str(error))
                )
        self._refresh_zones()

    def _refresh_zones(self) -> None:
        selected = self._zone_key(self._zone_selector.currentData()) or self._saved_text(
            _ZONE_SETTING
        )
        self._zone_selector.blockSignals(True)
        self._zone_selector.clear()
        world_map = self._loaded_map
        if world_map is not None:
            for zone in world_map.zones:
                self._zone_selector.addItem(self._zone_text(zone), zone)
        selected_index = next(
            (
                index
                for index in range(self._zone_selector.count())
                if self._zone_key(self._zone_selector.itemData(index)) == selected
            ),
            -1,
        )
        if selected_index >= 0:
            self._zone_selector.setCurrentIndex(selected_index)
        self._zone_selector.blockSignals(False)
        self._activate_button.setEnabled(self._zone_selector.count() > 0)

    def _zone_text(self, zone: VectorSpawnZone) -> str:
        return self._translator.text(
            Message.UI_WORLD_DATA_ZONE_ENTRY,
            monster=zone.monster_name or str(zone.monster_id),
            capacity=zone.capacity,
            x=round(zone.center_x),
            z=round(zone.center_z),
        )

    @Slot()
    def _on_activate_clicked(self) -> None:
        world_map = self._loaded_map
        zone = self._zone_selector.currentData()
        if world_map is None or not isinstance(zone, VectorSpawnZone):
            return
        all_zones = world_map.zones
        active_zones = tuple(all_zones) if len(all_zones) > 0 else (zone,)
        request = VectorNavigationRequest(
            world_map=world_map,
            anchor_zone=zone,
            active_zones=active_zones,
            goals=self._goals(world_map),
        )
        self.vector_navigation_requested.emit(request)
        self._status_label.setText(
            self._translator.text(
                Message.UI_WORLD_DATA_ACTIVE,
                world=world_map.world_name,
                monster=zone.monster_name or str(zone.monster_id),
            )
        )

    @Slot()
    def _on_deactivate_clicked(self) -> None:
        self.vector_navigation_cleared.emit()
        self._status_label.setText(self._translator.text(Message.UI_WORLD_DATA_INACTIVE))

    def _goals(self, world_map: WorldVectorMap) -> tuple[ZoneGoal, ...]:
        """Return the farming goals implied by the dashboard selection and the quota input."""

        quota = self._quota_spin.value() or None
        names = (
            world_map.monster_names if self._target_mob == ALL_TARGET_MOBS else (self._target_mob,)
        )
        return tuple(ZoneGoal(name, quota) for name in names)

    def _retranslate(self) -> None:
        self.setWindowTitle(self._translator.text(Message.UI_WORLD_DATA_TITLE))
        self._region_label.setText(self._translator.text(Message.UI_WORLD_DATA_REGION))
        self._map_label.setText(self._translator.text(Message.UI_WORLD_DATA_MAP))
        self._zone_label.setText(self._translator.text(Message.UI_WORLD_DATA_ZONE))
        self._quota_label.setText(self._translator.text(Message.UI_WORLD_DATA_QUOTA))
        self._quota_spin.setToolTip(self._translator.text(Message.UI_WORLD_DATA_QUOTA_TOOLTIP))
        self._extract_button.setText(self._translator.text(Message.UI_WORLD_DATA_EXTRACT))
        self._activate_button.setText(self._translator.text(Message.UI_WORLD_DATA_ACTIVATE))
        self._deactivate_button.setText(self._translator.text(Message.UI_WORLD_DATA_DEACTIVATE))
        self._close_button.setText(self._translator.text(Message.UI_WORLD_DATA_CLOSE))

    def _saved_text(self, key: str) -> str:
        value = self._settings.value(key, "")
        return value if isinstance(value, str) else ""

    def _saved_quota(self) -> int:
        value = self._settings.value(_QUOTA_SETTING, UNLIMITED_KILL_QUOTA)
        return value if isinstance(value, int) else UNLIMITED_KILL_QUOTA

    def _persist_state(self, *_args: object) -> None:
        """Persist only stable selection identities, never a list index."""

        region = self._region_selector.currentText()
        map_path = self._map_selector.currentData()
        zone = self._zone_selector.currentData()
        self._settings.setValue(_REGION_SETTING, region)
        self._settings.setValue(_MAP_SETTING, map_path.name if isinstance(map_path, Path) else "")
        self._settings.setValue(_ZONE_SETTING, self._zone_key(zone))
        self._settings.setValue(_QUOTA_SETTING, self._quota_spin.value())
        self._settings.sync()

    @staticmethod
    def _zone_key(value: object) -> str:
        if not isinstance(value, VectorSpawnZone):
            return ""
        return ":".join(
            str(part)
            for part in (
                value.monster_id,
                value.center_x,
                value.center_y,
                value.center_z,
                value.minimum_x,
                value.minimum_z,
                value.maximum_x,
                value.maximum_z,
            )
        )


def _extracted_map_paths(directory: Path) -> tuple[Path, ...]:
    """Return every extracted world map document under one directory, sorted by name."""

    if not directory.is_dir():
        return ()
    return tuple(sorted(directory.glob("*.json"), key=lambda path: path.name.lower()))
