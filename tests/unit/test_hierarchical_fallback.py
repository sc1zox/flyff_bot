"""Hierarchical model faults remain behind the deterministic fallback boundary."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.navigation.world_extractor import WorldCoordinate, WorldVectorMap
from flyff_bot.features.policy.action_payloads import ObjectiveKind
from flyff_bot.features.policy.hierarchical_onnx import HierarchicalOnnxPolicy
from flyff_bot.features.policy.hierarchical_training import train_hierarchical_policy
from flyff_bot.features.policy.hierarchical_training_simulator import TrainingObjective
from flyff_bot.features.policy.models import (
    LiveObservationState,
    PolicyCandidate,
    PolicyContext,
)
from flyff_bot.features.policy.runner import PolicyFaultCode, PolicyRunner
from flyff_bot.features.rl.models import NavMeshContext, PlayerKinematics
from flyff_bot.features.simulator.models import (
    CalibrationBaseline,
    CalibrationTolerance,
    QuestObjective,
)

# This test is about the fallback boundary, not about dynamics drift, so its calibration
# gate is deliberately wide: it must be satisfied without pinning simulated throughput.
UNCONSTRAINED_BASELINE = CalibrationBaseline(60.0, 8, 8.0, 6.0, 1.0, 0.0, 0.0)
UNCONSTRAINED_TOLERANCE = CalibrationTolerance(100.0, 100.0)


class _InvalidNetwork:
    def setInput(self, _blob: np.ndarray, _name: str = "") -> None:
        return None

    def forward(self) -> np.ndarray:
        return np.asarray([[np.nan, 0.0, 0.0, 0.0]])


def test_nan_hierarchical_output_halts_learned_automation(
    tmp_path: Path, world_map: WorldVectorMap
) -> None:
    objective = TrainingObjective((QuestObjective(ObjectiveKind.KILL, monster_id=7),))
    train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=objective,
        calibration=UNCONSTRAINED_BASELINE,
        calibration_tolerance=UNCONSTRAINED_TOLERANCE,
    )
    learned = HierarchicalOnnxPolicy(tmp_path, network_loader=lambda _path: _InvalidNetwork())
    mob = VisibleMob(7, "Aibatt", 0.9, 10, 20, 5, 5, 1.0, 2.0, 3.0)
    candidate = PolicyCandidate(mob, True, True, True, True, True, 0)
    context = PolicyContext(
        (candidate,),
        frozenset(),
        (False,),
        live_state=LiveObservationState(
            PlayerKinematics(1.0, 2.0, 3.0, 0.5), NavMeshContext("poly-1", 0.0, 12.0)
        ),
    )
    state = WorldState(1.0, Position(50, 50), 1, (), 0, viewport=Viewport(100, 100))
    runner = PolicyRunner(learned)

    action = runner.evaluate(state, context)

    assert action is None
    assert runner.last_fault is not None
    assert runner.last_fault.code is PolicyFaultCode.POLICY_EXCEPTION
    assert runner.last_fault.detail == "invalid_hierarchical_prediction"
