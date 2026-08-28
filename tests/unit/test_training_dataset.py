"""Tests for standard YOLO dataset validation."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from flyff_bot.features.training import validate_dataset


def _manifest(root: Path) -> Path:
    manifest = root / "data.yaml"
    manifest.write_text(
        "path: .\ntrain: images/train\nval: images/val\nnames:\n  0: Flame\n  1: Burudeng\n",
        encoding="utf-8",
    )
    for split in ("train", "val"):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
    return manifest


def _image(path: Path) -> None:
    assert cv2.imwrite(str(path), np.zeros((8, 8, 3), dtype=np.uint8))


def _labelled(root: Path, split: str, stem: str) -> None:
    _image(root / "images" / split / f"{stem}.png")
    (root / "labels" / split / f"{stem}.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")


def _split_manifest(root: Path) -> Path:
    """Write a manifest whose split directories are not the conventional default names."""

    manifest_path = root / "data.yaml"
    manifest_path.write_text(
        "path: .\ntrain: images/fitting\nval: images/holdout\nnames:\n  0: Flame\n",
        encoding="utf-8",
    )
    return manifest_path


def test_validator_accepts_multiclass_yolo_dataset(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    _labelled(tmp_path, "train", "flame")
    _labelled(tmp_path, "val", "burudeng")

    result = validate_dataset(manifest_path)

    assert result.is_valid
    assert result.manifest is not None
    assert result.manifest.class_names == ("Flame", "Burudeng")


def test_validator_reads_the_split_directories_the_manifest_declares(tmp_path: Path) -> None:
    """BUG-030: a manifest naming non-default split paths must be read, not guessed."""

    manifest_path = _split_manifest(tmp_path)
    for split in ("fitting", "holdout"):
        (tmp_path / "images" / split).mkdir(parents=True)
        (tmp_path / "labels" / split).mkdir(parents=True)
    _labelled(tmp_path, "fitting", "flame")
    _labelled(tmp_path, "holdout", "ember")

    result = validate_dataset(manifest_path)

    assert result.is_valid
    assert result.manifest is not None
    assert result.manifest.split_image_directories["train"] == (tmp_path / "images" / "fitting")
    assert result.manifest.label_directory("val") == (tmp_path / "labels" / "holdout")


def test_validator_reports_declared_split_directories_that_do_not_exist(tmp_path: Path) -> None:
    """BUG-030: the reported path is the declared one, not a guessed default layout."""

    manifest_path = _split_manifest(tmp_path)

    result = validate_dataset(manifest_path)

    assert [issue.code for issue in result.issues] == ["layout_missing", "layout_missing"]
    assert {issue.path for issue in result.issues} == {
        tmp_path / "images" / "fitting",
        tmp_path / "images" / "holdout",
    }


def test_validator_rejects_an_empty_training_or_validation_split(tmp_path: Path) -> None:
    """BUG-030: an empty split fits or measures nothing and must not validate."""

    manifest_path = _manifest(tmp_path)
    _labelled(tmp_path, "train", "flame")

    result = validate_dataset(manifest_path)

    assert not result.is_valid
    assert [issue.code for issue in result.issues] == ["split_empty"]
    assert result.issues[0].path == (tmp_path / "images" / "val")


def test_validator_reports_corrupt_images_missing_and_invalid_labels(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    corrupt_image = tmp_path / "images" / "train" / "corrupt.png"
    corrupt_image.write_bytes(b"not an image")
    _image(tmp_path / "images" / "train" / "missing.png")
    _image(tmp_path / "images" / "val" / "bad.png")
    (tmp_path / "labels" / "val" / "bad.txt").write_text("4 0.5 0.5 2 0\n", encoding="utf-8")
    orphan = tmp_path / "labels" / "val" / "orphan.txt"
    orphan.write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")

    result = validate_dataset(manifest_path)

    assert {issue.code for issue in result.issues} == {
        "image_corrupt",
        "label_missing",
        "label_invalid",
        "image_missing",
    }


def test_validator_rejects_non_contiguous_class_ids(tmp_path: Path) -> None:
    manifest_path = tmp_path / "data.yaml"
    manifest_path.write_text(
        "path: .\ntrain: images/train\nval: images/val\nnames:\n  1: Flame\n", encoding="utf-8"
    )

    result = validate_dataset(manifest_path)

    assert result.issues[0].code == "manifest_invalid"
