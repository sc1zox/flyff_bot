"""Fingerprint-bound, read-only extraction of an Entropia client's active camera.

The reader addresses only the small, documented ranges in an exact executable profile.  It
does not scan memory, modify the process, install hooks, or infer a profile for an unknown
build.  D3DX uses row-major matrices with row-vector multiplication, so the view-projection
matrix is ``view @ projection`` and screen depth spans zero through one.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Protocol

from flyff_bot.constants import DEFAULT_CLIENT_CAMERA_PROFILES_PATH
from flyff_bot.features.navigation.live_position import (
    EXPECTED_PROCESS_NAME,
    ProcessMemoryApi,
    WindowsProcessMemoryApi,
    WorldPosition,
    executable_sha256,
)

DEFAULT_CAMERA_POLL_HERTZ = 10.0
MATRIX_FLOAT_COUNT = 16
MATRIX_SIZE_BYTES = MATRIX_FLOAT_COUNT * 4
VECTOR_FLOAT_COUNT = 3
VECTOR_SIZE_BYTES = VECTOR_FLOAT_COUNT * 4
SINGULAR_MATRIX_EPSILON = 1e-8
NDC_NEAR_DEPTH = 0.0
NDC_FAR_DEPTH = 1.0

Matrix4x4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


@dataclass(frozen=True, slots=True)
class Vector3D:
    """A finite world-space direction or displacement."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("A world vector must be finite.")

    @property
    def length(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def normalized(self) -> Vector3D:
        length = self.length
        if length <= SINGULAR_MATRIX_EPSILON:
            raise ValueError("A zero-length world vector cannot be normalized.")
        return Vector3D(self.x / length, self.y / length, self.z / length)


@dataclass(frozen=True, slots=True)
class WorldRay3D:
    """A unit ray emitted from the effective camera eye in client-world coordinates."""

    origin: WorldPosition
    direction: Vector3D


@dataclass(frozen=True, slots=True)
class CameraState:
    """One coherent D3D9 camera snapshot derived from View and Projection matrices."""

    position: WorldPosition
    pitch_radians: float
    yaw_radians: float
    zoom_distance: float
    vertical_fov_radians: float
    view_matrix: Matrix4x4
    projection_matrix: Matrix4x4
    view_projection_matrix: Matrix4x4
    inverse_view_projection_matrix: Matrix4x4


class CameraReadErrorCode(StrEnum):
    """Why a camera poll intentionally returned no state."""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    WINDOW_NOT_FOREGROUND = "window_not_foreground"
    PROCESS_UNAVAILABLE = "process_unavailable"
    WRONG_PROCESS = "wrong_process"
    UNSUPPORTED_BUILD = "unsupported_build"
    HANDLE_LOST = "handle_lost"
    MALFORMED_READ = "malformed_read"
    INVALID_PROFILE_CONFIGURATION = "invalid_profile_configuration"


@dataclass(frozen=True, slots=True)
class CameraReadError:
    """A typed, non-fatal reason camera geometry is unavailable."""

    code: CameraReadErrorCode
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CameraReading:
    """The result of one live camera poll; unavailable geometry is always explicit."""

    state: CameraState | None = None
    error: CameraReadError | None = None
    sampled_at_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ClientCameraProfile:
    """The verified, smallest address set for one exact executable fingerprint.

    Projection is a renderer global rather than a ``CCamera`` member in both supported
    Entropia builds.  Camera angle scalars are deliberately not profiled: pitch, yaw, FOV,
    and zoom are derived from verified vectors and matrices instead of guessed fields.
    """

    sha256: str
    camera_pointer_rva: int
    pointer_size_bytes: int
    eye_position_offset: int
    view_matrix_offset: int
    look_at_offset: int
    projection_matrix_rva: int

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("A client build fingerprint must be a lowercase SHA-256 digest.")
        if self.pointer_size_bytes not in {4, 8}:
            raise ValueError("A camera pointer must be either 4 or 8 bytes wide.")
        if self.camera_pointer_rva <= 0 or self.projection_matrix_rva <= 0:
            raise ValueError("Camera global RVAs must be positive.")
        if min(self.eye_position_offset, self.view_matrix_offset, self.look_at_offset) < 0:
            raise ValueError("Camera structure offsets must be non-negative.")

    @property
    def camera_read_start_offset(self) -> int:
        return min(self.eye_position_offset, self.view_matrix_offset, self.look_at_offset)

    @property
    def camera_read_size_bytes(self) -> int:
        end_offset = max(
            self.eye_position_offset + VECTOR_SIZE_BYTES,
            self.view_matrix_offset + MATRIX_SIZE_BYTES,
            self.look_at_offset + VECTOR_SIZE_BYTES,
        )
        return end_offset - self.camera_read_start_offset


ENTROPIA_CAMERA_PROFILES: Mapping[str, ClientCameraProfile] = {
    "3446ffeb5d104a68d187e9e2ecfa216e1bdb88ce3f9201a046aa900525b6c07e": ClientCameraProfile(
        sha256="3446ffeb5d104a68d187e9e2ecfa216e1bdb88ce3f9201a046aa900525b6c07e",
        camera_pointer_rva=0x967FBC,
        pointer_size_bytes=4,
        eye_position_offset=0x4,
        view_matrix_offset=0x10,
        look_at_offset=0x90,
        projection_matrix_rva=0xB015D0,
    ),
    "8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5": ClientCameraProfile(
        sha256="8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5",
        camera_pointer_rva=0x7AD8E8,
        pointer_size_bytes=8,
        eye_position_offset=0x8,
        view_matrix_offset=0x14,
        look_at_offset=0x94,
        projection_matrix_rva=0x976B80,
    ),
}

DEFAULT_CLIENT_CAMERA_PROFILES_FILE = Path(DEFAULT_CLIENT_CAMERA_PROFILES_PATH)


def load_client_camera_profiles(path: Path) -> Mapping[str, ClientCameraProfile]:
    """Load one exact-fingerprint camera profile registry without a permissive fallback."""

    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Client camera profile configuration {path} is invalid: {error}"
        ) from error
    if not isinstance(payload, list):
        raise ValueError(f"Client camera profile configuration {path} must contain a JSON list.")
    profiles: dict[str, ClientCameraProfile] = {}
    required = {
        "sha256",
        "camera_pointer_rva",
        "pointer_size_bytes",
        "eye_position_offset",
        "view_matrix_offset",
        "look_at_offset",
        "projection_matrix_rva",
    }
    integer_fields = required - {"sha256"}
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Client camera profile entry {index} must be an object.")
        if missing := required.difference(item):
            raise ValueError(
                f"Client camera profile entry {index} is missing {', '.join(sorted(missing))}."
            )
        if not isinstance(item["sha256"], str):
            raise ValueError(
                f"Client camera profile entry {index} has a non-string SHA-256 digest."
            )
        if not all(
            isinstance(item[key], int) and not isinstance(item[key], bool) for key in integer_fields
        ):
            raise ValueError(f"Client camera profile entry {index} has a non-integer offset.")
        sha256 = item["sha256"].lower()
        try:
            profile = ClientCameraProfile(
                sha256=sha256, **{key: item[key] for key in integer_fields}
            )
        except ValueError as error:
            raise ValueError(f"Client camera profile entry {index} is invalid: {error}") from error
        if sha256 in profiles:
            raise ValueError(f"Client camera profile configuration repeats SHA-256 {sha256}.")
        profiles[sha256] = profile
    return profiles


