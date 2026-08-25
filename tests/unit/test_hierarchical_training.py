"""US-072-backed convergence and ONNX metadata coverage for US-073."""

import time
from pathlib import Path

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.navigation.world_extractor import WorldCoordinate, WorldVectorMap
from flyff_bot.features.policy.hierarchical_onnx import HierarchicalOnnxPolicy
from flyff_bot.features.policy.hierarchical_training import (
    read_hierarchical_metadata,
    train_hierarchical_policy,
)
from flyff_bot.features.policy.hierarchical_training_simulator import TrainingObjective
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext
from flyff_bot.features.policy.runner import PolicyRunner
from flyff_bot.features.simulator.models import QuestObjective, QuestObjectiveKind


def _objective() -> TrainingObjective:
    return TrainingObjective(
        (
            QuestObjective(QuestObjectiveKind.KILL, monster_id=7, required_count=2),
            QuestObjective(
                QuestObjectiveKind.GO_TO,
                position_x=20.0,
                position_z=10.0,
                radius_units=1.0,
            ),
            QuestObjective(
                QuestObjectiveKind.TALK_TO_NPC,
                npc_id="npc-1",
                position_x=20.0,
                position_z=10.0,
            ),
        )
    )


def test_training_exports_distinct_heads_and_beats_paired_baseline(
    tmp_path: Path, world_map: WorldVectorMap
) -> None:
    report = train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=_objective(),
    )
    metadata = read_hierarchical_metadata(report.metadata_path)

    assert report.learned_kills_per_minute > report.baseline_kills_per_minute
    assert report.learned_objectives_per_minute > report.baseline_objectives_per_minute
    assert report.high_level_model_path.read_bytes() != report.mid_level_model_path.read_bytes()
    assert metadata["world_name"] == "WdTest"


def test_model_digest_tampering_is_rejected(tmp_path: Path, world_map: WorldVectorMap) -> None:
    report = train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=_objective(),
    )
    report.high_level_model_path.write_bytes(b"tampered")

    try:
        read_hierarchical_metadata(report.metadata_path)
    except ValueError as error:
        assert str(error) == "model_digest_mismatch"
    else:
        raise AssertionError("Digest mismatch was accepted.")


def test_cached_two_head_inference_stays_inside_five_millisecond_budget(
    tmp_path: Path, world_map: WorldVectorMap
) -> None:
    train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=_objective(),
    )
    policy = HierarchicalOnnxPolicy(tmp_path)
    mob = VisibleMob(7, "Aibatt", 0.9, 10, 20, 5, 5, 1.0, 2.0, 3.0)
    candidate = PolicyCandidate(mob, True, True, True, True, True, 0)
    context = PolicyContext((candidate,), frozenset(), (False,))
    state = WorldState(1.0, Position(50, 50), 1, (), 0, viewport=Viewport(100, 100))
    runner = PolicyRunner(policy)
    runner.evaluate(state, context)

    started_at = time.perf_counter()
    for _iteration in range(100):
        runner.evaluate(state, context)
    elapsed = time.perf_counter() - started_at

    assert elapsed / 100 < 0.005
