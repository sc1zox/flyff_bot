"""Qt application entry point kept separate from the command-line adapter."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from flyff_bot.constants import (
    DEFAULT_MOB_LABELS_PATH,
    DEFAULT_MOB_MODEL_PATH,
    DEFAULT_PROCESS_NAME,
)
from flyff_bot.features.automation.orchestrator import FarmingOrchestrator
from flyff_bot.features.input_control import InputControlError, WindowsInputController
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


class WindowFocusControls(Protocol):
    """The foreground handoff required before a farming session can run."""

    def focus_window(self, window_handle: int) -> None: ...


def connect_farming_controls(
    window: MainWindow,
    orchestrator: FarmingControls,
    *,
    on_start: Callable[[], None] | None = None,
) -> None:
    """Connect dashboard intent signals to the small orchestration control surface."""

    window.start_requested.connect(on_start or orchestrator.start)
    window.pause_requested.connect(orchestrator.pause)
    window.emergency_stop_requested.connect(orchestrator.emergency_stop)


def start_farming(
    controller: WindowFocusControls, window_handle: int, orchestrator: FarmingControls
) -> None:
    """Return focus to the game before allowing guarded farming ticks to resume."""

    try:
        controller.focus_window(window_handle)
    except InputControlError:
        orchestrator.pause()
        return
    orchestrator.start()


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
            anchor = _read_template(anchor_path)
            flame_template = _read_template(flame_template_path)
            if anchor is not None and flame_template is not None:
                pipeline = PerceptionPipeline(
                    WindowsFrameSource(),
                    OpenCVDnnYoloDetector.from_files(
                        model_path,
                        labels_path,
                        DetectionConfig(confidence_threshold=0.3),
                    ),
                    TargetVerifier({"Flame": flame_template}, anchor),
                    LootLogReader(TesseractTextRecognizer()),
                )
                orchestrator = FarmingOrchestrator(
                    pipeline,
                    controller,
                    window_handle,
                    dashboard_feed=feed,
                )
                connect_farming_controls(
                    window,
                    orchestrator,
                    on_start=lambda: start_farming(controller, window_handle, orchestrator),
                )
                timer = QTimer(window)
                timer.timeout.connect(orchestrator.tick)
                timer.start(100)

    window.show()
    return application.exec()


def _read_template(path: Path) -> npt.NDArray[np.uint8] | None:
    """Read one BGR UI template when its image data is valid."""

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return None
    return cast("npt.NDArray[np.uint8]", image)
