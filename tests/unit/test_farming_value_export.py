"""Unit tests for ONNX artifact export, metadata integrity, and the offline CLI."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import onnx
import pytest
from farming_value_fixtures import telemetry_database, write_dataset
from onnx import numpy_helper

from flyff_bot.constants import ExitCode
from flyff_bot.features.ml.export import (
    GRAPH_INPUT_NAME,
    GRAPH_OUTPUT_NAME,
    METADATA_FILENAME,
    ONNX_OPSET_VERSION,
    ExportError,
    ExportErrorCode,
    artifact_filename,
    dataset_version,
    export_linear_model,
    read_git_commit,
)
from flyff_bot.features.ml.features import FEATURE_NAMES, MISSING_INDICATOR_SUFFIX
from flyff_bot.features.ml.models import ValueModelKind, fit_logistic, fit_ridge
from flyff_bot.features.ml.pipeline import (
    LABEL_NAMES,
    TrainingConfig,
    load_metadata,
    train_farming_value_models,
)
from flyff_bot.features.ml.train_farming_value import main
from flyff_bot.features.telemetry.exporter import TARGET_DECISIONS_FILE

_TWO_FEATURES = ("first", "second")


def _matrix(rows: int = 40) -> np.ndarray:
    steps = np.arange(rows, dtype=np.float64)
    return np.stack((steps, np.cos(steps)), axis=1)


def _initializers(model_proto: onnx.ModelProto) -> dict[str, np.ndarray]:
    return {tensor.name: numpy_helper.to_array(tensor) for tensor in model_proto.graph.initializer}


def test_an_exported_regression_graph_is_valid_and_self_contained(tmp_path: Path) -> None:
    matrix = _matrix()
    model = fit_ridge(matrix, matrix[:, 0] * 2.0, feature_names=_TWO_FEATURES, alpha=1e-6)

    path = export_linear_model(model, tmp_path / "travel_time.onnx")

    proto = onnx.load_model(str(path))
    onnx.checker.check_model(proto)
    assert proto.opset_import[0].version == ONNX_OPSET_VERSION
    assert [entry.name for entry in proto.graph.input] == [GRAPH_INPUT_NAME]
    assert [entry.name for entry in proto.graph.output] == [GRAPH_OUTPUT_NAME]
    assert [node.op_type for node in proto.graph.node] == [
        "IsNaN",
        "Where",
        "Cast",
        "Concat",
        "Gemm",
    ]


def test_an_exported_classifier_ends_in_a_probability(tmp_path: Path) -> None:
    matrix = _matrix()
    labels = (matrix[:, 0] > 20.0).astype(np.float64)
    model = fit_logistic(matrix, labels, feature_names=_TWO_FEATURES, l2=1e-3)

    proto = onnx.load_model(str(export_linear_model(model, tmp_path / "stuck_risk.onnx")))

    onnx.checker.check_model(proto)
    assert proto.graph.node[-1].op_type == "Sigmoid"


def test_the_exported_weights_reproduce_the_fitted_prediction(tmp_path: Path) -> None:
    matrix = _matrix()
    model = fit_ridge(matrix, matrix[:, 0] * 3.0 - 1.0, feature_names=_TWO_FEATURES, alpha=1e-6)
    proto = onnx.load_model(str(export_linear_model(model, tmp_path / "kill_time.onnx")))

    tensors = _initializers(proto)

    probe = np.array([[np.nan, 0.25], [7.0, -0.5]], dtype=np.float64)
    missing = np.isnan(probe)
    prepared = np.concatenate(
        (np.where(missing, tensors["medians"], probe), missing.astype(np.float64)), axis=1
    )
    replayed = prepared @ tensors["weights"].reshape(-1) + tensors["bias"][0]
    assert replayed == pytest.approx(model.predict(probe), rel=1e-5)


def test_an_unwritable_artifact_path_is_reported_as_an_export_failure(tmp_path: Path) -> None:
    matrix = _matrix()
    model = fit_ridge(matrix, matrix[:, 0], feature_names=_TWO_FEATURES)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ExportError) as error:
        export_linear_model(model, blocker / "travel_time.onnx")

    assert error.value.code is ExportErrorCode.EXPORT_FAILED


def test_the_dataset_version_tracks_the_exact_tables_it_digests(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)
    table = dataset / TARGET_DECISIONS_FILE

    before = dataset_version((table,))
    table.write_bytes(table.read_bytes() + b"\x00")

    assert before != dataset_version((table,))
    assert len(before) == len(dataset_version((table,)))


def test_the_git_commit_is_read_from_the_checked_out_reference(tmp_path: Path) -> None:
    git_directory = tmp_path / ".git"
    (git_directory / "refs" / "heads").mkdir(parents=True)
    (git_directory / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_directory / "refs" / "heads" / "main").write_text("a" * 40 + "\n", encoding="utf-8")

    assert read_git_commit(tmp_path) == "a" * 40
    assert read_git_commit(tmp_path / "absent") is None


def test_a_training_run_writes_every_artifact_and_a_complete_metadata_document(
    tmp_path: Path,
) -> None:
    dataset = write_dataset(tmp_path)
    output = tmp_path / "models" / "v1"

    report = train_farming_value_models(
        TrainingConfig(
            dataset_directory=dataset,
            output_directory=output,
            telemetry_database=telemetry_database(tmp_path),
            repository_root=Path(),
        )
    )

    assert sorted(path.name for path in output.iterdir()) == sorted(
        [METADATA_FILENAME] + [artifact_filename(kind) for kind in ValueModelKind]
    )
    metadata = load_metadata(report.metadata_path)
    assert metadata["artifact_version"] == "v1"
    assert metadata["onnx_opset"] == ONNX_OPSET_VERSION
    assert metadata["label_schema"] == list(LABEL_NAMES)
    assert metadata["followup_value_definition"] == "kills_next_10s"
    assert metadata["client_build_hashes"] == ["clienthash0", "clienthash1"]
    feature_schema = metadata["feature_schema"]
    assert isinstance(feature_schema, dict)
    assert feature_schema["raw_features"] == list(FEATURE_NAMES)
    assert feature_schema["missing_indicator_suffix"] == MISSING_INDICATOR_SUFFIX
    dataset_metadata = metadata["dataset"]
    assert isinstance(dataset_metadata, dict)
    assert dataset_metadata["session_count"] == 2
    assert dataset_metadata["split_strategy"] == "session"


def test_metadata_records_one_entry_with_metrics_for_every_prediction_head(
    tmp_path: Path,
) -> None:
    dataset = write_dataset(tmp_path)
    output = tmp_path / "models" / "v1"

    report = train_farming_value_models(
        TrainingConfig(dataset_directory=dataset, output_directory=output)
    )

    models = load_metadata(report.metadata_path)["models"]
    assert isinstance(models, dict)
    assert set(models) == {kind.value for kind in ValueModelKind}
    for kind in ValueModelKind:
        entry = models[kind.value]
        assert entry["trained"] is True
        assert entry["file"] == artifact_filename(kind)
        assert entry["metrics"] and entry["baseline_metrics"]
    assert models["stuck_risk"]["metrics"]["roc_auc"] is not None
    assert models["followup_value"]["metrics"]["spearman_rho"] is not None


def test_the_configured_cost_weights_are_recorded_in_the_metadata(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)
    output = tmp_path / "models" / "v1"

    exit_code = main(
        [
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--telemetry-database",
            str(telemetry_database(tmp_path)),
            "--followup-value",
            "targetable_mobs_after_kill",
            "--travel-weight",
            "2.0",
            "--followup-weight",
            "0.5",
        ]
    )

    assert exit_code == ExitCode.SUCCESS
    metadata = json.loads((output / METADATA_FILENAME).read_text(encoding="utf-8"))
    assert metadata["expected_cost_weights"]["travel"] == 2.0
    assert metadata["expected_cost_weights"]["followup"] == 0.5
    assert metadata["followup_value_definition"] == "targetable_mobs_after_kill"


def test_the_offline_command_trains_without_a_running_client(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)
    output = tmp_path / "models" / "v1"

    exit_code = main(["--dataset", str(dataset), "--output", str(output)])

    assert exit_code == ExitCode.SUCCESS
    for kind in ValueModelKind:
        onnx.checker.check_model(onnx.load_model(str(output / artifact_filename(kind))))


def test_the_offline_command_reports_a_missing_dataset(tmp_path: Path) -> None:
    exit_code = main(["--dataset", str(tmp_path / "absent"), "--output", str(tmp_path / "models")])

    assert exit_code == ExitCode.VALUE_MODEL_FAILURE
    assert not (tmp_path / "models").exists()


def test_the_offline_command_rejects_an_invalid_holdout_fraction(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    exit_code = main(
        [
            "--dataset",
            str(dataset),
            "--output",
            str(tmp_path / "models"),
            "--holdout-fraction",
            "1.5",
        ]
    )

    assert exit_code == ExitCode.VALUE_MODEL_FAILURE
