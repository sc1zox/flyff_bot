"""Developer calibration harness for the mob spawn distance relation (US-041).

This is not part of the shipped application and is never imported by `flyff_bot`. It
produces the raw evidence US-037 needs to replace the provisional bounding-box distance
literals in `PathingController._estimate_mob_position` with a fitted relation, and that
evidence cannot be obtained without running the game.

## What is actually measured

Under pinhole perspective projection the apparent height of a fixed-size model falls off
with the inverse of its distance, so the relation to fit is::

    distance = a / bounding_box_height + b

The coefficient `a` is directly proportional to focal length (camera zoom) and effective
pitch. Because apparent bounding box height changes dramatically when camera zoom varies,
100% reproducibility without memory inspection is guaranteed by operating at the
**zoom hard-stop** (mouse wheel scrolled all the way back to Flyff's maximum zoom limit)
with a **controlled ~45° camera pitch** (navigated from vertical hard-stop/reset to preserve
forward field of view), both during calibration and active bot farming.

Multiple mobs of the target class usually share the viewport, so the approach target is
identified once, on the first frame that detects it, as the candidate closest to the
viewport's vertical centreline -- the mob the operator lined the character up with -- and is
then followed from frame to frame by bounding-box overlap and centroid proximity
(`ApproachTargetTracker`). Picking the most confident candidate per frame instead let the
recorded height jump between foreground and background mobs of the same cluster, which
destroyed the monotonic height/travel relation the fit depends on (US-043).

A walk-in approach never reaches the mob: the client stops the character at melee range.
The absolute distance to the mob is therefore never observable. What *is* observable, per
frame, is how far the character still travels from that frame until the approach ends,
which the minimap odometry of US-035 measures directly:

    remaining_travel(i) = total_travel_of_the_run - travel_up_to_frame(i)

At the last frame `remaining_travel` is zero while the true distance is the melee stopping
distance `r_melee`, so substituting the observable into the model gives::

    remaining_travel = a / bounding_box_height + (b - r_melee)

`a` is recovered unchanged and the fitted intercept is the *combined* intercept with the
melee stopping distance folded into it, which is the second of the two options US-037
allows. Distances are in minimap pixels, the canonical unit US-035 establishes.

Because it only reads frames and holds one movement key, it stays inside the project's
safety boundaries: it captures through the documented GDI path, refuses to dispatch input
unless the client is foregrounded, and honours the `END` emergency stop through the shared
input controller.

Its console output is developer diagnostics rather than shipped user-visible text, so it
deliberately does not go through the locale files.

Usage (run on the Windows machine, with the client already running):

    uv run python scripts/capture_spawn_distance_samples.py walk-in \
        --mob-class aibatt --label aibatt-far
    uv run python scripts/capture_spawn_distance_samples.py bearing --label fov-1
    uv run python scripts/capture_spawn_distance_samples.py fit \
        --input "data/calibration/spawn_distance/*walk-in*"
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
import numpy.typing as npt

from flyff_bot.constants import (
    DEFAULT_MOB_LABELS_PATH,
    DEFAULT_MOB_MODEL_PATH,
    DEFAULT_PROCESS_NAME,
)
from flyff_bot.features.automation.camera_alignment import (
    CameraAligner,
    CameraAlignmentStatus,
    frame_minimap_locator,
)
from flyff_bot.features.input_control import WindowRef, WindowsInputController, parse_virtual_key
from flyff_bot.features.navigation.tracking import MovementTracker, TrackingQuality
from flyff_bot.features.vision.capture import WindowsFrameSource
from flyff_bot.features.vision.detection import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    BoundingBox,
    Detection,
    DetectionConfig,
    Detector,
    OpenCVDnnYoloDetector,
)
from flyff_bot.features.vision.minimap import MinimapOdometer
from flyff_bot.features.vision.models import CapturedFrame, FrameCaptureError

# Bumping this invalidates every recorded run rather than migrating it, per ADR-003.
# Version 2 marks the tracked approach target on every frame's detections (US-043); runs
# recorded before it picked a per-frame most-confident mob and cannot be re-interpreted.
MANIFEST_SCHEMA_VERSION = 2
MANIFEST_FILE_NAME = "manifest.json"
DEFAULT_OUTPUT_ROOT = Path("data/calibration/spawn_distance")
# `WindowsFrameSource` captures through `GetClientRect`, so frame row 0 is the first pixel
# below the title bar. The manifest names its origin because the frames shipped in `data/`
# are whole-window captures and the two coordinate systems must be re-based before they are
# compared, exactly as in `capture_minimap_samples.py`.
CAPTURE_ORIGIN = "client_area"

WALK_IN_PROTOCOL = "walk-in"
BEARING_PROTOCOL = "bearing"

DEFAULT_COUNTDOWN_SECONDS = 3.0
FOCUS_SETTLE_SECONDS = 0.3
DEFAULT_FORWARD_KEY = "w"
# At the measured 9.4 minimap px/s a 12 s approach covers roughly 113 px, which is almost
# two leash radii and therefore spans the whole usable bounding-box height range.
DEFAULT_WALK_IN_HOLD_SECONDS = 12.0
# Detection runs inline on every frame, so the loop is inference bound at a few frames per
# second. The budget is a guard against a runaway hold rather than a rate limit.
MAX_WALK_IN_FRAMES = 400
DEFAULT_BEARING_FRAME_COUNT = 12
BEARING_FRAME_INTERVAL_SECONDS = 0.5
# Margin around the stored bounding-box crop so the mob's silhouette stays visible and a
# later reviewer can judge whether the box actually bounds the model.
DETECTION_CROP_MARGIN_PIXELS = 8
PNG_COMPRESSION_LEVEL = 3
FIRST_REFERENCE_FILE_NAME = "reference_first.png"
LAST_REFERENCE_FILE_NAME = "reference_last.png"

# Frame-to-frame gates of the approach tracker. Consecutive frames of a walk-in overlap
# heavily, so any candidate that overlaps the previous box by this much is the same mob even
# when it grew fast enough to move its centroid a long way.
APPROACH_TARGET_MINIMUM_OVERLAP = 0.2
# Without overlap the match has to come from proximity alone. 120 px is wider than one
# frame's centroid drift at the near end of an approach and far narrower than the spacing of
# a spawn cluster, so a briefly hidden mob is recovered without ever adopting its neighbour.
APPROACH_TARGET_MAXIMUM_CENTROID_SHIFT_PIXELS = 120.0
# The detector drops the tracked mob for the odd frame when another model passes in front of
# it. Beyond this many consecutive misses the run has genuinely lost its target, and
# re-acquiring a different one would corrupt the height series the fit reads.
APPROACH_TARGET_MAXIMUM_MISSED_FRAMES = 2

# `d = a / h + b` has two free parameters, so a residual needs at least a third sample.
MINIMUM_FIT_SAMPLE_COUNT = 3
# Deterministic hold-out: every fourth sample by recording order. A pseudo-random split
# would make the reported accuracy depend on a seed that the story does not fix.
DEFAULT_HOLDOUT_STRIDE = 4
FIT_PARAMETER_COUNT = 2

ABORT_REASON_EMERGENCY_STOP = "emergency_stop"
ABORT_REASON_FOCUS_LOST = "focus_lost"
ABORT_REASON_FRAME_BUDGET = "frame_budget_exhausted"


class WindowAccess(Protocol):
    """The window-safety surface a capture run needs from the input controller."""

    def find_windows(self, process_name: str) -> list[WindowRef]:
        """Return the visible top-level windows of the target process."""

    def focus_window(self, window_handle: int) -> None:
        """Bring the target window to the foreground."""

    def is_foreground(self, window_handle: int) -> bool:
        """Return whether the target window is currently foregrounded."""

    def is_aborted(self) -> bool:
        """Return whether the emergency-stop key is currently held."""


@dataclass(frozen=True, slots=True)
class DetectionRecord:
    """One YOLO detection as recorded for offline fitting."""

    class_name: str
    confidence: float
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    width: int
    height: int
    centre_x_offset_pixels: float
    # True on exactly one detection per frame: the mob this walk-in is approaching, as
    # followed across the run by `ApproachTargetTracker`.
    is_approach_target: bool = False
    crop_file_name: str | None = None


@dataclass(frozen=True, slots=True)
class FrameRecord:
    """One captured frame: when it was read, where the character was, and what was seen."""

    index: int
    captured_at: float
    viewport_width: int
    viewport_height: int
    tracking_quality: str
    position_x: float
    position_y: float
    displacement_x: float | None
    displacement_y: float | None
    correlation_response: float | None
    heading_degrees: float | None
    zoom_signature: float
    detections: list[DetectionRecord] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Everything an offline fit needs to interpret one recorded sequence."""

    schema_version: int
    protocol: str
    label: str
    started_at_utc: str
    process_name: str
    window_title: str
    capture_origin: str
    client_width: int
    client_height: int
    mob_class: str | None = None
    camera_pitch_note: str | None = None
    forward_key: str | None = None
    hold_seconds: float | None = None
    key_down_at: float | None = None
    key_up_at: float | None = None
    aborted_reason: str | None = None
    frames: list[FrameRecord] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DistanceSample:
    """One fitting sample: an apparent height and the travel that still remained."""

    mob_class: str
    bounding_box_height: int
    remaining_travel_pixels: float


