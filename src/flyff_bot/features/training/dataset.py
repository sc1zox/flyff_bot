"""Validation for a small, standard YOLO detection dataset layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import yaml

DATASET_SPLITS = ("train", "val")
IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".webp"})
YOLO_LABEL_VALUE_COUNT = 5


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """The class registry and root directory declared by a YOLO data manifest."""

    path: Path
    root: Path
    class_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatasetIssue:
    """A machine-readable dataset problem with its affected path."""

    code: str
    path: Path


@dataclass(frozen=True, slots=True)
class DatasetValidationResult:
    """The outcome of validating a manifest and its image/label pairs."""

    manifest: DatasetManifest | None
    issues: tuple[DatasetIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Whether validation found no problems."""

        return not self.issues


def load_dataset_manifest(manifest_path: Path) -> DatasetManifest:
    """Load the constrained standard YOLO manifest used by this project."""

    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError("manifest_invalid") from error
    if not isinstance(raw, dict):
        raise ValueError("manifest_invalid")
    root_value = raw.get("path", ".")
    names = raw.get("names")
    train_path = raw.get("train")
    validation_path = raw.get("val")
    if (
        not isinstance(root_value, str)
        or not isinstance(train_path, str)
        or not isinstance(validation_path, str)
        or not isinstance(names, dict)
    ):
        raise ValueError("manifest_invalid")
    try:
        class_ids = sorted(names)
        if class_ids != list(range(len(class_ids))):
            raise ValueError
        class_names = tuple(names[class_id] for class_id in class_ids)
    except (TypeError, ValueError) as error:
        raise ValueError("manifest_invalid") from error
    if not class_names or any(
        not isinstance(name, str) or not name.strip() for name in class_names
    ):
        raise ValueError("manifest_invalid")
    root = (manifest_path.parent / root_value).resolve()
    return DatasetManifest(manifest_path, root, class_names)


def validate_dataset(manifest_path: Path) -> DatasetValidationResult:
    """Validate required YOLO directories, image readability, and label annotations."""

    try:
        manifest = load_dataset_manifest(manifest_path)
    except ValueError:
        return DatasetValidationResult(None, (DatasetIssue("manifest_invalid", manifest_path),))

    issues: list[DatasetIssue] = []
    for split in DATASET_SPLITS:
        image_directory = manifest.root / "images" / split
        label_directory = manifest.root / "labels" / split
        if not image_directory.is_dir() or not label_directory.is_dir():
            issues.append(DatasetIssue("layout_missing", manifest.root / split))
            continue
        images = [
            path for path in image_directory.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
        ]
        image_stems = {image.stem for image in images}
        for image_path in images:
            if cv2.imread(str(image_path), cv2.IMREAD_COLOR) is None:
                issues.append(DatasetIssue("image_corrupt", image_path))
                continue
            label_path = label_directory / f"{image_path.stem}.txt"
            if not label_path.is_file():
                issues.append(DatasetIssue("label_missing", image_path))
            else:
                issues.extend(_validate_label(label_path, len(manifest.class_names)))
        for label_path in label_directory.glob("*.txt"):
            if label_path.stem not in image_stems:
                issues.append(DatasetIssue("image_missing", label_path))
    return DatasetValidationResult(manifest, tuple(issues))


def _validate_label(label_path: Path, class_count: int) -> list[DatasetIssue]:
    try:
        lines = label_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [DatasetIssue("label_invalid", label_path)]
    issues: list[DatasetIssue] = []
    for line in lines:
        values = line.split()
        try:
            class_id = int(values[0])
            coordinates = [float(value) for value in values[1:]]
        except IndexError, ValueError:
            issues.append(DatasetIssue("label_invalid", label_path))
            continue
        if (
            len(values) != YOLO_LABEL_VALUE_COUNT
            or not 0 <= class_id < class_count
            or any(not 0.0 <= coordinate <= 1.0 for coordinate in coordinates)
            or coordinates[2] <= 0.0
            or coordinates[3] <= 0.0
        ):
            issues.append(DatasetIssue("label_invalid", label_path))
    return issues
