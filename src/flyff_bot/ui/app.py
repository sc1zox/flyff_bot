"""Qt application entry point kept separate from the command-line adapter."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt
from PySide6.QtWidgets import QApplication

from flyff_bot.constants import (
    DEFAULT_MOB_LABELS_PATH,
    DEFAULT_MOB_MODEL_PATH,
    DEFAULT_MONSTER_STATS_PANEL_PATH,
    DEFAULT_NAVIGATION_MAP_PATH,
    DEFAULT_PROCESS_NAME,
    DEFAULT_TARGET_ANCHOR_PATH,
)
from flyff_bot.features.automation.camera_alignment import (
    CameraAligner,
    frame_minimap_locator,
)
from flyff_bot.features.automation.controllers import CombatConfig, KeyBinding
from flyff_bot.features.automation.kill_goals import KillGoalConfig, KillGoalTracker
from flyff_bot.features.automation.kill_persistence import (
    DEFAULT_KILL_LOG_PATH,
    SqliteKillLog,
)
from flyff_bot.features.automation.orchestrator import FarmingConfig, FarmingOrchestrator
from flyff_bot.features.automation.powerup_controller import PowerUpConfig
from flyff_bot.features.automation.vitals_controller import VitalsTriggerConfig
from flyff_bot.features.diagnostics import DEFAULT_SESSION_LOG_DIRECTORY, SessionEventLogger
from flyff_bot.features.input_control import InputControlError, WindowsInputController
from flyff_bot.features.navigation.live_position import LivePositionReader
from flyff_bot.features.navigation.pathing import (
    PathingController,
    ProfileLoadOutcome,
    ProfileLoadResult,
)
from flyff_bot.features.navigation.persistence import load_profile
from flyff_bot.features.navigation.spatial import WorldPoint
from flyff_bot.features.navigation.vector_navigation import (
    VectorNavigationRequest,
    VectorZoneNavigator,
)
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.vision import (
    DetectionConfig,
    OpenCVDnnYoloDetector,
    TargetVerificationConfig,
    TargetVerifier,
    TesseractTextRecognizer,
    WindowsFrameSource,
    load_class_names,
    load_mob_anchor_templates,
)
from flyff_bot.features.vision.monster_stats import (
    MonsterStatsReader,
    load_header_anchor_template,
)
from flyff_bot.features.vision.ocr import TESSERACT_LANGUAGE_ENGLISH
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import DashboardFeed, WindowStatus
from flyff_bot.ui.main_window import MainWindow
from flyff_bot.ui.session_worker import SessionWorker
from flyff_bot.ui.theme import apply_theme

STANDBY_TICK_INTERVAL_SECONDS = 0.1
# Shown in place of a minimap scale that is not known. It is deliberately not a word, so the
# refusal message stays one localized sentence rather than an assembled one.
UNKNOWN_SCALE_TEXT = "?"


def _scale_text(zoom_signature: float | None) -> str:
    """Return one minimap scale as it appears inside an operator-facing sentence."""

    return UNKNOWN_SCALE_TEXT if zoom_signature is None else f"{zoom_signature:.1f}"


class FarmingControls(Protocol):
    """The dashboard-facing controls exposed by a farming session."""

    def start(self) -> None: ...

    def pause(self) -> None: ...

    def emergency_stop(self) -> None: ...

    def save_navigation_profile(self, path: Path) -> None: ...

    def load_navigation_profile(
        self, path: Path, *, accept_unmatched: bool = False
    ) -> ProfileLoadResult | None: ...

    def reset_navigation_map(self) -> None: ...

    def configure_vitals(self, config: VitalsTriggerConfig) -> None: ...

    def configure_powerups(self, config: PowerUpConfig) -> None: ...

    def request_camera_alignment(self) -> None: ...

    def configure_auto_align(self, enabled: bool) -> None: ...


class VectorNavigationControls(Protocol):
    """The session-side surface that adopts or drops an extracted world map."""

    def configure_vector_navigation(self, navigator: VectorZoneNavigator | None) -> None: ...


class SessionPositionSource(Protocol):
    """The live position the world-to-session frame registration is anchored at."""

    @property
    def position(self) -> WorldPoint: ...


class TargetGoalControls(Protocol):
    """The session-side surface that owns the operator's monster selection."""

    def configure_kill_goals(self, config: KillGoalConfig) -> None: ...


