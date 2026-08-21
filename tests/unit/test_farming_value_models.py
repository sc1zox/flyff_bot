"""Unit tests for model fitting, holdout metrics, and expected farming cost."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from farming_value_fixtures import telemetry_database, write_dataset

from flyff_bot.features.ml.cost import (
    ExpectedCostWeights,
    FarmingValuePrediction,
    expected_cost,
    expected_costs,
)
from flyff_bot.features.ml.features import MISSING_INDICATOR_SUFFIX, prepared_feature_names
from flyff_bot.features.ml.metrics import (
    classification_metrics,
    kendall_tau,
    mean_absolute_error,
    metrics_payload,
    pr_auc,
    ranking_metrics,
    regression_metrics,
    roc_auc,
    root_mean_squared_error,
    spearman_rho,
)
from flyff_bot.features.ml.models import (
    MINIMUM_TRAINING_SAMPLES,
    ModelError,
    ModelErrorCode,
    ValueModelKind,
    fit_baseline,
    fit_logistic,
    fit_ridge,
)
from flyff_bot.features.ml.pipeline import TrainingConfig, train_farming_value_models

_TWO_FEATURES = ("first", "second")


def _linear_matrix(rows: int = 40) -> np.ndarray:
    steps = np.arange(rows, dtype=np.float64)
    return np.stack((steps, np.cos(steps)), axis=1)


def test_ridge_recovers_a_linear_relationship_from_observed_rows() -> None:
    matrix = _linear_matrix()
    labels = 3.0 * matrix[:, 0] - 2.0 * matrix[:, 1] + 5.0

    model = fit_ridge(matrix, labels, feature_names=_TWO_FEATURES, alpha=1e-6)

    assert model.predict(matrix) == pytest.approx(labels, rel=1e-5)
    assert model.prepared_feature_names == prepared_feature_names(_TWO_FEATURES)


def test_a_missing_measurement_is_imputed_with_the_training_median_and_flagged() -> None:
    matrix = _linear_matrix()
    labels = matrix[:, 0] * 2.0
    model = fit_ridge(matrix, labels, feature_names=_TWO_FEATURES)

    prepared = model.prepare(np.array([[np.nan, 0.5]], dtype=np.float64))

    assert prepared[0, 0] == pytest.approx(float(np.median(matrix[:, 0])))
    assert prepared[0, 1] == 0.5
    assert prepared[0, 2] == 1.0
    assert prepared[0, 3] == 0.0
    assert model.prepared_feature_names[2] == f"first{MISSING_INDICATOR_SUFFIX}"


def test_ridge_ignores_rows_whose_label_was_never_observed() -> None:
    matrix = _linear_matrix()
    labels = matrix[:, 0] * 2.0
    censored = labels.copy()
    censored[::2] = np.nan

    model = fit_ridge(matrix, censored, feature_names=_TWO_FEATURES, alpha=1e-6)

    assert model.predict(matrix) == pytest.approx(labels, abs=1e-5)


def test_logistic_separates_two_observed_classes() -> None:
    matrix = _linear_matrix()
    labels = (matrix[:, 0] > 20.0).astype(np.float64)

    model = fit_logistic(matrix, labels, feature_names=_TWO_FEATURES, l2=1e-3)

    predictions = model.predict(matrix)
    assert bool(np.all((predictions >= 0.0) & (predictions <= 1.0)))
    assert roc_auc(labels, predictions) == pytest.approx(1.0)


def test_too_few_observed_samples_are_reported_instead_of_fitted() -> None:
    matrix = _linear_matrix(MINIMUM_TRAINING_SAMPLES - 1)
    labels = matrix[:, 0]

    with pytest.raises(ModelError) as error:
        fit_ridge(matrix, labels, feature_names=_TWO_FEATURES)

    assert error.value.code is ModelErrorCode.NOT_ENOUGH_SAMPLES


def test_a_constant_label_is_reported_instead_of_fitted() -> None:
    matrix = _linear_matrix()
    labels = np.full(matrix.shape[0], 4.0)

    with pytest.raises(ModelError) as error:
        fit_ridge(matrix, labels, feature_names=_TWO_FEATURES)

    assert error.value.code is ModelErrorCode.CONSTANT_LABEL


def test_a_single_observed_class_is_reported_instead_of_fitted() -> None:
    matrix = _linear_matrix()
    labels = np.ones(matrix.shape[0])

    with pytest.raises(ModelError) as error:
        fit_logistic(matrix, labels, feature_names=_TWO_FEATURES)

    assert error.value.code is ModelErrorCode.SINGLE_CLASS


def test_the_heuristic_baseline_scales_its_driving_measurement() -> None:
    matrix = _linear_matrix()
    labels = 4.0 * matrix[:, 0] + 1.0

    baseline = fit_baseline(matrix, labels, feature_names=_TWO_FEATURES, feature_name="first")

    assert baseline.feature_name == "first"
    assert baseline.predict(matrix, _TWO_FEATURES) == pytest.approx(labels)


def test_the_heuristic_baseline_falls_back_to_the_training_mean() -> None:
    matrix = _linear_matrix()
    labels = matrix[:, 0]

    baseline = fit_baseline(matrix, labels, feature_names=_TWO_FEATURES, feature_name=None)

    assert baseline.feature_name is None
    assert baseline.predict(matrix, _TWO_FEATURES) == pytest.approx(np.mean(labels))


def test_error_metrics_match_their_definitions() -> None:
    observed = np.array([1.0, 2.0, 3.0])
    predicted = np.array([1.0, 4.0, 3.0])

    assert mean_absolute_error(observed, predicted) == pytest.approx(2.0 / 3.0)
    assert root_mean_squared_error(observed, predicted) == pytest.approx(np.sqrt(4.0 / 3.0))
    assert regression_metrics(observed, predicted).sample_count == 3


def test_ranking_metrics_report_perfect_and_inverted_agreement() -> None:
    observed = np.array([1.0, 2.0, 3.0, 4.0])

    assert spearman_rho(observed, observed) == pytest.approx(1.0)
    assert kendall_tau(observed, observed) == pytest.approx(1.0)
    assert spearman_rho(observed, -observed) == pytest.approx(-1.0)
    assert kendall_tau(observed, -observed) == pytest.approx(-1.0)
    assert ranking_metrics(observed, observed).mae == pytest.approx(0.0)


def test_classification_metrics_rank_a_perfect_and_a_useless_score() -> None:
    observed = np.array([0.0, 0.0, 1.0, 1.0])
    perfect = np.array([0.1, 0.2, 0.8, 0.9])
    useless = np.array([0.5, 0.5, 0.5, 0.5])

    strong = classification_metrics(observed, perfect)
    weak = classification_metrics(observed, useless)

    assert strong.roc_auc == pytest.approx(1.0)
    assert strong.pr_auc == pytest.approx(1.0)
    assert strong.precision == pytest.approx(1.0)
    assert strong.recall == pytest.approx(1.0)
    assert weak.roc_auc == pytest.approx(0.5)
    assert weak.positive_rate == pytest.approx(0.5)


def test_undefined_metrics_stay_none_instead_of_becoming_a_placeholder() -> None:
    single_class = np.zeros(4)

    assert roc_auc(single_class, np.arange(4, dtype=np.float64)) is None
    assert pr_auc(single_class, np.arange(4, dtype=np.float64)) is None
    assert spearman_rho(np.zeros(4), np.zeros(4)) is None
    assert kendall_tau(np.zeros(4), np.zeros(4)) is None
    assert metrics_payload(None) == {}


def test_expected_cost_sums_the_weighted_prediction_components() -> None:
    prediction = FarmingValuePrediction(
        travel_time=4.0,
        stuck_probability=0.5,
        recovery_time=6.0,
        kill_time=3.0,
        followup_value=2.0,
    )

    assert expected_cost(prediction) == pytest.approx(4.0 + 3.0 + 0.5 * 6.0 - 2.0)
    weighted = expected_cost(
        prediction, ExpectedCostWeights(travel=2.0, kill=0.5, stuck=0.0, followup=3.0)
    )
    assert weighted == pytest.approx(8.0 + 1.5 + 0.0 - 6.0)


def test_expected_costs_evaluate_a_whole_candidate_batch() -> None:
    ones = np.ones(3)

    costs = expected_costs(ones * 4.0, ones * 0.5, ones * 6.0, ones * 3.0, ones * 2.0)

    assert costs == pytest.approx(np.full(3, 8.0))


def test_weights_are_recorded_in_a_metadata_friendly_mapping() -> None:
    weights = ExpectedCostWeights(travel=1.5, kill=2.0, stuck=0.25, followup=0.75)

    assert weights.as_dict() == {"travel": 1.5, "kill": 2.0, "stuck": 0.25, "followup": 0.75}


def test_a_training_run_fits_and_benchmarks_every_prediction_head(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    report = train_farming_value_models(
        TrainingConfig(
            dataset_directory=dataset,
            output_directory=tmp_path / "models" / "v1",
            telemetry_database=telemetry_database(tmp_path),
        )
    )

    assert report.trained_model_count == len(ValueModelKind)
    assert {artifact.kind for artifact in report.artifacts} == set(ValueModelKind)
    assert report.train_sample_count > 0
    assert report.holdout_sample_count > 0
    assert report.holdout_expected_cost is not None
    for artifact in report.artifacts:
        assert artifact.metrics
        assert artifact.baseline_metrics


def test_learned_heads_beat_their_heuristic_reference_on_the_holdout(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    report = train_farming_value_models(
        TrainingConfig(dataset_directory=dataset, output_directory=tmp_path / "models" / "v1")
    )

    timing_heads = {
        ValueModelKind.TRAVEL_TIME,
        ValueModelKind.RECOVERY_TIME,
        ValueModelKind.KILL_TIME,
    }
    for artifact in report.artifacts:
        if artifact.kind not in timing_heads:
            continue
        learned_error = artifact.metrics["mae"]
        heuristic_error = artifact.baseline_metrics["mae"]
        assert isinstance(learned_error, float)
        assert isinstance(heuristic_error, float)
        assert learned_error < heuristic_error


def test_a_head_without_enough_observed_labels_is_reported_as_untrained(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path, session_ids=("a", "b"), cycles_per_session=6)

    report = train_farming_value_models(
        TrainingConfig(dataset_directory=dataset, output_directory=tmp_path / "models" / "v1")
    )

    untrained = [artifact for artifact in report.artifacts if not artifact.trained]
    assert untrained
    assert all(artifact.filename is None and artifact.reason for artifact in untrained)
    assert report.holdout_expected_cost is None
