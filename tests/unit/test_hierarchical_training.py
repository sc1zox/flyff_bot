"""US-072-backed convergence and ONNX metadata coverage for US-073."""

import time
from pathlib import Path

import pytest

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.navigation.world_extractor import WorldCoordinate, WorldVectorMap
from flyff_bot.features.policy.action_payloads import CorridorAction, TacticalActionKind
from flyff_bot.features.policy.hierarchical_onnx import HierarchicalOnnxPolicy
from flyff_bot.features.policy.hierarchical_training import (
    HIERARCHICAL_METADATA_FILENAME,
    HIERARCHICAL_METADATA_SCHEMA_VERSION,
    MID_LEVEL_ACTION_ORDER,
    read_hierarchical_metadata,
    seed_ranges,
    train_hierarchical_policy,
)
from flyff_bot.features.policy.hierarchical_training_simulator import TrainingObjective
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext
from flyff_bot.features.policy.runner import PolicyRunner
from flyff_bot.features.rl.models import OBSERVATION_DIMENSION, RL_OBSERVATION_SCHEMA_VERSION
from flyff_bot.features.rl.rewards import RewardConfig
from flyff_bot.features.simulator import CalibrationBaseline, CalibrationError
from flyff_bot.features.simulator.models import QuestObjective, QuestObjectiveKind

# Aggregates a recorded US-054 session on this region would have produced. The training run
# refuses to write an artifact when its own rollouts drift away from them.
RECORDED_BASELINE = CalibrationBaseline(
    session_duration_seconds=66.5,
    kill_count=8,
    kills_per_minute=7.2,
    mean_travel_seconds=5.8,
    mean_combat_seconds=1.1,
    stuck_frequency=0.0,
    mean_recovery_seconds=0.0,
)


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
        calibration=RECORDED_BASELINE,
    )
    metadata = read_hierarchical_metadata(report.metadata_path)

    assert report.learned_kills_per_minute > report.baseline_kills_per_minute
    assert report.learned_objectives_per_minute > report.baseline_objectives_per_minute
    assert report.high_level_model_path.read_bytes() != report.mid_level_model_path.read_bytes()
    assert metadata["world_name"] == "WdTest"
    assert metadata["schema_version"] == HIERARCHICAL_METADATA_SCHEMA_VERSION
    assert metadata["feature_schema"] == {
        "version": RL_OBSERVATION_SCHEMA_VERSION,
        "width": OBSERVATION_DIMENSION,
    }


def test_training_evaluation_and_calibration_seeds_are_disjoint() -> None:
    seeds = seed_ranges(64)

    assert seeds.is_disjoint()
    assert not set(seeds.training) & set(seeds.evaluation)
    assert not set(seeds.training) & set(seeds.calibration)
    assert not set(seeds.evaluation) & set(seeds.calibration)
    assert seeds.evaluation.start >= seeds.training.stop


def test_the_two_heads_are_fitted_on_different_targets(
    tmp_path: Path, world_map: WorldVectorMap
) -> None:
    report = train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=_objective(),
        calibration=RECORDED_BASELINE,
    )
    metadata = read_hierarchical_metadata(report.metadata_path)
    models = metadata["models"]
    assert isinstance(models, dict)
    high = models["high_level"]
    mid = models["mid_level"]

    assert TacticalActionKind.ATTACK_POINT in mid["trained_actions"]
    assert set(mid["trained_actions"]) - set(high["trained_actions"])
    assert set(mid["trained_actions"]).issubset(MID_LEVEL_ACTION_ORDER)
    assert set(mid["trained_actions"]) != set(MID_LEVEL_ACTION_ORDER)


def test_an_untrained_action_class_is_never_selected_live(
    tmp_path: Path, world_map: WorldVectorMap
) -> None:
    report = train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=_objective(),
        calibration=RECORDED_BASELINE,
    )
    metadata = read_hierarchical_metadata(report.metadata_path)
    models = metadata["models"]
    assert isinstance(models, dict)
    untrained = set(MID_LEVEL_ACTION_ORDER) - set(models["mid_level"]["trained_actions"])
    policy = HierarchicalOnnxPolicy(tmp_path)
    mob = VisibleMob(7, "Aibatt", 0.9, 10, 20, 5, 5, 1.0, 2.0, 3.0)
    candidate = PolicyCandidate(mob, True, True, True, True, True, 0)
    context = PolicyContext(
        (candidate,),
        frozenset(),
        (False,),
        valid_corridor_ids=frozenset({"corridor-1"}),
    )
    state = WorldState(1.0, Position(50, 50), 1, (), 0, viewport=Viewport(100, 100))

    action = policy.evaluate(state, context)

    assert TacticalActionKind.CORRIDOR in untrained
    assert not isinstance(action, CorridorAction)


def test_calibration_drift_blocks_the_artifact_export(
    tmp_path: Path, world_map: WorldVectorMap
) -> None:
    drifting = CalibrationBaseline(
        session_duration_seconds=66.5,
        kill_count=2,
        kills_per_minute=1.8,
        mean_travel_seconds=5.8,
        mean_combat_seconds=1.1,
        stuck_frequency=0.0,
        mean_recovery_seconds=0.0,
    )

    with pytest.raises(CalibrationError):
        train_hierarchical_policy(
            tmp_path,
            world_map=world_map,
            start=WorldCoordinate(10.0, 10.0),
            objective=_objective(),
            calibration=drifting,
        )

    assert not (tmp_path / HIERARCHICAL_METADATA_FILENAME).exists()


def test_the_exported_metadata_names_one_versioned_reward_configuration(
    tmp_path: Path, world_map: WorldVectorMap
) -> None:
    report = train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=_objective(),
        calibration=RECORDED_BASELINE,
    )
    metadata = read_hierarchical_metadata(report.metadata_path)
    training = metadata["training"]
    assert isinstance(training, dict)

    assert training["reward_config_json"] == RewardConfig().as_json()


def test_model_digest_tampering_is_rejected(tmp_path: Path, world_map: WorldVectorMap) -> None:
    report = train_hierarchical_policy(
        tmp_path,
        world_map=world_map,
        start=WorldCoordinate(10.0, 10.0),
        objective=_objective(),
        calibration=RECORDED_BASELINE,
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
        calibration=RECORDED_BASELINE,
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
