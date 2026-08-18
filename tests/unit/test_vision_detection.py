"""Unit tests for model-free YOLO output decoding and filtering."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flyff_bot.features.vision import (
    CapturedFrame,
    ClientSize,
    DetectionConfig,
    DetectionError,
    DetectionErrorCode,
    OpenCVDnnYoloDetector,
)


class _Network:
    def __init__(self, output: np.ndarray) -> None:
        self.output = output
        self.received_input: np.ndarray | None = None

    def setInput(self, blob: np.ndarray) -> None:
        self.received_input = blob

    def forward(self) -> np.ndarray:
        return self.output


class _Loader:
    def __init__(self, network: _Network) -> None:
        self.network = network

    def load(self, _model_path: Path) -> _Network:
        return self.network


def _frame() -> CapturedFrame:
    return CapturedFrame(np.zeros((100, 200, 3), dtype=np.uint8), ClientSize(200, 100))


def test_detector_returns_structured_client_space_detection() -> None:
    network = _Network(np.array([[[320.0, 320.0, 160.0, 160.0, 0.1, 0.9]]], dtype=np.float32))
    detector = OpenCVDnnYoloDetector(network, ("npc", "mob"))

    detections = detector.detect(_frame())

    assert network.received_input is not None
    assert detections[0].bounding_box.x == 75
    assert detections[0].bounding_box.y == 38
    assert detections[0].bounding_box.width == 50
    assert detections[0].bounding_box.height == 24
    assert detections[0].confidence == pytest.approx(0.9)
    assert detections[0].class_id == 1
    assert detections[0].class_name == "mob"


def test_detector_filters_classes_and_returns_empty_when_no_mobs() -> None:
    output = np.array([[[320.0, 320.0, 100.0, 100.0, 0.95, 0.05]]], dtype=np.float32)
    detector = OpenCVDnnYoloDetector(
        _Network(output),
        ("npc", "mob"),
        DetectionConfig(allowed_class_names=frozenset({"mob"})),
    )

    assert detector.detect(_frame()) == []


@pytest.mark.parametrize(
    ("output", "expected_code"),
    [
        (np.zeros((1, 3), dtype=np.float32), DetectionErrorCode.INVALID_MODEL_OUTPUT),
        (np.zeros((1, 1, 4), dtype=np.float32), DetectionErrorCode.INVALID_MODEL_OUTPUT),
    ],
)
def test_detector_rejects_invalid_yolo_outputs(
    output: np.ndarray, expected_code: DetectionErrorCode
) -> None:
    detector = OpenCVDnnYoloDetector(_Network(output), ("mob",))

    with pytest.raises(DetectionError) as error:
        detector.detect(_frame())

    assert error.value.code is expected_code


def test_detector_rejects_unknown_class_filter() -> None:
    with pytest.raises(DetectionError) as error:
        OpenCVDnnYoloDetector(
            _Network(np.zeros((1, 1, 5), dtype=np.float32)),
            ("mob",),
            DetectionConfig(allowed_class_names=frozenset({"player"})),
        )

    assert error.value.code is DetectionErrorCode.UNKNOWN_CLASS_FILTER


def test_from_files_reports_missing_model_and_labels(tmp_path: Path) -> None:
    labels_path = tmp_path / "classes.txt"
    labels_path.write_text("mob\n", encoding="utf-8")

    with pytest.raises(DetectionError) as model_error:
        OpenCVDnnYoloDetector.from_files(tmp_path / "missing.onnx", labels_path)
    with pytest.raises(DetectionError) as labels_error:
        OpenCVDnnYoloDetector.from_files(
            tmp_path / "model.onnx",
            tmp_path / "missing.txt",
            _loader=_Loader(_Network(np.zeros((1, 1, 5)))),
        )

    assert model_error.value.code is DetectionErrorCode.MODEL_NOT_FOUND
    assert labels_error.value.code is DetectionErrorCode.LABELS_NOT_FOUND


def test_detector_applies_a_live_class_filter_change_without_reloading() -> None:
    output = np.array([[[320.0, 320.0, 100.0, 100.0, 0.95, 0.05]]], dtype=np.float32)
    detector = OpenCVDnnYoloDetector(_Network(output), ("npc", "mob"))

    assert [detection.class_name for detection in detector.detect(_frame())] == ["npc"]

    detector.update_allowed_class_names(frozenset({"mob"}))

    assert detector.config.allowed_class_names == frozenset({"mob"})
    assert detector.detect(_frame()) == []

    detector.update_allowed_class_names(frozenset())

    assert [detection.class_name for detection in detector.detect(_frame())] == ["npc"]


def test_detector_rejects_a_live_filter_change_to_an_unknown_class() -> None:
    detector = OpenCVDnnYoloDetector(_Network(np.zeros((1, 1, 5), dtype=np.float32)), ("mob",))

    with pytest.raises(DetectionError) as error:
        detector.update_allowed_class_names(frozenset({"player"}))

    assert error.value.code is DetectionErrorCode.UNKNOWN_CLASS_FILTER
    assert detector.config.allowed_class_names == frozenset()
