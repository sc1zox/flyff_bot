"""Standard holdout metrics for the offline farming value models.

All estimators are computed directly on numpy arrays so an evaluation run stays reproducible
and free of optional scientific dependencies. Metrics that are undefined for the given holdout
(a single class, fewer than two ranked pairs) return ``None`` rather than a placeholder number.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import numpy.typing as npt

DEFAULT_CLASSIFICATION_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class RegressionMetrics:
    """Absolute error metrics for a continuous prediction head."""

    sample_count: int
    mae: float
    rmse: float


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    """Threshold and ranking quality of the stuck-risk head."""

    sample_count: int
    positive_rate: float
    precision: float
    recall: float
    roc_auc: float | None
    pr_auc: float | None


@dataclass(frozen=True, slots=True)
class RankingMetrics:
    """Error and rank agreement for the follow-up value head."""

    sample_count: int
    mae: float
    rmse: float
    spearman_rho: float | None
    kendall_tau: float | None


def mean_absolute_error(
    observed: npt.NDArray[np.float64], predicted: npt.NDArray[np.float64]
) -> float:
    """Return the mean absolute deviation between observations and predictions."""

    return float(np.mean(np.abs(observed - predicted)))


def root_mean_squared_error(
    observed: npt.NDArray[np.float64], predicted: npt.NDArray[np.float64]
) -> float:
    """Return the root mean squared deviation between observations and predictions."""

    return float(np.sqrt(np.mean((observed - predicted) ** 2)))


def roc_auc(observed: npt.NDArray[np.float64], predicted: npt.NDArray[np.float64]) -> float | None:
    """Return the rank-based area under the ROC curve, or ``None`` for a single class."""

    positives = observed > 0.0
    positive_count = int(np.count_nonzero(positives))
    negative_count = int(observed.size - positive_count)
    if positive_count == 0 or negative_count == 0:
        return None
    ranks = _average_ranks(predicted)
    positive_rank_sum = float(np.sum(ranks[positives]))
    return (positive_rank_sum - positive_count * (positive_count + 1) / 2.0) / (
        positive_count * negative_count
    )


def pr_auc(observed: npt.NDArray[np.float64], predicted: npt.NDArray[np.float64]) -> float | None:
    """Return average precision, the interpolation-free area under the PR curve."""

    positives = observed > 0.0
    positive_count = int(np.count_nonzero(positives))
    if positive_count == 0:
        return None
    order = np.argsort(-predicted, kind="stable")
    ordered = positives[order]
    cumulative_positives = np.cumsum(ordered)
    positions = np.arange(1, ordered.size + 1, dtype=np.float64)
    precision_at_hits = cumulative_positives[ordered] / positions[ordered]
    return float(np.sum(precision_at_hits) / positive_count)


def precision_recall(
    observed: npt.NDArray[np.float64],
    predicted: npt.NDArray[np.float64],
    *,
    threshold: float = DEFAULT_CLASSIFICATION_THRESHOLD,
) -> tuple[float, float]:
    """Return precision and recall at one decision threshold, using zero for empty sets."""

    positives = observed > 0.0
    flagged = predicted >= threshold
    true_positives = int(np.count_nonzero(positives & flagged))
    flagged_count = int(np.count_nonzero(flagged))
    positive_count = int(np.count_nonzero(positives))
    precision = true_positives / flagged_count if flagged_count else 0.0
    recall = true_positives / positive_count if positive_count else 0.0
    return precision, recall


def spearman_rho(
    observed: npt.NDArray[np.float64], predicted: npt.NDArray[np.float64]
) -> float | None:
    """Return the rank correlation between observations and predictions."""

    if observed.size < 2:
        return None
    return _pearson(_average_ranks(observed), _average_ranks(predicted))


def kendall_tau(
    observed: npt.NDArray[np.float64], predicted: npt.NDArray[np.float64]
) -> float | None:
    """Return the tau-b rank correlation, which is defined even with tied values."""

    count = observed.size
    if count < 2:
        return None
    concordant = 0
    discordant = 0
    observed_ties = 0
    predicted_ties = 0
    for first in range(count - 1):
        for second in range(first + 1, count):
            observed_delta = observed[first] - observed[second]
            predicted_delta = predicted[first] - predicted[second]
            if observed_delta == 0.0 and predicted_delta == 0.0:
                continue
            if observed_delta == 0.0:
                observed_ties += 1
            elif predicted_delta == 0.0:
                predicted_ties += 1
            elif observed_delta * predicted_delta > 0.0:
                concordant += 1
            else:
                discordant += 1
    first_total = concordant + discordant + observed_ties
    second_total = concordant + discordant + predicted_ties
    if first_total == 0 or second_total == 0:
        return None
    return (concordant - discordant) / float(np.sqrt(first_total * second_total))


def regression_metrics(
    observed: npt.NDArray[np.float64], predicted: npt.NDArray[np.float64]
) -> RegressionMetrics:
    """Summarize a continuous head into its standard error metrics."""

    return RegressionMetrics(
        sample_count=int(observed.size),
        mae=mean_absolute_error(observed, predicted),
        rmse=root_mean_squared_error(observed, predicted),
    )


def classification_metrics(
    observed: npt.NDArray[np.float64],
    predicted: npt.NDArray[np.float64],
    *,
    threshold: float = DEFAULT_CLASSIFICATION_THRESHOLD,
) -> ClassificationMetrics:
    """Summarize the stuck-risk head into threshold and ranking quality."""

    precision, recall = precision_recall(observed, predicted, threshold=threshold)
    return ClassificationMetrics(
        sample_count=int(observed.size),
        positive_rate=float(np.mean(observed > 0.0)) if observed.size else 0.0,
        precision=precision,
        recall=recall,
        roc_auc=roc_auc(observed, predicted),
        pr_auc=pr_auc(observed, predicted),
    )


def ranking_metrics(
    observed: npt.NDArray[np.float64], predicted: npt.NDArray[np.float64]
) -> RankingMetrics:
    """Summarize the follow-up value head into error and rank agreement."""

    return RankingMetrics(
        sample_count=int(observed.size),
        mae=mean_absolute_error(observed, predicted),
        rmse=root_mean_squared_error(observed, predicted),
        spearman_rho=spearman_rho(observed, predicted),
        kendall_tau=kendall_tau(observed, predicted),
    )


def metrics_payload(
    metrics: RegressionMetrics | ClassificationMetrics | RankingMetrics | None,
) -> dict[str, object]:
    """Convert one metrics dataclass into a JSON-serializable mapping."""

    return {} if metrics is None else dict(asdict(metrics))


def _average_ranks(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Return one-based ranks that share the mean rank across tied values."""

    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.float64)
    ordered = values[order]
    index = 0
    while index < ordered.size:
        end = index
        while end + 1 < ordered.size and ordered[end + 1] == ordered[index]:
            end += 1
        ranks[order[index : end + 1]] = (index + end) / 2.0 + 1.0
        index = end + 1
    return ranks


def _pearson(first: npt.NDArray[np.float64], second: npt.NDArray[np.float64]) -> float | None:
    first_centred = first - first.mean()
    second_centred = second - second.mean()
    denominator = float(np.sqrt(float(np.sum(first_centred**2)) * float(np.sum(second_centred**2))))
    if denominator == 0.0:
        return None
    return float(np.sum(first_centred * second_centred) / denominator)