@dataclass(frozen=True, slots=True)
class InverseDistanceFit:
    """The fitted `d = a / h + b` relation for one mob class and its quality."""

    mob_class: str
    inverse_height_coefficient: float
    combined_intercept_pixels: float
    residual_standard_error_pixels: float
    sample_count: int
    holdout_count: int
    holdout_mean_absolute_error_pixels: float | None

    def predict(self, bounding_box_height: int) -> float:
        """Return the modelled remaining travel for one apparent bounding-box height."""

        if bounding_box_height <= 0:
            raise ValueError("Bounding box height must be positive.")
        return (
            self.inverse_height_coefficient / bounding_box_height + self.combined_intercept_pixels
        )


@dataclass(frozen=True, slots=True)
class ApproachTrackingConfig:
    """Association gates that keep one walk-in locked onto the mob it started on."""

    minimum_overlap: float = APPROACH_TARGET_MINIMUM_OVERLAP
    maximum_centroid_shift_pixels: float = APPROACH_TARGET_MAXIMUM_CENTROID_SHIFT_PIXELS
    maximum_missed_frames: int = APPROACH_TARGET_MAXIMUM_MISSED_FRAMES

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_overlap <= 1.0:
            raise ValueError("The overlap gate must lie between zero and one.")
        if self.maximum_centroid_shift_pixels <= 0.0:
            raise ValueError("The re-acquisition radius must be positive.")
        if self.maximum_missed_frames < 0:
            raise ValueError("The missed-frame budget must not be negative.")


