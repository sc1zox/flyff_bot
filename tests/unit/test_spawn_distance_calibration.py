"""Unit tests for the spawn distance calibration harness (US-041)."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from capture_spawn_distance_samples import (
    APPROACH_TARGET_MAXIMUM_MISSED_FRAMES,
    BEARING_PROTOCOL,
    DEFAULT_BEARING_FRAME_COUNT,
    DEFAULT_FORWARD_KEY,
    DEFAULT_HOLDOUT_STRIDE,
    DEFAULT_WALK_IN_HOLD_SECONDS,
    MANIFEST_SCHEMA_VERSION,
    WALK_IN_PROTOCOL,
    ApproachTargetTracker,
    ApproachTrackingConfig,
    DetectionRecord,
    DistanceSample,
    FrameRecord,
    RunManifest,
    acquire_window,
    build_parser,
    centroid_shift,
    fit_inverse_distance,
    group_samples_by_class,
    load_manifest,
    main,
    manifest_from_mapping,
    manifest_to_mapping,
    overlap_ratio,
    resolve_manifest_paths,
    walk_in_samples,
)

from flyff_bot.features.input_control import WindowRef
from flyff_bot.features.navigation.tracking import TrackingQuality
from flyff_bot.features.vision.detection import BoundingBox, Detection

MOB_CLASS = "aibatt"
CLIENT_WIDTH = 1600
CLIENT_HEIGHT = 1200
WINDOW_HANDLE = 4711


class _FakeController:
    """Window-safety double that reports exactly the state a test arranges."""

    def __init__(self, *, windows: list[WindowRef], foreground: bool, aborted: bool) -> None:
        self._windows = windows
        self._foreground = foreground
        self._aborted = aborted
        self.focused: list[int] = []

    def find_windows(self, process_name: str) -> list[WindowRef]:
        return self._windows

    def focus_window(self, window_handle: int) -> None:
        self.focused.append(window_handle)

    def is_foreground(self, window_handle: int) -> bool:
        return self._foreground

    def is_aborted(self) -> bool:
        return self._aborted


def _detection(
    height: int,
    *,
    confidence: float = 0.9,
    x: int = 800,
    is_approach_target: bool = True,
) -> DetectionRecord:
    return DetectionRecord(
        class_name=MOB_CLASS,
        confidence=confidence,
        x_min=x,
        y_min=400,
        x_max=x + 60,
        y_max=400 + height,
        width=60,
        height=height,
        centre_x_offset_pixels=x + 30.0 - CLIENT_WIDTH / 2.0,
        is_approach_target=is_approach_target,
    )


def _live(
    height: int,
    *,
    x: int,
    y: int = 400,
    width: int = 60,
    confidence: float = 0.9,
    class_name: str = MOB_CLASS,
) -> Detection:
    """Build one live detector output for the approach tracker."""

    return Detection(
        bounding_box=BoundingBox(x=x, y=y, width=width, height=height),
        confidence=confidence,
        class_id=0,
        class_name=class_name,
    )


def _frame(
    index: int,
    *,
    height: int | None,
    increment: float | None,
    quality: TrackingQuality = TrackingQuality.MEASURED,
) -> FrameRecord:
    return FrameRecord(
        index=index,
        captured_at=float(index) * 0.2,
        viewport_width=CLIENT_WIDTH,
        viewport_height=CLIENT_HEIGHT,
        tracking_quality=quality.value,
        position_x=0.0,
        position_y=float(index),
        displacement_x=None if increment is None else increment,
        displacement_y=None if increment is None else 0.0,
        correlation_response=None if increment is None else 0.8,
        heading_degrees=136.3,
        zoom_signature=91.0,
        detections=[] if height is None else [_detection(height)],
    )


def _manifest(frames: list[FrameRecord], *, protocol: str = WALK_IN_PROTOCOL) -> RunManifest:
    return RunManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        protocol=protocol,
        label="run-1",
        started_at_utc="2026-08-18T00:00:00+00:00",
        process_name="neuz.exe",
        window_title="Entropia - scizox",
        capture_origin="client_area",
        client_width=CLIENT_WIDTH,
        client_height=CLIENT_HEIGHT,
        mob_class=MOB_CLASS,
        camera_pitch_note="default",
        forward_key=DEFAULT_FORWARD_KEY,
        hold_seconds=DEFAULT_WALK_IN_HOLD_SECONDS,
        frames=frames,
    )


def _synthetic_samples(
    coefficient: float, intercept: float, heights: list[int]
) -> list[DistanceSample]:
    return [
        DistanceSample(
            mob_class=MOB_CLASS,
            bounding_box_height=height,
            remaining_travel_pixels=coefficient / height + intercept,
        )
        for height in heights
    ]


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------


def test_walk_in_parses_with_documented_defaults() -> None:
    # Arrange / Act
    args = build_parser().parse_args(
        [WALK_IN_PROTOCOL, "--label", "aibatt-far", "--mob-class", MOB_CLASS]
    )

    # Assert
    assert args.protocol == WALK_IN_PROTOCOL
    assert args.mob_class == MOB_CLASS
    assert args.key == DEFAULT_FORWARD_KEY
    assert args.hold == DEFAULT_WALK_IN_HOLD_SECONDS
    assert args.camera_pitch is None


def test_walk_in_requires_a_mob_class() -> None:
    # Arrange / Act / Assert
    with pytest.raises(SystemExit):
        build_parser().parse_args([WALK_IN_PROTOCOL, "--label", "aibatt-far"])


def test_bearing_parses_with_default_frame_count() -> None:
    # Arrange / Act
    args = build_parser().parse_args([BEARING_PROTOCOL, "--label", "fov-1"])

    # Assert
    assert args.protocol == BEARING_PROTOCOL
    assert args.count == DEFAULT_BEARING_FRAME_COUNT
    assert args.mob_class is None


def test_fit_accepts_several_inputs() -> None:
    # Arrange / Act
    args = build_parser().parse_args(["fit", "--input", "a/manifest.json", "b"])

    # Assert
    assert args.input == ["a/manifest.json", "b"]
    assert args.holdout_stride == DEFAULT_HOLDOUT_STRIDE


def test_missing_subcommand_is_rejected() -> None:
    # Arrange / Act / Assert
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


# --------------------------------------------------------------------------------------
# Manifest schema
# --------------------------------------------------------------------------------------


def test_manifest_round_trips_through_json() -> None:
    # Arrange
    manifest = _manifest(
        [_frame(0, height=40, increment=None), _frame(1, height=52, increment=3.0)]
    )

    # Act
    restored = manifest_from_mapping(json.loads(json.dumps(manifest_to_mapping(manifest))))

    # Assert
    assert restored == manifest


def test_manifest_with_unsupported_schema_version_is_rejected() -> None:
    # Arrange
    payload = manifest_to_mapping(_manifest([_frame(0, height=40, increment=None)]))
    payload["schema_version"] = MANIFEST_SCHEMA_VERSION + 1

    # Act / Assert
    with pytest.raises(ValueError, match="Unsupported manifest schema version"):
        manifest_from_mapping(payload)


def test_load_manifest_accepts_a_run_directory(tmp_path: Path) -> None:
    # Arrange
    manifest = _manifest([_frame(0, height=40, increment=None)])
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest_to_mapping(manifest)), encoding="utf-8"
    )

    # Act
    loaded = load_manifest(tmp_path)

    # Assert
    assert loaded == manifest


def test_resolve_manifest_paths_expands_globs_without_duplicates(tmp_path: Path) -> None:
    # Arrange
    payload = json.dumps(manifest_to_mapping(_manifest([])))
    for name in ("20260818-walk-in-a", "20260818-walk-in-b"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "manifest.json").write_text(payload, encoding="utf-8")

    # Act
    resolved = resolve_manifest_paths(
        [str(tmp_path / "*walk-in*"), str(tmp_path / "20260818-walk-in-a")]
    )

    # Assert
    assert [path.parent.name for path in resolved] == [
        "20260818-walk-in-a",
        "20260818-walk-in-b",
    ]


# --------------------------------------------------------------------------------------
# Sample extraction
# --------------------------------------------------------------------------------------


def test_walk_in_samples_measure_remaining_travel_backwards_from_the_stop() -> None:
    # Arrange: three measured increments of 2, 3 and 5 px after the first frame.
    manifest = _manifest(
        [
            _frame(0, height=30, increment=None),
            _frame(1, height=40, increment=2.0),
            _frame(2, height=55, increment=3.0),
            _frame(3, height=90, increment=5.0),
        ]
    )

    # Act
    samples = walk_in_samples(manifest)

    # Assert
    assert [sample.bounding_box_height for sample in samples] == [30, 40, 55, 90]
    assert [sample.remaining_travel_pixels for sample in samples] == [10.0, 8.0, 5.0, 0.0]


def test_walk_in_samples_drop_the_frames_before_an_unmeasured_increment() -> None:
    # Arrange: frame 2 has no measurement, so frames 0 and 1 have an unknown total travel.
    manifest = _manifest(
        [
            _frame(0, height=30, increment=None),
            _frame(1, height=40, increment=2.0),
            _frame(2, height=55, increment=None),
            _frame(3, height=90, increment=5.0),
        ]
    )

    # Act
    samples = walk_in_samples(manifest)

    # Assert
    assert [sample.bounding_box_height for sample in samples] == [55, 90]
    assert [sample.remaining_travel_pixels for sample in samples] == [5.0, 0.0]


def test_walk_in_samples_ignore_a_degraded_increment() -> None:
    # Arrange
    manifest = _manifest(
        [
            _frame(0, height=30, increment=None),
            _frame(1, height=40, increment=2.0, quality=TrackingQuality.DEGRADED),
            _frame(2, height=55, increment=3.0),
        ]
    )

    # Act
    samples = walk_in_samples(manifest)

    # Assert
    assert [sample.bounding_box_height for sample in samples] == [40, 55]


def test_walk_in_samples_skip_frames_without_the_target_class() -> None:
    # Arrange
    manifest = _manifest(
        [
            _frame(0, height=30, increment=None),
            _frame(1, height=None, increment=2.0),
            _frame(2, height=55, increment=3.0),
        ]
    )

    # Act
    samples = walk_in_samples(manifest)

    # Assert
    assert [sample.remaining_travel_pixels for sample in samples] == [5.0, 0.0]


def test_walk_in_samples_read_the_tracked_target_and_ignore_the_rest_of_the_cluster() -> None:
    """US-043: the recorded height must follow the tracked mob, not the confident one."""

    # Arrange
    crowded = replace(
        _frame(0, height=30, increment=None),
        detections=[
            _detection(30, confidence=0.95, x=200, is_approach_target=False),
            _detection(64, confidence=0.55, x=800, is_approach_target=True),
        ],
    )
    manifest = _manifest([crowded])

    # Act
    samples = walk_in_samples(manifest)

    # Assert
    assert [sample.bounding_box_height for sample in samples] == [64]


def test_walk_in_samples_skip_frames_where_the_tracker_lost_the_target() -> None:
    # Arrange
    untracked = replace(
        _frame(0, height=30, increment=None),
        detections=[_detection(30, x=200, is_approach_target=False)],
    )
    manifest = _manifest([untracked, _frame(1, height=64, increment=4.0)])

    # Act
    samples = walk_in_samples(manifest)

    # Assert
    assert [sample.bounding_box_height for sample in samples] == [64]


def test_bearing_runs_yield_no_distance_samples() -> None:
    # Arrange
    manifest = _manifest([_frame(0, height=40, increment=None)], protocol=BEARING_PROTOCOL)

    # Act / Assert
    assert walk_in_samples(manifest) == []


# --------------------------------------------------------------------------------------
# Curve fitting
# --------------------------------------------------------------------------------------


def test_fit_recovers_the_synthetic_coefficients_exactly() -> None:
    # Arrange
    samples = _synthetic_samples(2400.0, -6.5, [24, 30, 38, 50, 66, 88, 120])

    # Act
    fit = fit_inverse_distance(samples, MOB_CLASS)

    # Assert
    assert fit.inverse_height_coefficient == pytest.approx(2400.0, rel=1e-6)
    assert fit.combined_intercept_pixels == pytest.approx(-6.5, rel=1e-6)
    assert fit.residual_standard_error_pixels == pytest.approx(0.0, abs=1e-6)
    assert fit.sample_count == len(samples)


def test_fit_reports_a_held_out_error_over_the_deterministic_split() -> None:
    # Arrange
    samples = _synthetic_samples(2400.0, -6.5, [24, 30, 38, 50, 66, 88, 120, 150])

    # Act
    fit = fit_inverse_distance(samples, MOB_CLASS)

    # Assert
    assert fit.holdout_count == 2
    assert fit.holdout_mean_absolute_error_pixels == pytest.approx(0.0, abs=1e-6)


def test_fit_reports_the_residual_of_a_perturbed_sample() -> None:
    # Arrange
    samples = _synthetic_samples(2400.0, -6.5, [24, 30, 38, 50, 66, 88, 120])
    noisy = list(samples)
    noisy[3] = DistanceSample(
        mob_class=MOB_CLASS,
        bounding_box_height=samples[3].bounding_box_height,
        remaining_travel_pixels=samples[3].remaining_travel_pixels + 5.0,
    )

    # Act
    fit = fit_inverse_distance(noisy, MOB_CLASS)

    # Assert
    assert fit.residual_standard_error_pixels > 1.0
    assert math.isfinite(fit.residual_standard_error_pixels)


def test_fit_predicts_the_modelled_remaining_travel() -> None:
    # Arrange
    fit = fit_inverse_distance(_synthetic_samples(2400.0, -6.5, [24, 38, 66, 120]), MOB_CLASS)

    # Act
    predicted = fit.predict(50)

    # Assert
    assert predicted == pytest.approx(2400.0 / 50 - 6.5, rel=1e-6)


def test_fit_rejects_too_few_samples() -> None:
    # Arrange
    samples = _synthetic_samples(2400.0, -6.5, [24, 38])

    # Act / Assert
    with pytest.raises(ValueError, match="At least"):
        fit_inverse_distance(samples, MOB_CLASS)


def test_fit_rejects_a_holdout_stride_that_keeps_too_little_for_fitting() -> None:
    # Arrange
    samples = _synthetic_samples(2400.0, -6.5, [24, 38, 66, 120])

    # Act / Assert
    with pytest.raises(ValueError, match="Hold-out stride"):
        fit_inverse_distance(samples, MOB_CLASS, holdout_stride=1)


def test_samples_are_grouped_per_mob_class() -> None:
    # Arrange
    samples = [
        DistanceSample(mob_class="aibatt", bounding_box_height=40, remaining_travel_pixels=9.0),
        DistanceSample(mob_class="mushpang", bounding_box_height=70, remaining_travel_pixels=4.0),
        DistanceSample(mob_class="aibatt", bounding_box_height=90, remaining_travel_pixels=0.0),
    ]

    # Act
    grouped = group_samples_by_class(samples)

    # Assert
    assert sorted(grouped) == ["aibatt", "mushpang"]
    assert len(grouped["aibatt"]) == 2


# --------------------------------------------------------------------------------------
# Safety boundaries
# --------------------------------------------------------------------------------------


def test_acquire_window_halts_when_the_client_is_not_running() -> None:
    # Arrange
    controller = _FakeController(windows=[], foreground=True, aborted=False)

    # Act / Assert
    with pytest.raises(SystemExit, match=r"No visible neuz\.exe window found"):
        acquire_window(controller, "neuz.exe", 0.0)
    assert controller.focused == []


def test_acquire_window_halts_when_the_client_is_not_foregrounded() -> None:
    # Arrange
    window = WindowRef(handle=WINDOW_HANDLE, title="Entropia - scizox")
    controller = _FakeController(windows=[window], foreground=False, aborted=False)

    # Act / Assert
    with pytest.raises(SystemExit, match="not the foreground window"):
        acquire_window(controller, "neuz.exe", 0.0)


def test_acquire_window_halts_while_the_emergency_stop_is_held() -> None:
    # Arrange
    window = WindowRef(handle=WINDOW_HANDLE, title="Entropia - scizox")
    controller = _FakeController(windows=[window], foreground=True, aborted=True)

    # Act / Assert
    with pytest.raises(SystemExit, match="Emergency stop is held"):
        acquire_window(controller, "neuz.exe", 0.0)


def test_acquire_window_returns_the_focused_client() -> None:
    # Arrange
    window = WindowRef(handle=WINDOW_HANDLE, title="Entropia - scizox")
    controller = _FakeController(windows=[window], foreground=True, aborted=False)

    # Act
    acquired = acquire_window(controller, "neuz.exe", 0.0)

    # Assert
    assert acquired == window
    assert controller.focused == [WINDOW_HANDLE]


# --------------------------------------------------------------------------------------
# Continuous approach target tracking (US-043)
# --------------------------------------------------------------------------------------


def test_the_tracker_acquires_the_candidate_closest_to_the_viewport_centreline() -> None:
    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    # A background mob with a much taller box sits off to the side; the approach target is
    # the smaller, centred one the operator lined the character up with.
    off_centre = _live(196, x=200)
    centred = _live(49, x=CLIENT_WIDTH // 2 - 30)

    # Act
    acquired = tracker.track([off_centre, centred], CLIENT_WIDTH)

    # Assert
    assert acquired is centred


def test_the_tracker_ignores_candidates_of_another_class() -> None:
    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    other = _live(60, x=CLIENT_WIDTH // 2 - 30, class_name="wolf")
    mine = _live(60, x=CLIENT_WIDTH // 2 + 200)

    # Act
    acquired = tracker.track([other, mine], CLIENT_WIDTH)

    # Assert
    assert acquired is mine


def test_the_tracker_never_jumps_to_a_more_confident_mob_of_the_same_cluster() -> None:
    """The bug US-043 fixes: confidence flapping swapped foreground and background mobs."""

    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    approach_heights = [49, 58, 70, 86, 110, 143, 196]
    background = _live(196, x=120, y=380, confidence=0.99)
    tracked: list[int] = []

    # Act
    for step, height in enumerate(approach_heights):
        # The approach target grows and drifts a few pixels per frame while a large, very
        # confident mob sits off to the left for the whole run.
        target = _live(height, x=CLIENT_WIDTH // 2 - 30 + step * 4, y=400 - step * 3)
        chosen = tracker.track([background, target], CLIENT_WIDTH)
        assert chosen is target
        tracked.append(chosen.bounding_box.height)

    # Assert
    assert tracked == approach_heights


def test_the_tracker_prefers_the_overlapping_box_over_a_nearer_centroid() -> None:
    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    first = tracker.track([_live(80, x=760, y=400)], CLIENT_WIDTH)
    assert first is not None
    # The target grew downwards, which moved its centroid further than a neighbour that
    # happens to sit closer to where the target was.
    grown = _live(200, x=756, y=400)
    neighbour = _live(40, x=800, y=430)

    # Act
    chosen = tracker.track([neighbour, grown], CLIENT_WIDTH)

    # Assert
    assert chosen is grown
    assert centroid_shift(first.bounding_box, grown.bounding_box) > centroid_shift(
        first.bounding_box, neighbour.bounding_box
    )
    assert overlap_ratio(first.bounding_box, grown.bounding_box) > overlap_ratio(
        first.bounding_box, neighbour.bounding_box
    )


def test_the_tracker_refuses_a_candidate_outside_the_re_acquisition_radius() -> None:
    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    first = tracker.track([_live(80, x=760, y=400)], CLIENT_WIDTH)
    assert first is not None
    distant = _live(80, x=200, y=700)
    assert centroid_shift(first.bounding_box, distant.bounding_box) > (
        ApproachTrackingConfig().maximum_centroid_shift_pixels
    )

    # Act
    chosen = tracker.track([distant], CLIENT_WIDTH)

    # Assert
    assert chosen is None
    assert not tracker.is_lost


def test_the_tracker_re_acquires_the_target_after_a_short_occlusion() -> None:
    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    tracker.track([_live(80, x=760, y=400)], CLIENT_WIDTH)
    for _ in range(APPROACH_TARGET_MAXIMUM_MISSED_FRAMES):
        assert tracker.track([], CLIENT_WIDTH) is None
    reappeared = _live(92, x=756, y=396)

    # Act
    chosen = tracker.track([reappeared], CLIENT_WIDTH)

    # Assert
    assert chosen is reappeared
    assert not tracker.is_lost


def test_the_tracker_gives_up_rather_than_adopting_a_neighbour_after_the_miss_budget() -> None:
    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    tracker.track([_live(80, x=760, y=400)], CLIENT_WIDTH)
    for _ in range(APPROACH_TARGET_MAXIMUM_MISSED_FRAMES + 1):
        assert tracker.track([], CLIENT_WIDTH) is None

    # Act
    chosen = tracker.track([_live(80, x=758, y=402)], CLIENT_WIDTH)

    # Assert
    assert chosen is None
    assert tracker.is_lost


def test_the_tracker_keeps_acquiring_while_the_target_has_never_been_seen() -> None:
    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    for _ in range(APPROACH_TARGET_MAXIMUM_MISSED_FRAMES + 2):
        assert tracker.track([], CLIENT_WIDTH) is None
    late = _live(49, x=CLIENT_WIDTH // 2 - 30)

    # Act
    chosen = tracker.track([late], CLIENT_WIDTH)

    # Assert
    assert chosen is late
    assert not tracker.is_lost


def test_the_tracker_remembers_the_last_box_across_a_missed_frame() -> None:
    # Arrange
    tracker = ApproachTargetTracker(MOB_CLASS)
    first = tracker.track([_live(80, x=760, y=400)], CLIENT_WIDTH)
    assert first is not None

    # Act
    tracker.track([], CLIENT_WIDTH)

    # Assert
    assert tracker.tracked_box == first.bounding_box


def test_overlap_and_shift_describe_disjoint_and_identical_boxes() -> None:
    box = BoundingBox(x=100, y=100, width=40, height=80)

    assert overlap_ratio(box, box) == pytest.approx(1.0)
    assert overlap_ratio(box, BoundingBox(x=400, y=400, width=40, height=80)) == 0.0
    assert centroid_shift(box, box) == 0.0
    assert centroid_shift(box, BoundingBox(x=100, y=180, width=40, height=80)) == pytest.approx(
        80.0
    )


def test_tracking_config_rejects_gates_that_could_never_match() -> None:
    with pytest.raises(ValueError):
        ApproachTrackingConfig(minimum_overlap=0.0)
    with pytest.raises(ValueError):
        ApproachTrackingConfig(minimum_overlap=1.5)
    with pytest.raises(ValueError):
        ApproachTrackingConfig(maximum_centroid_shift_pixels=0.0)
    with pytest.raises(ValueError):
        ApproachTrackingConfig(maximum_missed_frames=-1)


def test_fit_names_a_run_it_cannot_read_instead_of_raising_a_traceback(tmp_path: Path) -> None:
    """US-043: runs recorded under the previous manifest schema are rejected by name."""

    # Arrange
    run = tmp_path / "20260818-000000-walk-in-old"
    run.mkdir()
    payload = manifest_to_mapping(_manifest([_frame(0, height=40, increment=None)]))
    payload["schema_version"] = MANIFEST_SCHEMA_VERSION - 1
    (run / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    # Act / Assert
    with pytest.raises(SystemExit) as excinfo:
        main(["fit", "--input", str(run)])
    assert "Unsupported manifest schema version" in str(excinfo.value)
