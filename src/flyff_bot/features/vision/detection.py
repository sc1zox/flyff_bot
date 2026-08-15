"""OpenCV DNN inference for standard raw YOLO ONNX detection models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.features.vision.models import CapturedFrame, ClientSize, PixelFormat

DEFAULT_INPUT_WIDTH = 640
DEFAULT_INPUT_HEIGHT = 640
DEFAULT_CONFIDENCE_THRESHOLD = 0.5
DEFAULT_NMS_THRESHOLD = 0.45
YOLO_BOX_VALUE_COUNT = 4
NORMALIZED_PIXEL_SCALE = 1.0 / 255.0


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A rectangle expressed in client-frame pixels."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Bounding box dimensions must be positive.")


@dataclass(frozen=True, slots=True)
class Detection:
    """One detected object with model-provided class information."""

    bounding_box: BoundingBox
    confidence: float
    class_id: int
    class_name: str


@dataclass(frozen=True, slots=True)
class DetectionConfig:
    """Stable inference and filtering configuration for a YOLO detector."""

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    nms_threshold: float = DEFAULT_NMS_THRESHOLD
    input_size: ClientSize = field(
        default_factory=lambda: ClientSize(DEFAULT_INPUT_WIDTH, DEFAULT_INPUT_HEIGHT)
    )
    allowed_class_names: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("Confidence threshold must be between zero and one.")
        if not 0.0 <= self.nms_threshold <= 1.0:
            raise ValueError("NMS threshold must be between zero and one.")


class DetectionErrorCode(StrEnum):
    """Known model-loading and inference failures."""

    MODEL_NOT_FOUND = "model_not_found"
    MODEL_LOAD_FAILED = "model_load_failed"
    LABELS_NOT_FOUND = "labels_not_found"
    LABELS_INVALID = "labels_invalid"
    UNKNOWN_CLASS_FILTER = "unknown_class_filter"
    INFERENCE_FAILED = "inference_failed"
    INVALID_MODEL_OUTPUT = "invalid_model_output"


class DetectionError(RuntimeError):
    """A known detection failure mapped to localized presentation text."""

    def __init__(self, code: DetectionErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class Detector(Protocol):
    """Injectable object detector used by perception consumers and tests."""

    def detect(self, frame: CapturedFrame) -> list[Detection]:
        """Return visible objects in the supplied client frame."""


class _Network(Protocol):
    def setInput(self, blob: npt.NDArray[np.float32]) -> None: ...

    def forward(self) -> npt.NDArray[np.float32]: ...


class _NetworkLoader(Protocol):
    def load(self, model_path: Path) -> _Network: ...


class _OpenCvNetworkLoader:
    def load(self, model_path: Path) -> _Network:
        if not model_path.is_file():
            raise DetectionError(DetectionErrorCode.MODEL_NOT_FOUND)
        try:
            return cast(_Network, cv2.dnn.readNetFromONNX(str(model_path)))
        except cv2.error as error:
            raise DetectionError(DetectionErrorCode.MODEL_LOAD_FAILED) from error


def load_class_names(labels_path: Path) -> tuple[str, ...]:
    """Read one non-empty class name per UTF-8 line, ordered by class ID."""

    try:
        class_names = tuple(labels_path.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError as error:
        raise DetectionError(DetectionErrorCode.LABELS_NOT_FOUND) from error
    except OSError as error:
        raise DetectionError(DetectionErrorCode.LABELS_INVALID) from error
    if not class_names or any(not class_name.strip() for class_name in class_names):
        raise DetectionError(DetectionErrorCode.LABELS_INVALID)
    return class_names


class OpenCVDnnYoloDetector:
    """CPU OpenCV-DNN detector for raw Ultralytics-style YOLO ONNX outputs."""

    def __init__(
        self,
        network: _Network,
        class_names: Sequence[str],
        config: DetectionConfig | None = None,
    ) -> None:
        self._network = network
        self._class_names = tuple(class_names)
        self._config = config or DetectionConfig()
        if not self._class_names or any(not name.strip() for name in self._class_names):
            raise DetectionError(DetectionErrorCode.LABELS_INVALID)
        unknown_names = self._config.allowed_class_names.difference(self._class_names)
        if unknown_names:
            raise DetectionError(DetectionErrorCode.UNKNOWN_CLASS_FILTER)

    @classmethod
    def from_files(
        cls,
        model_path: Path,
        labels_path: Path,
        config: DetectionConfig | None = None,
        *,
        _loader: _NetworkLoader | None = None,
    ) -> OpenCVDnnYoloDetector:
        """Load a model and its ordered class labels from explicit file paths."""

        loader = _loader or _OpenCvNetworkLoader()
        return cls(loader.load(model_path), load_class_names(labels_path), config)

    def detect(self, frame: CapturedFrame) -> list[Detection]:
        """Infer, filter, and suppress overlapping detections in client coordinates."""

        try:
            blob = cast(
                npt.NDArray[np.float32],
                cv2.dnn.blobFromImage(
                    frame.pixels,
                    scalefactor=NORMALIZED_PIXEL_SCALE,
                    size=(self._config.input_size.width, self._config.input_size.height),
                    swapRB=frame.pixel_format is PixelFormat.BGR,
                    crop=False,
                ),
            )
            self._network.setInput(blob)
            output = np.asarray(self._network.forward(), dtype=np.float32)
        except cv2.error as error:
            raise DetectionError(DetectionErrorCode.INFERENCE_FAILED) from error
        candidates = self._decode(output, frame.client_size)
        if not candidates:
            return []
        boxes = [
            [
                candidate.bounding_box.x,
                candidate.bounding_box.y,
                candidate.bounding_box.width,
                candidate.bounding_box.height,
            ]
            for candidate in candidates
        ]
        confidences = [candidate.confidence for candidate in candidates]
        indexes = cv2.dnn.NMSBoxes(
            boxes,
            confidences,
            self._config.confidence_threshold,
            self._config.nms_threshold,
        )
        return [candidates[int(index)] for index in np.asarray(indexes).reshape(-1)]

    def _decode(self, output: npt.NDArray[np.float32], source_size: ClientSize) -> list[Detection]:
        rows = _prediction_rows(output)
        detections: list[Detection] = []
        scale_x = source_size.width / self._config.input_size.width
        scale_y = source_size.height / self._config.input_size.height
        for row in rows:
            class_scores = row[YOLO_BOX_VALUE_COUNT:]
            class_id = int(np.argmax(class_scores))
            confidence = float(class_scores[class_id])
            if confidence < self._config.confidence_threshold or class_id >= len(self._class_names):
                continue
            class_name = self._class_names[class_id]
            if (
                self._config.allowed_class_names
                and class_name not in self._config.allowed_class_names
            ):
                continue
            box = _scaled_box(row, scale_x, scale_y, source_size)
            if box is not None:
                detections.append(Detection(box, confidence, class_id, class_name))
        return detections


def _prediction_rows(output: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    if output.ndim == 3 and output.shape[0] == 1:
        output = output[0]
    if output.ndim != 2:
        raise DetectionError(DetectionErrorCode.INVALID_MODEL_OUTPUT)
    if output.shape[0] >= YOLO_BOX_VALUE_COUNT + 1 and output.shape[0] < output.shape[1]:
        output = output.transpose()
    if output.shape[1] <= YOLO_BOX_VALUE_COUNT:
        raise DetectionError(DetectionErrorCode.INVALID_MODEL_OUTPUT)
    return output


def _scaled_box(
    row: npt.NDArray[np.float32], scale_x: float, scale_y: float, source_size: ClientSize
) -> BoundingBox | None:
    center_x, center_y, width, height = (float(value) for value in row[:YOLO_BOX_VALUE_COUNT])
    left = max(0, round((center_x - width / 2) * scale_x))
    top = max(0, round((center_y - height / 2) * scale_y))
    right = min(source_size.width, round((center_x + width / 2) * scale_x))
    bottom = min(source_size.height, round((center_y + height / 2) * scale_y))
    if right <= left or bottom <= top:
        return None
    return BoundingBox(left, top, right - left, bottom - top)
