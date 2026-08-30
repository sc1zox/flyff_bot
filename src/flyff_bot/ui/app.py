"""Qt application entry point kept separate from the command-line adapter."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from time import monotonic
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from flyff_bot.constants import (
    DEFAULT_CLIENT_DATA_ROOT,
    DEFAULT_DUNGEON_DATABASE_PATH,
    DEFAULT_MOB_LABELS_PATH,
    DEFAULT_MOB_MODEL_PATH,
    DEFAULT_PROCESS_NAME,
    DEFAULT_TARGET_ANCHOR_PATH,
)
from flyff_bot.features.automation.camera_alignment import CameraAligner
from flyff_bot.features.automation.controllers import CombatConfig, KeyBinding
from flyff_bot.features.automation.emergency_recovery import EmergencyRecoveryConfig
from flyff_bot.features.automation.kill_goals import KillGoalConfig, KillGoalTracker
from flyff_bot.features.automation.kill_persistence import (
    DEFAULT_KILL_LOG_PATH,
    SqliteKillLog,
)
from flyff_bot.features.automation.orchestrator import (
    FarmingConfig,
    FarmingOrchestrator,
)
from flyff_bot.features.automation.powerup_controller import PowerUpConfig
from flyff_bot.features.automation.quest_execution_models import QuestMenuPerceiver
from flyff_bot.features.automation.vitals_controller import VitalsTriggerConfig
from flyff_bot.features.diagnostics import DEFAULT_SESSION_LOG_DIRECTORY, SessionEventLogger
from flyff_bot.features.dungeons.live_reader import LiveDungeonCooldownReader
from flyff_bot.features.dungeons.persistence import load_dungeon_database
from flyff_bot.features.input_control import InputControlError, WindowsInputController
from flyff_bot.features.navigation.live_camera import LiveCameraReader
from flyff_bot.features.navigation.live_position import LivePositionReader
from flyff_bot.features.navigation.live_world_id import LiveWorldIdReader
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.teleporter_dialog import TemplateTeleporterDialogLocator
from flyff_bot.features.navigation.teleporter_dispatch import (
    LiveArrivalObserver,
    TeleporterDispatchConfig,
    TeleporterDispatcher,
)
from flyff_bot.features.navigation.teleporter_input import TeleporterWindowsInput
from flyff_bot.features.navigation.test_navigation import NavigationTestRequest
from flyff_bot.features.navigation.vector_navigation import (
    VectorNavigationRequest,
    VectorZoneNavigator,
)
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.player_stats.reader import LivePlayerStatsReader
from flyff_bot.features.policy.models import PolicyRuntimeMode
from flyff_bot.features.quests.goals import (
    QuestFarmingQueue,
    QuestGoalResolver,
    QuestResolution,
)
from flyff_bot.features.quests.models import QuestDefinition
from flyff_bot.features.vision import (
    DetectionConfig,
    OpenCVDnnYoloDetector,
    TargetVerifier,
    TesseractTextRecognizer,
    WindowsFrameSource,
    load_class_names,
    load_mob_anchor_templates,
)
from flyff_bot.features.vision.ocr import TESSERACT_LANGUAGE_ENGLISH
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import DashboardFeed
from flyff_bot.ui.main_window import MainWindow
from flyff_bot.ui.session_worker import (
    WORKER_WATCHDOG_INTERVAL_SECONDS,
    SessionWorker,
    is_worker_stalled,
)
from flyff_bot.ui.theme import apply_theme

STANDBY_TICK_INTERVAL_SECONDS = 0.1
MILLISECONDS_PER_SECOND = 1_000


class FarmingControls(Protocol):
    """The dashboard-facing controls exposed by a farming session."""

    def start(self) -> None: ...

    def pause(self) -> None: ...

    def emergency_stop(self) -> None: ...

    def configure_vitals(self, config: VitalsTriggerConfig) -> None: ...

    def configure_powerups(self, config: PowerUpConfig) -> None: ...

    def configure_emergency_recovery(self, config: EmergencyRecoveryConfig) -> None: ...

    def configure_auto_align(self, enabled: bool) -> None: ...

    def configure_policy_mode(self, mode: PolicyRuntimeMode) -> None: ...

    def configure_policy_model_directory(self, directory: str | None) -> None: ...


class VectorNavigationControls(Protocol):
    """The session-side surface that adopts or drops an extracted world map."""

    def configure_vector_navigation(self, navigator: VectorZoneNavigator | None) -> None: ...


class TestNavigationControls(Protocol):
    """The bounded session surface for one operator-selected map navigation test."""

    def request_test_navigation(self, request: NavigationTestRequest) -> None: ...

    def pause(self) -> None: ...


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


class AutopilotControls(Protocol):
    """The subset of session controls needed to arm one unattended session."""

    def arm_autopilot(self) -> None: ...

    def pause(self) -> None: ...


def connect_farming_controls(
    window: MainWindow,
    orchestrator: FarmingControls,
    *,
    on_start: Callable[[], None] | None = None,
) -> None:
    """Connect dashboard intent signals to orchestration controls."""

    window.start_requested.connect(on_start or orchestrator.start)
    window.pause_requested.connect(orchestrator.pause)
    window.emergency_stop_requested.connect(orchestrator.emergency_stop)
    window.vitals_config_changed.connect(orchestrator.configure_vitals)
    window.powerup_config_changed.connect(orchestrator.configure_powerups)
    window.emergency_config_changed.connect(orchestrator.configure_emergency_recovery)
    window.auto_align_changed.connect(orchestrator.configure_auto_align)


def connect_vector_navigation(
    window: MainWindow,
    session: VectorNavigationControls,
) -> None:
    """Arm or disarm extracted-map navigation from the world data manager."""

    def _activate(request: object) -> None:
        if not isinstance(request, VectorNavigationRequest):
            return
        session.configure_vector_navigation(request.navigator())

    def _deactivate() -> None:
        session.configure_vector_navigation(None)

    window.vector_navigation_requested.connect(_activate)
    window.vector_navigation_cleared.connect(_deactivate)


def connect_test_navigation(
    window: MainWindow,
    session: TestNavigationControls,
    *,
    on_start: Callable[[NavigationTestRequest], None] | None = None,
) -> None:
    """Forward only typed map destinations to the navigation-test session path."""

    def _activate(request: object) -> None:
        if isinstance(request, NavigationTestRequest):
            if on_start is not None:
                on_start(request)
            else:
                session.request_test_navigation(request)

    window.test_navigation_requested.connect(_activate)


def connect_target_selection(
    window: MainWindow,
    session: TargetGoalControls,
) -> None:
    """Push the monster selection into the session's quota tracker."""

    def _apply(config: object) -> None:
        if isinstance(config, KillGoalConfig):
            session.configure_kill_goals(config)

    window.target_selection_changed.connect(_apply)


