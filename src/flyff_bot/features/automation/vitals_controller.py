"""Reactive vitals trigger controller and input dispatcher for consumable items."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from flyff_bot.features.automation.controllers import DEFAULT_KEY_PRESS_DURATION_SECONDS
from flyff_bot.features.automation.models import ActionKind, PlayerVitals, WorldState
from flyff_bot.features.tactical_parameters import TacticalParameterSpace

DEFAULT_HP_THRESHOLD_PERCENTAGE = 70.0
DEFAULT_MP_THRESHOLD_PERCENTAGE = 30.0
DEFAULT_FP_THRESHOLD_PERCENTAGE = 20.0
DEFAULT_VITALS_DEBOUNCE_SECONDS = 0.8
# Zero percent HP is death evidence, never an item-consumption trigger.  The
# small positive lower bound also keeps a malformed zero reading fail-closed.
MINIMUM_TRIGGERABLE_VITAL_PERCENTAGE = 0.1

VIRTUAL_KEY_F1 = 0x70
VIRTUAL_KEY_F2 = 0x71
VIRTUAL_KEY_F3 = 0x72


class VitalTriggerType(StrEnum):
    """Supported player vital gauges for trigger rules."""

    HP = "hp"
    MP = "mp"
    FP = "fp"


@dataclass(frozen=True, slots=True)
class VitalTriggerRule:
    """Configuration for one vital threshold trigger slot."""

    vital_type: VitalTriggerType
    threshold_percentage: float
    virtual_key: int
    debounce_seconds: float = DEFAULT_VITALS_DEBOUNCE_SECONDS
    enabled: bool = True
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold_percentage <= 100.0:
            raise ValueError("Threshold percentage must be between 0.0 and 100.0.")
        if self.debounce_seconds < 0.0:
            raise ValueError("Debounce seconds must not be negative.")
        if self.key_press_duration_seconds <= 0.0:
            raise ValueError("Key press duration must be positive.")


@dataclass(frozen=True, slots=True)
class VitalsTriggerConfig:
    """Configured trigger rules for player vitals."""

    rules: tuple[VitalTriggerRule, ...] = field(
        default_factory=lambda: (
            VitalTriggerRule(
                vital_type=VitalTriggerType.HP,
                threshold_percentage=DEFAULT_HP_THRESHOLD_PERCENTAGE,
                virtual_key=VIRTUAL_KEY_F1,
            ),
            VitalTriggerRule(
                vital_type=VitalTriggerType.MP,
                threshold_percentage=DEFAULT_MP_THRESHOLD_PERCENTAGE,
                virtual_key=VIRTUAL_KEY_F2,
            ),
            VitalTriggerRule(
                vital_type=VitalTriggerType.FP,
                threshold_percentage=DEFAULT_FP_THRESHOLD_PERCENTAGE,
                virtual_key=VIRTUAL_KEY_F3,
            ),
        )
    )

    def rule_for(self, vital_type: VitalTriggerType) -> VitalTriggerRule | None:
        """Return the first rule matching the vital type."""

        for rule in self.rules:
            if rule.vital_type == vital_type:
                return rule
        return None


@dataclass(frozen=True, slots=True)
class VitalsDecision:
    """The outcome of evaluating vitals rules for one tick."""

    triggered: bool
    rule: VitalTriggerRule | None = None
    action_kind: ActionKind | None = None
    virtual_key: int | None = None
    key_press_duration_seconds: float = DEFAULT_KEY_PRESS_DURATION_SECONDS


class VitalsInputAdapter(Protocol):
    """Guarded platform operations needed to dispatch vital triggers."""

    def is_aborted(self) -> bool:
        """Return whether the emergency-stop hotkey was pressed."""

    def is_foreground(self, window_handle: int) -> bool:
        """Return whether the client window is active."""

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        """Press and release a virtual key while honoring the emergency stop."""


class VitalsTriggerController:
    """Evaluate WorldState player vitals against rules with priority and debounce."""

    def __init__(
        self,
        config: VitalsTriggerConfig | None = None,
        *,
        tactical_parameters: TacticalParameterSpace | None = None,
    ) -> None:
        self._config = config or VitalsTriggerConfig()
        if tactical_parameters is not None:
            self._config = _vitals_config_with_parameters(self._config, tactical_parameters)
        self._last_triggered_at_seconds: dict[VitalTriggerType, float] = {}

    def update_config(self, config: VitalsTriggerConfig) -> None:
        """Update the active rules configuration."""

        self._config = config

    def update_tactical_parameters(self, parameters: TacticalParameterSpace) -> None:
        """Apply shared recovery thresholds while preserving keys and enabled flags."""

        self._config = _vitals_config_with_parameters(self._config, parameters)

    def reset(self) -> None:
        """Clear all debounce cooldowns."""

        self._last_triggered_at_seconds.clear()

    def step(self, state: WorldState) -> VitalsDecision:
        """Evaluate vitals in priority order: HP first, then MP, then FP."""

        vitals = state.player_vitals
        observed_at = state.observed_at_seconds

        # Sort rules so HP is always evaluated before MP, and MP before FP
        priority_order = {
            VitalTriggerType.HP: 0,
            VitalTriggerType.MP: 1,
            VitalTriggerType.FP: 2,
        }
        sorted_rules = sorted(
            [r for r in self._config.rules if r.enabled],
            key=lambda r: priority_order.get(r.vital_type, 99),
        )

        for rule in sorted_rules:
            current_pct = self._get_vital_percentage(vitals, rule.vital_type)
            if (
                current_pct >= MINIMUM_TRIGGERABLE_VITAL_PERCENTAGE
                and current_pct <= rule.threshold_percentage
            ):
                last_fired = self._last_triggered_at_seconds.get(rule.vital_type, 0.0)
                if observed_at - last_fired >= rule.debounce_seconds:
                    self._last_triggered_at_seconds[rule.vital_type] = observed_at
                    return VitalsDecision(
                        triggered=True,
                        rule=rule,
                        action_kind=ActionKind.RECOVER,
                        virtual_key=rule.virtual_key,
                        key_press_duration_seconds=rule.key_press_duration_seconds,
                    )

        return VitalsDecision(triggered=False)

    @staticmethod
    def _get_vital_percentage(vitals: PlayerVitals, vital_type: VitalTriggerType) -> float:
        if vital_type is VitalTriggerType.HP:
            return vitals.hp_percentage
        if vital_type is VitalTriggerType.MP:
            return vitals.mp_percentage
        if vital_type is VitalTriggerType.FP:
            return vitals.fp_percentage
        return 100.0


def _vitals_config_with_parameters(
    config: VitalsTriggerConfig, parameters: TacticalParameterSpace
) -> VitalsTriggerConfig:
    thresholds = {
        VitalTriggerType.HP: parameters.hp_potion_threshold_percent,
        VitalTriggerType.MP: parameters.mp_threshold_percent,
    }
    return VitalsTriggerConfig(
        rules=tuple(
            replace(
                rule,
                threshold_percentage=thresholds.get(rule.vital_type, rule.threshold_percentage),
                debounce_seconds=(
                    parameters.recovery_debounce_seconds
                    if rule.vital_type in thresholds
                    else rule.debounce_seconds
                ),
            )
            for rule in config.rules
        )
    )


class VitalsInputDispatcher:
    """Send consumable hotkeys only while the client is focused and END is clear."""

    def __init__(self, adapter: VitalsInputAdapter, window_handle: int) -> None:
        self._adapter = adapter
        self._window_handle = window_handle

    def dispatch(self, decision: VitalsDecision) -> bool:
        """Dispatch a vital trigger hotkey if the decision is triggered."""

        if (
            not decision.triggered
            or decision.virtual_key is None
            or self._adapter.is_aborted()
            or not self._adapter.is_foreground(self._window_handle)
        ):
            return False

        self._adapter.send_key(decision.virtual_key, decision.key_press_duration_seconds)
        return True
