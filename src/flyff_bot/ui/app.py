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
    DEFAULT_NAVIGATION_MAP_PATH,
    DEFAULT_PROCESS_NAME,
)
from flyff_bot.features.automation.controllers import CombatConfig, KeyBinding
from flyff_bot.features.automation.orchestrator import FarmingConfig, FarmingOrchestrator
from flyff_bot.features.automation.vitals_controller import VitalsTriggerConfig
from flyff_bot.features.input_control import InputControlError, WindowsInputController
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.persistence import load_spatial_map
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.vision import (
    DetectionConfig,
    OpenCVDnnYoloDetector,
    TargetVerificationConfig,
    TargetVerifier,
    TesseractTextRecognizer,
    WindowsFrameSource,
)
from flyff_bot.features.vision.monster_stats import MonsterStatsReader
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import DashboardFeed, WindowStatus
from flyff_bot.ui.main_window import MainWindow
from flyff_bot.ui.theme import apply_theme

STANDBY_TICK_INTERVAL_MILLISECONDS = 100


class FarmingControls(Protocol):
    """The dashboard-facing controls exposed by a farming session."""

    def start(self) -> None: ...

    def pause(self) -> None: ...

    def emergency_stop(self) -> None: ...

    def save_navigation_profile(self, path: Path) -> None: ...

    def load_navigation_profile(self, path: Path) -> None: ...

    def reset_navigation_map(self) -> None: ...

    def configure_vitals(self, config: VitalsTriggerConfig) -> None: ...


class WindowFocusControls(Protocol):
    """The foreground handoff required before a farming session can run."""

    def focus_window(self, window_handle: int) -> None: ...


class StartableControls(Protocol):
    """The subset of session controls needed to initiate farming after window focus."""

    def start(self) -> None: ...

    def pause(self) -> None: ...


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

    def _safe_load_profile(path: Path) -> None:
        try:
            orchestrator.load_navigation_profile(path)
        except Exception as exc:
            window.show_error_dialog(
                window._translator.text(Message.UI_PROFILE_LOAD_ERROR_TITLE),
                window._translator.text(Message.UI_PROFILE_LOAD_ERROR_PROMPT, reason=str(exc)),
            )

    window.save_profile_requested.connect(orchestrator.save_navigation_profile)
    window.load_profile_requested.connect(_safe_load_profile)
    window.reset_navigation_requested.connect(orchestrator.reset_navigation_map)
    window.vitals_config_changed.connect(orchestrator.configure_vitals)


def start_farming(
    controller: WindowFocusControls, window_handle: int, orchestrator: StartableControls
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
    apply_theme(application)
    window = MainWindow(Translator.from_environment())
    feed = DashboardFeed(window)
    feed.update_available.connect(window.update_dashboard)

    controller = WindowsInputController()
    windows = controller.find_windows(DEFAULT_PROCESS_NAME)
    if windows:
        window.set_window_status(WindowStatus.NOT_FOREGROUND)
        window_handle = windows[0].handle
        window.attach_placement_target(controller, window_handle)
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
                target_verifier = TargetVerifier(
                    {"Flame": flame_template},
                    anchor,
                    TargetVerificationConfig(
                        anchor_match_threshold=window.anchor_threshold_spin.value(),
                        name_match_threshold=window.name_threshold_spin.value(),
                    ),
                )
                pipeline = PerceptionPipeline(
                    WindowsFrameSource(require_foreground=False),
                    OpenCVDnnYoloDetector.from_files(
                        model_path,
                        labels_path,
                        DetectionConfig(confidence_threshold=0.3),
                    ),
                    target_verifier,
                    monster_stats_reader=MonsterStatsReader(TesseractTextRecognizer()),
                )
                navigation_map_path = Path(DEFAULT_NAVIGATION_MAP_PATH)
                orchestrator = FarmingOrchestrator(
                    pipeline,
                    controller,
                    window_handle,
                    config=FarmingConfig(
                        combat=CombatConfig(
                            rotation=(KeyBinding(window.attack_virtual_key),),
                            target_acquisition_grace_seconds=window.target_grace_spin.value(),
                            kill_verification_enabled=window.kill_verification_toggle.isChecked(),
                        ),
                        vitals=window.get_vitals_config(),
                    ),
                    dashboard_feed=feed,
                    pathing=PathingController(
                        load_spatial_map(navigation_map_path), map_path=navigation_map_path
                    ),
                )
                window.attack_key_changed.connect(orchestrator.configure_attack_key)
                window.combat_grace_changed.connect(orchestrator.configure_combat_grace)
                window.kill_verification_changed.connect(orchestrator.configure_kill_verification)
                window.target_thresholds_changed.connect(target_verifier.update_thresholds)
                connect_farming_controls(
                    window,
                    orchestrator,
                    on_start=lambda: start_farming(controller, window_handle, orchestrator),
                )
                timer = QTimer(window)
                timer.timeout.connect(orchestrator.tick)
                timer.start(STANDBY_TICK_INTERVAL_MILLISECONDS)
    else:
        window.set_window_status(WindowStatus.NOT_FOUND)

    window.show()
    return application.exec()


def _read_template(path: Path) -> npt.NDArray[np.uint8] | None:
    """Read one BGR UI template when its image data is valid."""

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return None
    return cast("npt.NDArray[np.uint8]", image)
