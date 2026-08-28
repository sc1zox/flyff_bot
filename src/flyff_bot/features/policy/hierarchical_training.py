"""Reproducible masked policy training and two-head ONNX export for US-073."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from flyff_bot.features.ml.export import ONNX_OPSET_VERSION, ExportError, ExportErrorCode
from flyff_bot.features.navigation.world_extractor import WorldCoordinate, WorldVectorMap
from flyff_bot.features.policy.action_payloads import (
    STRATEGIC_GOAL_ORDER,
    StrategicGoalKind,
    TacticalActionKind,
    strategic_goal_index,
)
from flyff_bot.features.policy.contract import (
    CONTRACT_DOCUMENT_KEY,
    current_contract_stamp,
    verify_contract_document,
)
from flyff_bot.features.policy.hierarchical_training_simulator import (
    HierarchicalEpisodeMetrics,
    HierarchicalPolicyLearner,
    HierarchicalTrainingSimulator,
    PolicyFunction,
    TrainingObjective,
    policy_from_logits,
)
from flyff_bot.features.rl.models import RlObservation
from flyff_bot.features.simulator.calibration import validate_calibration
from flyff_bot.features.simulator.models import (
    CalibrationBaseline,
    CalibrationTolerance,
    SimulationMetrics,
)

HIERARCHICAL_METADATA_FILENAME = "hierarchical-metadata.json"
HIERARCHICAL_METADATA_SCHEMA_VERSION = 4
HIGH_LEVEL_INPUT_NAME = "strategic_features"
MID_LEVEL_INPUT_NAME = "tactical_features"
HIGH_LEVEL_OUTPUT_NAME = "strategic_logits"
MID_LEVEL_OUTPUT_NAME = "tactical_logits"
MINIMUM_TRAINING_EPISODES = 8
EVALUATION_EPISODES = 4
CALIBRATION_EPISODES = 4
# Every rollout draws its seed from exactly one of three blocks. The blocks are far enough
# apart that no episode count this pipeline accepts can make them meet, which is what keeps
# the reported evaluation out of sample.
SEED_BLOCK_SIZE = 100_000
TRAINING_SEED_BASE = 73_073
EVALUATION_SEED_BASE = TRAINING_SEED_BASE + SEED_BLOCK_SIZE
CALIBRATION_SEED_BASE = EVALUATION_SEED_BASE + SEED_BLOCK_SIZE
RIDGE_PENALTY = 0.01
Q_LEARNING_ROLLOUTS_PER_EPISODE = 32
Q_LEARNING_RATE = 0.35
Q_DISCOUNT_FACTOR = 0.95
Q_INITIAL_EXPLORATION = 0.5
Q_MINIMUM_EXPLORATION = 0.05
# Both heads emit one column per vocabulary member. Deriving the orders from the shared
# contract is what keeps an exported artifact readable by the live policy.
HIGH_LEVEL_ACTION_ORDER = tuple(goal.value for goal in STRATEGIC_GOAL_ORDER)
MID_LEVEL_ACTION_ORDER = tuple(action.value for action in TacticalActionKind)


@dataclass(frozen=True, slots=True)
class SeedRanges:
    """The three disjoint seed blocks one training run is allowed to draw from."""

    training: range
    evaluation: range
    calibration: range

    def is_disjoint(self) -> bool:
        """Return whether no seed is shared between any two blocks."""

        blocks = (set(self.training), set(self.evaluation), set(self.calibration))
        return len(blocks[0] | blocks[1] | blocks[2]) == sum(len(block) for block in blocks)


def seed_ranges(episode_count: int) -> SeedRanges:
    """Return the disjoint training, evaluation, and calibration seed blocks."""

    training_count = episode_count * Q_LEARNING_ROLLOUTS_PER_EPISODE
    counts = (training_count, EVALUATION_EPISODES, CALIBRATION_EPISODES)
    if any(count > SEED_BLOCK_SIZE for count in counts):
        raise ValueError("A seed block cannot hold the requested number of rollouts.")
    return SeedRanges(
        range(TRAINING_SEED_BASE, TRAINING_SEED_BASE + training_count),
        range(EVALUATION_SEED_BASE, EVALUATION_SEED_BASE + EVALUATION_EPISODES),
        range(CALIBRATION_SEED_BASE, CALIBRATION_SEED_BASE + CALIBRATION_EPISODES),
    )


@dataclass(frozen=True, slots=True)
class HierarchicalTrainingReport:
    """Paths and paired held-out convergence metrics from one training run."""

    metadata_path: Path
    high_level_model_path: Path
    mid_level_model_path: Path
    episode_count: int
    learned_kills_per_minute: float
    baseline_kills_per_minute: float
    learned_objectives_per_minute: float
    baseline_objectives_per_minute: float


def train_hierarchical_policy(
    output_directory: Path,
    *,
    world_map: WorldVectorMap,
    start: WorldCoordinate,
    objective: TrainingObjective,
    calibration: CalibrationBaseline,
    calibration_tolerance: CalibrationTolerance | None = None,
    episode_count: int = MINIMUM_TRAINING_EPISODES,
) -> HierarchicalTrainingReport:
    """Fit distinct masked strategic/tactical heads and verify paired convergence."""

    if episode_count < MINIMUM_TRAINING_EPISODES:
        raise ValueError("Hierarchical training requires at least eight episodes.")
    seeds = seed_ranges(episode_count)
    if not seeds.is_disjoint():
        raise ValueError("Training, evaluation, and calibration seeds must not overlap.")
    simulator = HierarchicalTrainingSimulator(world_map, start=start, objective=objective)
    learned_policy = _train_masked_q_policy(simulator, seeds=seeds.training)
    features: list[NDArray[np.float64]] = []
    high_actions: list[int] = []
    mid_actions: list[int] = []
    for seed in seeds.training[:episode_count]:
        observation, mask = simulator.reset(seed=seed)
        terminated = False
        truncated = False
        while not terminated and not truncated:
            action = learned_policy(observation, mask)
            features.append(simulator.encode(observation))
            high_actions.append(action)
            mid_actions.append(MID_LEVEL_ACTION_ORDER.index(simulator.tactical_kind(action)))
            observation, _reward, terminated, truncated, mask, _events = simulator.step(action)

    high_weights = _fit_linear_classifier(features, high_actions, len(HIGH_LEVEL_ACTION_ORDER))
    mid_weights = _fit_linear_classifier(features, mid_actions, len(MID_LEVEL_ACTION_ORDER))
    learned_metrics, baseline_metrics = _evaluate_paired(
        simulator, high_weights, seeds=seeds.evaluation
    )
    report_metrics = _convergence_metrics(learned_metrics, baseline_metrics)
    if (
        report_metrics[0] <= report_metrics[1]
        or report_metrics[2] <= report_metrics[3]
        or any(item.invalid_action_count for item in learned_metrics)
    ):
        raise ValueError("The learned policy did not converge beyond the heuristic baseline.")
    calibration_result = validate_calibration(
        _calibration_metrics(simulator, seeds=seeds.calibration),
        calibration,
        calibration_tolerance,
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    high_path = _export_policy_graph(
        output_directory / "high-level.onnx",
        high_weights,
        input_name=HIGH_LEVEL_INPUT_NAME,
        output_name=HIGH_LEVEL_OUTPUT_NAME,
    )
    mid_path = _export_policy_graph(
        output_directory / "mid-level.onnx",
        mid_weights,
        input_name=MID_LEVEL_INPUT_NAME,
        output_name=MID_LEVEL_OUTPUT_NAME,
    )
    metadata_path = output_directory / HIERARCHICAL_METADATA_FILENAME
    reward_config = simulator.config.reward
    metadata = {
        "schema_version": HIERARCHICAL_METADATA_SCHEMA_VERSION,
        "onnx_opset": ONNX_OPSET_VERSION,
        "world_name": world_map.world_name,
        CONTRACT_DOCUMENT_KEY: current_contract_stamp(
            reward_config_version=reward_config.version
        ).as_document(),
        "training": {
            "algorithm": "masked_q_learning_with_linear_onnx_heads",
            "episode_count": episode_count,
            "training_seeds": [seeds.training.start, seeds.training.stop],
            "evaluation_seeds": [seeds.evaluation.start, seeds.evaluation.stop],
            "calibration_seeds": [seeds.calibration.start, seeds.calibration.stop],
            "evaluation_episodes": EVALUATION_EPISODES,
            "calibration_episodes": CALIBRATION_EPISODES,
            "reward_config_version": reward_config.version,
            "reward_config_json": reward_config.as_json(),
            "ridge_penalty": RIDGE_PENALTY,
            "q_learning_rollouts_per_episode": Q_LEARNING_ROLLOUTS_PER_EPISODE,
            "q_learning_rate": Q_LEARNING_RATE,
            "q_discount_factor": Q_DISCOUNT_FACTOR,
        },
        "models": {
            "high_level": {
                "file": high_path.name,
                "sha256": _file_digest(high_path),
                "input_name": HIGH_LEVEL_INPUT_NAME,
                "output_name": HIGH_LEVEL_OUTPUT_NAME,
                "action_order": list(HIGH_LEVEL_ACTION_ORDER),
                "trained_actions": _trained_actions(high_actions, HIGH_LEVEL_ACTION_ORDER),
            },
            "mid_level": {
                "file": mid_path.name,
                "sha256": _file_digest(mid_path),
                "input_name": MID_LEVEL_INPUT_NAME,
                "output_name": MID_LEVEL_OUTPUT_NAME,
                "action_order": list(MID_LEVEL_ACTION_ORDER),
                "trained_actions": _trained_actions(mid_actions, MID_LEVEL_ACTION_ORDER),
            },
        },
        "metrics": {
            "learned_kills_per_minute": report_metrics[0],
            "baseline_kills_per_minute": report_metrics[1],
            "learned_objectives_per_minute": report_metrics[2],
            "baseline_objectives_per_minute": report_metrics[3],
            "calibration_kills_per_minute_error": (
                calibration_result.kills_per_minute_error_fraction
            ),
            "calibration_travel_time_error": calibration_result.travel_time_error_fraction,
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return HierarchicalTrainingReport(
        metadata_path,
        high_path,
        mid_path,
        episode_count,
        *report_metrics,
    )


def _baseline_action(_observation: object, mask: tuple[bool, ...]) -> int:
    target = strategic_goal_index(StrategicGoalKind.TARGET)
    return target if mask[target] else strategic_goal_index(StrategicGoalKind.WAIT)


def _train_masked_q_policy(
    simulator: HierarchicalTrainingSimulator, *, seeds: range
) -> PolicyFunction:
    q_values: dict[tuple[int, ...], NDArray[np.float64]] = {}
    random_source = np.random.default_rng(TRAINING_SEED_BASE)
    rollout_count = len(seeds)
    for rollout_index, seed in enumerate(seeds):
        observation, mask = simulator.reset(seed=seed)
        terminated = False
        truncated = False
        exploration = max(
            Q_MINIMUM_EXPLORATION,
            Q_INITIAL_EXPLORATION * (1.0 - rollout_index / rollout_count),
        )
        while not terminated and not truncated:
            state_key = _q_state_key(observation, mask)
            values = q_values.setdefault(state_key, np.full(len(STRATEGIC_GOAL_ORDER), 0.1))
            allowed = [index for index, is_allowed in enumerate(mask) if is_allowed]
            if random_source.random() < exploration:
                action = int(random_source.choice(allowed))
            else:
                action = max(allowed, key=lambda index: (values[index], -index))
            (
                next_observation,
                reward,
                terminated,
                truncated,
                next_mask,
                _events,
            ) = simulator.step(action)
            target = float(reward)
            if not terminated and not truncated:
                next_key = _q_state_key(next_observation, next_mask)
                next_values = q_values.setdefault(next_key, np.full(len(STRATEGIC_GOAL_ORDER), 0.1))
                allowed_next = [index for index, is_allowed in enumerate(next_mask) if is_allowed]
                target += Q_DISCOUNT_FACTOR * max(next_values[index] for index in allowed_next)
            values[action] += Q_LEARNING_RATE * (target - values[action])
            observation, mask = next_observation, next_mask

    def evaluate(observation: RlObservation, mask: tuple[bool, ...]) -> int:
        values = q_values.get(_q_state_key(observation, mask))
        allowed = [index for index, is_allowed in enumerate(mask) if is_allowed]
        if values is None:
            return strategic_goal_index(StrategicGoalKind.WAIT)
        return max(allowed, key=lambda index: (values[index], -index))

    return evaluate


def _q_state_key(observation: RlObservation, mask: tuple[bool, ...]) -> tuple[int, ...]:
    progress = tuple(round(value) for _required, value in observation.objective.objective_progress)
    return (
        *(int(value) for value in mask),
        int(observation.operational.current_target_index is not None),
        *progress,
    )


def _evaluate_paired(
    simulator: HierarchicalTrainingSimulator,
    weights: NDArray[np.float64],
    *,
    seeds: range,
) -> tuple[list[HierarchicalEpisodeMetrics], list[HierarchicalEpisodeMetrics]]:
    learned_policy = policy_from_logits(weights)
    learned: list[HierarchicalEpisodeMetrics] = []
    baseline: list[HierarchicalEpisodeMetrics] = []
    for seed in seeds:
        learned.append(simulator.run_episode(learned_policy, seed=seed))
        baseline.append(simulator.run_episode(_baseline_action, seed=seed))
    return learned, baseline


def _calibration_metrics(
    simulator: HierarchicalTrainingSimulator, *, seeds: range
) -> SimulationMetrics:
    """Aggregate held-out heuristic rollouts into one comparable set of simulated totals.

    Calibration asks whether the simulator's dynamics still match recorded farming, so it
    plays the deterministic expert rather than the fitted head: a policy defect must not be
    able to pass or fail the dynamics check.
    """

    totals = SimulationMetrics(0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    for seed in seeds:
        simulator.run_episode(HierarchicalPolicyLearner.predict_action, seed=seed)
        episode = simulator.metrics
        totals = SimulationMetrics(
            totals.elapsed_seconds + episode.elapsed_seconds,
            totals.kill_count + episode.kill_count,
            totals.travel_seconds + episode.travel_seconds,
            totals.combat_seconds + episode.combat_seconds,
            totals.recovery_seconds + episode.recovery_seconds,
            totals.idle_seconds + episode.idle_seconds,
            totals.distance_units + episode.distance_units,
            totals.stuck_count + episode.stuck_count,
        )
    return totals


def _trained_actions(labels: list[int], action_order: tuple[str, ...]) -> list[str]:
    """Return the action names the fitted head actually saw a positive example for."""

    trained = sorted({label for label in labels if 0 <= label < len(action_order)})
    if not trained:
        raise ValueError("A policy head was fitted without a single labelled action.")
    return [action_order[index] for index in trained]


def _convergence_metrics(
    learned: list[HierarchicalEpisodeMetrics], baseline: list[HierarchicalEpisodeMetrics]
) -> tuple[float, float, float, float]:
    return (
        statistics.fmean(item.kills_per_minute for item in learned),
        statistics.fmean(item.kills_per_minute for item in baseline),
        statistics.fmean(item.objectives_per_minute for item in learned),
        statistics.fmean(item.objectives_per_minute for item in baseline),
    )


def _fit_linear_classifier(
    features: list[NDArray[np.float64]], actions: list[int], action_count: int
) -> NDArray[np.float64]:
    if not features or len(features) != len(actions):
        raise ValueError("Hierarchical training observations are empty or inconsistent.")
    matrix = np.vstack(features).astype(np.float64)
    labels = np.asarray(actions, dtype=np.int64)
    design = matrix.T @ matrix + np.eye(matrix.shape[1]) * RIDGE_PENALTY
    weights = []
    for class_index in range(action_count):
        target = (labels == class_index).astype(np.float64)
        weights.append(np.linalg.solve(design, matrix.T @ target))
    return np.stack(weights, axis=1)


def _export_policy_graph(
    path: Path,
    weights: NDArray[np.float64],
    *,
    input_name: str,
    output_name: str,
) -> Path:
    try:
        import onnx
        from onnx import TensorProto, helper, numpy_helper
    except ImportError as error:
        raise ExportError(ExportErrorCode.ONNX_EXTRA_REQUIRED) from error
    graph = helper.make_graph(
        [helper.make_node("Gemm", [input_name, "weights", "bias"], [output_name])],
        path.stem,
        [helper.make_tensor_value_info(input_name, TensorProto.FLOAT, ["batch", weights.shape[0]])],
        [
            helper.make_tensor_value_info(
                output_name, TensorProto.FLOAT, ["batch", weights.shape[1]]
            )
        ],
        initializer=[
            numpy_helper.from_array(weights.astype(np.float32), "weights"),
            numpy_helper.from_array(np.zeros(weights.shape[1], dtype=np.float32), "bias"),
        ],
    )
    proto = helper.make_model(graph, opset_imports=[helper.make_opsetid("", ONNX_OPSET_VERSION)])
    try:
        onnx.checker.check_model(proto)
        onnx.save_model(proto, str(path))
    except (OSError, ValueError, onnx.checker.ValidationError) as error:
        raise ExportError(ExportErrorCode.EXPORT_FAILED, str(path)) from error
    return path


def read_hierarchical_metadata(path: Path) -> dict[str, object]:
    """Read and strictly validate the two-head artifact provenance document.

    An artifact stamped with another decision contract is refused by
    :func:`verify_contract_document` rather than loaded through a compatibility shim (US-079).
    """

    try:
        payload_object: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("metadata_invalid") from error
    if not isinstance(payload_object, dict):
        raise ValueError("metadata_invalid")
    payload = payload_object
    models = payload.get("models")
    metrics = payload.get("metrics")
    if payload.get("schema_version") != HIERARCHICAL_METADATA_SCHEMA_VERSION:
        raise ValueError("schema_incompatible")
    verify_contract_document(payload.get(CONTRACT_DOCUMENT_KEY))
    if not isinstance(models, dict) or set(models) != {"high_level", "mid_level"}:
        raise ValueError("model_heads_missing")
    expected_actions = {
        "high_level": list(HIGH_LEVEL_ACTION_ORDER),
        "mid_level": list(MID_LEVEL_ACTION_ORDER),
    }
    for name, expected_order in expected_actions.items():
        model = models.get(name)
        if not isinstance(model, dict) or model.get("action_order") != expected_order:
            raise ValueError("action_schema_incompatible")
        trained = model.get("trained_actions")
        if (
            not isinstance(trained, list)
            or not trained
            or not set(trained).issubset(expected_order)
        ):
            raise ValueError("trained_actions_invalid")
        filename = model.get("file")
        digest = model.get("sha256")
        if not isinstance(filename, str) or not isinstance(digest, str):
            raise ValueError("model_metadata_invalid")
        model_path = path.parent / filename
        if not model_path.is_file() or _file_digest(model_path) != digest:
            raise ValueError("model_digest_mismatch")
    if not isinstance(metrics, dict) or any(
        not isinstance(value, int | float) or not math.isfinite(float(value))
        for value in metrics.values()
    ):
        raise ValueError("metrics_invalid")
    return payload


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
