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
from flyff_bot.features.policy.action_payloads import TacticalActionKind
from flyff_bot.features.policy.hierarchical_training_simulator import (
    HierarchicalEpisodeMetrics,
    HierarchicalTrainingSimulator,
    PolicyFunction,
    TrainingObjective,
    policy_from_logits,
)
from flyff_bot.features.rl.models import (
    OBSERVATION_DIMENSION,
    RL_OBSERVATION_SCHEMA_VERSION,
    RlObservation,
)
from flyff_bot.features.simulator.engine import TacticalAction

HIERARCHICAL_METADATA_FILENAME = "hierarchical-metadata.json"
HIERARCHICAL_METADATA_SCHEMA_VERSION = 2
HIGH_LEVEL_INPUT_NAME = "strategic_features"
MID_LEVEL_INPUT_NAME = "tactical_features"
HIGH_LEVEL_OUTPUT_NAME = "strategic_logits"
MID_LEVEL_OUTPUT_NAME = "tactical_logits"
DEFAULT_ARTIFACT_VERSION = "us077-v2"
MINIMUM_TRAINING_EPISODES = 8
EVALUATION_EPISODES = 4
RANDOM_SEED = 73073
RIDGE_PENALTY = 0.01
Q_LEARNING_ROLLOUTS_PER_EPISODE = 32
Q_LEARNING_RATE = 0.35
Q_DISCOUNT_FACTOR = 0.95
Q_INITIAL_EXPLORATION = 0.5
Q_MINIMUM_EXPLORATION = 0.05
HIGH_LEVEL_ACTION_ORDER = ("target", "navigate", "interact", "wait")
MID_LEVEL_ACTION_ORDER = tuple(action.value for action in TacticalActionKind)
MID_LEVEL_LABEL_BY_SIMULATOR_ACTION = (
    MID_LEVEL_ACTION_ORDER.index(TacticalActionKind.TARGET),
    MID_LEVEL_ACTION_ORDER.index(TacticalActionKind.NAVIGATE),
    MID_LEVEL_ACTION_ORDER.index(TacticalActionKind.INTERACT),
    MID_LEVEL_ACTION_ORDER.index(TacticalActionKind.WAIT),
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
    episode_count: int = MINIMUM_TRAINING_EPISODES,
) -> HierarchicalTrainingReport:
    """Fit distinct masked strategic/tactical heads and verify paired convergence."""

    if episode_count < MINIMUM_TRAINING_EPISODES:
        raise ValueError("Hierarchical training requires at least eight episodes.")
    simulator = HierarchicalTrainingSimulator(world_map, start=start, objective=objective)
    learned_policy = _train_masked_q_policy(simulator, episode_count=episode_count)
    features: list[NDArray[np.float64]] = []
    high_actions: list[int] = []
    mid_actions: list[int] = []
    for episode_index in range(episode_count):
        observation, mask = simulator.reset(seed=RANDOM_SEED + episode_index)
        terminated = False
        truncated = False
        while not terminated and not truncated:
            action = learned_policy(observation, mask)
            features.append(simulator.encode(observation))
            high_actions.append(action)
            mid_actions.append(MID_LEVEL_LABEL_BY_SIMULATOR_ACTION[action])
            observation, _reward, terminated, truncated, mask, _events = simulator.step(action)

    high_weights = _fit_linear_classifier(features, high_actions, len(HIGH_LEVEL_ACTION_ORDER))
    mid_weights = _fit_linear_classifier(features, mid_actions, len(MID_LEVEL_ACTION_ORDER))
    learned_metrics, baseline_metrics = _evaluate_paired(
        simulator,
        high_weights,
        episode_count=EVALUATION_EPISODES,
        first_seed=RANDOM_SEED + episode_count,
    )
    report_metrics = _convergence_metrics(learned_metrics, baseline_metrics)
    if (
        report_metrics[0] <= report_metrics[1]
        or report_metrics[2] <= report_metrics[3]
        or any(item.invalid_action_count for item in learned_metrics)
    ):
        raise ValueError("The learned policy did not converge beyond the heuristic baseline.")

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
    metadata = {
        "schema_version": HIERARCHICAL_METADATA_SCHEMA_VERSION,
        "artifact_version": DEFAULT_ARTIFACT_VERSION,
        "onnx_opset": ONNX_OPSET_VERSION,
        "world_name": world_map.world_name,
        "feature_schema": {
            "version": RL_OBSERVATION_SCHEMA_VERSION,
            "width": OBSERVATION_DIMENSION,
        },
        "training": {
            "algorithm": "masked_q_learning_with_linear_onnx_heads",
            "episode_count": episode_count,
            "training_seed": RANDOM_SEED,
            "evaluation_seed": RANDOM_SEED + episode_count,
            "evaluation_episodes": EVALUATION_EPISODES,
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
            },
            "mid_level": {
                "file": mid_path.name,
                "sha256": _file_digest(mid_path),
                "input_name": MID_LEVEL_INPUT_NAME,
                "output_name": MID_LEVEL_OUTPUT_NAME,
                "action_order": list(MID_LEVEL_ACTION_ORDER),
            },
        },
        "metrics": {
            "learned_kills_per_minute": report_metrics[0],
            "baseline_kills_per_minute": report_metrics[1],
            "learned_objectives_per_minute": report_metrics[2],
            "baseline_objectives_per_minute": report_metrics[3],
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
    target = int(TacticalAction.TARGET_NEAREST)
    return target if mask[target] else int(TacticalAction.WAIT)


def _train_masked_q_policy(
    simulator: HierarchicalTrainingSimulator, *, episode_count: int
) -> PolicyFunction:
    q_values: dict[tuple[int, ...], NDArray[np.float64]] = {}
    random_source = np.random.default_rng(RANDOM_SEED)
    rollout_count = episode_count * Q_LEARNING_ROLLOUTS_PER_EPISODE
    for rollout_index in range(rollout_count):
        observation, mask = simulator.reset(seed=RANDOM_SEED + rollout_index)
        terminated = False
        truncated = False
        exploration = max(
            Q_MINIMUM_EXPLORATION,
            Q_INITIAL_EXPLORATION * (1.0 - rollout_index / rollout_count),
        )
        while not terminated and not truncated:
            state_key = _q_state_key(observation, mask)
            values = q_values.setdefault(state_key, np.full(len(TacticalAction), 0.1))
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
                next_values = q_values.setdefault(next_key, np.full(len(TacticalAction), 0.1))
                allowed_next = [index for index, is_allowed in enumerate(next_mask) if is_allowed]
                target += Q_DISCOUNT_FACTOR * max(next_values[index] for index in allowed_next)
            values[action] += Q_LEARNING_RATE * (target - values[action])
            observation, mask = next_observation, next_mask

    def evaluate(observation: RlObservation, mask: tuple[bool, ...]) -> int:
        values = q_values.get(_q_state_key(observation, mask))
        allowed = [index for index, is_allowed in enumerate(mask) if is_allowed]
        if values is None:
            return int(TacticalAction.WAIT)
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
    episode_count: int,
    first_seed: int,
) -> tuple[list[HierarchicalEpisodeMetrics], list[HierarchicalEpisodeMetrics]]:
    learned_policy = policy_from_logits(weights)
    learned: list[HierarchicalEpisodeMetrics] = []
    baseline: list[HierarchicalEpisodeMetrics] = []
    for episode_index in range(episode_count):
        seed = first_seed + episode_index
        learned.append(simulator.run_episode(learned_policy, seed=seed))
        baseline.append(simulator.run_episode(_baseline_action, seed=seed))
    return learned, baseline


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
    """Read and strictly validate the two-head artifact provenance document."""

    try:
        payload_object: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("metadata_invalid") from error
    if not isinstance(payload_object, dict):
        raise ValueError("metadata_invalid")
    payload = payload_object
    feature_schema = payload.get("feature_schema")
    models = payload.get("models")
    metrics = payload.get("metrics")
    if payload.get("schema_version") != HIERARCHICAL_METADATA_SCHEMA_VERSION:
        raise ValueError("schema_incompatible")
    if (
        not isinstance(feature_schema, dict)
        or feature_schema.get("version") != RL_OBSERVATION_SCHEMA_VERSION
        or feature_schema.get("width") != OBSERVATION_DIMENSION
    ):
        raise ValueError("feature_schema_incompatible")
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
