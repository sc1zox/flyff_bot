"""Disk persistence for the unrecoverable-stuck emergency teleport settings (US-040)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flyff_bot.features.automation.emergency_recovery import EmergencyRecoveryConfig

DEFAULT_EMERGENCY_CONFIG_PATH = Path("data/emergency_recovery_config.json")
JSON_INDENT_SPACES = 2
# An explicitly unassigned hotkey has to survive a restart, so ``null`` is a stored value
# rather than a missing key: a reader that fell back to the default would silently re-arm a
# teleport the operator switched off.
TELEPORT_KEY_FIELD = "teleport_virtual_key"
STUCK_TIMEOUT_FIELD = "stuck_timeout_seconds"
SETTLE_DELAY_FIELD = "settle_delay_seconds"
# Named so the handlers below stay single-name `except` clauses. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
CONFIG_FIELD_ERRORS = (ValueError, TypeError)
CONFIG_READ_ERRORS = (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError, TypeError)


def emergency_config_to_dict(config: EmergencyRecoveryConfig) -> dict[str, Any]:
    """Serialize an EmergencyRecoveryConfig to a JSON-compatible dictionary."""

    return {
        TELEPORT_KEY_FIELD: config.teleport_virtual_key,
        STUCK_TIMEOUT_FIELD: config.stuck_timeout_seconds,
        SETTLE_DELAY_FIELD: config.settle_delay_seconds,
    }


def emergency_config_from_dict(data: dict[str, Any]) -> EmergencyRecoveryConfig:
    """Deserialize a dictionary into an EmergencyRecoveryConfig, or return the defaults."""

    if not isinstance(data, dict):
        return EmergencyRecoveryConfig()
    defaults = EmergencyRecoveryConfig()
    stored_key = data.get(TELEPORT_KEY_FIELD, defaults.teleport_virtual_key)
    try:
        return EmergencyRecoveryConfig(
            teleport_virtual_key=None if stored_key is None else int(stored_key),
            stuck_timeout_seconds=float(
                data.get(STUCK_TIMEOUT_FIELD, defaults.stuck_timeout_seconds)
            ),
            settle_delay_seconds=float(data.get(SETTLE_DELAY_FIELD, defaults.settle_delay_seconds)),
        )
    except CONFIG_FIELD_ERRORS:
        return defaults


def save_emergency_config(
    config: EmergencyRecoveryConfig, path: Path = DEFAULT_EMERGENCY_CONFIG_PATH
) -> None:
    """Persist the emergency teleport configuration to disk as JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(emergency_config_to_dict(config), indent=JSON_INDENT_SPACES)
    path.write_text(payload, encoding="utf-8")


def load_emergency_config(
    path: Path = DEFAULT_EMERGENCY_CONFIG_PATH,
) -> EmergencyRecoveryConfig:
    """Load the emergency teleport configuration from disk, or return the defaults."""

    if not path.is_file():
        return EmergencyRecoveryConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return emergency_config_from_dict(data)
    except CONFIG_READ_ERRORS:
        return EmergencyRecoveryConfig()
