"""Standalone top-level window hosting the 2D navigation and spawn heatmap canvas."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QMainWindow, QWidget

from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.path_inspector import PathInspectorWidget


class NavigationMapWindow(QMainWindow):
    """Secondary top-level window for the navigation map with emergency-stop support."""

    closed = Signal()
    emergency_stop_requested = Signal()

    def __init__(
        self,
        translator: Translator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator
        self._inspector: PathInspectorWidget | None = None
        self._retranslate()
        self.resize(700, 520)

    @property
    def inspector(self) -> PathInspectorWidget | None:
        """Return the currently hosted path inspector widget."""

        return self._inspector

    def set_inspector(self, inspector: PathInspectorWidget) -> None:
        """Host the path inspector widget as the central widget."""

        self._inspector = inspector
        self.setCentralWidget(inspector)

    def take_inspector(self) -> PathInspectorWidget | None:
        """Detach and return the hosted inspector widget for re-docking."""

        inspector = self._inspector
        if inspector is not None:
            inspector.setParent(None)
            self._inspector = None
        return inspector

    def set_translator(self, translator: Translator) -> None:
        """Update translator and retranslate window title."""

        self._translator = translator
        self._retranslate()
        if self._inspector is not None:
            self._inspector.set_translator(translator)

    def _retranslate(self) -> None:
        self.setWindowTitle(self._translator.text(Message.UI_MAP_WINDOW_TITLE))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Trigger emergency stop immediately upon Escape keypress."""

        if event.key() == Qt.Key.Key_Escape:
            self.emergency_stop_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Emit closed signal before window closes to sync docked state."""

        self.closed.emit()
        super().closeEvent(event)
