"""Tests for schema version 2 profiles and minimap landmark anchoring (US-036).

The matching tests replay the recorded minimap frames shipped under
`data/assets/fixtures/minimap/`, so the confidence separation they assert is the one measured
in `docs/sources/2026-08-18-minimap-odometry-feasibility-spike.md` rather than a synthetic
construction. The two purely synthetic cases are the identity match and a rolled disk, which
are the only ways to state an exactly known offset.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
from minimap_doubles import REFERENCE_ZOOM_SIGNATURE, MirrorOdometer
from minimap_fixtures import sequence, still

from flyff_bot.features.automation.controllers import VIRTUAL_KEY_W
from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.navigation.anchoring import (
    AnchorMatchOutcome,
    MapAnchor,
    ProfileAnchorState,
    match_anchor,
)
from flyff_bot.features.navigation.pathing import (
    PathingController,
    ProfileLoadOutcome,
)
from flyff_bot.features.navigation.persistence import (
    PROFILE_ANCHOR_KEY,
    NavigationProfile,
    load_profile,
    save_profile,
)
from flyff_bot.features.navigation.spatial import (
    SPATIAL_MAP_SCHEMA_VERSION,
    SpatialMap,
    WorldPoint,
)
from flyff_bot.features.navigation.tracking import MovementModel
from flyff_bot.features.vision.minimap import (
    ZOOM_SIGNATURE_TOLERANCE_FRACTION,
    locate_minimap,
    read_minimap,
)
from flyff_bot.features.vision.models import CapturedFrame

# The walk burst holds `W` for three seconds. Correlating its first frame against its last
# recovers this player travel, which agrees with the 27.6 px traverse at bearing 136.3 deg
# measured for the same recording in `docs/sources/2026-08-18-minimap-odometry-calibration.md`.
RECORDED_WALK_TRAVEL_EAST_PIXELS = 19.15
RECORDED_WALK_TRAVEL_NORTH_PIXELS = -20.96
FIXTURE_OFFSET_TOLERANCE_PIXELS = 0.5

# A profile recorded at a different minimap zoom level. It is expressed relative to the
# accepted tolerance rather than pinned to the recorded maximum zoom-out signature, because
# the two recorded levels sit only just outside the tolerance US-043 widened it to.
MISMATCHED_ZOOM_SIGNATURE = REFERENCE_ZOOM_SIGNATURE * (
    1.0 + 2.0 * ZOOM_SIGNATURE_TOLERANCE_FRACTION
)
STORED_ANCHOR_POSITION = WorldPoint(120.0, -45.0)


def _xy(point: WorldPoint | None) -> tuple[float, float]:
    """Return one position as a comparable pair."""

    assert point is not None
    return (point.x, point.y)


# One recorded minimap landmark: its greyscale disk and the zoom signature it was drawn at.
type _Disk = tuple[npt.NDArray[np.uint8], float]


def _disk(frame: CapturedFrame) -> _Disk:
    """Return the greyscale minimap disk of one recorded frame and its zoom signature."""

    geometry = locate_minimap(frame)
    assert geometry is not None
    sample = read_minimap(frame, geometry)
    return sample.surface_greyscale, sample.zoom_signature


def _walk_disks() -> tuple[_Disk, _Disk]:
    frames = sequence("walk").frames
    return _disk(frames[0].frame), _disk(frames[-1].frame)


def _anchor(
    surface: npt.NDArray[np.uint8],
    zoom_signature: float,
    position: WorldPoint = STORED_ANCHOR_POSITION,
    heading_degrees: float = 0.0,
) -> MapAnchor:
    return MapAnchor(
        surface=surface,
        position=position,
        heading_degrees=heading_degrees,
        zoom_signature=zoom_signature,
    )


def _learned_map() -> SpatialMap:
    spatial_map = SpatialMap()
    spatial_map.record_visit(WorldPoint(10.0, 10.0), at_seconds=1.0)
    spatial_map.record_visit(WorldPoint(30.0, 30.0), at_seconds=2.0)
    spatial_map.record_spawn(WorldPoint(30.0, 30.0), at_seconds=2.0)
    return spatial_map


def _state(at_seconds: float, *, with_mob: bool = False) -> WorldState:
    return WorldState(
        observed_at_seconds=at_seconds,
        position=Position(0, 0),
        nearby_mob_count=1 if with_mob else 0,
        inventory=(),
        progress_marker=0,
        visible_mobs=((VisibleMob(0, "Flame", 0.9, 50, 50, 20, 20),) if with_mob else ()),
        viewport=Viewport(100, 100),
    )


def _tracked_controller(
    surface: npt.NDArray[np.uint8] | None,
    *,
    zoom_signature: float = REFERENCE_ZOOM_SIGNATURE,
) -> tuple[PathingController, MirrorOdometer]:
    """Return a controller that has already taken one confident measurement."""

    odometer = MirrorOdometer(MovementModel(), zoom_signature=zoom_signature, surface=surface)
    controller = PathingController(odometer=odometer)
    controller.observe(_state(10.0))
    return controller, odometer


# ---------------------------------------------------------------------------------------
# Schema version 2 persistence
# ---------------------------------------------------------------------------------------


def test_profile_document_is_written_at_schema_version_two(tmp_path: Path) -> None:
    path = tmp_path / "camp.json"

    save_profile(NavigationProfile(_learned_map()), path)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert SPATIAL_MAP_SCHEMA_VERSION == 2
    assert document["version"] == 2
    assert PROFILE_ANCHOR_KEY not in document


def test_profile_round_trip_preserves_the_stored_landmark(tmp_path: Path) -> None:
    surface, zoom_signature = _disk(still("zoom_default"))
    anchor = _anchor(surface, zoom_signature, heading_degrees=137.5)
    path = tmp_path / "camp.json"

    save_profile(NavigationProfile(_learned_map(), anchor), path)
    restored = load_profile(path)

    assert restored.spatial_map.known_cells() == _learned_map().known_cells()
    assert restored.anchor is not None
    assert restored.anchor.position == STORED_ANCHOR_POSITION
    assert restored.anchor.heading_degrees == pytest.approx(137.5)
    assert restored.anchor.zoom_signature == pytest.approx(zoom_signature)
    assert np.array_equal(restored.anchor.surface, surface)


def test_unsupported_schema_version_is_rejected_naming_the_version(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"version": 1, "cells": [], "edges": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported spatial map schema version: 1"):
        load_profile(path)


@pytest.mark.parametrize(
    "anchor_payload",
    [
        pytest.param("not-an-object", id="not_an_object"),
        pytest.param({}, id="empty"),
        pytest.param({"x": 1.0, "y": 2.0, "heading_degrees": 0.0}, id="missing_disk"),
        pytest.param(
            {
                "surface_png_base64": "not base64!",
                "x": 1.0,
                "y": 2.0,
                "heading_degrees": 0.0,
                "zoom_signature": 90.0,
            },
            id="undecodable_disk",
        ),
        pytest.param(
            {
                "surface_png_base64": "iVBORw0KGgo=",
                "x": 1.0,
                "y": 2.0,
                "heading_degrees": 0.0,
                "zoom_signature": 90.0,
            },
            id="truncated_disk",
        ),
        pytest.param(
            {
                "surface_png_base64": "",
                "x": 1.0,
                "y": 2.0,
                "heading_degrees": 400.0,
                "zoom_signature": 90.0,
            },
            id="impossible_heading",
        ),
    ],
)
def test_corrupt_anchor_records_load_as_unanchored(tmp_path: Path, anchor_payload: object) -> None:
    document = _learned_map().to_dict()
    document[PROFILE_ANCHOR_KEY] = anchor_payload
    path = tmp_path / "corrupt_anchor.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    profile = load_profile(path)

    assert profile.anchor is None
    assert len(profile.spatial_map.known_cells()) == 2


def test_a_missing_profile_starts_an_empty_unanchored_one(tmp_path: Path) -> None:
    profile = load_profile(tmp_path / "absent.json")

    assert profile.spatial_map.known_cells() == ()
    assert profile.anchor is None


# ---------------------------------------------------------------------------------------
# Landmark matching
# ---------------------------------------------------------------------------------------


def test_identical_disk_reports_the_stored_position() -> None:
    surface, zoom_signature = _disk(still("zoom_default"))

    match = match_anchor(_anchor(surface, zoom_signature), surface, zoom_signature)

    assert match.outcome is AnchorMatchOutcome.MATCHED
    assert _xy(match.position) == pytest.approx(_xy(STORED_ANCHOR_POSITION), abs=1e-6)


def test_shifted_disk_recovers_the_known_offset() -> None:
    surface, zoom_signature = _disk(still("zoom_default"))
    # The map content is moved five pixels east and three pixels up, which is what the client
    # draws when the player moves five pixels west and three pixels south.
    shifted = np.roll(np.roll(surface, 5, axis=1), -3, axis=0)

    match = match_anchor(_anchor(surface, zoom_signature), shifted, zoom_signature)

    assert match.outcome is AnchorMatchOutcome.MATCHED
    assert match.position is not None
    assert match.position.x == pytest.approx(STORED_ANCHOR_POSITION.x - 5.0, abs=0.2)
    assert match.position.y == pytest.approx(STORED_ANCHOR_POSITION.y - 3.0, abs=0.2)


def test_recorded_traverse_recovers_the_measured_travel() -> None:
    (start_surface, start_zoom), (end_surface, end_zoom) = _walk_disks()

    match = match_anchor(_anchor(start_surface, start_zoom), end_surface, end_zoom)

    assert match.outcome is AnchorMatchOutcome.MATCHED
    assert match.position is not None
    assert match.position.x == pytest.approx(
        STORED_ANCHOR_POSITION.x + RECORDED_WALK_TRAVEL_EAST_PIXELS,
        abs=FIXTURE_OFFSET_TOLERANCE_PIXELS,
    )
    assert match.position.y == pytest.approx(
        STORED_ANCHOR_POSITION.y + RECORDED_WALK_TRAVEL_NORTH_PIXELS,
        abs=FIXTURE_OFFSET_TOLERANCE_PIXELS,
    )


def test_unrelated_minimap_content_is_not_matched() -> None:
    (walk_surface, walk_zoom), _ = _walk_disks()
    turn_surface, turn_zoom = _disk(sequence("turn").frames[0].frame)

    match = match_anchor(_anchor(walk_surface, walk_zoom), turn_surface, turn_zoom)

    assert match.outcome is AnchorMatchOutcome.UNMATCHED
    assert match.position is None


def test_profile_from_another_zoom_level_is_a_scale_mismatch() -> None:
    default_surface, default_zoom = _disk(still("zoom_default"))
    zoomed_surface, zoomed_zoom = _disk(still("zoom_maximum_out"))

    match = match_anchor(_anchor(default_surface, default_zoom), zoomed_surface, zoomed_zoom)

    assert match.outcome is AnchorMatchOutcome.SCALE_MISMATCH
    assert match.position is None
    assert match.stored_zoom_signature == pytest.approx(default_zoom)
    assert match.live_zoom_signature == pytest.approx(zoomed_zoom)


def test_a_disk_of_an_impossible_shape_is_not_matched() -> None:
    surface, zoom_signature = _disk(still("zoom_default"))

    match = match_anchor(_anchor(surface, zoom_signature), surface[:-1, :], zoom_signature)

    assert match.outcome is AnchorMatchOutcome.UNMATCHED


# ---------------------------------------------------------------------------------------
# Saving: the landmark a later session will match against
# ---------------------------------------------------------------------------------------


def test_saving_with_a_confident_fix_stores_the_live_landmark(tmp_path: Path) -> None:
    surface, _ = _disk(still("zoom_default"))
    controller, odometer = _tracked_controller(surface)
    odometer.command(VIRTUAL_KEY_W, duration_seconds=1.0)
    controller.integrate_movement(VIRTUAL_KEY_W, duration_seconds=1.0)
    controller.observe(_state(11.0))
    path = tmp_path / "camp.json"

    assert controller.save_map(path) is ProfileAnchorState.ANCHORED

    profile = load_profile(path)
    assert profile.anchor is not None
    assert np.array_equal(profile.anchor.surface, surface)
    assert _xy(profile.anchor.position) == pytest.approx(_xy(controller.position), abs=1e-6)
    assert controller.profile_anchor_state is ProfileAnchorState.ANCHORED


def test_saving_while_tracking_is_degraded_stores_no_landmark(tmp_path: Path) -> None:
    surface, _ = _disk(still("zoom_default"))
    controller = PathingController(odometer=MirrorOdometer(MovementModel(), surface=surface))
    controller.spatial_map.record_visit(WorldPoint(5.0, 5.0), at_seconds=1.0)
    path = tmp_path / "camp.json"

    assert controller.save_map(path) is ProfileAnchorState.UNANCHORED

    profile = load_profile(path)
    assert profile.anchor is None
    assert controller.profile_anchor_state is ProfileAnchorState.UNANCHORED


# ---------------------------------------------------------------------------------------
# Loading: re-anchor or refuse
# ---------------------------------------------------------------------------------------


def test_anchored_load_places_the_character_in_the_profiles_frame(tmp_path: Path) -> None:
    surface, zoom_signature = _disk(still("zoom_default"))
    path = tmp_path / "camp.json"
    save_profile(
        NavigationProfile(_learned_map(), _anchor(surface, zoom_signature)),
        path,
    )
    controller, _ = _tracked_controller(surface, zoom_signature=zoom_signature)

    result = controller.load_map(path)

    assert result.outcome is ProfileLoadOutcome.ANCHORED
    assert controller.profile_anchor_state is ProfileAnchorState.ANCHORED
    assert controller.map_is_read_only is False
    assert _xy(controller.position) == pytest.approx(_xy(STORED_ANCHOR_POSITION), abs=1e-6)
    assert len(controller.spatial_map.known_cells()) == 2


def test_anchored_load_adds_the_movement_since_the_landmark_was_captured(tmp_path: Path) -> None:
    surface, zoom_signature = _disk(still("zoom_default"))
    path = tmp_path / "camp.json"
    save_profile(NavigationProfile(_learned_map(), _anchor(surface, zoom_signature)), path)
    controller, _ = _tracked_controller(surface, zoom_signature=zoom_signature)
    # Movement dispatched after the last measurement is predicted, not measured, so it is not
    # part of the landmark and has to be added on top of the recovered position.
    controller.integrate_movement(VIRTUAL_KEY_W, duration_seconds=1.0)
    predicted_north = controller.position.y

    controller.load_map(path)

    assert predicted_north > 0.0
    assert _xy(controller.position) == pytest.approx(
        (STORED_ANCHOR_POSITION.x, STORED_ANCHOR_POSITION.y + predicted_north), abs=1e-6
    )


def test_unmatched_load_leaves_the_active_map_untouched(tmp_path: Path) -> None:
    (walk_surface, walk_zoom), _ = _walk_disks()
    turn_surface, turn_zoom = _disk(sequence("turn").frames[0].frame)
    path = tmp_path / "elsewhere.json"
    save_profile(NavigationProfile(_learned_map(), _anchor(turn_surface, turn_zoom)), path)
    controller, _ = _tracked_controller(walk_surface, zoom_signature=walk_zoom)
    controller.observe(_state(11.0))
    active_cells = controller.spatial_map.known_cells()

    result = controller.load_map(path)

    assert result.outcome is ProfileLoadOutcome.UNMATCHED
    assert controller.spatial_map.known_cells() == active_cells
    assert controller.profile_anchor_state is ProfileAnchorState.SESSION
    assert controller.map_is_read_only is False


def test_operator_accepted_unmatched_load_is_read_only(tmp_path: Path) -> None:
    (walk_surface, walk_zoom), _ = _walk_disks()
    turn_surface, turn_zoom = _disk(sequence("turn").frames[0].frame)
    path = tmp_path / "elsewhere.json"
    save_profile(NavigationProfile(_learned_map(), _anchor(turn_surface, turn_zoom)), path)
    controller, _ = _tracked_controller(walk_surface, zoom_signature=walk_zoom)

    result = controller.load_map(path, accept_unmatched=True)

    assert result.outcome is ProfileLoadOutcome.READ_ONLY
    assert controller.profile_anchor_state is ProfileAnchorState.READ_ONLY
    assert controller.map_is_read_only is True
    assert len(controller.spatial_map.known_cells()) == 2


def test_scale_mismatch_load_leaves_the_active_map_untouched(tmp_path: Path) -> None:
    surface, _ = _disk(still("zoom_default"))
    path = tmp_path / "zoomed.json"
    save_profile(
        NavigationProfile(_learned_map(), _anchor(surface, MISMATCHED_ZOOM_SIGNATURE)), path
    )
    controller, _ = _tracked_controller(surface)
    active_cells = controller.spatial_map.known_cells()

    result = controller.load_map(path)

    assert result.outcome is ProfileLoadOutcome.SCALE_MISMATCH
    assert result.stored_zoom_signature == pytest.approx(MISMATCHED_ZOOM_SIGNATURE)
    assert result.live_zoom_signature == pytest.approx(REFERENCE_ZOOM_SIGNATURE)
    assert controller.spatial_map.known_cells() == active_cells
    assert controller.profile_anchor_state is ProfileAnchorState.SESSION


def test_unanchored_profile_loads_read_only(tmp_path: Path) -> None:
    surface, _ = _disk(still("zoom_default"))
    path = tmp_path / "degraded.json"
    save_profile(NavigationProfile(_learned_map()), path)
    controller, _ = _tracked_controller(surface)

    result = controller.load_map(path)

    assert result.outcome is ProfileLoadOutcome.UNANCHORED
    assert controller.profile_anchor_state is ProfileAnchorState.UNANCHORED
    assert controller.map_is_read_only is True


def test_a_profile_without_a_live_landmark_cannot_be_anchored(tmp_path: Path) -> None:
    surface, zoom_signature = _disk(still("zoom_default"))
    path = tmp_path / "camp.json"
    save_profile(NavigationProfile(_learned_map(), _anchor(surface, zoom_signature)), path)
    # No disk was ever decoded, so this session has nothing to match the landmark against.
    controller, _ = _tracked_controller(None)

    assert controller.load_map(path).outcome is ProfileLoadOutcome.UNMATCHED


# ---------------------------------------------------------------------------------------
# Read-only maps
# ---------------------------------------------------------------------------------------


def test_read_only_map_records_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    surface, _ = _disk(still("zoom_default"))
    path = tmp_path / "degraded.json"
    save_profile(NavigationProfile(_learned_map()), path)
    controller, odometer = _tracked_controller(surface)
    controller.load_map(path)

    calls: list[str] = []
    for name in ("record_visit", "record_spawn", "record_stall"):
        monkeypatch.setattr(
            controller.spatial_map,
            name,
            lambda *args, _name=name, **kwargs: calls.append(_name),
        )

    at_seconds = 20.0
    for _ in range(5):
        odometer.command(VIRTUAL_KEY_W, duration_seconds=1.0)
        controller.integrate_movement(VIRTUAL_KEY_W, duration_seconds=1.0)
        controller.observe(_state(at_seconds, with_mob=True))
        at_seconds += 1.0

    assert calls == []


def test_read_only_map_is_never_written_back(tmp_path: Path) -> None:
    surface, _ = _disk(still("zoom_default"))
    path = tmp_path / "degraded.json"
    save_profile(NavigationProfile(_learned_map()), path)
    before = path.read_text(encoding="utf-8")
    controller, _ = _tracked_controller(surface)
    controller.load_map(path)

    assert controller.save_map() is ProfileAnchorState.UNANCHORED
    assert controller.save_map(tmp_path / "copy.json") is ProfileAnchorState.UNANCHORED

    assert path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "copy.json").exists()


def test_reset_returns_the_map_to_a_writable_session_recording(tmp_path: Path) -> None:
    surface, _ = _disk(still("zoom_default"))
    path = tmp_path / "degraded.json"
    save_profile(NavigationProfile(_learned_map()), path)
    controller, _ = _tracked_controller(surface)
    controller.load_map(path)

    controller.reset()

    assert controller.profile_anchor_state is ProfileAnchorState.SESSION
    assert controller.map_is_read_only is False
    assert controller.spatial_map.known_cells() == ()


def test_snapshot_reports_the_anchor_state(tmp_path: Path) -> None:
    surface, _ = _disk(still("zoom_default"))
    path = tmp_path / "degraded.json"
    save_profile(NavigationProfile(_learned_map()), path)
    controller, _ = _tracked_controller(surface)

    assert controller.snapshot().profile_anchor_state is ProfileAnchorState.SESSION

    controller.load_map(path)

    assert controller.snapshot().profile_anchor_state is ProfileAnchorState.UNANCHORED


def test_observing_a_writable_map_still_learns(tmp_path: Path) -> None:
    surface, _ = _disk(still("zoom_default"))
    controller, odometer = _tracked_controller(surface)
    odometer.command(VIRTUAL_KEY_W, duration_seconds=1.0)
    controller.integrate_movement(VIRTUAL_KEY_W, duration_seconds=1.0)
    controller.observe(replace(_state(11.0, with_mob=True)))

    assert len(controller.spatial_map.known_cells()) > 1
    assert controller.map_is_read_only is False
