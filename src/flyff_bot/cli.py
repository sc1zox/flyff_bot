"""Command-line interface for Flyff Bot."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.constants import (
    DEFAULT_CLIENT_CATALOG_PATH,
    DEFAULT_CLIENT_DATA_ROOT,
    DEFAULT_CLIENT_WORLD_ROOT,
    DEFAULT_DATASET_MANIFEST_PATH,
    DEFAULT_DUNGEON_DATABASE_PATH,
    DEFAULT_KEY_DURATION_SECONDS,
    DEFAULT_MOB_LABELS_PATH,
    DEFAULT_MOB_MODEL_PATH,
    DEFAULT_MOVER_LABEL_MAPPING_PATH,
    DEFAULT_POLICY_MODEL_DIRECTORY,
    DEFAULT_PROCESS_NAME,
    DEFAULT_QUEST_DATABASE_PATH,
    DEFAULT_SOURCE_MANIFEST_PATH,
    DEFAULT_START_DELAY_SECONDS,
    DEFAULT_TARGET_ANCHOR_PATH,
    DEFAULT_TELEMETRY_AREA_ID,
    DEFAULT_TELEMETRY_DATABASE_PATH,
    DEFAULT_TELEMETRY_DATASET_PATH,
    DEFAULT_TELEMETRY_ROOT,
    DEFAULT_TELEPORTER_DATABASE_PATH,
    DEFAULT_TRAINING_EPOCHS,
    DEFAULT_WORLD_MAP_DIRECTORY,
    DEFAULT_WORLD_MONSTER_IDS_PATH,
    MINIMUM_KEY_DURATION_SECONDS,
    ExitCode,
)
from flyff_bot.features.automation.controllers import (
    CombatConfig,
    KeyBinding,
    SearchConfig,
)
from flyff_bot.features.automation.models import DesiredState
from flyff_bot.features.automation.orchestrator import (
    FarmingConfig,
    FarmingOrchestrator,
)
from flyff_bot.features.dungeons.extraction import (
    DungeonExtractionDiagnostic,
    extract_dungeon_definitions,
)
from flyff_bot.features.dungeons.persistence import save_dungeon_database
from flyff_bot.features.input_control import (
    InputControlError,
    InputErrorCode,
    WindowsInputController,
    parse_virtual_key,
)
from flyff_bot.features.navigation.client_archive import ClientArchiveError
from flyff_bot.features.navigation.live_camera import LiveCameraReader
from flyff_bot.features.navigation.live_position import LivePositionReader
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshBaker
from flyff_bot.features.navigation.navmesh_persistence import (
    load_baked_navmesh,
    save_baked_navmesh,
    world_navmesh_path,
)
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.teleporter_extraction import (
    TeleporterExtractionDiagnostic,
    TeleporterExtractionWarning,
    extract_teleporter_catalog,
    save_teleporter_catalog,
)
from flyff_bot.features.navigation.world_extractor import (
    ExtractionDiagnostic,
    ExtractionWarning,
    WorldExtractionError,
    discover_world_directories,
    extract_world,
    load_monster_names,
    save_world_map,
    summarize,
)
from flyff_bot.features.navigation.world_geometry import terrain_triangles
from flyff_bot.features.perception.catalog_join import load_mob_catalog_join
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.player_stats.reader import LivePlayerStatsReader
from flyff_bot.features.policy.models import (
    DEFAULT_POLICY_RUNTIME_MODE,
    PolicyRuntimeMode,
)
from flyff_bot.features.quests.extraction import (
    DEFAULT_QUEST_LANGUAGE,
    QuestExtractionDiagnostic,
    QuestExtractionWarning,
    extract_quest_database,
)
from flyff_bot.features.quests.persistence import save_quest_database
from flyff_bot.features.telemetry import (
    JsonlTelemetryWorker,
    SqliteTelemetryStore,
    TelemetryDatasetExporter,
    TelemetryRecorder,
    TelemetrySessionMetadata,
)
from flyff_bot.features.training import TrainingError, train_and_export, validate_dataset
from flyff_bot.features.vision import (
    DetectionConfig,
    DetectionError,
    FrameCaptureError,
    FrameCaptureErrorCode,
    OpenCVDnnYoloDetector,
    TargetVerifier,
    TesseractTextRecognizer,
    WindowsFrameSource,
    load_class_names,
    load_mob_anchor_templates,
)
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import FarmingGoal

COUNTDOWN_POLL_SECONDS = 0.05
BOT_VERSION = "0.1.0"


class FarmingConfigurationError(ValueError):
    """A localized configuration problem that prevents starting a farm session."""

    def __init__(self, message: Message) -> None:
        super().__init__(message.value)
        self.message = message


def _selected_language(arguments: Sequence[str] | None) -> Language:
    default_language = Translator.from_environment().language
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--language", choices=[language.value for language in Language])
    known_arguments, _ = parser.parse_known_args(arguments)
    if known_arguments.language is None:
        return default_language
    return Language(known_arguments.language)


def _argument_parser(translator: Translator) -> argparse.ArgumentParser:
    def key_type(value: str) -> int:
        try:
            return parse_virtual_key(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(translator.text(Message.INVALID_KEY)) from error

    parser = argparse.ArgumentParser(description=translator.text(Message.APP_DESCRIPTION))
    parser.add_argument(
        "--language",
        choices=[language.value for language in Language],
        default=translator.language.value,
        help=translator.text(Message.HELP_LANGUAGE),
    )
    parser.add_argument(
        "--process",
        default=DEFAULT_PROCESS_NAME,
        help=translator.text(Message.HELP_PROCESS, default=DEFAULT_PROCESS_NAME),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help=translator.text(Message.HELP_LIST),
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--key",
        type=key_type,
        metavar="KEY",
        help=translator.text(Message.HELP_KEY),
    )
    actions.add_argument(
        "--validate-mob-dataset",
        action="store_true",
        help=translator.text(Message.HELP_VALIDATE_MOB_DATASET),
    )
    actions.add_argument(
        "--train-mob-detector",
        action="store_true",
        help=translator.text(Message.HELP_TRAIN_MOB_DETECTOR),
    )
    actions.add_argument(
        "--export-telemetry",
        action="store_true",
        help=translator.text(Message.HELP_EXPORT_TELEMETRY),
    )
    parser.add_argument(
        "--telemetry-database",
        default=DEFAULT_TELEMETRY_DATABASE_PATH,
        help=translator.text(
            Message.HELP_TELEMETRY_DATABASE, default=DEFAULT_TELEMETRY_DATABASE_PATH
        ),
    )
    parser.add_argument(
        "--telemetry-dataset",
        default=DEFAULT_TELEMETRY_DATASET_PATH,
        help=translator.text(
            Message.HELP_TELEMETRY_DATASET, default=DEFAULT_TELEMETRY_DATASET_PATH
        ),
    )
    parser.add_argument(
        "--telemetry-root",
        default=DEFAULT_TELEMETRY_ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--telemetry-area",
        default=DEFAULT_TELEMETRY_AREA_ID,
        help=translator.text(Message.HELP_TELEMETRY_AREA, default=DEFAULT_TELEMETRY_AREA_ID),
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET_MANIFEST_PATH,
        help=translator.text(Message.HELP_DATASET, default=DEFAULT_DATASET_MANIFEST_PATH),
    )
    parser.add_argument(
        "--output-model",
        default=DEFAULT_MOB_MODEL_PATH,
        help=translator.text(Message.HELP_OUTPUT_MODEL, default=DEFAULT_MOB_MODEL_PATH),
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=DEFAULT_TRAINING_EPOCHS,
        help=translator.text(Message.HELP_EPOCHS, default=DEFAULT_TRAINING_EPOCHS),
    )
    parser.add_argument("--base-model", help=translator.text(Message.HELP_BASE_MODEL))
    actions.add_argument(
        "--extract-world",
        action="store_true",
        help=translator.text(Message.HELP_EXTRACT_WORLD),
    )
    parser.add_argument(
        "--client-world-root",
        default=DEFAULT_CLIENT_WORLD_ROOT,
        help=translator.text(Message.HELP_CLIENT_WORLD_ROOT, default=DEFAULT_CLIENT_WORLD_ROOT),
    )
    parser.add_argument(
        "--world-map-directory",
        default=DEFAULT_WORLD_MAP_DIRECTORY,
        help=translator.text(Message.HELP_WORLD_MAP_DIRECTORY, default=DEFAULT_WORLD_MAP_DIRECTORY),
    )
    parser.add_argument(
        "--bake-navmesh",
        action="store_true",
        help=translator.text(Message.HELP_BAKE_NAVMESH),
    )
    parser.add_argument(
        "--navmesh-map",
        help=translator.text(Message.HELP_NAVMESH_MAP),
    )
    parser.add_argument(
        "--world",
        action="append",
        default=[],
        help=translator.text(Message.HELP_WORLD_REGION),
    )
    actions.add_argument(
        "--extract-quests",
        action="store_true",
        help=translator.text(Message.HELP_EXTRACT_QUESTS),
    )
    actions.add_argument(
        "--extract-teleporters",
        action="store_true",
        help=translator.text(Message.HELP_EXTRACT_TELEPORTERS),
    )
    actions.add_argument(
        "--extract-dungeons",
        action="store_true",
        help=translator.text(Message.HELP_EXTRACT_DUNGEONS),
    )
    parser.add_argument(
        "--client-data-root",
        default=DEFAULT_CLIENT_DATA_ROOT,
        help=translator.text(Message.HELP_CLIENT_DATA_ROOT, default=DEFAULT_CLIENT_DATA_ROOT),
    )
    parser.add_argument(
        "--quest-database",
        default=DEFAULT_QUEST_DATABASE_PATH,
        help=translator.text(Message.HELP_QUEST_DATABASE, default=DEFAULT_QUEST_DATABASE_PATH),
    )
    parser.add_argument(
        "--quest-language",
        default=DEFAULT_QUEST_LANGUAGE,
        help=translator.text(Message.HELP_QUEST_LANGUAGE, default=DEFAULT_QUEST_LANGUAGE),
    )
    parser.add_argument(
        "--teleporter-database",
        default=DEFAULT_TELEPORTER_DATABASE_PATH,
        help=translator.text(
            Message.HELP_TELEPORTER_DATABASE, default=DEFAULT_TELEPORTER_DATABASE_PATH
        ),
    )
    parser.add_argument(
        "--dungeon-database",
        default=DEFAULT_DUNGEON_DATABASE_PATH,
        help=translator.text(Message.HELP_DUNGEON_DATABASE, default=DEFAULT_DUNGEON_DATABASE_PATH),
    )
    actions.add_argument(
        "--detect-mobs",
        action="store_true",
        help=translator.text(Message.HELP_DETECT_MOBS),
    )
    actions.add_argument(
        "--farm",
        "--auto",
        action="store_true",
        help=translator.text(Message.HELP_FARM),
    )
    parser.add_argument("--model", help=translator.text(Message.HELP_MODEL))
    parser.add_argument("--labels", help=translator.text(Message.HELP_LABELS))
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help=translator.text(Message.HELP_CONFIDENCE, default=0.5),
    )
    parser.add_argument(
        "--class-name",
        action="append",
        default=[],
        help=translator.text(Message.HELP_CLASS_NAME),
    )
    actions.add_argument(
        "--click",
        nargs=2,
        type=int,
        metavar=("X", "Y"),
        help=translator.text(Message.HELP_CLICK),
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_KEY_DURATION_SECONDS,
        help=translator.text(Message.HELP_DURATION, default=DEFAULT_KEY_DURATION_SECONDS),
    )
    parser.add_argument(
        "--rotation-key",
        type=key_type,
        action="append",
        default=[],
        help=translator.text(Message.HELP_ROTATION_KEY),
    )
    parser.add_argument(
        "--attack-cooldown",
        type=float,
        default=0.5,
        help=translator.text(Message.HELP_ATTACK_COOLDOWN, default=0.5),
    )
    parser.add_argument(
        "--search-retry",
        type=float,
        default=0.5,
        help=translator.text(Message.HELP_SEARCH_RETRY, default=0.5),
    )
    parser.add_argument(
        "--search-idle-timeout",
        type=float,
        default=5.0,
        help=translator.text(Message.HELP_SEARCH_IDLE_TIMEOUT, default=5.0),
    )
    parser.add_argument(
        "--search-rotation-duration",
        type=float,
        default=0.2,
        help=translator.text(Message.HELP_SEARCH_ROTATION_DURATION, default=0.2),
    )
    parser.add_argument(
        "--search-settle-pause",
        type=float,
        default=0.3,
        help=translator.text(Message.HELP_SEARCH_SETTLE_PAUSE, default=0.3),
    )
    parser.add_argument(
        "--search-movement-duration",
        type=float,
        default=1.0,
        help=translator.text(Message.HELP_SEARCH_MOVEMENT_DURATION, default=1.0),
    )
    parser.add_argument(
        "--policy-mode",
        choices=[mode.value for mode in PolicyRuntimeMode],
        default=DEFAULT_POLICY_RUNTIME_MODE.value,
        help=translator.text(Message.HELP_POLICY_MODE),
    )
    parser.add_argument(
        "--policy-model-dir",
        default=DEFAULT_POLICY_MODEL_DIRECTORY,
        help=translator.text(Message.HELP_POLICY_MODEL_DIR, default=DEFAULT_POLICY_MODEL_DIRECTORY),
    )
    parser.add_argument("--goal-item", help=translator.text(Message.HELP_GOAL_ITEM))
    parser.add_argument("--goal-count", type=int, help=translator.text(Message.HELP_GOAL_COUNT))
    parser.add_argument("--target-anchor", help=translator.text(Message.HELP_TARGET_ANCHOR))
    parser.add_argument(
        "--target-name",
        action="append",
        default=[],
        help=translator.text(Message.HELP_TARGET_NAME),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_START_DELAY_SECONDS,
        help=translator.text(Message.HELP_DELAY, default=DEFAULT_START_DELAY_SECONDS),
    )
    return parser


def _known_error_message(error: InputControlError) -> Message:
    if error.code is InputErrorCode.UNSUPPORTED_PLATFORM:
        return Message.WINDOWS_ONLY
    return Message.FOCUS_FAILED


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the input-control command and return a stable process exit code."""

    language = _selected_language(arguments)
    translator = Translator(language)
    args = _argument_parser(translator).parse_args(arguments)

    try:
        dataset_path = Path(args.dataset)
        if args.validate_mob_dataset:
            result = validate_dataset(dataset_path)
            if result.is_valid:
                print(translator.text(Message.DATASET_VALID, dataset=dataset_path))
                return ExitCode.SUCCESS
            for issue in result.issues:
                print(
                    translator.text(Message.DATASET_ISSUE, code=issue.code, path=issue.path),
                    file=sys.stderr,
                )
            return ExitCode.DATASET_FAILURE
        if args.train_mob_detector:
            train_and_export(
                dataset_path,
                Path(args.output_model),
                Path(DEFAULT_MOB_LABELS_PATH),
                base_model=args.base_model or "yolo11n.pt",
                epochs=args.epochs,
            )
            print(
                translator.text(
                    Message.TRAINING_COMPLETE,
                    model=Path(args.output_model),
                    labels=Path(DEFAULT_MOB_LABELS_PATH),
                )
            )
            return ExitCode.SUCCESS
        if args.export_telemetry:
            paths = TelemetryDatasetExporter(
                SqliteTelemetryStore(Path(args.telemetry_database))
            ).export(Path(args.telemetry_dataset))
            print(translator.text(Message.TELEMETRY_EXPORTED))
            for path in paths:
                print(path)
            return ExitCode.SUCCESS
        if args.extract_world:
            return _extract_worlds(args, translator)
        if args.extract_quests:
            return _extract_quests(args, translator)
        if args.extract_teleporters:
            return _extract_teleporters(args, translator)
        if args.extract_dungeons:
            return _extract_dungeons(args, translator)
        controller = WindowsInputController()
        windows = controller.find_windows(args.process)
        if not windows:
            print(translator.text(Message.NO_WINDOW, process=args.process), file=sys.stderr)
            return ExitCode.WINDOW_NOT_FOUND

        for index, window in enumerate(windows):
            print(
                translator.text(
                    Message.WINDOW_LINE,
                    index=index,
                    handle=window.handle,
                    title=repr(window.title),
                )
            )
        if args.list or (
            args.key is None and args.click is None and not args.detect_mobs and not args.farm
        ):
            return ExitCode.SUCCESS

        window_handle = windows[0].handle
        delay_seconds = max(0.0, args.delay)
        if delay_seconds > 0.0:
            print(translator.text(Message.COUNTDOWN, seconds=f"{delay_seconds:g}"))
            deadline = time.monotonic() + delay_seconds
            while time.monotonic() < deadline:
                if controller.is_aborted():
                    print(translator.text(Message.ABORTED))
                    return ExitCode.ABORTED
                time.sleep(COUNTDOWN_POLL_SECONDS)

        controller.focus_window(window_handle)
        if controller.is_aborted():
            print(translator.text(Message.ABORTED))
            return ExitCode.ABORTED

        if args.farm:
            orchestrator = _farming_orchestrator(args, controller, window_handle)
            print(translator.text(Message.FARM_STARTED))
            orchestrator.start()
            try:
                asyncio.run(orchestrator.run())
            finally:
                orchestrator.close()
            if orchestrator.mode.name == "EMERGENCY_STOPPED":
                print(translator.text(Message.ABORTED))
                return ExitCode.ABORTED
            print(translator.text(Message.FARM_STOPPED))
            return ExitCode.SUCCESS

        if args.detect_mobs:
            if args.model is None or args.labels is None:
                print(translator.text(Message.DETECTION_OPTIONS_REQUIRED), file=sys.stderr)
                return ExitCode.DETECTION_FAILURE
            detector = OpenCVDnnYoloDetector.from_files(
                Path(args.model),
                Path(args.labels),
                DetectionConfig(
                    confidence_threshold=args.confidence,
                    allowed_class_names=frozenset(args.class_name),
                ),
            )
            frame = WindowsFrameSource().capture(window_handle)
            detections = detector.detect(frame)
            print(translator.text(Message.DETECTION_SUMMARY, count=len(detections)))
            for detection in detections:
                box = detection.bounding_box
                print(
                    translator.text(
                        Message.DETECTION_LINE,
                        class_name=detection.class_name,
                        confidence=f"{detection.confidence:.2f}",
                        x=box.x,
                        y=box.y,
                        width=box.width,
                        height=box.height,
                    )
                )
            return ExitCode.SUCCESS

        if args.key is not None:
            controller.send_key(args.key, max(MINIMUM_KEY_DURATION_SECONDS, args.duration))
        else:
            controller.click_client(window_handle, *args.click)
        print(translator.text(Message.INPUT_SENT))
        return ExitCode.SUCCESS
    except FrameCaptureError as error:
        capture_messages = {
            FrameCaptureErrorCode.INVALID_WINDOW: Message.FRAME_INVALID_WINDOW,
            FrameCaptureErrorCode.MINIMIZED: Message.FRAME_MINIMIZED,
            FrameCaptureErrorCode.OCCLUDED: Message.FRAME_OCCLUDED,
            FrameCaptureErrorCode.CAPTURE_FAILED: Message.FRAME_CAPTURE_FAILED,
            FrameCaptureErrorCode.UNSUPPORTED_PLATFORM: Message.WINDOWS_ONLY,
        }
        print(translator.text(capture_messages[error.code]), file=sys.stderr)
        return ExitCode.DETECTION_FAILURE
    except TrainingError as error:
        print(translator.text(Message.TRAINING_FAILED, reason=error), file=sys.stderr)
        return ExitCode.TRAINING_FAILURE
    except FarmingConfigurationError as error:
        print(translator.text(error.message), file=sys.stderr)
        return ExitCode.DETECTION_FAILURE
    except (InputControlError, DetectionError, ValueError) as error:
        if args.export_telemetry:
            print(translator.text(Message.TELEMETRY_EXPORT_FAILED, reason=error), file=sys.stderr)
            return ExitCode.DATASET_FAILURE
        if isinstance(error, DetectionError | ValueError):
            print(translator.text(Message.DETECTION_FAILED, reason=error), file=sys.stderr)
            return ExitCode.DETECTION_FAILURE
        print(translator.text(_known_error_message(error)), file=sys.stderr)
        return ExitCode.INPUT_FAILURE
    except OSError as error:
        if args.export_telemetry:
            print(translator.text(Message.TELEMETRY_EXPORT_FAILED, reason=error), file=sys.stderr)
            return ExitCode.DATASET_FAILURE
        print(translator.text(Message.INPUT_FAILED, reason=error), file=sys.stderr)
        return ExitCode.INPUT_FAILURE


