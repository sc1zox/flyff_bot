"""Theme stylesheet loader and application utility for modern dark UI."""

from __future__ import annotations

import logging
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget

LOGGER = logging.getLogger(__name__)


def load_theme_stylesheet(custom_path: Path | None = None) -> str:
    """Load the dark slate QSS stylesheet safely with error fallback."""

    try:
        if custom_path is not None:
            return custom_path.read_text(encoding="utf-8")
        resource = files("flyff_bot.ui").joinpath("theme.qss")
        return resource.read_text(encoding="utf-8")
    except Exception as exc:
        LOGGER.warning("Failed to load dark theme stylesheet: %s", exc)
        return ""


def apply_theme(
    target: QApplication | QWidget | QCoreApplication, custom_path: Path | None = None
) -> None:
    """Apply the modern dark theme to the Qt application or widget."""

    stylesheet = load_theme_stylesheet(custom_path)
    if stylesheet and isinstance(target, (QApplication, QWidget)):
        target.setStyleSheet(stylesheet)
