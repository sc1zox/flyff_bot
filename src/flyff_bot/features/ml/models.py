"""Lightweight, deterministic value models for offline farming and navigation prediction.

Every model here is a regularized linear predictor over a prepared feature matrix. Preparation
replaces a missing measurement with the median observed during training and appends a paired
missing indicator, so an imputed value is always distinguishable from a real one and no model
ever sees a fabricated measurement it cannot recognize as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from flyff_bot.features.ml.features import FEATURE_NAMES, prepared_feature_names

# A ridge fit needs more rows than a handful to be meaningful, and a logistic fit needs both
# classes. Below these floors the caller is told the model was not trained instead of being
# handed weights fitted to noise.
MINIMUM_TRAINING_SAMPLES = 8
DEFAULT_RIDGE_ALPHA = 1.0
DEFAULT_LOGISTIC_L2 = 1.0
LOGISTIC_MAX_ITERATIONS = 50
LOGISTIC_CONVERGENCE_TOLERANCE = 1e-8
# Guards the IRLS weight matrix against saturated probabilities collapsing the Hessian.
LOGISTIC_MINIMUM_VARIANCE = 1e-6


class ValueModelKind(StrEnum):
    """The five prediction heads that make up one farming value model version."""

    TRAVEL_TIME = "travel_time"
    STUCK_RISK = "stuck_risk"
    RECOVERY_TIME = "recovery_time"
    KILL_TIME = "kill_time"
    FOLLOWUP_VALUE = "followup_value"


class ModelErrorCode(StrEnum):
    """Machine-readable reasons a model head could not be fitted."""

    NOT_ENOUGH_SAMPLES = "not_enough_samples"
    CONSTANT_LABEL = "constant_label"
    SINGLE_CLASS = "single_class"


class ModelError(ValueError):
    """A model head had insufficient observed data to be fitted honestly."""

    def __init__(self, code: ModelErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class LinearValueModel:
    """A fitted linear (optionally logistic) predictor over prepared farming features."""

    feature_names: tuple[str, ...]
    medians: npt.NDArray[np.float64]
    weights: npt.NDArray[np.float64]
    intercept: float
    logistic: bool

    def prepare(self, matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Impute missing measurements and append their indicator columns."""

        missing = np.isnan(matrix)
        filled = np.where(missing, self.medians, matrix)
        return np.concatenate((filled, missing.astype(np.float64)), axis=1)

    def predict(self, matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Return one prediction per row of a raw (NaN-carrying) feature matrix."""

        scores = self.prepare(matrix) @ self.weights + self.intercept
        return _sigmoid(scores) if self.logistic else scores

    @property
    def prepared_feature_names(self) -> tuple[str, ...]:
        """Return the ordered column names the weight vector is indexed by."""

        return prepared_feature_names(self.feature_names)


@dataclass(frozen=True, slots=True)
class ScalarBaseline:
    """The heuristic reference predictor a learned head has to beat to be worth shipping.

    With a driving feature it is the least-squares scaling of that single measurement, which is
    exactly the shape of the deterministic cost terms the live controller already uses. Without
    one it degenerates to the training mean, the strongest possible constant guess.
    """

    feature_name: str | None
    scale: float
    offset: float

    def predict(
        self, matrix: npt.NDArray[np.float64], feature_names: tuple[str, ...]
    ) -> npt.NDArray[np.float64]:
        """Return one baseline prediction per row of a raw feature matrix."""

        if self.feature_name is None or self.feature_name not in feature_names:
            return np.full(matrix.shape[0], self.offset, dtype=np.float64)
        column = matrix[:, feature_names.index(self.feature_name)]
        return np.where(np.isnan(column), self.offset, self.scale * column + self.offset)


def fit_ridge(
    matrix: npt.NDArray[np.float64],
    labels: npt.NDArray[np.float64],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    alpha: float = DEFAULT_RIDGE_ALPHA,
) -> LinearValueModel:
    """Fit an L2-regularized least-squares predictor on the observed rows of a label."""

    prepared, medians, targets = _standardized_design(matrix, labels)
    if float(np.ptp(targets)) == 0.0:
        raise ModelError(ModelErrorCode.CONSTANT_LABEL)
    design, mean, scale = _standardize(prepared)
    centre = float(np.mean(targets))
    penalty = alpha * np.eye(design.shape[1], dtype=np.float64)
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ (targets - centre))
    return _folded_model(feature_names, medians, coefficients, centre, mean, scale, logistic=False)


def fit_logistic(
    matrix: npt.NDArray[np.float64],
    labels: npt.NDArray[np.float64],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    l2: float = DEFAULT_LOGISTIC_L2,
) -> LinearValueModel:
    """Fit an L2-regularized logistic classifier with Newton iterations on observed rows."""

    prepared, medians, targets = _standardized_design(matrix, labels)
    if len(np.unique(targets)) < 2:
        raise ModelError(ModelErrorCode.SINGLE_CLASS)
    design, mean, scale = _standardize(prepared)
    augmented = np.concatenate((design, np.ones((design.shape[0], 1), dtype=np.float64)), axis=1)
    penalty = l2 * np.eye(augmented.shape[1], dtype=np.float64)
    # The intercept is never shrunk; only the slopes carry the regularization.
    penalty[-1, -1] = 0.0
    coefficients = np.zeros(augmented.shape[1], dtype=np.float64)
    for _ in range(LOGISTIC_MAX_ITERATIONS):
        probabilities = _sigmoid(augmented @ coefficients)
        variance = np.maximum(probabilities * (1.0 - probabilities), LOGISTIC_MINIMUM_VARIANCE)
        gradient = augmented.T @ (probabilities - targets) + penalty @ coefficients
        hessian = augmented.T @ (augmented * variance[:, None]) + penalty
        step = np.linalg.solve(hessian, gradient)
        coefficients = coefficients - step
        if float(np.max(np.abs(step))) < LOGISTIC_CONVERGENCE_TOLERANCE:
            break
    return _folded_model(
        feature_names,
        medians,
        coefficients[:-1],
        float(coefficients[-1]),
        mean,
        scale,
        logistic=True,
    )


def fit_baseline(
    matrix: npt.NDArray[np.float64],
    labels: npt.NDArray[np.float64],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    feature_name: str | None = None,
) -> ScalarBaseline:
    """Fit the heuristic reference predictor used to benchmark one learned head."""

    observed = ~np.isnan(labels)
    if not bool(np.any(observed)):
        raise ModelError(ModelErrorCode.NOT_ENOUGH_SAMPLES)
    targets = labels[observed]
    mean = float(np.mean(targets))
    if feature_name is None or feature_name not in feature_names:
        return ScalarBaseline(None, 0.0, mean)
    column = matrix[observed, feature_names.index(feature_name)]
    usable = ~np.isnan(column)
    if int(np.count_nonzero(usable)) < 2 or float(np.ptp(column[usable])) == 0.0:
        return ScalarBaseline(None, 0.0, mean)
    design = np.stack((column[usable], np.ones(int(np.count_nonzero(usable)))), axis=1)
    solution, *_ = np.linalg.lstsq(design, targets[usable], rcond=None)
    return ScalarBaseline(feature_name, float(solution[0]), float(solution[1]))


def observed_rows(labels: npt.NDArray[np.float64]) -> npt.NDArray[np.bool_]:
    """Return the mask of samples whose label was actually observed in a session."""

    return ~np.isnan(labels)


def _standardized_design(
    matrix: npt.NDArray[np.float64], labels: npt.NDArray[np.float64]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    observed = observed_rows(labels)
    if int(np.count_nonzero(observed)) < MINIMUM_TRAINING_SAMPLES:
        raise ModelError(ModelErrorCode.NOT_ENOUGH_SAMPLES)
    rows = matrix[observed]
    medians = _column_medians(rows)
    missing = np.isnan(rows)
    filled = np.where(missing, medians, rows)
    prepared = np.concatenate((filled, missing.astype(np.float64)), axis=1)
    return prepared, medians, labels[observed]


def _column_medians(rows: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Return per-feature training medians, using zero only where nothing was ever observed."""

    medians = np.zeros(rows.shape[1], dtype=np.float64)
    for index in range(rows.shape[1]):
        column = rows[:, index]
        observed = column[~np.isnan(column)]
        if observed.size:
            medians[index] = float(np.median(observed))
    return medians


def _standardize(
    prepared: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    mean = prepared.mean(axis=0)
    scale = prepared.std(axis=0)
    scale = np.where(scale > 0.0, scale, 1.0)
    return (prepared - mean) / scale, mean, scale


def _folded_model(
    feature_names: tuple[str, ...],
    medians: npt.NDArray[np.float64],
    coefficients: npt.NDArray[np.float64],
    intercept: float,
    mean: npt.NDArray[np.float64],
    scale: npt.NDArray[np.float64],
    *,
    logistic: bool,
) -> LinearValueModel:
    """Fold the fitting-time standardization into the exported raw-feature weights."""

    weights = coefficients / scale
    return LinearValueModel(
        feature_names=feature_names,
        medians=medians,
        weights=weights,
        intercept=intercept - float(np.dot(mean, weights)),
        logistic=logistic,
    )


def _sigmoid(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    return np.asarray(1.0 / (1.0 + np.exp(-np.clip(values, -60.0, 60.0))), dtype=np.float64)
