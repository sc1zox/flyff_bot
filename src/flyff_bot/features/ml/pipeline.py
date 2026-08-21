"""Offline training run that turns US-054 telemetry into a versioned value-model artifact set.

The pipeline never touches the game client. It reads exported Parquet tables, fits the five
prediction heads on training sessions only, benchmarks each head against its heuristic
reference on held-out sessions, and writes ONNX artifacts plus a provenance document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from flyff_bot.features.ml.cost import DEFAULT_COST_WEIGHTS, ExpectedCostWeights
from flyff_bot.features.ml.cost import expected_costs as compute_expected_costs
from flyff_bot.features.ml.dataset import (
    DEFAULT_HOLDOUT_FRACTION,
    DatasetSplit,
    FarmingSample,
    FollowupValueDefinition,
    SplitStrategy,
    build_samples,
    split_samples,
)
from flyff_bot.features.ml.export import (
    METADATA_FILENAME,
    ModelArtifact,
    artifact_filename,
    build_metadata,
    dataset_version,
    export_linear_model,
    read_git_commit,
    write_metadata,
)
from flyff_bot.features.ml.features import FEATURE_NAMES, feature_matrix, label_vector
from flyff_bot.features.ml.metrics import (
    classification_metrics,
    metrics_payload,
    ranking_metrics,
    regression_metrics,
)
from flyff_bot.features.ml.models import (
    DEFAULT_LOGISTIC_L2,
    DEFAULT_RIDGE_ALPHA,
    LinearValueModel,
    ModelError,
    ValueModelKind,
    fit_baseline,
    fit_logistic,
    fit_ridge,
    observed_rows,
)
from flyff_bot.features.telemetry.exporter import (
    KILL_CYCLES_FILE,
    NAVIGATION_TRAJECTORIES_FILE,
    TARGET_DECISIONS_FILE,
)
from flyff_bot.features.telemetry.models import TelemetryEventKind
from flyff_bot.features.telemetry.storage import SqliteTelemetryStore

DEFAULT_ARTIFACT_VERSION = "v1"
DEFAULT_FOLLOWUP_DEFINITION = FollowupValueDefinition.KILLS_NEXT_10S
# Ground-truth column names recorded in the artifact metadata so a consumer can trace every
# prediction back to the observed session transition it was fitted on.
LABEL_NAMES: tuple[str, ...] = (
    "actual_travel_time",
    "stuck_occurred",
    "actual_stuck_time",
    "actual_recovery_time",
    "actual_kill_time",
    "kill_to_kill_time",
    "targetable_mobs_after_kill",
    "kills_next_5s",
    "kills_next_10s",
)
# The single measurement each heuristic reference predictor scales. ``None`` means the
# heuristic controller has no corresponding rule, so its best guess is the training mean.
BASELINE_FEATURES: dict[ValueModelKind, str | None] = {
    ValueModelKind.TRAVEL_TIME: "path_distance",
    ValueModelKind.STUCK_RISK: None,
    ValueModelKind.RECOVERY_TIME: None,
    ValueModelKind.KILL_TIME: None,
    ValueModelKind.FOLLOWUP_VALUE: "nearby_targetable_mob_count",
}


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Every input of one reproducible offline training run."""

    dataset_directory: Path
    output_directory: Path
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION
    ridge_alpha: float = DEFAULT_RIDGE_ALPHA
    logistic_l2: float = DEFAULT_LOGISTIC_L2
    followup_definition: FollowupValueDefinition = DEFAULT_FOLLOWUP_DEFINITION
    cost_weights: ExpectedCostWeights = DEFAULT_COST_WEIGHTS
    telemetry_database: Path | None = None
    repository_root: Path = Path()


@dataclass(frozen=True, slots=True)
class TrainingReport:
    """What one training run produced, for CLI reporting and automated verification."""

    metadata_path: Path
    artifacts: tuple[ModelArtifact, ...]
    train_sample_count: int
    holdout_sample_count: int
    session_count: int
    split_strategy: SplitStrategy
    holdout_expected_cost: float | None

    @property
    def trained_model_count(self) -> int:
        """Return how many of the five prediction heads were fitted and exported."""

        return sum(1 for artifact in self.artifacts if artifact.trained)


def train_farming_value_models(config: TrainingConfig) -> TrainingReport:
    """Build the dataset, fit and benchmark every head, and export the artifact set."""

    samples = build_samples(config.dataset_directory)
    split = split_samples(samples, holdout_fraction=config.holdout_fraction)
    train_matrix = feature_matrix(tuple(sample.features for sample in split.train))
    holdout_matrix = feature_matrix(tuple(sample.features for sample in split.holdout))
    models: dict[ValueModelKind, LinearValueModel] = {}
    artifacts: list[ModelArtifact] = []
    for kind in ValueModelKind:
        artifact, model = _train_head(
            kind,
            config,
            train_matrix=train_matrix,
            holdout_matrix=holdout_matrix,
            split=split,
        )
        artifacts.append(artifact)
        if model is not None:
            models[kind] = model
    holdout_expected_cost = _holdout_expected_cost(models, holdout_matrix, config.cost_weights)
    metadata_path = _write_artifact_metadata(config, split, tuple(artifacts), holdout_expected_cost)
    return TrainingReport(
        metadata_path=metadata_path,
        artifacts=tuple(artifacts),
        train_sample_count=len(split.train),
        holdout_sample_count=len(split.holdout),
        session_count=len(split.session_ids),
        split_strategy=split.strategy,
        holdout_expected_cost=holdout_expected_cost,
    )