class CameraProcessMemoryApi(ProcessMemoryApi, Protocol):
    """The read-only process boundary additionally needed for foreground-gated camera polling."""

    def is_window_foreground(self, window_handle: int) -> bool: ...


class LiveCameraReader:
    """Poll exact-profile camera matrices at a bounded foreground-only cadence."""

    def __init__(
        self,
        window_handle: int | Callable[[], int | None],
        *,
        api: CameraProcessMemoryApi | None = None,
        profiles: Mapping[str, ClientCameraProfile] | None = None,
        profiles_path: Path = DEFAULT_CLIENT_CAMERA_PROFILES_FILE,
        poll_hertz: float = DEFAULT_CAMERA_POLL_HERTZ,
        event_sink: Callable[[CameraReadError], None] | None = None,
    ) -> None:
        if poll_hertz <= 0.0:
            raise ValueError("Live camera poll rate must be positive.")
        self._window_handle_provider = (
            window_handle if callable(window_handle) else lambda: window_handle
        )
        self._api = api
        self._profiles: Mapping[str, ClientCameraProfile] = (
            ENTROPIA_CAMERA_PROFILES if profiles is None else profiles
        )
        self._profile_configuration_error: str | None = None
        if profiles is None and profiles_path.is_file():
            try:
                self._profiles = load_client_camera_profiles(profiles_path)
            except ValueError as error:
                self._profiles = {}
                self._profile_configuration_error = str(error)
        self._poll_interval_seconds = 1.0 / poll_hertz
        self._event_sink = event_sink
        self._handle: int | None = None
        self._module_base: int | None = None
        self._profile: ClientCameraProfile | None = None
        self._window_handle: int | None = None
        self._polled_at_seconds: float | None = None
        self._last_reading = CameraReading()
        self._last_error_code: CameraReadErrorCode | None = None
        self._lock = RLock()

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def poll(self, at_seconds: float) -> CameraReading:
        """Return the latest complete camera state or an explicit unavailable result."""

        with self._lock:
            if (
                self._polled_at_seconds is not None
                and at_seconds - self._polled_at_seconds < self._poll_interval_seconds
            ):
                return self._last_reading
            self._polled_at_seconds = at_seconds
            try:
                if self._profile_configuration_error is not None:
                    raise _CameraOpenError(
                        CameraReadErrorCode.INVALID_PROFILE_CONFIGURATION,
                        self._profile_configuration_error,
                    )
                window_handle = self._window_handle_provider()
                if window_handle is None or window_handle == 0:
                    raise _CameraOpenError(
                        CameraReadErrorCode.PROCESS_UNAVAILABLE, "No game window is available."
                    )
                api = self._api_or_raise()
                if not api.is_window_foreground(window_handle):
                    raise _CameraOpenError(
                        CameraReadErrorCode.WINDOW_NOT_FOREGROUND,
                        "The game window is not foregrounded.",
                    )
                if self._window_handle != window_handle:
                    self.close()
                    self._window_handle = window_handle
                self._ensure_open(window_handle)
                state = self._read_state()
                self._last_reading = CameraReading(state=state, sampled_at_seconds=at_seconds)
                self._last_error_code = None
            except _MalformedCameraRead as error:
                self._fail(CameraReadErrorCode.MALFORMED_READ, str(error))
            except _CameraOpenError as error:
                self._fail(error.code, str(error))
            except OSError as error:
                self._fail(CameraReadErrorCode.HANDLE_LOST, str(error))
            return self._last_reading

    def close(self) -> None:
        """Release the read-only handle; repeated close calls are safe."""

        if self._handle is not None:
            self._api_or_raise().close(self._handle)
        self._handle = None
        self._module_base = None
        self._profile = None

    def _api_or_raise(self) -> CameraProcessMemoryApi:
        if self._api is None:
            try:
                self._api = WindowsProcessMemoryApi()
            except OSError as error:
                raise _CameraOpenError(
                    CameraReadErrorCode.UNSUPPORTED_PLATFORM, str(error)
                ) from error
        return self._api

    def _ensure_open(self, window_handle: int) -> None:
        if self._handle is not None:
            return
        api = self._api_or_raise()
        try:
            process_id = api.process_id_for_window(window_handle)
            handle = api.open_read_process(process_id)
        except OSError as error:
            raise _CameraOpenError(CameraReadErrorCode.PROCESS_UNAVAILABLE, str(error)) from error
        try:
            executable = api.executable_path(handle)
            if executable.name.casefold() != EXPECTED_PROCESS_NAME:
                raise _CameraOpenError(
                    CameraReadErrorCode.WRONG_PROCESS,
                    f"Expected {EXPECTED_PROCESS_NAME}, got {executable.name}.",
                )
            digest = executable_sha256(executable)
            profile = self._profiles.get(digest)
            if profile is None:
                raise _CameraOpenError(
                    CameraReadErrorCode.UNSUPPORTED_BUILD,
                    f"No camera profile exists for client build SHA-256 {digest} at {executable}.",
                )
            module_base = api.main_module_base(process_id)
        except (OSError, _CameraOpenError) as error:
            api.close(handle)
            if isinstance(error, _CameraOpenError):
                raise
            raise _CameraOpenError(CameraReadErrorCode.PROCESS_UNAVAILABLE, str(error)) from error
        self._handle = handle
        self._module_base = module_base
        self._profile = profile

    def _read_state(self) -> CameraState:
        assert self._handle is not None
        assert self._module_base is not None
        assert self._profile is not None
        api = self._api_or_raise()
        pointer_bytes = api.read(
            self._handle,
            self._module_base + self._profile.camera_pointer_rva,
            self._profile.pointer_size_bytes,
        )
        if len(pointer_bytes) != self._profile.pointer_size_bytes:
            raise _MalformedCameraRead("The camera pointer read was incomplete.")
        pointer_format = "<I" if self._profile.pointer_size_bytes == 4 else "<Q"
        camera_address = int(struct.unpack(pointer_format, pointer_bytes)[0])
        if camera_address == 0:
            raise _MalformedCameraRead("The active camera pointer is null.")
        camera_bytes = api.read(
            self._handle,
            camera_address + self._profile.camera_read_start_offset,
            self._profile.camera_read_size_bytes,
        )
        if len(camera_bytes) != self._profile.camera_read_size_bytes:
            raise _MalformedCameraRead("The camera structure read was incomplete.")
        projection_bytes = api.read(
            self._handle,
            self._module_base + self._profile.projection_matrix_rva,
            MATRIX_SIZE_BYTES,
        )
        if len(projection_bytes) != MATRIX_SIZE_BYTES:
            raise _MalformedCameraRead("The projection matrix read was incomplete.")
        view = _matrix_from_bytes(
            camera_bytes,
            self._profile.view_matrix_offset - self._profile.camera_read_start_offset,
        )
        look_at = _vector_from_bytes(
            camera_bytes,
            self._profile.look_at_offset - self._profile.camera_read_start_offset,
        )
        projection = _matrix_from_bytes(projection_bytes)
        try:
            inverse_view = invert_matrix(view)
            view_projection = multiply_matrices(view, projection)
            inverse_view_projection = invert_matrix(view_projection)
            position = WorldPosition(*inverse_view[3][:3])
            forward = Vector3D(*inverse_view[2][:3]).normalized()
            zoom_distance = Vector3D(
                look_at[0] - position.x,
                look_at[1] - position.y,
                look_at[2] - position.z,
            ).length
            fov_scale = projection[1][1]
            if fov_scale <= SINGULAR_MATRIX_EPSILON:
                raise ValueError("The projection matrix has no positive vertical FOV scale.")
        except ValueError as error:
            raise _MalformedCameraRead(str(error)) from error
        return CameraState(
            position=position,
            pitch_radians=math.asin(max(-1.0, min(1.0, forward.y))),
            yaw_radians=math.atan2(forward.x, forward.z),
            zoom_distance=zoom_distance,
            vertical_fov_radians=2.0 * math.atan(1.0 / fov_scale),
            view_matrix=view,
            projection_matrix=projection,
            view_projection_matrix=view_projection,
            inverse_view_projection_matrix=inverse_view_projection,
        )

    def _fail(self, code: CameraReadErrorCode, detail: str) -> None:
        self.close()
        error = CameraReadError(code, detail)
        self._last_reading = CameraReading(error=error)
        if code is self._last_error_code:
            return
        self._last_error_code = code
        if self._event_sink is not None:
            self._event_sink(error)


