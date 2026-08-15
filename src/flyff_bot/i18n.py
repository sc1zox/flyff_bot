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
    FARM_OPTIONS_REQUIRED = "error.farm_options_required"
    FARM_GOAL_REQUIRED = "error.farm_goal_required"
    FARM_TEMPLATE_UNREADABLE = "error.farm_template_unreadable"
    DETECTION_FAILED = "error.detection_failed"
    DETECTION_SUMMARY = "status.detection_summary"
    DETECTION_LINE = "status.detection_line"
    HELP_READ_LOOT = "help.read_loot"
    HELP_FARM = "help.farm"
    HELP_ROTATION_KEY = "help.rotation_key"
    HELP_ATTACK_COOLDOWN = "help.attack_cooldown"
    HELP_LOOT_WAIT = "help.loot_wait"
    HELP_SEARCH_RETRY = "help.search_retry"
    HELP_SEARCH_IDLE_TIMEOUT = "help.search_idle_timeout"
    HELP_SEARCH_ROTATION_DURATION = "help.search_rotation_duration"
    HELP_SEARCH_TILT_DURATION = "help.search_tilt_duration"
    HELP_SEARCH_SETTLE_PAUSE = "help.search_settle_pause"
    HELP_SEARCH_TILT_KEY = "help.search_tilt_key"
    HELP_SEARCH_MOVEMENT_DURATION = "help.search_movement_duration"
    HELP_NAVIGATION_MAP = "help.navigation_map"
    HELP_GOAL_ITEM = "help.goal_item"
    HELP_GOAL_COUNT = "help.goal_count"
    HELP_TARGET_ANCHOR = "help.target_anchor"
    HELP_TARGET_TEMPLATE = "help.target_template"
    LOOT_OCR_ENGINE_UNAVAILABLE = "error.loot_ocr_engine_unavailable"
    LOOT_OCR_FAILED = "error.loot_ocr_failed"
    LOOT_SUMMARY = "status.loot_summary"
    LOOT_LINE = "status.loot_line"
    FARM_STARTED = "status.farm_started"
    FARM_STOPPED = "status.farm_stopped"
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
    UI_STATUS_ACTIVE = "ui.status_active"
    UI_STATUS_PAUSED = "ui.status_paused"
    UI_STATUS_EMERGENCY_STOPPED = "ui.status_emergency_stopped"
    UI_STATUS_RECONCILING = "ui.status_reconciling"
    UI_STATUS_SEARCH_ROTATING = "ui.status_search_rotating"
    UI_STATUS_SEARCH_TILTING = "ui.status_search_tilting"
    UI_STATUS_SEARCH_ROAMING = "ui.status_search_roaming"
    UI_STATUS_SEARCH_MINIMAP = "ui.status_search_minimap"
    UI_BOT_STATUS = "ui.bot_status"
    UI_GOAL_PROGRESS = "ui.goal_progress"
    UI_NO_GOAL = "ui.no_goal"
    UI_START = "ui.start"
    UI_PAUSE = "ui.pause"
    UI_EMERGENCY_STOP = "ui.emergency_stop"
    UI_ATTACK_KEY = "ui.attack_key"
    UI_ATTACK_KEY_TOOLTIP = "ui.attack_key_tooltip"
    UI_ATTACK_KEY_RECORDING = "ui.attack_key_recording"
    UI_ATTACK_KEY_UNSUPPORTED = "ui.attack_key_unsupported"
    UI_DEBUG_OVERLAY = "ui.debug_overlay"
    UI_PATH_INSPECTOR = "ui.path_inspector"
    UI_PATH_INSPECTOR_STANDBY = "ui.path_inspector_standby"
    UI_NAV_LEGEND_PLAYER = "ui.nav_legend_player"
    UI_NAV_LEGEND_SPAWN = "ui.nav_legend_spawn"
    UI_NAV_LEGEND_PATH = "ui.nav_legend_path"
    UI_NAV_LEGEND_OBSTACLE = "ui.nav_legend_obstacle"
    UI_NAV_LEGEND_ROUTE = "ui.nav_legend_route"
    UI_NAV_LEGEND_SAFE = "ui.nav_legend_safe"
    UI_LANGUAGE = "ui.language"
    UI_LANGUAGE_GERMAN = "ui.language_german"
    UI_LANGUAGE_ENGLISH = "ui.language_english"
    UI_TARGET_VALID = "ui.target_valid"
    UI_TARGET_WRONG = "ui.target_wrong"
    UI_TARGET_NONE = "ui.target_none"
    UI_TARGET_ANNOTATION = "ui.target_annotation"
    UI_MOB_ANNOTATION = "ui.mob_annotation"
    UI_NO_TARGET_NAME = "ui.no_target_name"
    UI_PROFILE_NAME_PLACEHOLDER = "ui.profile_name_placeholder"
    UI_PROFILE_SAVE = "ui.profile_save"
    UI_PROFILE_LOAD = "ui.profile_load"
    UI_PROFILE_RESET = "ui.profile_reset"
    UI_PROFILE_RESET_TITLE = "ui.profile_reset_title"
    UI_PROFILE_RESET_PROMPT = "ui.profile_reset_prompt"
    UI_PROFILE_LOAD_ERROR_TITLE = "ui.profile_load_error_title"
    UI_PROFILE_LOAD_ERROR_PROMPT = "ui.profile_load_error_prompt"
    UI_PROFILE_CELLS_COUNT = "ui.profile_cells_count"


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
