"""Disk persistence for the unrecoverable-stuck built-in teleporter reset (US-051)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flyff_bot.features.automation.emergency_recovery import EmergencyRecoveryConfig
from flyff_bot.features.navigation.teleporter_models import TeleporterDestination

DEFAULT_EMERGENCY_CONFIG_PATH = Path("data/emergency_recovery_config.json")
JSON_INDENT_SPACES = 2
# The selected client destination has to survive restarts; an absent value deliberately
# means "no reset target", so no default destination can silently arm itself.
DESTINATION_FIELD = "destination_id"
STUCK_TIMEOUT_FIELD = "stuck_timeout_seconds"
CONFIRMATION_TIMEOUT_FIELD = "confirmation_timeout_seconds"
TELEPORTER_HOTKEY_FIELD = "teleporter_hotkey_virtual_key"
# Named so the handlers below stay single-name `except` clauses. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
CONFIG_FIELD_ERRORS = (ValueError, TypeError)
CONFIG_READ_ERRORS = (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError, TypeError)


def emergency_config_to_dict(config: EmergencyRecoveryConfig) -> dict[str, Any]:
    """Serialize an EmergencyRecoveryConfig to a JSON-compatible dictionary."""

    return {
        DESTINATION_FIELD: (
            None if config.destination is None else config.destination.destination_id
        ),
        STUCK_TIMEOUT_FIELD: config.stuck_timeout_seconds,
        CONFIRMATION_TIMEOUT_FIELD: config.confirmation_timeout_seconds,
        TELEPORTER_HOTKEY_FIELD: config.teleporter_hotkey_virtual_key,
    }


def emergency_config_from_dict(
    data: dict[str, Any],
    destinations: tuple[TeleporterDestination, ...] = (),
) -> EmergencyRecoveryConfig:
    """Deserialize a dictionary into an EmergencyRecoveryConfig, or return the defaults."""

    if not isinstance(data, dict):
        return EmergencyRecoveryConfig()
    defaults = EmergencyRecoveryConfig()
    stored_destination_id = data.get(DESTINATION_FIELD)
    destination = next(
        (
            candidate
            for candidate in destinations
            if stored_destination_id == candidate.destination_id
        ),
        None,
    )
    try:
        return EmergencyRecoveryConfig(
            destination=destination,
            stuck_timeout_seconds=float(
                data.get(STUCK_TIMEOUT_FIELD, defaults.stuck_timeout_seconds)
            ),
            confirmation_timeout_seconds=float(
                data.get(CONFIRMATION_TIMEOUT_FIELD, defaults.confirmation_timeout_seconds)
            ),
            teleporter_hotkey_virtual_key=int(
                data.get(TELEPORTER_HOTKEY_FIELD, defaults.teleporter_hotkey_virtual_key)
            ),
        )
    except CONFIG_FIELD_ERRORS:
        return defaults


def save_emergency_config(
    config: EmergencyRecoveryConfig,
    path: Path = DEFAULT_EMERGENCY_CONFIG_PATH,
    destinations: tuple[TeleporterDestination, ...] = (),
) -> None:
    """Persist the emergency teleport configuration to disk as JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(emergency_config_to_dict(config), indent=JSON_INDENT_SPACES)
    path.write_text(payload, encoding="utf-8")


def load_emergency_config(
    path: Path = DEFAULT_EMERGENCY_CONFIG_PATH,
    destinations: tuple[TeleporterDestination, ...] = (),
) -> EmergencyRecoveryConfig:
    """Load the emergency teleport configuration from disk, or return the defaults."""

    if not path.is_file():
        return EmergencyRecoveryConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return emergency_config_from_dict(data, destinations)
    except CONFIG_READ_ERRORS:
        return EmergencyRecoveryConfig()
