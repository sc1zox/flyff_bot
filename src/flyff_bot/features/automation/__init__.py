"""Automation architecture foundation."""

from flyff_bot.features.automation.executor import VerifiedExecutor
from flyff_bot.features.automation.models import Action, Observation, PlayerVitals, WorldState
from flyff_bot.features.automation.orchestrator import FarmingConfig, FarmingOrchestrator
from flyff_bot.features.automation.planner import Planner
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
    "FarmingConfig",
    "FarmingOrchestrator",
    "Observation",
    "Planner",
    "PlayerVitals",
    "Supervisor",
    "VerifiedExecutor",
    "VitalTriggerRule",
    "VitalTriggerType",
    "VitalsDecision",
    "VitalsInputAdapter",
    "VitalsInputDispatcher",
    "VitalsTriggerConfig",
    "VitalsTriggerController",
    "WorldState",
]
