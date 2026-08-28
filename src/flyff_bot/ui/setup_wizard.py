"""Initial setup wizard for one-click, unified client extraction (US-078)."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.setup.extraction import (
    InvalidClientDirectory,
    UnifiedClientExtractor,
)
from flyff_bot.features.setup.models import (
    ClientSetupPaths,
    SetupExtractionResult,
    SetupProgress,
)
from flyff_bot.i18n import Message, Translator

_EXTRACTION_THREAD_NAME = "flyff-bot-unified-client-extraction"


class _SetupWorker(QObject):
    """Run the unified extractor off the GUI thread and bridge its progress."""

    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        client_root: Path,
        output_paths_provider: object,
        monster_names_path: Path | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client_root = client_root
        self._output_paths_provider = output_paths_provider
        self._monster_names_path = monster_names_path
        self._extractor: UnifiedClientExtractor | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, profile_source: Path | None) -> bool:
        if self.is_running:
            return False
        self._thread = threading.Thread(
            target=self._run,
            args=(profile_source,),
            name=_EXTRACTION_THREAD_NAME,
            daemon=True,
        )
        self._thread.start()
        return True

    def cancel(self) -> None:
        if self._extractor is not None:
            self._extractor.cancel()

    def join(self, timeout_seconds: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout_seconds)

    def _run(self, profile_source: Path | None) -> None:
        try:
            self._extractor = UnifiedClientExtractor(
                self._client_root,
                self._output_paths(),
                monster_names_path=self._monster_names_path,
                profile_source_path=profile_source,
                progress=self._emit_progress,
            )
            result = self._extractor.run()
        except (OSError, ValueError) as error:
            self.failed.emit(str(error))
            return
        self.completed.emit(result)

    def _output_paths(self) -> ClientSetupPaths:
        provider = self._output_paths_provider
        if isinstance(provider, SetupWizard):
            return provider.setup_output_paths()
        return UnifiedClientExtractor.default_output_paths()

    @Slot(object)
    def _emit_progress(self, progress: object) -> None:
        if isinstance(progress, SetupProgress):
            self.progress.emit(progress)


class SetupWizard(QDialog):
    """Validate a client folder, run all passes, and show typed diagnostics."""

    setup_completed = Signal(object)

    def __init__(
        self,
        translator: Translator,
        *,
        client_world_root: Path,
        world_map_directory: Path,
        monster_names_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self._translator = translator
        self._client_world_root = client_world_root.parent.parent
        self._world_map_directory = world_map_directory
        self._monster_names_path = monster_names_path
        self._worker = _SetupWorker(
            self._client_world_root,
            parent,
            monster_names_path,
            self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)

        self._path_edit = QLineEdit()
        self._browse_button = QPushButton()
        self._start_button = QPushButton()
        self._cancel_button = QPushButton()
        self._close_button = QPushButton()
        self._progress_bar = QProgressBar()
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._summary_view = QTextEdit()
        self._summary_view.setReadOnly(True)
        self._path_label = QLabel()

        path_actions = QHBoxLayout()
        path_actions.addWidget(self._path_edit)
        path_actions.addWidget(self._browse_button)
        actions = QHBoxLayout()
        actions.addWidget(self._start_button)
        actions.addWidget(self._cancel_button)
        actions.addStretch()
        actions.addWidget(self._close_button)
        layout = QVBoxLayout()
        form = QGridLayout()
        form.addWidget(self._path_label, 0, 0)
        form.addLayout(path_actions, 0, 1)
        layout.addLayout(form)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._status_label)
        layout.addWidget(self._summary_view)
        layout.addLayout(actions)
        self.setLayout(layout)
        self._connect_controls()
        self._retranslate()

    @property
    def path_edit(self) -> QLineEdit:
        return self._path_edit

    @property
    def start_button(self) -> QPushButton:
        return self._start_button

    @property
    def cancel_button(self) -> QPushButton:
        return self._cancel_button

    @property
    def summary_view(self) -> QTextEdit:
        return self._summary_view

    @property
    def is_running(self) -> bool:
        return self._worker.is_running

    def set_translator(self, translator: Translator) -> None:
        self._translator = translator
        self._retranslate()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._worker.cancel()
        self._worker.join()
        super().closeEvent(event)

    def setup_output_paths(self) -> ClientSetupPaths:
        paths = UnifiedClientExtractor.default_output_paths()
        paths.world_map_directory = self._world_map_directory
        return paths

    def _connect_controls(self) -> None:
        self._browse_button.clicked.connect(self._on_browse_clicked)
        self._start_button.clicked.connect(self._on_start_clicked)
        self._cancel_button.clicked.connect(self._worker.cancel)
        self._cancel_button.clicked.connect(
            lambda: self._status_label.setText(self._translator.text(Message.UI_SETUP_CANCELING))
        )
        self._close_button.clicked.connect(self.close)

    @Slot()
    def _on_browse_clicked(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "", self._path_edit.text())
        if selected:
            self._path_edit.setText(str(Path(selected)))

    @Slot()
    def _on_start_clicked(self) -> None:
        client_root = Path(self._path_edit.text())
        try:
            UnifiedClientExtractor.validate_client_directory(client_root)
        except InvalidClientDirectory:
            self._status_label.setText(self._translator.text(Message.UI_SETUP_INVALID_DIRECTORY))
            return
        self._set_running_state(True)
        if not self._worker.start(None):
            self._set_running_state(False)

    @Slot(int, str)
    def _on_progress(self, progress: object) -> None:
        if not isinstance(progress, SetupProgress):
            return
        self._progress_bar.setValue(progress.percent)
        self._status_label.setText(progress.detail)

    @Slot(object)
    def _on_completed(self, result: object) -> None:
        self._set_running_state(False)
        if not isinstance(result, SetupExtractionResult):
            raise TypeError("The setup worker completed without a typed extraction result.")
        self._progress_bar.setValue(100)
        self._status_label.setText(self._translator.text(Message.UI_SETUP_COMPLETE))
        self._summary_view.setPlainText(self._summary_text(result))
        self.setup_completed.emit(result)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._set_running_state(False)
        self._status_label.setText(self._translator.text(Message.UI_SETUP_FAILED, reason=message))
        QMessageBox.warning(
            self,
            self._translator.text(Message.UI_SETUP_TITLE),
            self._translator.text(Message.UI_SETUP_FAILED, reason=message),
        )

    def _set_running_state(self, running: bool) -> None:
        self._start_button.setEnabled(not running)
        self._browse_button.setEnabled(not running)
        self._path_edit.setEnabled(not running)
        self._cancel_button.setEnabled(running)

    def _summary_text(self, result: SetupExtractionResult) -> str:
        memory_text = (
            self._translator.text(
                Message.UI_SETUP_MEMORY_PROFILE_VERIFIED,
                sha256=result.memory_profile.sha256,
                fields=result.memory_profile.field_count,
            )
            if result.memory_profile is not None
            else self._translator.text(Message.UI_SETUP_MEMORY_PROFILE_MISSING)
        )
        summary = self._translator.text(
            Message.UI_SETUP_SUMMARY,
            worlds=result.world_count,
            quests=result.quest_count,
            dungeons=result.dungeon_count,
            movers=result.mover_count,
            drops=result.drop_count,
            items=result.item_count,
            memory=memory_text,
        )
        if not result.diagnostics:
            return summary
        warnings = "\n".join(
            f"{diagnostic.warning.value}: {diagnostic.detail}".strip(": ")
            for diagnostic in result.diagnostics
        )
        return f"{summary}\n{warnings}"

    def _retranslate(self) -> None:
        self.setWindowTitle(self._translator.text(Message.UI_SETUP_TITLE))
        self._path_label.setText(self._translator.text(Message.UI_SETUP_CLIENT_PATH))
        self._browse_button.setText(self._translator.text(Message.UI_SETUP_BROWSE))
        self._start_button.setText(self._translator.text(Message.UI_SETUP_START))
        self._cancel_button.setText(self._translator.text(Message.UI_SETUP_CANCEL))
        self._close_button.setText(self._translator.text(Message.UI_WORLD_DATA_CLOSE))
