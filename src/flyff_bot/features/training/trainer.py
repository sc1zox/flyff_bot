"""Optional Ultralytics adapter for local custom-model training and export."""

from __future__ import annotations

import shutil
from pathlib import Path

from flyff_bot.features.training.dataset import DatasetManifest, validate_dataset

DEFAULT_BASE_MODEL = "yolo11n.pt"


class TrainingError(RuntimeError):
    """A local training or model-export failure."""


def train_and_export(
    manifest_path: Path,
    output_model_path: Path,
    labels_path: Path,
    *,
    base_model: str = DEFAULT_BASE_MODEL,
    epochs: int = 100,
) -> DatasetManifest:
    """Train a lightweight YOLO model and export its ONNX model and ordered labels."""

    validation = validate_dataset(manifest_path)
    if not validation.is_valid or validation.manifest is None:
        raise TrainingError("dataset_invalid")
    if epochs <= 0:
        raise TrainingError("epochs_invalid")
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise TrainingError("training_extra_required") from error
    try:
        model = YOLO(base_model)
        model.train(data=str(manifest_path), epochs=epochs)
        exported_model = Path(model.export(format="onnx"))
        output_model_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(exported_model, output_model_path)
        labels_path.parent.mkdir(parents=True, exist_ok=True)
        labels_path.write_text("\n".join(validation.manifest.class_names) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as error:
        raise TrainingError("training_failed") from error
    return validation.manifest