class ClassFilterableDetector(Protocol):
    """The perception-side surface that follows the operator's monster selection."""

    def update_allowed_class_names(self, allowed_class_names: frozenset[str]) -> None: ...


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
            result = orchestrator.load_navigation_profile(path)
        except Exception as exc:
            window.show_error_dialog(
                window._translator.text(Message.UI_PROFILE_LOAD_ERROR_TITLE),
                window._translator.text(Message.UI_PROFILE_LOAD_ERROR_PROMPT, reason=str(exc)),
            )
            return
        if result is None:
            return
        if result.outcome is ProfileLoadOutcome.SCALE_MISMATCH:
            window.show_error_dialog(
                window._translator.text(Message.UI_PROFILE_SCALE_MISMATCH_TITLE),
                window._translator.text(
                    Message.UI_PROFILE_SCALE_MISMATCH_PROMPT,
                    stored=_scale_text(result.stored_zoom_signature),
                    live=_scale_text(result.live_zoom_signature),
                ),
            )
            return
        if result.outcome is ProfileLoadOutcome.UNMATCHED and window.confirm_read_only_profile():
            _safe_load_profile_read_only(path)

    def _safe_load_profile_read_only(path: Path) -> None:
        try:
            orchestrator.load_navigation_profile(path, accept_unmatched=True)
        except Exception as exc:
            window.show_error_dialog(
                window._translator.text(Message.UI_PROFILE_LOAD_ERROR_TITLE),
                window._translator.text(Message.UI_PROFILE_LOAD_ERROR_PROMPT, reason=str(exc)),
            )

    window.save_profile_requested.connect(orchestrator.save_navigation_profile)
    window.load_profile_requested.connect(_safe_load_profile)
    window.reset_navigation_requested.connect(orchestrator.reset_navigation_map)
    window.vitals_config_changed.connect(orchestrator.configure_vitals)
    window.powerup_config_changed.connect(orchestrator.configure_powerups)
    window.auto_align_changed.connect(orchestrator.configure_auto_align)
    window.align_camera_requested.connect(orchestrator.request_camera_alignment)


def connect_vector_navigation(
    window: MainWindow,
    session: VectorNavigationControls,
    positions: SessionPositionSource,
) -> None:
    """Arm or disarm extracted-map navigation from the world data manager.

    The registration is only meaningful against the position measured when the operator
    confirms it, so the navigator is built here, at the moment of the request, rather than
    inside the dialog that has no access to the live estimate (US-045).
    """

    def _activate(request: object) -> None:
        if not isinstance(request, VectorNavigationRequest):
            return
        session.configure_vector_navigation(request.navigator(positions.position))

    def _deactivate() -> None:
        session.configure_vector_navigation(None)

    window.vector_navigation_requested.connect(_activate)
    window.vector_navigation_cleared.connect(_deactivate)


def target_class_applier(
    detector: ClassFilterableDetector,
    verifier: TargetVerifier,
    class_names: Sequence[str],
    *,
    default_anchor_path: Path | None = None,
) -> Callable[[frozenset[str]], None]:
    """Return the callback that narrows detection and verification to a class set.

    Filtering at the detector is what keeps a non-target monster out of
    :class:`WorldState` entirely, so no candidate selection or template match is ever
    spent on it; the verifier only has to agree with that same choice. An empty set
    restores every known class, which is what an unrestricted selection means.
    """

    def _apply_classes(allowed: frozenset[str]) -> None:
        selected = tuple(class_names) if not allowed else tuple(sorted(allowed))
        detector.update_allowed_class_names(allowed)
        verifier.update_allowed_names(
            selected,
            load_mob_anchor_templates(selected, default_anchor_path=default_anchor_path) or None,
        )

    return _apply_classes