def _centroid(box: BoundingBox) -> tuple[float, float]:
    """Return the centre of one bounding box in client-frame pixels."""

    return box.x + box.width / 2.0, box.y + box.height / 2.0


def centroid_shift(first: BoundingBox, second: BoundingBox) -> float:
    """Return how far two bounding-box centres lie apart, in client-frame pixels."""

    first_x, first_y = _centroid(first)
    second_x, second_y = _centroid(second)
    return math.hypot(first_x - second_x, first_y - second_y)


def overlap_ratio(first: BoundingBox, second: BoundingBox) -> float:
    """Return the intersection over union of two bounding boxes."""

    width = min(first.x + first.width, second.x + second.width) - max(first.x, second.x)
    height = min(first.y + first.height, second.y + second.height) - max(first.y, second.y)
    if width <= 0 or height <= 0:
        return 0.0
    intersection = float(width * height)
    union = float(first.width * first.height + second.width * second.height) - intersection
    return intersection / union


class ApproachTargetTracker:
    """Follow the one mob a walk-in approaches across every frame of the run (US-043).

    The operator lines the character up with the mob before starting, so the target is
    acquired as the candidate whose box centre sits closest to the viewport's vertical
    centreline. Every later frame is matched against the *previous* tracked box rather than
    re-selected on its own merits, which is what keeps the recorded height series attached
    to one physical mob while a whole spawn cluster drifts through the viewport.

    A frame that offers no acceptable match leaves the last known box in place and is simply
    not recorded, so a mob hidden behind another model for a frame or two is picked up again
    where it reappears. Once the miss budget is spent the target counts as lost and nothing
    further is tracked, because adopting whatever is nearby afterwards is exactly the jump
    this tracker exists to prevent.
    """

    def __init__(self, mob_class: str, *, config: ApproachTrackingConfig | None = None) -> None:
        self._mob_class = mob_class
        self._config = config or ApproachTrackingConfig()
        self._tracked: BoundingBox | None = None
        self._missed_frames = 0
        self._lost = False

    @property
    def is_lost(self) -> bool:
        """Return whether the approach target was dropped for longer than the budget."""

        return self._lost

    @property
    def tracked_box(self) -> BoundingBox | None:
        """Return the last accepted box of the approach target, if there was one."""

        return self._tracked

    def track(self, detections: Sequence[Detection], viewport_width: int) -> Detection | None:
        """Return this frame's approach target, or ``None`` when it was not seen."""

        if self._lost:
            return None
        candidates = [
            detection for detection in detections if detection.class_name == self._mob_class
        ]
        chosen = (
            self._acquire(candidates, viewport_width)
            if self._tracked is None
            else self._associate(candidates)
        )
        if chosen is None:
            self._missed_frames += 1
            if (
                self._tracked is not None
                and self._missed_frames > self._config.maximum_missed_frames
            ):
                self._lost = True
            return None
        self._missed_frames = 0
        self._tracked = chosen.bounding_box
        return chosen

    @staticmethod
    def _acquire(candidates: Sequence[Detection], viewport_width: int) -> Detection | None:
        """Pick the candidate the character is facing: the one nearest the centreline."""

        if not candidates:
            return None
        centre = viewport_width / 2.0

        def distance_from_centreline(detection: Detection) -> tuple[float, int]:
            offset, _ = _centroid(detection.bounding_box)
            # A tie between two equally centred mobs goes to the taller, and therefore
            # nearer, of the two.
            return abs(offset - centre), -detection.bounding_box.height

        return min(candidates, key=distance_from_centreline)

    def _associate(self, candidates: Sequence[Detection]) -> Detection | None:
        """Match the previous tracked box against this frame's candidates."""

        tracked = self._tracked
        assert tracked is not None
        scored: list[tuple[float, float, Detection]] = []
        for candidate in candidates:
            overlap = overlap_ratio(tracked, candidate.bounding_box)
            shift = centroid_shift(tracked, candidate.bounding_box)
            if (
                overlap < self._config.minimum_overlap
                and shift > self._config.maximum_centroid_shift_pixels
            ):
                continue
            scored.append((-overlap, shift, candidate))
        if not scored:
            return None
        return min(scored, key=lambda entry: (entry[0], entry[1]))[2]


