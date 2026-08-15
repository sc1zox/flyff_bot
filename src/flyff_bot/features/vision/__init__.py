"""Client-frame capture for the perception pipeline."""

from flyff_bot.features.vision.capture import FrameSource, WindowsFrameSource
from flyff_bot.features.vision.detection import (
    BoundingBox,
    Detection,
    DetectionConfig,
    DetectionError,
    DetectionErrorCode,
    Detector,
    OpenCVDnnYoloDetector,
    load_class_names,
)
from flyff_bot.features.vision.models import (
    CapturedFrame,
    ClientPoint,
    ClientSize,
    FrameCaptureError,
    FrameCaptureErrorCode,
    PixelFormat,
)
from flyff_bot.features.vision.target_verification import (
    TargetRegion,
    TargetStatus,
    TargetVerificationConfig,
    TargetVerificationResult,
    TargetVerifier,
    extract_target_region,
)

__all__ = [
    "BoundingBox",
    "CapturedFrame",
    "ClientPoint",
    "ClientSize",
    "Detection",
    "DetectionConfig",
    "DetectionError",
    "DetectionErrorCode",
    "Detector",
    "FrameCaptureError",
    "FrameCaptureErrorCode",
    "FrameSource",
    "OpenCVDnnYoloDetector",
    "PixelFormat",
    "TargetRegion",
    "TargetStatus",
    "TargetVerificationConfig",
    "TargetVerificationResult",
    "TargetVerifier",
    "WindowsFrameSource",
    "extract_target_region",
    "load_class_names",
]
