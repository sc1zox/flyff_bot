"""Disk persistence for player vitals threshold triggers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerConfig,
    VitalTriggerRule,
    VitalTriggerType,
)

DEFAULT_VITALS_CONFIG_PATH = Path("data/vitals_config.json")
JSON_INDENT_SPACES = 2


def vitals_config_to_dict(config: VitalsTriggerConfig) -> dict[str, Any]:
    """Serialize VitalsTriggerConfig to a JSON-compatible dictionary."""

    return {
        "rules": [
            {
                "vital_type": rule.vital_type.value,
                "threshold_percentage": rule.threshold_percentage,
                "virtual_key": rule.virtual_key,
                "debounce_seconds": rule.debounce_seconds,
                "enabled": rule.enabled,
                "key_press_duration_seconds": rule.key_press_duration_seconds,
            }
            for rule in config.rules
        ]
    }


def vitals_config_from_dict(data: dict[str, Any]) -> VitalsTriggerConfig:
    """Deserialize a dictionary into a VitalsTriggerConfig instance."""

    if not isinstance(data, dict) or "rules" not in data or not isinstance(data["rules"], list):
        return VitalsTriggerConfig()

    rules: list[VitalTriggerRule] = []
    for item in data["rules"]:
        if not isinstance(item, dict):
            continue
        try:
            vital_type = VitalTriggerType(item["vital_type"])
            threshold_pct = float(item["threshold_percentage"])
            virtual_key = int(item["virtual_key"])
            debounce_sec = float(item.get("debounce_seconds", 0.8))
            enabled = bool(item.get("enabled", True))
            duration = float(item.get("key_press_duration_seconds", 0.05))
            rules.append(
                VitalTriggerRule(
                    vital_type=vital_type,
                    threshold_percentage=threshold_pct,
                    virtual_key=virtual_key,
                    debounce_seconds=debounce_sec,
                    enabled=enabled,
                    key_press_duration_seconds=duration,
                )
            )
        except KeyError, ValueError, TypeError:
            continue

    if not rules:
        return VitalsTriggerConfig()
    return VitalsTriggerConfig(rules=tuple(rules))


def save_vitals_config(
    config: VitalsTriggerConfig, path: Path = DEFAULT_VITALS_CONFIG_PATH
) -> None:
    """Persist the vitals trigger configuration to disk as JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(vitals_config_to_dict(config), indent=JSON_INDENT_SPACES)
    path.write_text(payload, encoding="utf-8")


def load_vitals_config(path: Path = DEFAULT_VITALS_CONFIG_PATH) -> VitalsTriggerConfig:
    """Load the vitals trigger configuration from disk, or return default config."""

    if not path.is_file():
        return VitalsTriggerConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return vitals_config_from_dict(data)
    except json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError, TypeError:
        return VitalsTriggerConfig()
