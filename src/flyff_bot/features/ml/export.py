"""Versioned ONNX and metadata artifacts for one trained farming value model set.

An exported graph is self-contained: it accepts the raw feature matrix with ``NaN`` for every
unobserved measurement and performs imputation, missing indication, and the linear prediction
itself. A consumer therefore cannot accidentally disagree with the training-time preparation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import numpy as np

from flyff_bot.features.ml.features import MISSING_INDICATOR_SUFFIX
from flyff_bot.features.ml.models import LinearValueModel, ValueModelKind

METADATA_FILENAME = "metadata.json"
METADATA_SCHEMA_VERSION = 1
ONNX_OPSET_VERSION = 17
ONNX_SUFFIX = ".onnx"
GRAPH_INPUT_NAME = "features"
GRAPH_OUTPUT_NAME = "prediction"
BATCH_DIMENSION_NAME = "batch"
DATASET_VERSION_DIGEST_LENGTH = 16


class ExportErrorCode(StrEnum):
    """Machine-readable reasons an artifact could not be written."""

    ONNX_EXTRA_REQUIRED = "onnx_extra_required"
    EXPORT_FAILED = "export_failed"


class ExportError(RuntimeError):
    """A model artifact could not be produced."""

    def __init__(self, code: ExportErrorCode, detail: str = "") -> None:
        super().__init__(f"{code.value}:{detail}" if detail else code.value)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    """One exported prediction head and the holdout evidence that justifies it."""

    kind: ValueModelKind
    filename: str | None
    trained: bool
    reason: str | None
    metrics: dict[str, object]
    baseline_metrics: dict[str, object]


def artifact_filename(kind: ValueModelKind) -> str:
    """Return the stable file name one prediction head is exported under."""

    return f"{kind.value}{ONNX_SUFFIX}"


def export_linear_model(model: LinearValueModel, path: Path) -> Path:
    """Write one fitted head as a self-contained ONNX graph and return its path."""

    try:
        import onnx
        from onnx import TensorProto, helper, numpy_helper
    except ImportError as error:
        raise ExportError(ExportErrorCode.ONNX_EXTRA_REQUIRED) from error
    feature_count = len(model.feature_names)
    initializers = [
        numpy_helper.from_array(model.medians.astype(np.float32), "medians"),
        numpy_helper.from_array(
            model.weights.astype(np.float32).reshape(2 * feature_count, 1), "weights"
        ),
        numpy_helper.from_array(np.array([model.intercept], dtype=np.float32), "bias"),
    ]
    score_name = "score" if model.logistic else GRAPH_OUTPUT_NAME
    nodes = [
        helper.make_node("IsNaN", [GRAPH_INPUT_NAME], ["missing"]),
        helper.make_node("Where", ["missing", "medians", GRAPH_INPUT_NAME], ["filled"]),
        helper.make_node("Cast", ["missing"], ["indicators"], to=TensorProto.FLOAT),
        helper.make_node("Concat", ["filled", "indicators"], ["prepared"], axis=1),
        helper.make_node("Gemm", ["prepared", "weights", "bias"], [score_name]),
    ]
    if model.logistic:
        nodes.append(helper.make_node("Sigmoid", [score_name], [GRAPH_OUTPUT_NAME]))
    graph = helper.make_graph(
        nodes,
        path.stem,
        [
            helper.make_tensor_value_info(
                GRAPH_INPUT_NAME, TensorProto.FLOAT, [BATCH_DIMENSION_NAME, feature_count]
            )
        ],
        [
            helper.make_tensor_value_info(
                GRAPH_OUTPUT_NAME, TensorProto.FLOAT, [BATCH_DIMENSION_NAME, 1]
            )
        ],
        initializer=initializers,
    )
    proto = helper.make_model(graph, opset_imports=[helper.make_opsetid("", ONNX_OPSET_VERSION)])
    try:
        onnx.checker.check_model(proto)
        path.parent.mkdir(parents=True, exist_ok=True)
        onnx.save_model(proto, str(path))
    except (OSError, ValueError, onnx.checker.ValidationError) as error:
        raise ExportError(ExportErrorCode.EXPORT_FAILED, str(path)) from error
    return path


def write_metadata(path: Path, payload: dict[str, object]) -> Path:
    """Write the schema-validated model metadata document and return its path."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        raise ExportError(ExportErrorCode.EXPORT_FAILED, str(path)) from error
    return path


def build_metadata(
    *,
    artifact_version: str,
    dataset_directory: Path,
    dataset_version: str,
    feature_names: tuple[str, ...],
    label_names: tuple[str, ...],
    followup_value_definition: str,
    expected_cost_weights: dict[str, float],
    split_strategy: str,
    session_ids: tuple[str, ...],
    train_sample_count: int,
    holdout_sample_count: int,
    artifacts: tuple[ModelArtifact, ...],
    git_commit: str | None,
    client_build_hashes: tuple[str, ...],
) -> dict[str, object]:
    """Assemble the complete provenance document that accompanies exported artifacts."""

    return {
        "schema_version": METADATA_SCHEMA_VERSION,
        "artifact_version": artifact_version,
        "created_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "client_build_hashes": list(client_build_hashes),
        "onnx_opset": ONNX_OPSET_VERSION,
        "dataset": {
            "path": str(dataset_directory),
            "version": dataset_version,
            "session_count": len(session_ids),
            "session_ids": list(session_ids),
            "split_strategy": split_strategy,
            "train_sample_count": train_sample_count,
            "holdout_sample_count": holdout_sample_count,
        },
        "feature_schema": {
            "raw_features": list(feature_names),
            "missing_indicator_suffix": MISSING_INDICATOR_SUFFIX,
            "imputation": "training_median",
            "input_name": GRAPH_INPUT_NAME,
            "output_name": GRAPH_OUTPUT_NAME,
        },
        "label_schema": list(label_names),
        "followup_value_definition": followup_value_definition,
        "expected_cost_weights": expected_cost_weights,
        "models": {
            artifact.kind.value: {
                "file": artifact.filename,
                "trained": artifact.trained,
                "reason": artifact.reason,
                "metrics": artifact.metrics,
                "baseline_metrics": artifact.baseline_metrics,
            }
            for artifact in artifacts
        },
    }


def dataset_version(paths: tuple[Path, ...]) -> str:
    """Return a stable digest of the exact telemetry tables a model was trained on."""

    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:DATASET_VERSION_DIGEST_LENGTH]


def read_git_commit(repository_root: Path) -> str | None:
    """Read the checked-out commit from the git directory without invoking git itself."""

    head_path = repository_root / ".git" / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head.startswith("ref:"):
        return head or None
    reference = (repository_root / ".git" / head.removeprefix("ref:").strip()).resolve()
    try:
        return reference.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