def connect_target_selection(window: MainWindow, controls: TargetGoalControls) -> None:
    """Route the operator's monster selection and kill quotas into the session.

    The session owns the resulting class filter: a quota that completes mid-run has to
    narrow targeting exactly the way an operator's edit does (US-035).
    """

    window.target_selection_changed.connect(controls.configure_kill_goals)


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
        anchor_path = Path(DEFAULT_TARGET_ANCHOR_PATH)

        if model_path.is_file() and labels_path.is_file():
            allowed_names = load_class_names(labels_path)
            window.set_target_mob_options(allowed_names)
            default_anchor_path = anchor_path if anchor_path.is_file() else None
            anchors = load_mob_anchor_templates(
                allowed_names,
                default_anchor_path=default_anchor_path,
            )
            if anchors:
                target_verifier = TargetVerifier(
                    allowed_names,
                    anchors,
                    TesseractTextRecognizer(),
                    TargetVerificationConfig(
                        anchor_match_threshold=window.anchor_threshold_spin.value(),
                    ),
                )
                frame_source = WindowsFrameSource(require_foreground=False)
                detector = OpenCVDnnYoloDetector.from_files(
                    model_path,
                    labels_path,
                    DetectionConfig(confidence_threshold=0.3),
                )
                pipeline = PerceptionPipeline(
                    frame_source,
                    detector,
                    target_verifier,
                    monster_stats_reader=MonsterStatsReader(
                        # The stats HUD is English in every client locale, so requiring the
                        # German language pack here would only add a way for it to fail.
                        TesseractTextRecognizer(language=TESSERACT_LANGUAGE_ENGLISH),
                        header_anchor_template=load_header_anchor_template(
                            Path(DEFAULT_MONSTER_STATS_PANEL_PATH)
                        ),
                    ),
                )
                navigation_map_path = Path(DEFAULT_NAVIGATION_MAP_PATH)
                apply_target_classes = target_class_applier(
                    detector,
                    target_verifier,
                    allowed_names,
                    default_anchor_path=default_anchor_path,
                )
                pathing = PathingController(
                    load_profile(navigation_map_path).spatial_map,
                    map_path=navigation_map_path,
                    position_reader=LivePositionReader(window_handle),
                )
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
                        powerups=window.get_powerup_config(),
                        auto_align_camera=window.auto_align_toggle.isChecked(),
                    ),
                    dashboard_feed=feed,
                    pathing=pathing,
                    camera_aligner=CameraAligner(
                        controller,
                        window_handle,
                        locate_minimap_geometry=frame_minimap_locator(frame_source, window_handle),
                    ),
                    kill_goals=KillGoalTracker(
                        window.target_selection,
                        recorder=SqliteKillLog(Path(DEFAULT_KILL_LOG_PATH)),
                    ),
                    on_target_classes_changed=apply_target_classes,
                    event_logger=SessionEventLogger(DEFAULT_SESSION_LOG_DIRECTORY),
                    foreground_window_info=controller.foreground_window_info,
                )
                window.attack_key_changed.connect(orchestrator.configure_attack_key)
                window.combat_grace_changed.connect(orchestrator.configure_combat_grace)
                window.kill_verification_changed.connect(orchestrator.configure_kill_verification)
                window.anchor_threshold_changed.connect(target_verifier.update_anchor_threshold)
                connect_target_selection(window, orchestrator)
                connect_farming_controls(
                    window,
                    orchestrator,
                    on_start=lambda: start_farming(controller, window_handle, orchestrator),
                )
                connect_vector_navigation(window, orchestrator, pathing)
                # Ticking on a worker thread keeps frame capture and OCR out of the Qt event
                # loop; results reach the widgets only through the dashboard feed's signal.
                worker = SessionWorker(orchestrator.tick, STANDBY_TICK_INTERVAL_SECONDS)
                window.register_teardown(worker.stop)
                window.register_teardown(orchestrator.close)
                worker.start()
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
