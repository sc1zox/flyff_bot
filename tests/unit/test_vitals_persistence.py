"""Unit tests for vitals trigger configuration persistence."""

from pathlib import Path

from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerConfig,
    VitalTriggerRule,
    VitalTriggerType,
)
from flyff_bot.features.automation.vitals_persistence import (
    load_vitals_config,
    save_vitals_config,
    vitals_config_from_dict,
    vitals_config_to_dict,
)


def test_vitals_config_dict_roundtrip() -> None:
    config = VitalsTriggerConfig(
        rules=(
            VitalTriggerRule(
                vital_type=VitalTriggerType.HP,
                threshold_percentage=80.0,
                virtual_key=0x70,
                debounce_seconds=1.2,
                enabled=True,
                key_press_duration_seconds=0.1,
            ),
            VitalTriggerRule(
                vital_type=VitalTriggerType.MP,
                threshold_percentage=40.0,
                virtual_key=0x71,
                debounce_seconds=0.5,
                enabled=False,
                key_press_duration_seconds=0.05,
            ),
        )
    )

    data = vitals_config_to_dict(config)
    restored = vitals_config_from_dict(data)

    assert len(restored.rules) == 2
    hp_rule = restored.rule_for(VitalTriggerType.HP)
    assert hp_rule is not None
    assert hp_rule.threshold_percentage == 80.0
    assert hp_rule.virtual_key == 0x70
    assert hp_rule.debounce_seconds == 1.2
    assert hp_rule.enabled is True
    assert hp_rule.key_press_duration_seconds == 0.1

    mp_rule = restored.rule_for(VitalTriggerType.MP)
    assert mp_rule is not None
    assert mp_rule.threshold_percentage == 40.0
    assert mp_rule.virtual_key == 0x71
    assert mp_rule.debounce_seconds == 0.5
    assert mp_rule.enabled is False


def test_vitals_config_file_save_and_load(tmp_path: Path) -> None:
    config_file = tmp_path / "vitals.json"
    config = VitalsTriggerConfig(
        rules=(
            VitalTriggerRule(
                vital_type=VitalTriggerType.FP,
                threshold_percentage=25.0,
                virtual_key=0x72,
                debounce_seconds=0.9,
            ),
        )
    )

    save_vitals_config(config, config_file)
    assert config_file.is_file()

    loaded = load_vitals_config(config_file)
    fp_rule = loaded.rule_for(VitalTriggerType.FP)
    assert fp_rule is not None
    assert fp_rule.threshold_percentage == 25.0
    assert fp_rule.virtual_key == 0x72
    assert fp_rule.debounce_seconds == 0.9


def test_load_vitals_config_missing_or_corrupt(tmp_path: Path) -> None:
    missing_file = tmp_path / "does_not_exist.json"
    default_config = load_vitals_config(missing_file)
    assert len(default_config.rules) == 3

    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("invalid json content {{{", encoding="utf-8")
    loaded_corrupt = load_vitals_config(corrupt_file)
    assert len(loaded_corrupt.rules) == 3
