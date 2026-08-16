"""Command-line interface for Flyff Bot."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.constants import (
    DEFAULT_DATASET_MANIFEST_PATH,
    DEFAULT_KEY_DURATION_SECONDS,
    DEFAULT_MOB_LABELS_PATH,
    DEFAULT_MOB_MODEL_PATH,
    DEFAULT_NAVIGATION_MAP_PATH,
    DEFAULT_PROCESS_NAME,
    DEFAULT_START_DELAY_SECONDS,
    DEFAULT_TRAINING_EPOCHS,
    MINIMUM_KEY_DURATION_SECONDS,
    ExitCode,
)
from flyff_bot.features.automation.controllers import (
    CombatConfig,
    KeyBinding,
    SearchConfig,
)
from flyff_bot.features.automation.models import DesiredState
from flyff_bot.features.automation.orchestrator import FarmingConfig, FarmingOrchestrator
from flyff_bot.features.input_control import (
    InputControlError,
    InputErrorCode,
    WindowsInputController,
    parse_virtual_key,
)
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.persistence import load_spatial_map
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.training import TrainingError, train_and_export, validate_dataset
from flyff_bot.features.vision import (
    DetectionConfig,
    DetectionError,
    FrameCaptureError,
    FrameCaptureErrorCode,
    LootLogReader,
    LootOcrError,
    LootOcrErrorCode,
    OpenCVDnnYoloDetector,
    TargetVerifier,
    TesseractTextRecognizer,
    WindowsFrameSource,
)
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import FarmingGoal

COUNTDOWN_POLL_SECONDS = 0.05


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
        "--detect-mobs",
        action="store_true",
        help=translator.text(Message.HELP_DETECT_MOBS),
    )
    actions.add_argument(
        "--read-loot",
        action="store_true",
        help=translator.text(Message.HELP_READ_LOOT),
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
        "--search-tilt-duration",
        type=float,
        default=0.2,
        help=translator.text(Message.HELP_SEARCH_TILT_DURATION, default=0.2),
    )
    parser.add_argument(
        "--search-settle-pause",
        type=float,
        default=0.3,
        help=translator.text(Message.HELP_SEARCH_SETTLE_PAUSE, default=0.3),
    )
    parser.add_argument(
        "--search-tilt-key",
        type=key_type,
        default=0x26,
        help=translator.text(Message.HELP_SEARCH_TILT_KEY, default="up"),
    )
    parser.add_argument(
        "--search-movement-duration",
        type=float,
        default=1.0,
        help=translator.text(Message.HELP_SEARCH_MOVEMENT_DURATION, default=1.0),
    )
    parser.add_argument(
        "--navigation-map",
        default=DEFAULT_NAVIGATION_MAP_PATH,
        help=translator.text(Message.HELP_NAVIGATION_MAP, default=DEFAULT_NAVIGATION_MAP_PATH),
    )
    parser.add_argument("--goal-item", help=translator.text(Message.HELP_GOAL_ITEM))
    parser.add_argument("--goal-count", type=int, help=translator.text(Message.HELP_GOAL_COUNT))
    parser.add_argument("--target-anchor", help=translator.text(Message.HELP_TARGET_ANCHOR))
    parser.add_argument(
        "--target-template",
        nargs=2,
        metavar=("NAME", "PATH"),
        action="append",
        default=[],
        help=translator.text(Message.HELP_TARGET_TEMPLATE),
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
            args.key is None
            and args.click is None
            and not args.detect_mobs
            and not args.read_loot
            and not args.farm
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
            asyncio.run(orchestrator.run())
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

        if args.read_loot:
            frame = WindowsFrameSource().capture(window_handle)
            events = LootLogReader(TesseractTextRecognizer()).read(frame)
            print(translator.text(Message.LOOT_SUMMARY, count=len(events)))
            for event in events:
                print(
                    translator.text(
                        Message.LOOT_LINE,
                        timestamp=event.timestamp.isoformat(),
                        item_name=event.item_name,
                        count=event.count,
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
    except LootOcrError as error:
        message = (
            Message.LOOT_OCR_ENGINE_UNAVAILABLE
            if error.code is LootOcrErrorCode.ENGINE_UNAVAILABLE
            else Message.LOOT_OCR_FAILED
        )
        print(translator.text(message), file=sys.stderr)
        return ExitCode.LOOT_OCR_FAILURE
    except TrainingError as error:
        print(translator.text(Message.TRAINING_FAILED, reason=error), file=sys.stderr)
        return ExitCode.TRAINING_FAILURE
    except FarmingConfigurationError as error:
        print(translator.text(error.message), file=sys.stderr)
        return ExitCode.DETECTION_FAILURE
    except (InputControlError, DetectionError, ValueError) as error:
        if isinstance(error, DetectionError | ValueError):
            print(translator.text(Message.DETECTION_FAILED, reason=error), file=sys.stderr)
            return ExitCode.DETECTION_FAILURE
        print(translator.text(_known_error_message(error)), file=sys.stderr)
        return ExitCode.INPUT_FAILURE
    except OSError as error:
        print(translator.text(Message.INPUT_FAILED, reason=error), file=sys.stderr)
        return ExitCode.INPUT_FAILURE


def _farming_orchestrator(
    args: argparse.Namespace, controller: WindowsInputController, window_handle: int
) -> FarmingOrchestrator:
    model_path = args.model or DEFAULT_MOB_MODEL_PATH
    labels_path = args.labels or DEFAULT_MOB_LABELS_PATH
    target_anchor = args.target_anchor or (
        "models/target_anchor.png" if Path("models/target_anchor.png").is_file() else None
    )
    target_templates = args.target_template or (
        [("Flame", "models/target_flame.png")] if Path("models/target_flame.png").is_file() else []
    )
    if (
        not Path(model_path).is_file()
        or not Path(labels_path).is_file()
        or target_anchor is None
        or not target_templates
    ):
        raise FarmingConfigurationError(Message.FARM_OPTIONS_REQUIRED)
    if (args.goal_item is None) != (args.goal_count is None):
        raise FarmingConfigurationError(Message.FARM_GOAL_REQUIRED)
    anchor = _load_template(target_anchor)
    templates = {name: _load_template(path) for name, path in target_templates}
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
        TargetVerifier(templates, anchor),
    )
    navigation_map_path = Path(args.navigation_map)
    return FarmingOrchestrator(
        pipeline,
        controller,
        window_handle,
        pathing=PathingController(
            load_spatial_map(navigation_map_path), map_path=navigation_map_path
        ),
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
                tilt_step_duration_seconds=args.search_tilt_duration,
                tilt_virtual_key=args.search_tilt_key,
                movement_step_duration_seconds=args.search_movement_duration,
            ),
        ),
    )


def _load_template(path: str) -> npt.NDArray[np.uint8]:
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise FarmingConfigurationError(Message.FARM_TEMPLATE_UNREADABLE)
    return cast("npt.NDArray[np.uint8]", image)