def head_labels(
    samples: tuple[FarmingSample, ...],
    kind: ValueModelKind,
    definition: FollowupValueDefinition,
) -> npt.NDArray[np.float64]:
    """Return the observed ground truth of one prediction head, ``NaN`` where unobserved."""

    match kind:
        case ValueModelKind.TRAVEL_TIME:
            values = tuple(sample.labels.actual_travel_time for sample in samples)
        case ValueModelKind.STUCK_RISK:
            values = tuple(float(sample.labels.stuck_occurred) for sample in samples)
        case ValueModelKind.RECOVERY_TIME:
            values = tuple(sample.labels.actual_recovery_time for sample in samples)
        case ValueModelKind.KILL_TIME:
            values = tuple(sample.labels.actual_kill_time for sample in samples)
        case ValueModelKind.FOLLOWUP_VALUE:
            values = tuple(sample.labels.followup_value(definition) for sample in samples)
    return label_vector(values)


def _train_head(
    kind: ValueModelKind,
    config: TrainingConfig,
    *,
    train_matrix: npt.NDArray[np.float64],
    holdout_matrix: npt.NDArray[np.float64],
    split: DatasetSplit,
) -> tuple[ModelArtifact, LinearValueModel | None]:
    train_labels = head_labels(split.train, kind, config.followup_definition)
    holdout_labels = head_labels(split.holdout, kind, config.followup_definition)
    try:
        model = (
            fit_logistic(train_matrix, train_labels, l2=config.logistic_l2)
            if kind is ValueModelKind.STUCK_RISK
            else fit_ridge(train_matrix, train_labels, alpha=config.ridge_alpha)
        )
        baseline = fit_baseline(train_matrix, train_labels, feature_name=BASELINE_FEATURES[kind])
    except ModelError as error:
        return (
            ModelArtifact(
                kind, None, trained=False, reason=error.code.value, metrics={}, baseline_metrics={}
            ),
            None,
        )
    export_linear_model(model, config.output_directory / artifact_filename(kind))
    observed = observed_rows(holdout_labels)
    return (
        ModelArtifact(
            kind=kind,
            filename=artifact_filename(kind),
            trained=True,
            reason=None,
            metrics=_evaluate(
                kind, holdout_labels[observed], model.predict(holdout_matrix[observed])
            ),
            baseline_metrics=_evaluate(
                kind,
                holdout_labels[observed],
                baseline.predict(holdout_matrix[observed], FEATURE_NAMES),
            ),
        ),
        model,
    )


def _evaluate(
    kind: ValueModelKind,
    observed: npt.NDArray[np.float64],
    predicted: npt.NDArray[np.float64],
) -> dict[str, object]:
    """Score one head with the metric family its target quantity calls for."""

    if observed.size == 0:
        return {}
    if kind is ValueModelKind.STUCK_RISK:
        return metrics_payload(classification_metrics(observed, predicted))
    if kind is ValueModelKind.FOLLOWUP_VALUE:
        return metrics_payload(ranking_metrics(observed, predicted))
    return metrics_payload(regression_metrics(observed, predicted))


def _holdout_expected_cost(
    models: dict[ValueModelKind, LinearValueModel],
    holdout_matrix: npt.NDArray[np.float64],
    weights: ExpectedCostWeights,
) -> float | None:
    """Return the mean expected farming cost the model set assigns to the holdout."""

    if holdout_matrix.shape[0] == 0 or len(models) < len(ValueModelKind):
        return None
    costs = compute_expected_costs(
        models[ValueModelKind.TRAVEL_TIME].predict(holdout_matrix),
        models[ValueModelKind.STUCK_RISK].predict(holdout_matrix),
        models[ValueModelKind.RECOVERY_TIME].predict(holdout_matrix),
        models[ValueModelKind.KILL_TIME].predict(holdout_matrix),
        models[ValueModelKind.FOLLOWUP_VALUE].predict(holdout_matrix),
        weights,
    )
    return float(np.mean(costs))


def _write_artifact_metadata(
    config: TrainingConfig,
    split: DatasetSplit,
    artifacts: tuple[ModelArtifact, ...],
    holdout_expected_cost: float | None,
) -> Path:
    payload = build_metadata(
        artifact_version=config.output_directory.name or DEFAULT_ARTIFACT_VERSION,
        dataset_directory=config.dataset_directory,
        dataset_version=dataset_version(
            tuple(
                config.dataset_directory / name
                for name in (
                    TARGET_DECISIONS_FILE,
                    NAVIGATION_TRAJECTORIES_FILE,
                    KILL_CYCLES_FILE,
                )
            )
        ),
        feature_names=FEATURE_NAMES,
        label_names=LABEL_NAMES,
        followup_value_definition=config.followup_definition.value,
        expected_cost_weights=config.cost_weights.as_dict(),
        split_strategy=split.strategy.value,
        session_ids=split.session_ids,
        train_sample_count=len(split.train),
        holdout_sample_count=len(split.holdout),
        artifacts=artifacts,
        git_commit=read_git_commit(config.repository_root),
        client_build_hashes=client_build_hashes(config.telemetry_database, split.session_ids),
    )
    payload["holdout_expected_cost"] = holdout_expected_cost
    return write_metadata(config.output_directory / METADATA_FILENAME, payload)


def client_build_hashes(database: Path | None, session_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Read the client digests of the recorded sessions, or nothing when unavailable."""

    if database is None or not database.is_file():
        return ()
    wanted = set(session_ids)
    digests = {
        digest
        for event in SqliteTelemetryStore(database).events(TelemetryEventKind.SESSION_HEADER)
        if event["session_id"] in wanted
        and isinstance(digest := event["payload"].get("client_sha256"), str)
    }
    return tuple(sorted(digests))


def load_metadata(path: Path) -> dict[str, object]:
    """Read an exported metadata document back for verification and diagnostics."""

    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("metadata_invalid")
    return decoded