_ARCHIVE_WARNING_MESSAGES = {
    ExtractionWarning.UNSUPPORTED_ARCHIVE_INDEX: Message.WORLD_ARCHIVE_INDEX_SKIPPED,
    ExtractionWarning.UNREADABLE_ARCHIVE_BLOCK: Message.WORLD_ARCHIVE_BLOCK_SKIPPED,
    ExtractionWarning.UNREADABLE_OBJECT_FILE: Message.WORLD_OBJECT_FILE_SKIPPED,
}


def _extract_worlds(args: argparse.Namespace, translator: Translator) -> int:
    """Extract the selected client regions offline and report what each one produced.

    Extraction never touches the game process or the client's own files, so it runs before
    any window is looked up. One region that cannot be read leaves the others untouched and
    only changes the exit code.
    """

    root = Path(args.client_world_root)
    output_directory = Path(args.world_map_directory)
    regions = discover_world_directories(root)
    selected = {name.lower() for name in args.world}
    if selected:
        regions = tuple(region for region in regions if region.name.lower() in selected)
    if not regions:
        print(translator.text(Message.WORLD_EXTRACTION_NO_REGIONS, root=root), file=sys.stderr)
        return ExitCode.WORLD_EXTRACTION_FAILURE
    monster_names_path = Path(DEFAULT_WORLD_MONSTER_IDS_PATH)
    monster_names = load_monster_names(monster_names_path) if monster_names_path.is_file() else {}
    failed = False
    for region in regions:
        diagnostics: list[ExtractionDiagnostic] = []
        try:
            world_map = extract_world(region, monster_names=monster_names, diagnostics=diagnostics)
            summary = summarize(world_map, save_world_map(world_map, output_directory), diagnostics)
            artifact = (
                save_baked_navmesh(
                    NavMeshBaker().bake(
                        terrain_triangles(world_map.terrain_blocks, world_map.dimensions)
                    ),
                    world_navmesh_path(output_directory, world_map.world_name),
                )
                if args.bake_navmesh
                else None
            )
        except (OSError, WorldExtractionError) as error:
            print(
                translator.text(Message.WORLD_EXTRACTION_FAILED, world=region.name, reason=error),
                file=sys.stderr,
            )
            failed = True
            continue
        for diagnostic in summary.diagnostics:
            print(
                translator.text(
                    _ARCHIVE_WARNING_MESSAGES[diagnostic.warning],
                    world=region.name,
                    detail=diagnostic.detail,
                ),
                file=sys.stderr,
            )
        print(
            translator.text(
                Message.WORLD_EXTRACTED,
                world=summary.world_name,
                blocks=summary.terrain_block_count,
                declared=summary.declared_block_count,
                zones=summary.zone_count,
                obstacles=summary.obstacle_count,
                path=summary.output_path,
            )
        )
        if artifact is not None:
            print(
                translator.text(
                    Message.NAVMESH_BAKED,
                    world=summary.world_name,
                    polygons=len(artifact.mesh.polygons),
                    path=artifact.path,
                )
            )
    print(
        translator.text(
            Message.WORLD_EXTRACTION_COMPLETE,
            regions=len(regions),
            directory=output_directory,
        )
    )
    return ExitCode.WORLD_EXTRACTION_FAILURE if failed else ExitCode.SUCCESS


