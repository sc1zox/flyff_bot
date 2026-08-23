from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from flyff_bot.features.automation.emergency_persistence import (
    DEFAULT_EMERGENCY_CONFIG_PATH,
    load_emergency_config,
    save_emergency_config,
)
from flyff_bot.features.automation.emergency_recovery import EmergencyRecoveryConfig
from flyff_bot.features.automation.powerup_controller import PowerUpConfig
from flyff_bot.features.automation.powerup_persistence import (
    DEFAULT_POWERUP_CONFIG_PATH,
    load_powerup_config,
    save_powerup_config,
)
from flyff_bot.features.automation.vitals_controller import VitalsTriggerConfig
from flyff_bot.features.automation.vitals_persistence import (
    DEFAULT_VITALS_CONFIG_PATH,
    load_vitals_config,
    save_vitals_config,
)
from flyff_bot.i18n import Translator
from flyff_bot.ui.main_window_parts.recovery_settings import RecoverySettingsPanel
from flyff_bot.ui.main_window_parts.vitals_settings import VitalsSettingsPanel
from flyff_bot.ui.powerup_panel import PowerUpPanel


class SettingsController(QObject):
    """Coordinate feature configuration widgets and their persistence."""

    vitals_changed = Signal(object)
    powerup_changed = Signal(object)
    emergency_changed = Signal(object)

    def __init__(
        self,
        translator: Translator,
        *,
        recovery_panel: RecoverySettingsPanel,
        vitals_panel: VitalsSettingsPanel,
        powerup_panel: PowerUpPanel,
        vitals_path: Path | None = None,
        powerup_path: Path | None = None,
        emergency_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.recovery_panel = recovery_panel
        self.vitals_panel = vitals_panel
        self.powerup_panel = powerup_panel
        self._vitals_path = vitals_path or DEFAULT_VITALS_CONFIG_PATH
        self._powerup_path = powerup_path or DEFAULT_POWERUP_CONFIG_PATH
        self._emergency_path = emergency_path or DEFAULT_EMERGENCY_CONFIG_PATH
        self.load_vitals()
        self.load_powerups()
        self.load_emergency()

    def load_vitals(self) -> None:
        self.vitals_panel.load_config(load_vitals_config(self._vitals_path))

    def save_vitals(self) -> VitalsTriggerConfig:
        config = self.vitals_panel.get_config()
        save_vitals_config(config, self._vitals_path)
        return config

    @property
    def vitals_config(self) -> VitalsTriggerConfig:
        return self.vitals_panel.get_config()

    def load_powerups(self) -> None:
        self.powerup_panel.set_config(load_powerup_config(self._powerup_path))

    @property
    def powerup_config(self) -> PowerUpConfig:
        return self.powerup_panel.config

    def handle_powerup_changed(self, config: object) -> None:
        if isinstance(config, PowerUpConfig):
            save_powerup_config(config, self._powerup_path)
            self.powerup_changed.emit(config)

    def load_emergency(self) -> None:
        self.recovery_panel.load_config(
            load_emergency_config(self._emergency_path),
        )

    def save_emergency(self) -> EmergencyRecoveryConfig:
        config = self.recovery_panel.get_config()
        save_emergency_config(config, self._emergency_path)
        return config

    @property
    def emergency_config(self) -> EmergencyRecoveryConfig:
        return self.recovery_panel.get_config()
