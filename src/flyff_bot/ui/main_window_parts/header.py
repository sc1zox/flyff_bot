from __future__ import annotations

from flyff_bot.features.automation.kill_goals import MobKillProgress
from flyff_bot.features.navigation.live_camera import CameraReadErrorCode
from flyff_bot.features.navigation.live_position import PositionReadErrorCode
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import BotStatus, WindowStatus


def status_message(status: BotStatus) -> Message:
    return {
        BotStatus.ACTIVE: Message.UI_STATUS_ACTIVE,
        BotStatus.STANDBY: Message.UI_STATUS_STANDBY,
        BotStatus.COMPLETED: Message.UI_STATUS_COMPLETED,
        BotStatus.PAUSED: Message.UI_STATUS_PAUSED,
        BotStatus.EMERGENCY_STOPPED: Message.UI_STATUS_EMERGENCY_STOPPED,
        BotStatus.COMBAT: Message.UI_STATUS_COMBAT,
        BotStatus.RECONCILING: Message.UI_STATUS_RECONCILING,
        BotStatus.SEARCH_ROTATING: Message.UI_STATUS_SEARCH_ROTATING,
        BotStatus.SEARCH_SCANNING: Message.UI_STATUS_SEARCH_SCANNING,
        BotStatus.REPOSITIONING: Message.UI_STATUS_REPOSITIONING,
        BotStatus.APPROACHING: Message.UI_STATUS_APPROACHING,
        BotStatus.ALIGNING: Message.UI_STATUS_ALIGNING,
        BotStatus.ALIGNMENT_FAILED: Message.UI_STATUS_ALIGNMENT_FAILED,
        BotStatus.EMERGENCY_TELEPORT: Message.UI_STATUS_EMERGENCY_TELEPORT,
        BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE: (
            Message.UI_STATUS_EMERGENCY_TELEPORT_UNAVAILABLE
        ),
        BotStatus.DEAD: Message.UI_STATUS_DEAD,
        BotStatus.FAULTED: Message.UI_STATUS_FAULTED,
    }[status]


def status_category(status: BotStatus) -> str:
    if status == BotStatus.ACTIVE:
        return "active"
    if status in {BotStatus.STANDBY, BotStatus.COMPLETED}:
        return "standby"
    if status == BotStatus.COMBAT:
        return "combat"
    if status == BotStatus.PAUSED:
        return "paused"
    if status in {
        BotStatus.EMERGENCY_STOPPED,
        BotStatus.ALIGNMENT_FAILED,
        BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE,
        BotStatus.DEAD,
        BotStatus.FAULTED,
    }:
        return "emergency_stopped"
    if status in {BotStatus.RECONCILING, BotStatus.ALIGNING, BotStatus.EMERGENCY_TELEPORT}:
        return "reconciling"
    return "search"


def gps_error_message(code: PositionReadErrorCode) -> Message:
    return {
        PositionReadErrorCode.UNSUPPORTED_PLATFORM: Message.UI_GPS_ERROR_UNSUPPORTED_PLATFORM,
        PositionReadErrorCode.WINDOW_NOT_FOREGROUND: Message.UI_GPS_ERROR_WINDOW_NOT_FOREGROUND,
        PositionReadErrorCode.PROCESS_UNAVAILABLE: Message.UI_GPS_ERROR_PROCESS_UNAVAILABLE,
        PositionReadErrorCode.WRONG_PROCESS: Message.UI_GPS_ERROR_WRONG_PROCESS,
        PositionReadErrorCode.UNSUPPORTED_BUILD: Message.UI_GPS_ERROR_UNSUPPORTED_BUILD,
        PositionReadErrorCode.HANDLE_LOST: Message.UI_GPS_ERROR_HANDLE_LOST,
        PositionReadErrorCode.MALFORMED_READ: Message.UI_GPS_ERROR_MALFORMED_READ,
        PositionReadErrorCode.INVALID_PROFILE_CONFIGURATION: (
            Message.UI_GPS_ERROR_INVALID_PROFILE_CONFIGURATION
        ),
    }[code]


def camera_error_message(code: CameraReadErrorCode) -> Message:
    return {
        CameraReadErrorCode.UNSUPPORTED_PLATFORM: Message.UI_CAMERA_ERROR_UNSUPPORTED_PLATFORM,
        CameraReadErrorCode.WINDOW_NOT_FOREGROUND: Message.UI_CAMERA_ERROR_WINDOW_NOT_FOREGROUND,
        CameraReadErrorCode.PROCESS_UNAVAILABLE: Message.UI_CAMERA_ERROR_PROCESS_UNAVAILABLE,
        CameraReadErrorCode.WRONG_PROCESS: Message.UI_CAMERA_ERROR_WRONG_PROCESS,
        CameraReadErrorCode.UNSUPPORTED_BUILD: Message.UI_CAMERA_ERROR_UNSUPPORTED_BUILD,
        CameraReadErrorCode.HANDLE_LOST: Message.UI_CAMERA_ERROR_HANDLE_LOST,
        CameraReadErrorCode.MALFORMED_READ: Message.UI_CAMERA_ERROR_MALFORMED_READ,
        CameraReadErrorCode.INVALID_PROFILE_CONFIGURATION: (
            Message.UI_CAMERA_ERROR_INVALID_PROFILE_CONFIGURATION
        ),
    }[code]


def window_status_message(status: WindowStatus) -> Message:
    return {
        WindowStatus.OK: Message.UI_WINDOW_OK,
        WindowStatus.NOT_FOREGROUND: Message.UI_WINDOW_NOT_FOREGROUND,
        WindowStatus.MINIMIZED: Message.UI_WINDOW_MINIMIZED,
        WindowStatus.NOT_FOUND: Message.UI_WINDOW_NOT_FOUND,
        WindowStatus.CAPTURE_FAILED: Message.UI_WINDOW_CAPTURE_FAILED,
    }[status]


def kill_progress_text(
    translator: Translator,
    progress: tuple[MobKillProgress, ...],
) -> str:
    if not progress:
        return translator.text(Message.UI_KILL_PROGRESS_NONE)
    entries = [
        translator.text(
            (
                Message.UI_KILL_PROGRESS_UNLIMITED_ENTRY
                if item.is_unlimited
                else Message.UI_KILL_PROGRESS_ENTRY
            ),
            name=item.class_name,
            kills=item.kills,
            required=item.required_kills,
        )
        for item in progress
    ]
    return translator.text(Message.UI_KILL_PROGRESS_SUMMARY, progress=", ".join(entries))