def multiply_matrices(left: Matrix4x4, right: Matrix4x4) -> Matrix4x4:
    """Return the row-vector-compatible product ``left @ right``."""

    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(4))
            for column in range(4)
        )
        for row in range(4)
    )  # type: ignore[return-value]


def invert_matrix(matrix: Matrix4x4) -> Matrix4x4:
    """Invert a finite 4x4 matrix with Gauss-Jordan elimination and pivot rejection."""

    rows = [
        list(row) + [float(row_index == column) for column in range(4)]
        for row_index, row in enumerate(matrix)
    ]
    for column in range(4):
        pivot_row = max(range(column, 4), key=lambda row: abs(rows[row][column]))
        pivot = rows[pivot_row][column]
        if not math.isfinite(pivot) or abs(pivot) <= SINGULAR_MATRIX_EPSILON:
            raise ValueError("The matrix is singular or near-singular.")
        rows[column], rows[pivot_row] = rows[pivot_row], rows[column]
        rows[column] = [value / pivot for value in rows[column]]
        for row in range(4):
            if row == column:
                continue
            factor = rows[row][column]
            rows[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(rows[row], rows[column], strict=True)
            ]
    inverse = tuple(tuple(row[4:]) for row in rows)
    if not all(math.isfinite(value) for row in inverse for value in row):
        raise ValueError("The matrix inverse contains a non-finite value.")
    return inverse  # type: ignore[return-value]


