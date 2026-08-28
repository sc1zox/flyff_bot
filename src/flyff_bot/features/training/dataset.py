"""Validation for a small, standard YOLO detection dataset layout."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import cv2
import yaml

DATASET_SPLITS = ("train", "val")
IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".webp"})
YOLO_LABEL_VALUE_COUNT = 5
# The standard YOLO layout pairs an image directory with a label directory that differs only
# in this one path component, so the declared image path determines where labels are read.
IMAGE_DIRECTORY_NAME = "images"
LABEL_DIRECTORY_NAME = "labels"
# Named so the handlers below stay single-name `except` clauses. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
ANNOTATION_FIELD_ERRORS = (IndexError, ValueError)


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """The class registry, root and declared split locations of a YOLO data manifest."""

    path: Path
    root: Path
    class_names: tuple[str, ...]
    split_image_directories: Mapping[str, Path]

    def label_directory(self, split: str) -> Path:
        """Return the label directory paired with one declared split image directory."""

        return _paired_label_directory(self.split_image_directories[split])


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
    return DatasetManifest(
        manifest_path,
        root,
        class_names,
        {
            "train": (root / train_path).resolve(),
            "val": (root / validation_path).resolve(),
        },
    )


def _paired_label_directory(image_directory: Path) -> Path:
    """Return the label directory of one image directory, keeping the rest of the path.

    Only the last `images` component is rewritten, so a dataset root that itself contains
    the word `images` is not corrupted by the substitution.
    """

    parts = list(image_directory.parts)
    for position in range(len(parts) - 1, -1, -1):
        if parts[position] == IMAGE_DIRECTORY_NAME:
            parts[position] = LABEL_DIRECTORY_NAME
            return Path(*parts)
    return image_directory.parent / LABEL_DIRECTORY_NAME / image_directory.name


def validate_dataset(manifest_path: Path) -> DatasetValidationResult:
    """Validate required YOLO directories, image readability, and label annotations."""

    try:
        manifest = load_dataset_manifest(manifest_path)
    except ValueError:
        return DatasetValidationResult(None, (DatasetIssue("manifest_invalid", manifest_path),))

    issues: list[DatasetIssue] = []
    for split in DATASET_SPLITS:
        image_directory = manifest.split_image_directories[split]
        label_directory = manifest.label_directory(split)
        if not image_directory.is_dir() or not label_directory.is_dir():
            issues.append(DatasetIssue("layout_missing", image_directory))
            continue
        images = [
            path for path in image_directory.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
        ]
        if not images:
            # Training or validating against an empty split silently produces a model that
            # was never fitted or never measured, so it is refused here (BUG-030).
            issues.append(DatasetIssue("split_empty", image_directory))
            continue
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
        except ANNOTATION_FIELD_ERRORS:
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
