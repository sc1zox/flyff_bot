"""Automation architecture foundation.

The orchestrator is deliberately not re-exported here. It depends on the policy, quests,
navigation, and UI-facing modules, several of which name `flyff_bot.features.automation`
leaves themselves; re-exporting it made importing any automation leaf drag the whole graph
in and left `flyff_bot.cli` and `flyff_bot.ui.app` unimportable from a cold interpreter.
Import it from `flyff_bot.features.automation.orchestrator` instead.
"""

from flyff_bot.features.automation.models import Action, Observation, PlayerVitals, WorldState
from flyff_bot.features.automation.supervisor import Supervisor
from flyff_bot.features.automation.vitals_controller import (
    VitalsDecision,
    VitalsInputAdapter,
    VitalsInputDispatcher,
    VitalsTriggerConfig,
    VitalsTriggerController,
    VitalTriggerRule,
    VitalTriggerType,
)

__all__ = [
    "Action",
    "Observation",
    "PlayerVitals",
    "Supervisor",
    "VitalTriggerRule",
    "VitalTriggerType",
    "VitalsDecision",
    "VitalsInputAdapter",
    "VitalsInputDispatcher",
    "VitalsTriggerConfig",
    "VitalsTriggerController",
    "WorldState",
]
