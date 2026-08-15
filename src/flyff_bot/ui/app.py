"""Qt application entry point kept separate from the command-line adapter."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import cv2
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from flyff_bot.constants import (
    DEFAULT_MOB_LABELS_PATH,
    DEFAULT_MOB_MODEL_PATH,
    DEFAULT_PROCESS_NAME,
)
from flyff_bot.features.automation.orchestrator import FarmingOrchestrator
from flyff_bot.features.input_control import WindowsInputController
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.vision import (
    DetectionConfig,
    LootLogReader,
    OpenCVDnnYoloDetector,
    TargetVerifier,
    TesseractTextRecognizer,
    WindowsFrameSource,
)
from flyff_bot.i18n import Translator
from flyff_bot.ui.dashboard import DashboardFeed
from flyff_bot.ui.main_window import MainWindow


class FarmingControls(Protocol):
    """The dashboard-facing controls exposed by a farming session."""

    def start(self) -> None: ...

    def pause(self) -> None: ...

    def emergency_stop(self) -> None: ...


def connect_farming_controls(window: MainWindow, orchestrator: FarmingControls) -> None:
    """Connect dashboard intent signals to the small orchestration control surface."""

    window.start_requested.connect(orchestrator.start)
    window.pause_requested.connect(orchestrator.pause)
    window.emergency_stop_requested.connect(orchestrator.emergency_stop)


def run_desktop(arguments: Sequence[str] | None = None) -> int:
    """Launch the native desktop window and return Qt's exit code."""

    application = QApplication(list(arguments or sys.argv))
    window = MainWindow(Translator.from_environment())
    feed = DashboardFeed(window)
    feed.update_available.connect(window.update_dashboard)

    controller = WindowsInputController()
    windows = controller.find_windows(DEFAULT_PROCESS_NAME)
    if windows:
        window_handle = windows[0].handle
        model_path = Path(DEFAULT_MOB_MODEL_PATH)
        labels_path = Path(DEFAULT_MOB_LABELS_PATH)
        anchor_path = Path("models/target_anchor.png")
        flame_template_path = Path("models/target_flame.png")

        if (
            model_path.is_file()
            and labels_path.is_file()
            and anchor_path.is_file()
            and flame_template_path.is_file()
        ):
            anchor = cv2.imread(str(anchor_path))
            flame_template = cv2.imread(str(flame_template_path))
            templates = {"Flame": flame_template} if flame_template is not None else {}
            pipeline = PerceptionPipeline(
                WindowsFrameSource(),
                OpenCVDnnYoloDetector.from_files(
                    model_path,
                    labels_path,
                    DetectionConfig(confidence_threshold=0.3),
                ),
                TargetVerifier(templates, anchor),
                LootLogReader(TesseractTextRecognizer()),
            )
            orchestrator = FarmingOrchestrator(
                pipeline,
                controller,
                window_handle,
                dashboard_feed=feed,
            )
            connect_farming_controls(window, orchestrator)
            timer = QTimer(window)
            timer.timeout.connect(orchestrator.tick)
            timer.start(100)

    window.show()
    return application.exec()