@dataclass(slots=True)
class _HeldKeyTiming:
    """Perf-counter bracket around the guarded key hold running on its own thread."""

    down_at: float | None = None
    up_at: float | None = None
    error: BaseException | None = None


# --------------------------------------------------------------------------------------
# Manifest serialisation
# --------------------------------------------------------------------------------------


def manifest_to_mapping(manifest: RunManifest) -> dict[str, Any]:
    """Return the JSON-ready mapping of one run manifest."""

    return asdict(manifest)


def manifest_from_mapping(payload: Mapping[str, Any]) -> RunManifest:
    """Rebuild a run manifest, rejecting any schema version this script did not write."""

    version = payload.get("schema_version")
    if version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"Unsupported manifest schema version: {version!r}.")
    frames = [
        FrameRecord(
            **{key: value for key, value in frame.items() if key != "detections"},
            detections=[DetectionRecord(**detection) for detection in frame["detections"]],
        )
        for frame in payload["frames"]
    ]
    return RunManifest(
        **{key: value for key, value in payload.items() if key != "frames"},
        frames=frames,
    )


def load_manifest(path: Path) -> RunManifest:
    """Read one `manifest.json`, or the manifest inside one run directory."""

    manifest_path = path / MANIFEST_FILE_NAME if path.is_dir() else path
    return manifest_from_mapping(json.loads(manifest_path.read_text(encoding="utf-8")))


def resolve_manifest_paths(patterns: Sequence[str]) -> list[Path]:
    """Expand paths and globs into the run manifests they name, in stable order."""

    resolved: list[Path] = []
    for pattern in patterns:
        matches = [Path(match) for match in sorted(glob.glob(pattern))]
        candidates = matches or [Path(pattern)]
        for candidate in candidates:
            manifest_path = candidate / MANIFEST_FILE_NAME if candidate.is_dir() else candidate
            if manifest_path.is_file() and manifest_path not in resolved:
                resolved.append(manifest_path)
    return resolved


# --------------------------------------------------------------------------------------
# Offline fitting
# --------------------------------------------------------------------------------------


def _approach_detection(frame: FrameRecord, mob_class: str) -> DetectionRecord | None:
    """Return the tracked approach target of one frame, if the tracker held it there."""

    for detection in frame.detections:
        if detection.is_approach_target and detection.class_name == mob_class:
            return detection
    return None


def _measured_increment(frame: FrameRecord) -> float | None:
    """Return the travel since the previous frame, or ``None`` when it was not measured."""

    if frame.tracking_quality != TrackingQuality.MEASURED.value:
        return None
    if frame.displacement_x is None or frame.displacement_y is None:
        return None
    return math.hypot(frame.displacement_x, frame.displacement_y)


def walk_in_samples(manifest: RunManifest) -> list[DistanceSample]:
    """Turn one walk-in run into fitting samples of apparent height versus remaining travel.

    Remaining travel is accumulated backwards from the end of the run, so an unmeasured
    increment invalidates only the frames *before* it: everything from that frame onwards
    still has a fully measured travel chain to the stopping point. The frames before the
    last gap are therefore dropped rather than silently under-counted.
    """

    if manifest.protocol != WALK_IN_PROTOCOL or manifest.mob_class is None:
        return []
    frames = manifest.frames
    if not frames:
        return []

    first_usable = 0
    for index, frame in enumerate(frames):
        if index > 0 and _measured_increment(frame) is None:
            first_usable = index
    usable = frames[first_usable:]

    travelled = 0.0
    cumulative: list[tuple[FrameRecord, float]] = []
    for offset, frame in enumerate(usable):
        if offset > 0:
            increment = _measured_increment(frame)
            travelled += 0.0 if increment is None else increment
        cumulative.append((frame, travelled))
    total = cumulative[-1][1]

    samples: list[DistanceSample] = []
    for frame, travel in cumulative:
        detection = _approach_detection(frame, manifest.mob_class)
        if detection is None or detection.height <= 0:
            continue
        samples.append(
            DistanceSample(
                mob_class=manifest.mob_class,
                bounding_box_height=detection.height,
                remaining_travel_pixels=total - travel,
            )
        )
    return samples


def _least_squares(samples: Sequence[DistanceSample]) -> tuple[float, float, float]:
    """Fit `d = a / h + b` and return the coefficient, intercept, and residual error."""

    design = np.array(
        [[1.0 / sample.bounding_box_height, 1.0] for sample in samples], dtype=np.float64
    )
    observed = np.array([sample.remaining_travel_pixels for sample in samples], dtype=np.float64)
    solution, _, _, _ = np.linalg.lstsq(design, observed, rcond=None)
    residuals = observed - design @ solution
    degrees_of_freedom = max(1, len(samples) - FIT_PARAMETER_COUNT)
    error = math.sqrt(float(residuals @ residuals) / degrees_of_freedom)
    return float(solution[0]), float(solution[1]), error


