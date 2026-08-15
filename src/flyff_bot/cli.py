"""Command-line interface for Flyff Bot."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from flyff_bot.constants import (
    DEFAULT_DATASET_MANIFEST_PATH,
    DEFAULT_KEY_DURATION_SECONDS,
    DEFAULT_MOB_LABELS_PATH,
    DEFAULT_MOB_MODEL_PATH,
    DEFAULT_PROCESS_NAME,
    DEFAULT_START_DELAY_SECONDS,
    DEFAULT_TRAINING_EPOCHS,
    MINIMUM_KEY_DURATION_SECONDS,
    ExitCode,
)
from flyff_bot.features.input_control import (
    InputControlError,
    InputErrorCode,
    WindowsInputController,
    parse_virtual_key,
)
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
    TesseractTextRecognizer,
    WindowsFrameSource,
)
from flyff_bot.i18n import Language, Message, Translator

COUNTDOWN_POLL_SECONDS = 0.05


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
            args.key is None and args.click is None and not args.detect_mobs and not args.read_loot
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
    except (InputControlError, DetectionError, ValueError) as error:
        if isinstance(error, DetectionError | ValueError):
            print(translator.text(Message.DETECTION_FAILED, reason=error), file=sys.stderr)
            return ExitCode.DETECTION_FAILURE
        print(translator.text(_known_error_message(error)), file=sys.stderr)
        return ExitCode.INPUT_FAILURE
    except OSError as error:
        print(translator.text(Message.INPUT_FAILED, reason=error), file=sys.stderr)
        return ExitCode.INPUT_FAILURE