_QUEST_WARNING_MESSAGES = {
    QuestExtractionWarning.MISSING_QUEST_SCRIPT: Message.QUEST_SCRIPT_SKIPPED,
    QuestExtractionWarning.MISSING_CLIENT_TABLE: Message.QUEST_TABLE_SKIPPED,
    QuestExtractionWarning.UNREADABLE_ARCHIVE: Message.QUEST_ARCHIVE_SKIPPED,
}


def _extract_quests(args: argparse.Namespace, translator: Translator) -> int:
    """Extract the client's quest definitions offline and write the JSON database.

    Extraction reads the client's own packed data and writes only into this repository's
    artifact directory, so it opens no game window and modifies no client file.
    """

    root = Path(args.client_data_root)
    output_path = Path(args.quest_database)
    diagnostics: list[QuestExtractionDiagnostic] = []
    try:
        database = extract_quest_database(
            root, language=args.quest_language, diagnostics=diagnostics
        )
    except (OSError, ClientArchiveError) as error:
        print(
            translator.text(Message.QUEST_EXTRACTION_FAILED, reason=error),
            file=sys.stderr,
        )
        return ExitCode.QUEST_EXTRACTION_FAILURE
    for diagnostic in diagnostics:
        message = _QUEST_WARNING_MESSAGES.get(diagnostic.warning)
        if message is not None:
            print(translator.text(message, detail=diagnostic.detail), file=sys.stderr)
    if not database.quests:
        print(
            translator.text(Message.QUEST_ARCHIVE_MISSING, path=root),
            file=sys.stderr,
        )
        return ExitCode.QUEST_EXTRACTION_FAILURE
    save_quest_database(database, output_path)
    print(
        translator.text(
            Message.QUEST_EXTRACTED,
            quests=len(database.quests),
            farmable=len(database.farmable),
            path=output_path,
        )
    )
    return ExitCode.SUCCESS