def fit_inverse_distance(
    samples: Sequence[DistanceSample],
    mob_class: str,
    holdout_stride: int = DEFAULT_HOLDOUT_STRIDE,
) -> InverseDistanceFit:
    """Fit the inverse-distance relation and score it on a deterministic hold-out split."""

    if len(samples) < MINIMUM_FIT_SAMPLE_COUNT:
        raise ValueError(
            f"At least {MINIMUM_FIT_SAMPLE_COUNT} samples are required to fit a relation."
        )
    if holdout_stride < FIT_PARAMETER_COUNT:
        raise ValueError("Hold-out stride must leave at least half of the samples for fitting.")
    coefficient, intercept, error = _least_squares(samples)

    held_out = [sample for index, sample in enumerate(samples) if index % holdout_stride == 0]
    trained_on = [sample for index, sample in enumerate(samples) if index % holdout_stride != 0]
    holdout_error: float | None = None
    if held_out and len(trained_on) >= MINIMUM_FIT_SAMPLE_COUNT:
        holdout_coefficient, holdout_intercept, _ = _least_squares(trained_on)
        holdout_error = float(
            np.mean(
                [
                    abs(
                        holdout_coefficient / sample.bounding_box_height
                        + holdout_intercept
                        - sample.remaining_travel_pixels
                    )
                    for sample in held_out
                ]
            )
        )
    return InverseDistanceFit(
        mob_class=mob_class,
        inverse_height_coefficient=coefficient,
        combined_intercept_pixels=intercept,
        residual_standard_error_pixels=error,
        sample_count=len(samples),
        holdout_count=len(held_out) if holdout_error is not None else 0,
        holdout_mean_absolute_error_pixels=holdout_error,
    )


def group_samples_by_class(
    samples: Iterable[DistanceSample],
) -> dict[str, list[DistanceSample]]:
    """Group samples per mob class, because model heights differ per class (US-037)."""

    grouped: dict[str, list[DistanceSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.mob_class, []).append(sample)
    return grouped


# --------------------------------------------------------------------------------------
# Live capture
# --------------------------------------------------------------------------------------


def _detection_record(
    detection: Detection,
    client_width: int,
    *,
    is_approach_target: bool,
    crop_file_name: str | None,
) -> DetectionRecord:
    """Describe one detection in the coordinates the offline fit reads."""

    box = detection.bounding_box
    centre_x = box.x + box.width / 2.0
    return DetectionRecord(
        class_name=detection.class_name,
        confidence=float(detection.confidence),
        x_min=box.x,
        y_min=box.y,
        x_max=box.x + box.width,
        y_max=box.y + box.height,
        width=box.width,
        height=box.height,
        centre_x_offset_pixels=centre_x - client_width / 2.0,
        is_approach_target=is_approach_target,
        crop_file_name=crop_file_name,
    )


def _crop_detection(frame: CapturedFrame, detection: Detection) -> npt.NDArray[np.uint8]:
    """Return a lossless copy of the detection's bounding box with a small margin."""

    box = detection.bounding_box
    margin = DETECTION_CROP_MARGIN_PIXELS
    left = max(0, box.x - margin)
    top = max(0, box.y - margin)
    right = min(frame.client_size.width, box.x + box.width + margin)
    bottom = min(frame.client_size.height, box.y + box.height + margin)
    return np.ascontiguousarray(frame.pixels[top:bottom, left:right])


def _observe_frame(
    index: int,
    frame: CapturedFrame,
    captured_at: float,
    odometer: MinimapOdometer,
    tracker: MovementTracker,
    detector: Detector,
    approach_tracker: ApproachTargetTracker | None,
) -> tuple[FrameRecord, npt.NDArray[np.uint8] | None]:
    """Fold one frame into odometry and detection, returning its record and target crop."""

    reading = odometer.observe(frame)
    update = tracker.observe(reading, captured_at)
    position = tracker.position
    displacement = None if reading is None else reading.displacement

    detections = detector.detect(frame)
    target = (
        None
        if approach_tracker is None
        else approach_tracker.track(detections, frame.client_size.width)
    )
    crop_file_name = None if target is None else _crop_file_name(index)
    records = [
        _detection_record(
            detection,
            frame.client_size.width,
            is_approach_target=detection is target,
            crop_file_name=crop_file_name if detection is target else None,
        )
        for detection in detections
    ]
    record = FrameRecord(
        index=index,
        captured_at=captured_at,
        viewport_width=frame.client_size.width,
        viewport_height=frame.client_size.height,
        tracking_quality=update.quality.value,
        position_x=position.x,
        position_y=position.y,
        displacement_x=None if displacement is None else displacement.x,
        displacement_y=None if displacement is None else displacement.y,
        correlation_response=None if displacement is None else displacement.response,
        heading_degrees=None if reading is None else reading.heading_degrees,
        zoom_signature=0.0 if reading is None else reading.zoom_signature,
        detections=records,
    )
    return record, None if target is None else _crop_detection(frame, target)


def _crop_file_name(index: int) -> str:
    """Return the file name of one frame's stored target bounding-box crop."""

    return f"frame_{index:04d}_crop.png"


def _write_png(path: Path, pixels: npt.NDArray[np.uint8]) -> None:
    """Encode one image losslessly, failing loudly when OpenCV refuses it."""

    if not cv2.imwrite(str(path), pixels, [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION_LEVEL]):
        raise RuntimeError(f"Failed to write {path.name}.")


def _prepare_output_directory(root: Path, protocol: str, label: str) -> Path:
    """Create a fresh timestamped directory for one recorded sequence."""

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    directory = root / f"{stamp}-{protocol}-{label}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def acquire_window(
    controller: WindowAccess, process_name: str, countdown_seconds: float
) -> WindowRef:
    """Focus the client and refuse to continue unless it really is in the foreground.

    Nothing in this script may dispatch input before this check passes: a key sent to
    whatever window happens to be focused is exactly the failure the foreground rule of
    `windows-safety-and-input.md` exists to prevent.
    """

    windows = controller.find_windows(process_name)
    if not windows:
        raise SystemExit(
            f"No visible {process_name} window found. Start the client before recording."
        )
    window = windows[0]
    print(f"Target window: {window.title!r} (handle {window.handle})")
    controller.focus_window(window.handle)
    time.sleep(FOCUS_SETTLE_SECONDS)
    for remaining in range(int(countdown_seconds), 0, -1):
        print(f"Recording in {remaining}...")
        time.sleep(1.0)
    if controller.is_aborted():
        raise SystemExit("Emergency stop is held; no input was dispatched.")
    if not controller.is_foreground(window.handle):
        raise SystemExit(f"{window.title!r} is not the foreground window; no input was dispatched.")
    return window


