"""Small resource-bundle based internationalization layer."""

from __future__ import annotations

import json
import locale
from enum import StrEnum
from importlib.resources import files


class Language(StrEnum):
    """Languages shipped with the application."""

    GERMAN = "de"
    ENGLISH = "en"


class Message(StrEnum):
    """Stable identifiers for every user-visible application message."""

    APP_DESCRIPTION = "app.description"
    HELP_PROCESS = "help.process"
    HELP_LIST = "help.list"
    HELP_KEY = "help.key"
    HELP_CLICK = "help.click"
    HELP_DURATION = "help.duration"
    HELP_DELAY = "help.delay"
    HELP_LANGUAGE = "help.language"
    INVALID_KEY = "error.invalid_key"
    WINDOWS_ONLY = "error.windows_only"
    NO_WINDOW = "error.no_window"
    FOCUS_FAILED = "error.focus_failed"
    INPUT_FAILED = "error.input_failed"
    WINDOW_LINE = "status.window_line"
    COUNTDOWN = "status.countdown"
    ABORTED = "status.aborted"
    INPUT_SENT = "status.input_sent"
    UI_TITLE = "ui.title"
    UI_WORLD_STATUS = "ui.world_status"
    FRAME_INVALID_WINDOW = "error.frame_invalid_window"
    FRAME_MINIMIZED = "error.frame_minimized"
    FRAME_OCCLUDED = "error.frame_occluded"
    FRAME_CAPTURE_FAILED = "error.frame_capture_failed"
    HELP_DETECT_MOBS = "help.detect_mobs"
    HELP_MODEL = "help.model"
    HELP_LABELS = "help.labels"
    HELP_CONFIDENCE = "help.confidence"
    HELP_CLASS_NAME = "help.class_name"
    DETECTION_OPTIONS_REQUIRED = "error.detection_options_required"
    DETECTION_FAILED = "error.detection_failed"
    DETECTION_SUMMARY = "status.detection_summary"
    DETECTION_LINE = "status.detection_line"
    HELP_READ_LOOT = "help.read_loot"
    LOOT_OCR_ENGINE_UNAVAILABLE = "error.loot_ocr_engine_unavailable"
    LOOT_OCR_FAILED = "error.loot_ocr_failed"
    LOOT_SUMMARY = "status.loot_summary"
    LOOT_LINE = "status.loot_line"
    HELP_VALIDATE_MOB_DATASET = "help.validate_mob_dataset"
    HELP_TRAIN_MOB_DETECTOR = "help.train_mob_detector"
    HELP_DATASET = "help.dataset"
    HELP_OUTPUT_MODEL = "help.output_model"
    HELP_EPOCHS = "help.epochs"
    HELP_BASE_MODEL = "help.base_model"
    DATASET_VALID = "status.dataset_valid"
    DATASET_ISSUE = "status.dataset_issue"
    TRAINING_COMPLETE = "status.training_complete"
    TRAINING_FAILED = "error.training_failed"


class Translator:
    """Load and format one locale resource bundle."""

    def __init__(self, language: Language) -> None:
        resource = files("flyff_bot.locales").joinpath(f"{language.value}.json")
        raw_messages: object = json.loads(resource.read_text(encoding="utf-8"))
        if not isinstance(raw_messages, dict):
            msg = f"Invalid locale bundle: {resource.name}"
            raise TypeError(msg)
        self._messages = {str(key): str(value) for key, value in raw_messages.items()}
        self.language = language

    @classmethod
    def from_environment(cls) -> Translator:
        """Select German for German environments and English otherwise."""

        locale_name = locale.getlocale()[0] or ""
        language = Language.GERMAN if locale_name.lower().startswith("de") else Language.ENGLISH
        return cls(language)

    def text(self, message: Message, **values: object) -> str:
        """Return a formatted message and fail loudly for incomplete bundles."""

        template = self._messages[message.value]
        return template.format(**values)