def _extract_teleporters(args: argparse.Namespace, translator: Translator) -> int:
    """Extract teleporter destinations offline and write a canonical JSON catalog."""

    root = Path(args.client_data_root)
    output_path = Path(args.teleporter_database)
    diagnostics: list[TeleporterExtractionDiagnostic] = []
    try:
        catalog = extract_teleporter_catalog(root, diagnostics=diagnostics)
    except OSError as error:
        print(
            translator.text(Message.TELEPORT_EXTRACTION_FAILED, reason=error),
            file=sys.stderr,
        )
        return ExitCode.TELEPORTER_EXTRACTION_FAILURE
    for diagnostic in diagnostics:
        message = {
            TeleporterExtractionWarning.MISSING_CLIENT_ARCHIVE: Message.TELEPORT_ASSET_MISSING,
            TeleporterExtractionWarning.MISSING_TELEPORTER_ASSET: Message.TELEPORT_ASSET_MISSING,
            TeleporterExtractionWarning.UNREADABLE_ARCHIVE: Message.TELEPORT_ARCHIVE_SKIPPED,
            TeleporterExtractionWarning.MALFORMED_RECORD: Message.TELEPORT_RECORD_SKIPPED,
        }[diagnostic.warning]
        print(translator.text(message, detail=diagnostic.detail), file=sys.stderr)
    if not catalog.destinations:
        return ExitCode.TELEPORTER_EXTRACTION_FAILURE
    save_teleporter_catalog(catalog, output_path)
    print(
        translator.text(
            Message.TELEPORT_EXTRACTED,
            destinations=len(catalog.destinations),
            path=output_path,
        )
    )
    return ExitCode.SUCCESS