def align_viewport(
    controller: WindowsInputController, source: WindowsFrameSource, window_handle: int
) -> None:
    """Put the client on the standardized viewport state before recording.

    The fitted relation only holds at the camera state it was recorded at and the odometry
    only reports calibrated pixels at the minimap's zoom-out hard stop, so a run that could
    not reach that state is refused rather than written as if it had (US-042, US-043).
    """

    status = CameraAligner(
        controller,
        window_handle,
        locate_minimap_geometry=frame_minimap_locator(source, window_handle),
    ).align()
    if status is not CameraAlignmentStatus.ALIGNED:
        raise SystemExit(f"Camera alignment did not complete ({status.value}); nothing recorded.")
    print(
        "Minimap zoomed out to its hard stop; camera aligned to the zoom hard-stop "
        "and standardized pitch."
    )


def _hold_key_on_thread(
    controller: WindowsInputController,
    window_handle: int,
    virtual_key: int,
    seconds: float,
    timing: _HeldKeyTiming,
) -> None:
    """Hold the forward key through the guarded path while the caller keeps capturing."""

    timing.down_at = time.perf_counter()
    try:
        controller.send_key_while_guarded(window_handle, virtual_key, seconds)
    except (OSError, RuntimeError) as error:  # surfaced on the main thread
        timing.error = error
    finally:
        timing.up_at = time.perf_counter()


def _build_detector(args: argparse.Namespace) -> Detector:
    """Load the shipped mob detector with the run's confidence threshold."""

    return OpenCVDnnYoloDetector.from_files(
        Path(args.model),
        Path(args.labels),
        DetectionConfig(confidence_threshold=args.confidence),
    )


def _write_run(
    output_directory: Path,
    manifest: RunManifest,
    crops: Sequence[tuple[int, npt.NDArray[np.uint8]]],
    references: Sequence[tuple[str, npt.NDArray[np.uint8]]],
) -> None:
    """Flush every captured artefact of one run, including after an emergency stop."""

    for file_name, pixels in references:
        _write_png(output_directory / file_name, pixels)
    for index, pixels in crops:
        _write_png(output_directory / _crop_file_name(index), pixels)
    (output_directory / MANIFEST_FILE_NAME).write_text(
        json.dumps(manifest_to_mapping(manifest), indent=2), encoding="utf-8"
    )


