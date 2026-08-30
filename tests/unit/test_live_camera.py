"""Read-only fingerprinted camera extraction and D3D9 unprojection tests (US-056)."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

import pytest

from flyff_bot.features.navigation.live_camera import (
    ENTROPIA_CAMERA_PROFILES,
    MATRIX_SIZE_BYTES,
    CameraReadError,
    CameraReadErrorCode,
    CameraState,
    ClientCameraProfile,
    LiveCameraReader,
    WorldProjectionStatus,
    invert_matrix,
    load_client_camera_profiles,
    project_world_to_screen,
    unproject_screen_ray,
)
from flyff_bot.features.navigation.live_position import (
    PROCESS_QUERY_LIMITED_INFORMATION,
    PROCESS_VM_READ,
    WorldPosition,
)

WINDOW_HANDLE = 42
RESTARTED_WINDOW_HANDLE = 43
PROCESS_ID = 1337
PROCESS_HANDLE = 99
MODULE_BASE = 0x140000000
CAMERA_ADDRESS = 0x220000000
CAMERA_POINTER_RVA = 0xBAD8E8
PROJECTION_RVA = 0xD76B80

IDENTITY_MATRIX = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)
D3D_PROJECTION = (
    (0.5, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 100.0 / 99.0, 1.0),
    (0.0, 0.0, -100.0 / 99.0, 0.0),
)


class FakeCameraMemoryApi:
    def __init__(self, executable: Path, profile: ClientCameraProfile) -> None:
        self.executable = executable
        self.profile = profile
        self.reads: list[tuple[int, int]] = []
        self.closed: list[int] = []
        self.open_count = 0
        self.foreground = True
        self.fail_read = False
        self.short_read = False
        self.view_matrix = IDENTITY_MATRIX

    def is_window_foreground(self, window_handle: int) -> bool:
        assert window_handle in {WINDOW_HANDLE, RESTARTED_WINDOW_HANDLE}
        return self.foreground

    def process_id_for_window(self, window_handle: int) -> int:
        assert window_handle in {WINDOW_HANDLE, RESTARTED_WINDOW_HANDLE}
        return PROCESS_ID

    def open_read_process(self, process_id: int) -> int:
        assert process_id == PROCESS_ID
        self.open_count += 1
        return PROCESS_HANDLE

    def executable_path(self, process_handle: int) -> Path:
        assert process_handle == PROCESS_HANDLE
        return self.executable

    def main_module_base(self, process_id: int) -> int:
        assert process_id == PROCESS_ID
        return MODULE_BASE

    def read(self, process_handle: int, address: int, size: int) -> bytes:
        assert process_handle == PROCESS_HANDLE
        self.reads.append((address, size))
        if self.fail_read:
            raise OSError("lost")
        if address == MODULE_BASE + self.profile.camera_pointer_rva:
            return CAMERA_ADDRESS.to_bytes(self.profile.pointer_size_bytes, "little")
        if address == CAMERA_ADDRESS + self.profile.camera_read_start_offset:
            payload = bytearray(self.profile.camera_read_size_bytes)
            struct.pack_into(
                "<3f",
                payload,
                self.profile.eye_position_offset - self.profile.camera_read_start_offset,
                0.0,
                0.0,
                0.0,
            )
            struct.pack_into(
                "<16f",
                payload,
                self.profile.view_matrix_offset - self.profile.camera_read_start_offset,
                *(value for row in self.view_matrix for value in row),
            )
            struct.pack_into(
                "<3f",
                payload,
                self.profile.look_at_offset - self.profile.camera_read_start_offset,
                0.0,
                0.0,
                10.0,
            )
            return bytes(payload[:-1] if self.short_read else payload)
        assert address == MODULE_BASE + self.profile.projection_matrix_rva
        return struct.pack("<16f", *(value for row in D3D_PROJECTION for value in row))

    def close(self, process_handle: int) -> None:
        self.closed.append(process_handle)


@pytest.fixture
def configured_reader(
    tmp_path: Path,
) -> tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]]:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"camera test build")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    profile = ClientCameraProfile(
        digest,
        CAMERA_POINTER_RVA,
        8,
        eye_position_offset=0x8,
        view_matrix_offset=0x14,
        look_at_offset=0x94,
        projection_matrix_rva=PROJECTION_RVA,
    )
    api = FakeCameraMemoryApi(executable, profile)
    events: list[CameraReadError] = []
    reader = LiveCameraReader(
        WINDOW_HANDLE,
        api=api,
        profiles={digest: profile},
        event_sink=events.append,
    )
    return reader, api, events


def test_reader_uses_only_read_process_rights() -> None:
    assert PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ == 0x1010


def test_embedded_profiles_match_the_staticly_verified_x86_and_x64_layouts() -> None:
    x86 = ENTROPIA_CAMERA_PROFILES[
        "3446ffeb5d104a68d187e9e2ecfa216e1bdb88ce3f9201a046aa900525b6c07e"
    ]
    x64 = ENTROPIA_CAMERA_PROFILES[
        "8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5"
    ]

    assert (x86.camera_pointer_rva, x86.view_matrix_offset, x86.projection_matrix_rva) == (
        0x967FBC,
        0x10,
        0xB015D0,
    )
    assert (x64.pointer_size_bytes, x64.camera_pointer_rva, x64.look_at_offset) == (
        8,
        0xBAD8E8,
        0x94,
    )


def test_profile_file_parses_the_checked_in_x86_and_x64_profiles() -> None:
    profiles = load_client_camera_profiles(Path("data/config/client_camera_profiles.json"))

    assert profiles == ENTROPIA_CAMERA_PROFILES


def test_profile_loader_rejects_boolean_and_duplicate_offsets(tmp_path: Path) -> None:
    path = tmp_path / "camera_profiles.json"
    path.write_text(
        json.dumps(
            [
                {
                    "sha256": "a" * 64,
                    "camera_pointer_rva": True,
                    "pointer_size_bytes": 8,
                    "eye_position_offset": 8,
                    "view_matrix_offset": 20,
                    "look_at_offset": 148,
                    "projection_matrix_rva": PROJECTION_RVA,
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-integer"):
        load_client_camera_profiles(path)


def test_reader_reads_only_the_profiled_pointer_camera_span_and_projection(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
) -> None:
    reader, api, events = configured_reader

    reading = reader.poll(1.0)

    assert reading.error is None
    assert reading.state is not None
    assert reading.state.position.x == pytest.approx(0.0)
    assert reading.state.pitch_radians == pytest.approx(0.0)
    assert reading.state.yaw_radians == pytest.approx(0.0)
    assert reading.state.zoom_distance == pytest.approx(10.0)
    assert reading.state.vertical_fov_radians == pytest.approx(math.pi / 2.0)
    assert events == []
    assert api.reads == [
        (MODULE_BASE + CAMERA_POINTER_RVA, 8),
        (CAMERA_ADDRESS + 0x8, 0x98),
        (MODULE_BASE + PROJECTION_RVA, MATRIX_SIZE_BYTES),
    ]


def test_reader_reports_downward_pitch_as_positive_degrees(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
) -> None:
    reader, api, _events = configured_reader
    cosine = math.cos(math.radians(45.0))
    sine = math.sin(math.radians(45.0))
    api.view_matrix = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, cosine, -sine, 0.0),
        (0.0, sine, cosine, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )

    reading = reader.poll(1.0)

    assert reading.state is not None
    assert reading.state.pitch_degrees == pytest.approx(45.0)


def test_default_poll_rate_caches_the_last_reading_until_ten_hertz(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
) -> None:
    reader, api, _events = configured_reader

    first = reader.poll(1.0)
    throttled = reader.poll(1.09)
    fresh = reader.poll(1.10)

    assert first is throttled
    assert fresh.state is not None
    assert len(api.reads) == 6


def test_foreground_loss_returns_a_typed_error_without_opening_or_reading(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
) -> None:
    reader, api, events = configured_reader
    api.foreground = False

    reading = reader.poll(0.0)

    assert reading.state is None
    assert reading.error is not None
    assert reading.error.code is CameraReadErrorCode.WINDOW_NOT_FOREGROUND
    assert api.open_count == 0
    assert api.reads == []
    assert [event.code for event in events] == [CameraReadErrorCode.WINDOW_NOT_FOREGROUND]


def test_short_camera_structure_read_closes_the_handle(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
) -> None:
    reader, api, events = configured_reader
    api.short_read = True

    reading = reader.poll(0.0)

    assert reading.state is None
    assert reading.error is not None
    assert reading.error.code is CameraReadErrorCode.MALFORMED_READ
    assert api.closed == [PROCESS_HANDLE]
    assert events[0].code is CameraReadErrorCode.MALFORMED_READ


def test_lost_handle_recovers_on_the_next_eligible_poll(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
) -> None:
    reader, api, events = configured_reader
    api.fail_read = True
    assert reader.poll(0.0).error is not None

    api.fail_read = False
    recovered = reader.poll(0.1)

    assert recovered.state is not None
    assert api.open_count == 2
    assert [event.code for event in events] == [CameraReadErrorCode.HANDLE_LOST]


def test_window_handle_provider_reacquires_after_a_client_restart(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"restart camera test build")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    profile = ClientCameraProfile(digest, CAMERA_POINTER_RVA, 8, 0x8, 0x14, 0x94, PROJECTION_RVA)
    api = FakeCameraMemoryApi(executable, profile)
    handles = iter((WINDOW_HANDLE, RESTARTED_WINDOW_HANDLE))
    reader = LiveCameraReader(lambda: next(handles), api=api, profiles={digest: profile})

    assert reader.poll(0.0).state is not None
    assert reader.poll(0.1).state is not None
    assert api.open_count == 2
    assert api.closed == [PROCESS_HANDLE]


def test_singular_matrices_are_rejected_before_unprojection() -> None:
    singular = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )

    with pytest.raises(ValueError, match="singular"):
        invert_matrix(singular)


def test_unprojection_matches_the_d3d_perspective_frustum(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
) -> None:
    reader, _api, _events = configured_reader
    state = reader.poll(0.0).state
    assert state is not None

    top_left = unproject_screen_ray(0.0, 0.0, 200, 100, state)
    centre = unproject_screen_ray(100.0, 50.0, 200, 100, state)
    bottom_right = unproject_screen_ray(200.0, 100.0, 200, 100, state)

    assert centre.direction.x == pytest.approx(0.0)
    assert centre.direction.y == pytest.approx(0.0)
    assert centre.direction.z == pytest.approx(1.0)
    assert top_left.direction.x == pytest.approx(-2.0 / math.sqrt(6.0))
    assert top_left.direction.y == pytest.approx(1.0 / math.sqrt(6.0))
    assert top_left.direction.z == pytest.approx(1.0 / math.sqrt(6.0))
    assert bottom_right.direction.x == pytest.approx(2.0 / math.sqrt(6.0))
    assert bottom_right.direction.y == pytest.approx(-1.0 / math.sqrt(6.0))
    assert bottom_right.direction.z == pytest.approx(1.0 / math.sqrt(6.0))


def test_world_projection_returns_the_client_pixel_of_a_point_ahead_of_the_camera(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
) -> None:
    reader, _api, _events = configured_reader
    state = reader.poll(0.0).state
    assert state is not None

    projection = project_world_to_screen(WorldPosition(0.0, 0.0, 10.0), 200, 100, state)

    assert projection.status is WorldProjectionStatus.VISIBLE
    assert (projection.x, projection.y) == (100, 50)


@pytest.mark.parametrize(
    ("position", "status"),
    [
        (WorldPosition(0.0, 0.0, -10.0), WorldProjectionStatus.BEHIND_CAMERA),
        (WorldPosition(500.0, 0.0, 10.0), WorldProjectionStatus.OUTSIDE_VIEWPORT),
        (WorldPosition(math.nan, 0.0, 10.0), WorldProjectionStatus.INVALID),
    ],
)
def test_world_projection_refuses_a_click_target_it_cannot_prove(
    configured_reader: tuple[LiveCameraReader, FakeCameraMemoryApi, list[CameraReadError]],
    position: WorldPosition,
    status: WorldProjectionStatus,
) -> None:
    reader, _api, _events = configured_reader
    state = reader.poll(0.0).state
    assert state is not None

    projection = project_world_to_screen(position, 200, 100, state)

    assert projection.status is status
    assert projection.x is None and projection.y is None


def test_world_projection_requires_a_positive_viewport() -> None:
    with pytest.raises(ValueError, match="Viewport"):
        project_world_to_screen(WorldPosition(0.0, 0.0, 1.0), 0, 100, CameraState())
