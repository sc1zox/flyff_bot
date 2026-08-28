"""Offline farming, navigation, and quest dynamics simulation.

`environment.SimulatorGymEnvironment` is deliberately absent here. It is the declared
Gymnasium environment and needs the optional `rl` extra, while this package is imported
along the live policy-loading path, which must stay free of a training framework
(BUG-030). Offline trainers import that module by its full path.
"""

from flyff_bot.features.policy.action_payloads import ObjectiveKind
from flyff_bot.features.simulator.calibration import CalibrationError, validate_calibration
from flyff_bot.features.simulator.engine import (
    FarmingSimulator,
    IllegalSimulatorAction,
    SimulatedMonster,
)
from flyff_bot.features.simulator.models import (
    SIMULATOR_SCHEMA_VERSION,
    CalibrationBaseline,
    CalibrationTolerance,
    MonsterLifecycle,
    QuestObjective,
    SimulationMetrics,
    SimulatorConfig,
    fit_calibration,
)

__all__ = [
    "SIMULATOR_SCHEMA_VERSION",
    "CalibrationBaseline",
    "CalibrationError",
    "CalibrationTolerance",
    "FarmingSimulator",
    "IllegalSimulatorAction",
    "MonsterLifecycle",
    "ObjectiveKind",
    "QuestObjective",
    "SimulatedMonster",
    "SimulationMetrics",
    "SimulatorConfig",
    "fit_calibration",
    "validate_calibration",
]