def _run_walk_in(args: argparse.Namespace) -> int:
    """Record a synchronized approach: held forward key, odometry, and mob detections."""

    controller = WindowsInputController()
    source = WindowsFrameSource()
    detector = _build_detector(args)
    virtual_key = parse_virtual_key(args.key)
    window = acquire_window(controller, args.process, args.countdown)
    if args.align_camera:
        align_viewport(controller, source, window.handle)

    odometer = MinimapOdometer()
    tracker = MovementTracker()
    approach_tracker = ApproachTargetTracker(args.mob_class)
    probe = source.capture(window.handle)

    timing = _HeldKeyTiming()
    key_thread = threading.Thread(
        target=_hold_key_on_thread,
        args=(controller, window.handle, virtual_key, args.hold, timing),
        daemon=True,
    )
    frames: list[FrameRecord] = []
    crops: list[tuple[int, npt.NDArray[np.uint8]]] = []
    started_at = time.perf_counter()
    key_thread.start()
    reason = _capture_walk_in(
        source,
        controller,
        window.handle,
        started_at + args.hold,
        odometer,
        tracker,
        detector,
        approach_tracker,
        frames,
        crops,
    )
    key_thread.join()
    if timing.error is not None:
        raise SystemExit(f"Key hold failed: {timing.error}")
    if not frames:
        raise SystemExit(
            f"No frames were captured ({reason or 'unknown reason'}); nothing written."
        )
    try:
        closing_pixels = source.capture(window.handle).pixels
    except FrameCaptureError:
        controller.focus_window(window.handle)
        time.sleep(0.1)
        try:
            closing_pixels = source.capture(window.handle).pixels
        except FrameCaptureError:
            closing_pixels = probe.pixels

    output_directory = _prepare_output_directory(args.output, WALK_IN_PROTOCOL, args.label)
    manifest = RunManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        protocol=WALK_IN_PROTOCOL,
        label=args.label,
        started_at_utc=datetime.now(UTC).isoformat(),
        process_name=args.process,
        window_title=window.title,
        capture_origin=CAPTURE_ORIGIN,
        client_width=probe.client_size.width,
        client_height=probe.client_size.height,
        mob_class=args.mob_class,
        camera_pitch_note=args.camera_pitch,
        forward_key=args.key,
        hold_seconds=args.hold,
        key_down_at=timing.down_at,
        key_up_at=timing.up_at,
        aborted_reason=reason,
        frames=frames,
    )
    _write_run(
        output_directory,
        manifest,
        crops,
        (
            (FIRST_REFERENCE_FILE_NAME, probe.pixels),
            (LAST_REFERENCE_FILE_NAME, closing_pixels),
        ),
    )
    _report_run(output_directory, manifest)
    return 0


def _capture_walk_in(
    source: WindowsFrameSource,
    controller: WindowsInputController,
    window_handle: int,
    deadline: float,
    odometer: MinimapOdometer,
    tracker: MovementTracker,
    detector: Detector,
    approach_tracker: ApproachTargetTracker,
    frames: list[FrameRecord],
    crops: list[tuple[int, npt.NDArray[np.uint8]]],
) -> str | None:
    """Capture until the hold expires; return an abort reason if one occurred."""

    while time.perf_counter() < deadline:
        if controller.is_aborted():
            return ABORT_REASON_EMERGENCY_STOP
        if not controller.is_foreground(window_handle):
            return ABORT_REASON_FOCUS_LOST
        if len(frames) >= MAX_WALK_IN_FRAMES:
            return ABORT_REASON_FRAME_BUDGET
        captured_at = time.perf_counter()
        try:
            frame = source.capture(window_handle)
        except FrameCaptureError as error:
            return error.code.value
        record, crop = _observe_frame(
            len(frames), frame, captured_at, odometer, tracker, detector, approach_tracker
        )
        frames.append(record)
        if crop is not None:
            crops.append((record.index, crop))
    return None


def _run_bearing(args: argparse.Namespace) -> int:
    """Record stationary frames so the horizontal half-angle can be read off later."""

    controller = WindowsInputController()
    source = WindowsFrameSource()
    detector = _build_detector(args)
    window = acquire_window(controller, args.process, args.countdown)
    if args.align_camera:
        align_viewport(controller, source, window.handle)

    odometer = MinimapOdometer()
    tracker = MovementTracker()
    approach_tracker = None if args.mob_class is None else ApproachTargetTracker(args.mob_class)
    frames: list[FrameRecord] = []
    crops: list[tuple[int, npt.NDArray[np.uint8]]] = []
    probe = source.capture(window.handle)
    reason: str | None = None
    for _ in range(args.count):
        if controller.is_aborted():
            reason = ABORT_REASON_EMERGENCY_STOP
            break
        captured_at = time.perf_counter()
        frame = source.capture(window.handle)
        record, crop = _observe_frame(
            len(frames), frame, captured_at, odometer, tracker, detector, approach_tracker
        )
        frames.append(record)
        if crop is not None:
            crops.append((record.index, crop))
        time.sleep(BEARING_FRAME_INTERVAL_SECONDS)
    if not frames:
        raise SystemExit("No frames were captured; nothing written.")

    output_directory = _prepare_output_directory(args.output, BEARING_PROTOCOL, args.label)
    manifest = RunManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        protocol=BEARING_PROTOCOL,
        label=args.label,
        started_at_utc=datetime.now(UTC).isoformat(),
        process_name=args.process,
        window_title=window.title,
        capture_origin=CAPTURE_ORIGIN,
        client_width=probe.client_size.width,
        client_height=probe.client_size.height,
        mob_class=args.mob_class,
        camera_pitch_note=args.camera_pitch,
        aborted_reason=reason,
        frames=frames,
    )
    _write_run(output_directory, manifest, crops, ((FIRST_REFERENCE_FILE_NAME, probe.pixels),))
    _report_run(output_directory, manifest)
    for record in frames:
        for detection in record.detections:
            print(
                f"  frame {record.index:04d} {detection.class_name}: "
                f"x-offset {detection.centre_x_offset_pixels:+.1f} px, "
                f"heading {record.heading_degrees}"
            )
    return 0