class QuestGoalControls(Protocol):
    """The subset of session controls needed to farm a queue of selected quests."""

    def configure_quest_queue(self, queue: QuestFarmingQueue | None) -> None: ...


def connect_quest_selection(
    window: MainWindow,
    session: QuestGoalControls,
    resolver: Callable[[], QuestGoalResolver],
) -> None:
    """Resolve the operator's quest selection and arm the session's quest queue.

    A quest whose monsters have no extracted spawn zone still enters the queue, but its
    resolution issue is reported on the quest panel as a localized diagnostic instead of
    being silently dropped.
    """

    def _apply(selection: object) -> None:
        quests = tuple(
            item for item in _as_sequence(selection) if isinstance(item, QuestDefinition)
        )
        if not quests:
            session.configure_quest_queue(None)
            window.quest_panel.set_status_text(
                window.translator.text(Message.UI_QUEST_NO_SELECTION)
            )
            return
        resolutions = resolver().resolve_all(quests)
        session.configure_quest_queue(QuestFarmingQueue(resolutions))
        window.quest_panel.set_status_text(_issue_text(window, resolutions))

    window.quest_selection_changed.connect(_apply)


def _as_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, list | tuple):
        return tuple(value)
    return ()


def _issue_text(window: MainWindow, resolutions: Sequence[QuestResolution]) -> str:
    lines: list[str] = []
    for resolution in resolutions:
        monsters = ", ".join(
            target.monster_name for target in resolution.targets if target.zone is None
        )
        title = resolution.quest.display_title
        lines.extend(
            window.quest_panel.issue_text(issue, title, monsters) for issue in resolution.issues
        )
    return chr(10).join(lines)