def unproject_screen_ray(
    screen_x: float,
    screen_y: float,
    viewport_width: int,
    viewport_height: int,
    camera_state: CameraState,
) -> WorldRay3D:
    """Transform one client-space pixel into an exact camera-origin world ray."""

    if viewport_width <= 0 or viewport_height <= 0:
        raise ValueError("Viewport dimensions must be positive.")
    if not all(math.isfinite(value) for value in (screen_x, screen_y)):
        raise ValueError("Screen coordinates must be finite.")
    ndc_x = 2.0 * screen_x / viewport_width - 1.0
    ndc_y = 1.0 - 2.0 * screen_y / viewport_height
    far_world = _transform_row_vector(
        (ndc_x, ndc_y, NDC_FAR_DEPTH, 1.0), camera_state.inverse_view_projection_matrix
    )
    direction = Vector3D(
        far_world[0] - camera_state.position.x,
        far_world[1] - camera_state.position.y,
        far_world[2] - camera_state.position.z,
    ).normalized()
    return WorldRay3D(origin=camera_state.position, direction=direction)


def _matrix_from_bytes(payload: bytes, offset: int = 0) -> Matrix4x4:
    values = struct.unpack_from("<16f", payload, offset)
    if not all(math.isfinite(value) for value in values):
        raise _MalformedCameraRead("A camera matrix contained a non-finite value.")
    return tuple(tuple(float(values[row * 4 + column]) for column in range(4)) for row in range(4))  # type: ignore[return-value]


def _vector_from_bytes(payload: bytes, offset: int) -> tuple[float, float, float]:
    values = struct.unpack_from("<3f", payload, offset)
    if not all(math.isfinite(value) for value in values):
        raise _MalformedCameraRead("A camera vector contained a non-finite value.")
    return tuple(float(value) for value in values)  # type: ignore[return-value]


def _transform_row_vector(
    vector: tuple[float, float, float, float], matrix: Matrix4x4
) -> tuple[float, float, float]:
    transformed = tuple(
        sum(vector[row] * matrix[row][column] for row in range(4)) for column in range(4)
    )
    if (
        not all(math.isfinite(value) for value in transformed)
        or abs(transformed[3]) <= SINGULAR_MATRIX_EPSILON
    ):
        raise ValueError("Unprojection produced an invalid homogeneous coordinate.")
    return (
        transformed[0] / transformed[3],
        transformed[1] / transformed[3],
        transformed[2] / transformed[3],
    )


class _MalformedCameraRead(ValueError):
    pass


class _CameraOpenError(OSError):
    def __init__(self, code: CameraReadErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