def _report_run(output_directory: Path, manifest: RunManifest) -> None:
    """Print what a finished run produced, including why it stopped early."""

    detections = sum(len(frame.detections) for frame in manifest.frames)
    tracked = sum(
        1
        for frame in manifest.frames
        if any(detection.is_approach_target for detection in frame.detections)
    )
    print(f"Wrote {len(manifest.frames)} frames ({detections} detections) to {output_directory}.")
    print(f"Approach target tracked on {tracked} of {len(manifest.frames)} frames.")
    if manifest.aborted_reason is not None:
        print(f"Capture stopped early: {manifest.aborted_reason}")


def _run_fit(args: argparse.Namespace) -> int:
    """Fit `d = a / h + b` per mob class over every manifest the input names."""

    manifest_paths = resolve_manifest_paths(args.input)
    if not manifest_paths:
        raise SystemExit("No run manifests matched the given input.")
    samples: list[DistanceSample] = []
    for path in manifest_paths:
        try:
            manifest = load_manifest(path)
        except ValueError as error:
            # Runs recorded before the tracked approach target was marked cannot be
            # re-interpreted, so they are named rather than skipped silently (ADR-003).
            raise SystemExit(f"{path}: {error}") from error
        run_samples = walk_in_samples(manifest)
        print(f"{path}: {len(run_samples)} samples")
        samples.extend(run_samples)

    grouped = group_samples_by_class(samples)
    if not grouped:
        raise SystemExit("No walk-in samples were found in the given manifests.")
    for mob_class, class_samples in sorted(grouped.items()):
        if len(class_samples) < MINIMUM_FIT_SAMPLE_COUNT:
            print(f"{mob_class}: {len(class_samples)} samples, too few to fit.")
            continue
        fit = fit_inverse_distance(class_samples, mob_class, args.holdout_stride)
        holdout = (
            "not evaluated"
            if fit.holdout_mean_absolute_error_pixels is None
            else (
                f"{fit.holdout_mean_absolute_error_pixels:.3f} px over {fit.holdout_count} samples"
            )
        )
        print(
            f"{mob_class}: a = {fit.inverse_height_coefficient:.3f}, "
            f"b = {fit.combined_intercept_pixels:.3f} px, "
            f"residual standard error = {fit.residual_standard_error_pixels:.3f} px, "
            f"n = {fit.sample_count}, held-out MAE = {holdout}"
        )
    return 0


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Describe the two recording protocols and the offline fit."""

    parser = argparse.ArgumentParser(
        description="Record and fit mob spawn distance calibration evidence."
    )
    parser.add_argument("--process", default=DEFAULT_PROCESS_NAME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--countdown", type=float, default=DEFAULT_COUNTDOWN_SECONDS)
    parser.add_argument(
        "--no-camera-align",
        dest="align_camera",
        action="store_false",
        help="Skip the standardized camera alignment before recording (US-042).",
    )
    subparsers = parser.add_subparsers(dest="protocol", required=True)

    walk_in = subparsers.add_parser(
        WALK_IN_PROTOCOL, help="Walk toward a stationary mob while recording odometry."
    )
    walk_in.add_argument("--label", required=True)
    walk_in.add_argument("--mob-class", required=True, dest="mob_class")
    walk_in.add_argument("--key", default=DEFAULT_FORWARD_KEY)
    walk_in.add_argument("--hold", type=float, default=DEFAULT_WALK_IN_HOLD_SECONDS)
    _add_detection_arguments(walk_in)

    bearing = subparsers.add_parser(
        BEARING_PROTOCOL, help="Record stationary frames for the field-of-view half-angle."
    )
    bearing.add_argument("--label", required=True)
    bearing.add_argument("--mob-class", default=None, dest="mob_class")
    bearing.add_argument("--count", type=int, default=DEFAULT_BEARING_FRAME_COUNT)
    _add_detection_arguments(bearing)

    fit = subparsers.add_parser("fit", help="Fit the inverse-distance relation offline.")
    fit.add_argument("--input", required=True, nargs="+")
    fit.add_argument("--holdout-stride", type=int, default=DEFAULT_HOLDOUT_STRIDE)
    return parser


def _add_detection_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the detector options and the capture conditions US-037 requires recorded."""

    parser.add_argument("--model", default=DEFAULT_MOB_MODEL_PATH)
    parser.add_argument("--labels", default=DEFAULT_MOB_LABELS_PATH)
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument(
        "--camera-pitch",
        dest="camera_pitch",
        default=None,
        help="Free-text note of the camera pitch used, which the fit is only valid at.",
    )


def main(argv: list[str] | None = None) -> int:
    """Run one recording protocol against the live client, or fit recorded runs."""

    args = build_parser().parse_args(argv)
    if args.protocol == "fit":
        return _run_fit(args)
    if sys.platform != "win32":
        raise SystemExit("Recording requires the Windows client.")
    if args.protocol == WALK_IN_PROTOCOL:
        return _run_walk_in(args)
    return _run_bearing(args)


if __name__ == "__main__":
    raise SystemExit(main())
