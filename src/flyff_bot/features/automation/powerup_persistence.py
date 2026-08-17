"""Disk persistence for the configured timed power-up hotkeys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flyff_bot.features.automation.controllers import DEFAULT_KEY_PRESS_DURATION_SECONDS
from flyff_bot.features.automation.powerup_controller import (
    DEFAULT_POWERUP_STAGGER_SECONDS,
    PowerUpConfig,
    PowerUpEntry,
)

DEFAULT_POWERUP_CONFIG_PATH = Path("data/powerups_config.json")
JSON_INDENT_SPACES = 2


def powerup_config_to_dict(config: PowerUpConfig) -> dict[str, Any]:
    """Serialize a PowerUpConfig to a JSON-compatible dictionary."""

    return {
        "stagger_seconds": config.stagger_seconds,
        "entries": [
            {
                "label": entry.label,
                "virtual_key": entry.virtual_key,
                "interval_seconds": entry.interval_seconds,
                "enabled": entry.enabled,
                "key_press_duration_seconds": entry.key_press_duration_seconds,
            }
            for entry in config.entries
        ],
    }


def powerup_config_from_dict(data: dict[str, Any]) -> PowerUpConfig:
    """Deserialize a dictionary into a PowerUpConfig, skipping unusable entries.

    A stored empty entry list is preserved rather than replaced by defaults: an
    operator who removed every row must not find them restored on restart.
    """

    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return PowerUpConfig()

    try:
        stagger_seconds = float(data.get("stagger_seconds", DEFAULT_POWERUP_STAGGER_SECONDS))
    except ValueError, TypeError:
        stagger_seconds = DEFAULT_POWERUP_STAGGER_SECONDS

    entries: list[PowerUpEntry] = []
    for item in data["entries"]:
        if not isinstance(item, dict):
            continue
        try:
            entries.append(
                PowerUpEntry(
                    virtual_key=int(item["virtual_key"]),
                    interval_seconds=int(item["interval_seconds"]),
                    label=str(item.get("label", "")),
                    enabled=bool(item.get("enabled", True)),
                    key_press_duration_seconds=float(
                        item.get("key_press_duration_seconds", DEFAULT_KEY_PRESS_DURATION_SECONDS)
                    ),
                )
            )
        except KeyError, ValueError, TypeError:
            continue

    try:
        return PowerUpConfig(entries=tuple(entries), stagger_seconds=stagger_seconds)
    except ValueError:
        return PowerUpConfig(entries=tuple(entries))


def save_powerup_config(config: PowerUpConfig, path: Path = DEFAULT_POWERUP_CONFIG_PATH) -> None:
    """Persist the power-up configuration to disk as JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(powerup_config_to_dict(config), indent=JSON_INDENT_SPACES)
    path.write_text(payload, encoding="utf-8")


def load_powerup_config(path: Path = DEFAULT_POWERUP_CONFIG_PATH) -> PowerUpConfig:
    """Load the power-up configuration from disk, or return an empty configuration."""

    if not path.is_file():
        return PowerUpConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return powerup_config_from_dict(data)
    except json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError, TypeError:
        return PowerUpConfig()
