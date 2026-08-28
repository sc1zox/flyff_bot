"""Tests for local YOLO export integration without a real training run."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
from _pytest.monkeypatch import MonkeyPatch

from flyff_bot.features.training import train_and_export


def _dataset(root: Path) -> Path:
    root.mkdir()
    manifest = root / "data.yaml"
    manifest.write_text(
        "path: .\ntrain: images/train\nval: images/val\nnames:\n  0: Flame\n  1: Burudeng\n",
        encoding="utf-8",
    )
    for split in ("train", "val"):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
        image = root / "images" / split / "sample.png"
        assert cv2.imwrite(str(image), np.zeros((8, 8, 3), dtype=np.uint8))
        (root / "labels" / split / "sample.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n",
            encoding="utf-8",
        )
    return manifest


def test_training_exports_ordered_utf8_labels(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source_model = tmp_path / "source.onnx"
    source_model.write_bytes(b"model")

    class FakeYolo:
        def __init__(self, base_model: str) -> None:
            assert base_model == "base.pt"

        def train(self, *, data: str, epochs: int) -> None:
            assert Path(data).name == "data.yaml"
            assert epochs == 3

        def export(self, *, format: str) -> str:
            assert format == "onnx"
            return str(source_model)

    ultralytics = ModuleType("ultralytics")
    ultralytics.YOLO = FakeYolo  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ultralytics", ultralytics)
    output_model = tmp_path / "models" / "mob_detector.onnx"
    labels_path = tmp_path / "models" / "labels.txt"

    train_and_export(
        _dataset(tmp_path / "dataset"), output_model, labels_path, base_model="base.pt", epochs=3
    )

    assert output_model.read_bytes() == b"model"
    assert labels_path.read_text(encoding="utf-8") == "Flame\nBurudeng\n"