def _extract_dungeons(args: argparse.Namespace, translator: Translator) -> int:
    """Extract the client's dungeon declarations offline and write the JSON database."""

    root = Path(args.client_data_root)
    output_path = Path(args.dungeon_database)
    diagnostics: list[DungeonExtractionDiagnostic] = []
    try:
        dungeons = extract_dungeon_definitions(root, diagnostics=diagnostics)
    except (OSError, ClientArchiveError) as error:
        print(
            translator.text(Message.DUNGEON_EXTRACTION_FAILED, reason=error),
            file=sys.stderr,
        )
        return ExitCode.DUNGEON_EXTRACTION_FAILURE
    if not dungeons:
        print(
            translator.text(Message.DUNGEON_ARCHIVE_MISSING, path=root),
            file=sys.stderr,
        )
        return ExitCode.DUNGEON_EXTRACTION_FAILURE
    save_dungeon_database(dungeons, output_path, language="English", client_digest="")
    print(
        translator.text(
            Message.DUNGEON_EXTRACTED,
            dungeons=len(dungeons),
            path=output_path,
        )
    )
    return ExitCode.SUCCESS


def _farming_orchestrator(
    args: argparse.Namespace, controller: WindowsInputController, window_handle: int
) -> FarmingOrchestrator:
    model_path = args.model or DEFAULT_MOB_MODEL_PATH
    labels_path = args.labels or DEFAULT_MOB_LABELS_PATH
    if (args.goal_item is None) != (args.goal_count is None):
        raise FarmingConfigurationError(Message.FARM_GOAL_REQUIRED)
    allowed_names = (
        tuple(args.target_name) or tuple(args.class_name) or load_class_names(Path(labels_path))
    )
    if args.target_anchor:
        anchors: tuple[npt.NDArray[np.uint8], ...] = (_load_template(args.target_anchor),)
    else:
        anchors = load_mob_anchor_templates(
            allowed_names,
            default_anchor_path=DEFAULT_TARGET_ANCHOR_PATH
            if Path(DEFAULT_TARGET_ANCHOR_PATH).is_file()
            else None,
        )
    if not Path(model_path).is_file() or not Path(labels_path).is_file() or not anchors:
        raise FarmingConfigurationError(Message.FARM_OPTIONS_REQUIRED)
    rotation = tuple(
        KeyBinding(virtual_key, args.attack_cooldown)
        for virtual_key in (args.rotation_key or [0x20])
    )
    goal = FarmingGoal(args.goal_item, args.goal_count) if args.goal_item is not None else None
    pipeline = PerceptionPipeline(
        WindowsFrameSource(),
        OpenCVDnnYoloDetector.from_files(
            Path(model_path),
            Path(labels_path),
            DetectionConfig(
                confidence_threshold=args.confidence,
                allowed_class_names=frozenset(args.class_name),
            ),
        ),
        TargetVerifier(allowed_names, anchors, TesseractTextRecognizer()),
        player_stats_reader=LivePlayerStatsReader(window_handle),
    )
    navmesh_artifact = load_baked_navmesh(Path(args.navmesh_map)) if args.navmesh_map else None
    pathing = PathingController(
        position_reader=LivePositionReader(window_handle),
        camera_reader=LiveCameraReader(window_handle),
        navmesh=None if navmesh_artifact is None else navmesh_artifact.mesh,
    )
    # The pathing controller polls the camera and owns the baked mesh, so it is what lets a
    # perception tick unproject its own detections onto walkable ground (US-057).
    pipeline.attach_world_geometry(pathing)
    # The extracted catalog is what turns a class name into the mover the client actually
    # declares. Absent artifacts leave detections unenriched (US-083).
    pipeline.attach_client_catalog(
        load_mob_catalog_join(
            Path(DEFAULT_CLIENT_CATALOG_PATH),
            Path(DEFAULT_MOVER_LABEL_MAPPING_PATH),
            Path(DEFAULT_SOURCE_MANIFEST_PATH),
        )
    )
    return FarmingOrchestrator(
        pipeline,
        controller,
        window_handle,
        pathing=pathing,
        config=FarmingConfig(
            combat=CombatConfig(
                allowed_class_names=frozenset(args.class_name),
                rotation=rotation,
                key_press_duration_seconds=max(MINIMUM_KEY_DURATION_SECONDS, args.duration),
            ),
            desired_state=DesiredState(),
            goal=goal,
            search_retry_seconds=args.search_retry,
            search=SearchConfig(
                idle_timeout_seconds=args.search_idle_timeout,
                rotation_step_duration_seconds=args.search_rotation_duration,
                rotation_settle_pause_seconds=args.search_settle_pause,
                movement_step_duration_seconds=args.search_movement_duration,
            ),
            policy_mode=PolicyRuntimeMode(args.policy_mode),
            policy_model_directory=args.policy_model_dir,
        ),
        telemetry=_telemetry_recorder(
            args,
            model_path,
            labels_path,
            controller,
            window_handle,
            navmesh=None if navmesh_artifact is None else navmesh_artifact.mesh,
            navmesh_version=None if navmesh_artifact is None else navmesh_artifact.content_digest,
        ),
    )


