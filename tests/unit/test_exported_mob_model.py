"""Compatibility check run automatically once a local exported model is available."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flyff_bot.features.vision import CapturedFrame, ClientSize, OpenCVDnnYoloDetector

MODEL_PATH = Path("models/mob_detector.onnx")
LABELS_PATH = Path("models/labels.txt")


def test_exported_model_loads_and_infers_on_a_sample_frame() -> None:
    """Load and execute the local artifact emitted by the training workflow."""

    if not MODEL_PATH.is_file() or not LABELS_PATH.is_file():
        pytest.skip("Run --train-mob-detector to create the local ONNX artifact.")
    detector = OpenCVDnnYoloDetector.from_files(MODEL_PATH, LABELS_PATH)
    frame = CapturedFrame(np.zeros((64, 64, 3), dtype=np.uint8), ClientSize(64, 64))

    detections = detector.detect(frame)

    assert isinstance(detections, list)
