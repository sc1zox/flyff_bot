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


def test_validator_accepts_multiclass_yolo_dataset(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    _image(tmp_path / "images" / "train" / "flame.png")
    (tmp_path / "labels" / "train" / "flame.txt").write_text(
        "0 0.5 0.5 0.2 0.2\n", encoding="utf-8"
    )

    result = validate_dataset(manifest_path)

    assert result.is_valid
    assert result.manifest is not None
    assert result.manifest.class_names == ("Flame", "Burudeng")


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