def _telemetry_recorder(
    args: argparse.Namespace,
    model_path: str,
    labels_path: str,
    controller: WindowsInputController,
    window_handle: int,
    *,
    navmesh: BakedNavMesh | None = None,
    navmesh_version: str | None = None,
) -> TelemetryRecorder:
    """Build telemetry metadata from the already-discovered, query-only client identity."""

    store = SqliteTelemetryStore(Path(args.telemetry_database))
    root = Path(args.telemetry_root)
    executable = controller.process_image_path(window_handle)
    client_sha256 = _sha256(Path(executable)) if executable is not None else None
    if navmesh is None and args.navmesh_map:
        artifact = load_baked_navmesh(Path(args.navmesh_map))
        navmesh = artifact.mesh
        navmesh_version = artifact.content_digest
    return TelemetryRecorder(
        TelemetrySessionMetadata(
            area_id=args.telemetry_area,
            client_sha256=client_sha256,
            bot_version=BOT_VERSION,
            active_models=(model_path, labels_path),
            navmesh_version=navmesh_version,
            active_spawn_zone=None,
        ),
        lambda session_id, area_id: JsonlTelemetryWorker(
            session_id, area_id, root=root, store=store
        ),
        navmesh=navmesh,
    )


def _sha256(path: Path) -> str | None:
    """Return the executable digest, retaining nullable metadata when it cannot be read."""

    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return None


def _load_template(path: str) -> npt.NDArray[np.uint8]:
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise FarmingConfigurationError(Message.FARM_TEMPLATE_UNREADABLE)
    return cast("npt.NDArray[np.uint8]", image)