def target_class_applier(
    detector: ClassFilterableDetector,
    verifier: TargetVerifier,
    all_names: Sequence[str],
    *,
    default_anchor_path: Path | None = None,
) -> Callable[[frozenset[str]], None]:
    """Return a callback that updates YOLO classes and reloads verification templates."""

    def apply(allowed: frozenset[str]) -> None:
        detector.update_allowed_class_names(allowed)
        names = tuple(allowed) if allowed else tuple(all_names)
        anchors = load_mob_anchor_templates(names, default_anchor_path=default_anchor_path)
        verifier.update_allowed_names(names, header_anchor_templates=anchors)

    return apply


def start_farming(
    controller: WindowFocusControls,
    window_handle: int,
    session: StartableControls,
) -> None:
    """Bring the game client foregrounded before the session can dispatch inputs."""

    try:
        controller.focus_window(window_handle)
    except InputControlError:
        session.pause()
        return
    session.start()


def arm_autopilot(
    controller: WindowFocusControls,
    window_handle: int,
    session: AutopilotControls,
) -> None:
    """Foreground the client, then arm one self-directed unattended session."""

    try:
        controller.focus_window(window_handle)
    except InputControlError:
        session.pause()
        return
    session.arm_autopilot()


def start_test_navigation(
    controller: WindowFocusControls,
    window_handle: int,
    session: TestNavigationControls,
    request: NavigationTestRequest,
) -> None:
    """Foreground the client, then start one test-navigation movement."""

    try:
        controller.focus_window(window_handle)
    except InputControlError:
        session.pause()
        return
    session.request_test_navigation(request)


