"""Hierarchical model faults remain behind the deterministic fallback boundary."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.navigation.world_extractor import WorldCoordinate, WorldVectorMap
from flyff_bot.features.policy.hierarchical_onnx import HierarchicalOnnxPolicy
from flyff_bot.features.policy.hierarchical_training import train_hierarchical_policy
from flyff_bot.features.policy.hierarchical_training_simulator import TrainingObjective
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext
from flyff_bot.features.policy.runner import PolicyRunner
from flyff_bot.features.simulator.models import QuestObjective, QuestObjectiveKind


class _InvalidNetwork:
    def setInput(self, _blob: np.ndarray, _name: str = "") -> None:
        return None

    def forward(self) -> np.ndarray:
        return np.asarray([[np.nan, 0.0, 0.0, 0.0]])


def test_nan_hierarchical_output_triggers_exact_heuristic_fallback(
    tmp_path: Path, world_map: WorldVectorMap
) -> None:
    objective = TrainingObjective((QuestObjective(QuestObjectiveKind.KILL, monster_id=7),))
    train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=objective,
    )
    learned = HierarchicalOnnxPolicy(tmp_path, network_loader=lambda _path: _InvalidNetwork())
    mob = VisibleMob(7, "Aibatt", 0.9, 10, 20, 5, 5, 1.0, 2.0, 3.0)
    candidate = PolicyCandidate(mob, True, True, True, True, True, 0)
    context = PolicyContext((candidate,), frozenset(), (False,))
    state = WorldState(1.0, Position(50, 50), 1, (), 0, viewport=Viewport(100, 100))
    runner = PolicyRunner(learned)

    action = runner.evaluate(state, context)

    assert action is not None and action.kind.value == "target"
    assert runner.last_fallback_reason == "invalid_hierarchical_prediction"