def run_desktop(arguments: Sequence[str] | None = None) -> int:
    """Launch the localized PySide6 dashboard."""

    existing = QApplication.instance()
    owns_app = existing is None
    if existing is None:
        app = QApplication(list(arguments or sys.argv))
    elif isinstance(existing, QApplication):
        app = existing
    else:
        raise RuntimeError(
            "The desktop dashboard requires a QApplication, not a bare QCoreApplication."
        )

    translator = Translator.from_environment()
    window = MainWindow(translator)
    # Everything the operator extracted earlier is adopted before the window is shown, so a
    # complete install never needs a manual reload step (US-085).
    window.reload_client_data()
    feed = DashboardFeed()
    feed.update_available.connect(window.update_dashboard)

    controller = WindowsInputController()
    windows = controller.find_windows(DEFAULT_PROCESS_NAME)
    frame_source = WindowsFrameSource()

    if windows:
        window_handle = windows[0].handle
        window.attach_placement_target(controller, window_handle)
        model_path = Path(DEFAULT_MOB_MODEL_PATH)
        labels_path = Path(DEFAULT_MOB_LABELS_PATH)
        if model_path.is_file() and labels_path.is_file():
            allowed_names = load_class_names(labels_path)
            window.target_selection_panel.set_class_names(allowed_names)
            default_anchor_path = (
                Path(DEFAULT_TARGET_ANCHOR_PATH)
                if Path(DEFAULT_TARGET_ANCHOR_PATH).is_file()
                else None
            )
            anchors = load_mob_anchor_templates(
                allowed_names, default_anchor_path=default_anchor_path
            )
            if anchors:
                detector = OpenCVDnnYoloDetector.from_files(
                    model_path,
                    labels_path,
                    DetectionConfig(
                        confidence_threshold=0.5,
                        allowed_class_names=frozenset(allowed_names),
                    ),
                )
                target_verifier = TargetVerifier(
                    allowed_names,
                    anchors,
                    TesseractTextRecognizer(language=TESSERACT_LANGUAGE_ENGLISH),
                    tactical_parameters=window.tactical_parameters,
                )
                player_stats_reader = LivePlayerStatsReader(window_handle)
                pipeline = PerceptionPipeline(
                    frame_source,
                    detector,
                    target_verifier,
                    player_stats_reader=player_stats_reader,
                )
                apply_target_classes = target_class_applier(
                    detector,
                    target_verifier,
                    allowed_names,
                    default_anchor_path=default_anchor_path,
                )
                position_reader = LivePositionReader(window_handle)
                camera_reader = LiveCameraReader(window_handle)
                emergency_config = window.get_emergency_config()
                teleporter_input = TeleporterWindowsInput(
                    controller,
                    window_handle,
                    dialog_locator=TemplateTeleporterDialogLocator(
                        frame_source,
                        Path(DEFAULT_CLIENT_DATA_ROOT),
                    ),
                )
                teleporter_dispatcher = TeleporterDispatcher(
                    teleporter_input,
                    window_handle,
                    LiveArrivalObserver(position_reader, LiveWorldIdReader(window_handle)),
                    config=TeleporterDispatchConfig(
                        hotkey_virtual_key=emergency_config.teleporter_hotkey_virtual_key,
                        confirmation_timeout_seconds=(
                            emergency_config.confirmation_timeout_seconds
                        ),
                    ),
                )
                pathing = PathingController(
                    position_reader=position_reader,
                    camera_reader=camera_reader,
                    tactical_parameters=window.tactical_parameters,
                    teleporter_dispatcher=teleporter_dispatcher,
                )
                # The pathing controller polls the camera and owns the baked mesh, so it is
                # what lets a perception tick unproject its own detections (US-057).
                pipeline.attach_world_geometry(pathing)
                # The extracted catalog is what turns a class name into the mover the client
                # actually declares. Absent artifacts leave detections unenriched (US-083).
                pipeline.attach_client_catalog(window.mob_catalog_join)
                # A wizard run mid-session republishes the join, so a fresh extraction takes
                # effect without restarting the application (US-085).
                window.client_data_reloaded.connect(pipeline.attach_client_catalog)
                try:
                    dungeon_definitions = load_dungeon_database(Path(DEFAULT_DUNGEON_DATABASE_PATH))
                except OSError, ValueError:
                    dungeon_definitions = ()
                dungeon_reader = (
                    LiveDungeonCooldownReader(
                        window_handle,
                        {definition.dungeon_id: definition for definition in dungeon_definitions},
                    )
                    if dungeon_definitions
                    else None
                )
                quest_menu_perceiver = QuestMenuPerceiver(
                    TesseractTextRecognizer(language=TESSERACT_LANGUAGE_ENGLISH),
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
                        emergency=emergency_config,
                        tactical_parameters=window.tactical_parameters,
                        auto_align_camera=window.auto_align_toggle.isChecked(),
                        policy_mode=window.policy_mode,
                        policy_model_directory=window.policy_model_directory,
                    ),
                    dashboard_feed=feed,
                    pathing=pathing,
                    camera_aligner=CameraAligner(
                        controller,
                        window_handle,
                        camera_reader,
                        tactical_parameters=window.tactical_parameters,
                    ),
                    kill_goals=KillGoalTracker(
                        window.target_selection,
                        recorder=SqliteKillLog(Path(DEFAULT_KILL_LOG_PATH)),
                    ),
                    on_target_classes_changed=apply_target_classes,
                    quest_menu_perceiver=quest_menu_perceiver,
                    event_logger=SessionEventLogger(DEFAULT_SESSION_LOG_DIRECTORY),
                    foreground_window_info=controller.foreground_window_info,
                    teleporter_catalog=window.teleporter_catalog,
                    dungeon_provider=dungeon_reader,
                )

                def reload_memory_profiles(_profile_update: object) -> None:
                    position_reader.reload_profiles()
                    camera_reader.reload_profiles()
                    player_stats_reader.reload_profiles()
                    pipeline.restore_player_stats_provider(player_stats_reader)
                    if dungeon_reader is not None:
                        dungeon_reader.reload_profiles()
                    orchestrator.restore_player_stats_readiness()

                window.memory_profiles_updated.connect(reload_memory_profiles)
                window.attack_key_changed.connect(orchestrator.configure_attack_key)
                window.combat_grace_changed.connect(orchestrator.configure_combat_grace)
                window.combat_class_changed.connect(orchestrator.configure_combat_class)
                window.policy_mode_changed.connect(orchestrator.configure_policy_mode)
                window.policy_model_directory_changed.connect(
                    orchestrator.configure_policy_model_directory
                )
                window.engagement_distance_changed.connect(
                    orchestrator.configure_engagement_distance
                )
                window.tactical_parameters_changed.connect(
                    orchestrator.configure_tactical_parameters
                )
                window.tactical_parameters_changed.connect(
                    lambda parameters: target_verifier.update_anchor_threshold(
                        parameters.target_verification_threshold
                    )
                )
                window.kill_verification_changed.connect(orchestrator.configure_kill_verification)
                window.anchor_threshold_changed.connect(target_verifier.update_anchor_threshold)
                connect_target_selection(window, orchestrator)
                connect_farming_controls(
                    window,
                    orchestrator,
                    on_start=lambda: start_farming(controller, window_handle, orchestrator),
                )
                connect_vector_navigation(window, orchestrator)
                connect_test_navigation(
                    window,
                    orchestrator,
                    on_start=lambda req: start_test_navigation(
                        controller, window_handle, orchestrator, req
                    ),
                )
                connect_quest_selection(
                    window,
                    orchestrator,
                    lambda: QuestGoalResolver(
                        None
                        if pathing.vector_navigator is None
                        else pathing.vector_navigator.world_map,
                        window.quest_npc_positions,
                    ),
                )
                window.autopilot_arm_requested.connect(
                    lambda: arm_autopilot(controller, window_handle, orchestrator)
                )
                worker = SessionWorker(
                    orchestrator.tick,
                    STANDBY_TICK_INTERVAL_SECONDS,
                    on_fault=orchestrator.handle_tick_fault,
                )
                window._teardowns.append(worker.stop)
                worker.start()
                # A dead worker thread must not leave the dashboard presenting its last
                # successful state as if the session were still running (US-086).
                watchdog = QTimer(window)
                watchdog.setInterval(
                    round(WORKER_WATCHDOG_INTERVAL_SECONDS * MILLISECONDS_PER_SECOND)
                )
                watchdog.timeout.connect(
                    lambda: window.set_worker_stalled(
                        is_worker_stalled(
                            is_running=worker.is_running,
                            health=worker.health,
                            now=monotonic(),
                            tick_interval_seconds=STANDBY_TICK_INTERVAL_SECONDS,
                        )
                    )
                )
                watchdog.start()
                window._teardowns.append(watchdog.stop)
    else:
        window.window_label.setText(
            translator.text(Message.UI_WINDOW_NOT_FOUND, process=DEFAULT_PROCESS_NAME)
        )

    apply_theme(window)
    window.show()
    # Only a fresh install with no extracted data opens the wizard automatically; a partial
    # or complete install opens the dashboard directly, with the wizard still reachable from
    # the menu and the Start button reporting any remaining gap (US-088).
    if window.is_setup_autostart_required():
        window.show_setup_wizard()

    if owns_app:
        exit_code = app.exec()
        for teardown in window._teardowns:
            teardown()
        return exit_code
    return 0


def _load_template(path: str) -> npt.NDArray[np.uint8]:
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Template image not readable: {path}")
    return cast("npt.NDArray[np.uint8]", image)
