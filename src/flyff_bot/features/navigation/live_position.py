"""Read the local player's world coordinates from the permitted client memory region.

The shipped Entropia client keeps the active player in one build-specific global pointer.
Only that pointer and the 12-byte ``D3DXVECTOR3`` at ``CMover + 0x188`` are read.  The
adapter never scans process memory and never opens the process with write access.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import math
import struct
import sys
from collections.abc import Callable, Mapping
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Protocol

from flyff_bot.constants import DEFAULT_CLIENT_POSITION_PROFILES_PATH

DEFAULT_POSITION_POLL_HERTZ = 10.0
POSITION_FLOAT_COUNT = 3
POSITION_STRUCT_SIZE_BYTES = POSITION_FLOAT_COUNT * 4
PLAYER_POSITION_OFFSET = 0x188
EXPECTED_PROCESS_NAME = "neuz.exe"

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOOLHELP_SNAPSHOT_MODULE = 0x00000008
TOOLHELP_SNAPSHOT_MODULE_32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAXIMUM_PROCESS_PATH_LENGTH = 32_768
MAXIMUM_MODULE_NAME_LENGTH = 256


@dataclass(frozen=True, slots=True)
class WorldPosition:
    """One live client position in Flyff world coordinates."""

    x: float
    y: float
    z: float

    def distance_to(self, other: WorldPosition) -> float:
        """Return full 3D Euclidean distance to another position."""

        return math.sqrt(
            (other.x - self.x) ** 2 + (other.y - self.y) ** 2 + (other.z - self.z) ** 2
        )


class PositionSource(StrEnum):
    """The source currently anchoring navigation."""

    LIVE = "live"
    MINIMAP_FALLBACK = "minimap_fallback"


class PositionReadErrorCode(StrEnum):
    """Why a live coordinate read could not produce a position."""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    WINDOW_NOT_FOREGROUND = "window_not_foreground"
    PROCESS_UNAVAILABLE = "process_unavailable"
    WRONG_PROCESS = "wrong_process"
    UNSUPPORTED_BUILD = "unsupported_build"
    HANDLE_LOST = "handle_lost"
    MALFORMED_READ = "malformed_read"
    INVALID_PROFILE_CONFIGURATION = "invalid_profile_configuration"


@dataclass(frozen=True, slots=True)
class PositionReadError:
    """Typed diagnostic emitted when GPS falls back to minimap odometry."""

    code: PositionReadErrorCode
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PositionReading:
    """The result of one poll, including fallback state and diagnostics."""

    source: PositionSource
    position: WorldPosition | None = None
    error: PositionReadError | None = None
    sampled_at_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ClientPositionProfile:
    """The two offsets needed for one fingerprinted Entropia client build."""

    sha256: str
    player_pointer_rva: int
    pointer_size_bytes: int
    position_offset: int = PLAYER_POSITION_OFFSET

    def __post_init__(self) -> None:
        if len(self.sha256) != 64:
            raise ValueError("A client build fingerprint must be a SHA-256 digest.")
        if self.player_pointer_rva <= 0 or self.position_offset < 0:
            raise ValueError("Client position offsets must be non-negative module offsets.")
        if self.pointer_size_bytes not in {4, 8}:
            raise ValueError("A client pointer must be either 4 or 8 bytes wide.")


ENTROPIA_POSITION_PROFILES: Mapping[str, ClientPositionProfile] = {
    # Entropia/Entropia/bin32/neuz.exe, built 2026-08-14.
    "3446ffeb5d104a68d187e9e2ecfa216e1bdb88ce3f9201a046aa900525b6c07e": (
        ClientPositionProfile(
            "3446ffeb5d104a68d187e9e2ecfa216e1bdb88ce3f9201a046aa900525b6c07e",
            player_pointer_rva=0x94F698,
            pointer_size_bytes=4,
        )
    ),
    # Entropia/Entropia/bin64/neuz.exe, built 2026-08-14.
    "8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5": (
        ClientPositionProfile(
            "8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5",
            player_pointer_rva=0xB7C908,
            pointer_size_bytes=8,
        )
    ),
}

DEFAULT_CLIENT_POSITION_PROFILES_FILE = Path(DEFAULT_CLIENT_POSITION_PROFILES_PATH)


def load_client_position_profiles(path: Path) -> Mapping[str, ClientPositionProfile]:
    """Load validated operator-maintained client profiles from one JSON document.

    The document is a JSON list of profile objects.  A malformed operator file is rejected
    explicitly: silently substituting offsets would defeat the fingerprint safety boundary.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Client profile configuration {path} is invalid: {error}") from error
    if not isinstance(payload, list):
        raise ValueError(f"Client profile configuration {path} must contain a JSON list.")

    profiles: dict[str, ClientPositionProfile] = {}
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Client profile entry {index} must be an object.")
        required = {"sha256", "player_pointer_rva", "pointer_size_bytes"}
        if missing := required.difference(item):
            raise ValueError(
                f"Client profile entry {index} is missing {', '.join(sorted(missing))}."
            )
        if not all(
            isinstance(item[key], int) and not isinstance(item[key], bool)
            for key in ("player_pointer_rva", "pointer_size_bytes")
        ):
            raise ValueError(
                f"Client profile entry {index} has non-integer offsets or pointer size."
            )
        position_offset = item.get("position_offset", PLAYER_POSITION_OFFSET)
        if not isinstance(position_offset, int) or isinstance(position_offset, bool):
            raise ValueError(f"Client profile entry {index} has a non-integer position offset.")
        sha256 = item["sha256"]
        if not isinstance(sha256, str):
            raise ValueError(f"Client profile entry {index} has a non-string SHA-256 digest.")
        normalized_sha256 = sha256.lower()
        if any(character not in "0123456789abcdef" for character in normalized_sha256):
            raise ValueError(f"Client profile entry {index} has an invalid SHA-256 digest.")
        try:
            profile = ClientPositionProfile(
                normalized_sha256,
                player_pointer_rva=item["player_pointer_rva"],
                pointer_size_bytes=item["pointer_size_bytes"],
                position_offset=position_offset,
            )
        except ValueError as error:
            raise ValueError(f"Client profile entry {index} is invalid: {error}") from error
        if normalized_sha256 in profiles:
            raise ValueError(f"Client profile configuration repeats SHA-256 {normalized_sha256}.")
        profiles[normalized_sha256] = profile
    return profiles


class ProcessMemoryApi(Protocol):
    """The narrow Win32 boundary used by :class:`LivePositionReader`."""

    def process_id_for_window(self, window_handle: int) -> int: ...

    def open_read_process(self, process_id: int) -> int: ...

    def executable_path(self, process_handle: int) -> Path: ...

    def main_module_base(self, process_id: int) -> int: ...

    def read(self, process_handle: int, address: int, size: int) -> bytes: ...

    def close(self, process_handle: int) -> None: ...


class _ModuleEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * MAXIMUM_MODULE_NAME_LENGTH),
        ("szExePath", wintypes.WCHAR * MAXIMUM_PROCESS_PATH_LENGTH),
    ]


class WindowsProcessMemoryApi:
    """Documented Win32 adapter with read-only process rights."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Live position reading is only available on Windows.")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_api()

    def _configure_api(self) -> None:
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.LPVOID,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._kernel32.ReadProcessMemory.restype = wintypes.BOOL
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self._kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self._kernel32.Module32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ModuleEntry32W),
        ]
        self._kernel32.Module32FirstW.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def process_id_for_window(self, window_handle: int) -> int:
        process_id = wintypes.DWORD()
        if not self._user32.GetWindowThreadProcessId(window_handle, ctypes.byref(process_id)):
            raise OSError(ctypes.get_last_error(), "The game window has no process.")
        return int(process_id.value)

    def open_read_process(self, process_id: int) -> int:
        handle = self._kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
            False,
            process_id,
        )
        if not handle:
            raise OSError(ctypes.get_last_error(), "The game process could not be opened.")
        return int(handle)

    def executable_path(self, process_handle: int) -> Path:
        size = wintypes.DWORD(MAXIMUM_PROCESS_PATH_LENGTH)
        path = ctypes.create_unicode_buffer(size.value)
        if not self._kernel32.QueryFullProcessImageNameW(
            process_handle, 0, path, ctypes.byref(size)
        ):
            raise OSError(ctypes.get_last_error(), "The game executable path is unavailable.")
        return Path(path.value)

    def main_module_base(self, process_id: int) -> int:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(
            TOOLHELP_SNAPSHOT_MODULE | TOOLHELP_SNAPSHOT_MODULE_32, process_id
        )
        if not snapshot or int(snapshot) == INVALID_HANDLE_VALUE:
            raise OSError(ctypes.get_last_error(), "The game module list is unavailable.")
        try:
            entry = _ModuleEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not self._kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
                raise OSError(ctypes.get_last_error(), "The game module base is unavailable.")
            address = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value
            if address is None:
                raise OSError("The game module base is null.")
            return int(address)
        finally:
            self._kernel32.CloseHandle(snapshot)

    def read(self, process_handle: int, address: int, size: int) -> bytes:
        buffer = (ctypes.c_ubyte * size)()
        read_size = ctypes.c_size_t()
        if not self._kernel32.ReadProcessMemory(
            process_handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read_size),
        ):
            raise OSError(ctypes.get_last_error(), "The coordinate memory read failed.")
        return bytes(buffer[: read_size.value])

    def close(self, process_handle: int) -> None:
        if process_handle:
            self._kernel32.CloseHandle(process_handle)


class LivePositionReader:
    """Poll a fingerprinted Entropia build's player coordinate struct at 10 Hz."""

    def __init__(
        self,
        window_handle: int,
        *,
        api: ProcessMemoryApi | None = None,
        profiles: Mapping[str, ClientPositionProfile] | None = None,
        profiles_path: Path = DEFAULT_CLIENT_POSITION_PROFILES_FILE,
        poll_hertz: float = DEFAULT_POSITION_POLL_HERTZ,
        event_sink: Callable[[PositionReadError], None] | None = None,
    ) -> None:
        if poll_hertz <= 0.0:
            raise ValueError("Live position poll rate must be positive.")
        self._window_handle = window_handle
        self._api = api
        self._profiles: Mapping[str, ClientPositionProfile] = (
            ENTROPIA_POSITION_PROFILES if profiles is None else profiles
        )
        self._profiles_path = profiles_path
        self._profile_configuration_error: str | None = None
        if profiles is None:
            if profiles_path.is_file():
                try:
                    self._profiles = load_client_position_profiles(profiles_path)
                except ValueError as error:
                    self._profiles = {}
                    self._profile_configuration_error = str(error)
            else:
                self._profiles = ENTROPIA_POSITION_PROFILES
        self._poll_interval_seconds = 1.0 / poll_hertz
        self._event_sink = event_sink
        self._handle: int | None = None
        self._module_base: int | None = None
        self._profile: ClientPositionProfile | None = None
        self._polled_at_seconds: float | None = None
        self._last_reading = PositionReading(PositionSource.MINIMAP_FALLBACK)
        self._last_error_code: PositionReadErrorCode | None = None
        self._lock = RLock()
        self._logger = logging.getLogger(__name__)

    @property
    def source(self) -> PositionSource:
        return self._last_reading.source

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def poll(self, at_seconds: float) -> PositionReading:
        """Return the newest position, throttled to the configured poll interval."""

        with self._lock:
            if (
                self._polled_at_seconds is not None
                and at_seconds - self._polled_at_seconds < self._poll_interval_seconds
            ):
                return self._last_reading
            self._polled_at_seconds = at_seconds
            try:
                if self._profile_configuration_error is not None:
                    raise _PositionOpenError(
                        PositionReadErrorCode.INVALID_PROFILE_CONFIGURATION,
                        self._profile_configuration_error,
                    )
                self._ensure_open()
                assert self._handle is not None
                assert self._module_base is not None
                assert self._profile is not None
                pointer_bytes = self._api_or_raise().read(
                    self._handle,
                    self._module_base + self._profile.player_pointer_rva,
                    self._profile.pointer_size_bytes,
                )
                if len(pointer_bytes) != self._profile.pointer_size_bytes:
                    raise _MalformedPositionRead("The player pointer read was incomplete.")
                pointer_format = "<I" if self._profile.pointer_size_bytes == 4 else "<Q"
                player_address = int(struct.unpack(pointer_format, pointer_bytes)[0])
                if player_address == 0:
                    raise _MalformedPositionRead("The active player pointer is null.")
                payload = self._api_or_raise().read(
                    self._handle,
                    player_address + self._profile.position_offset,
                    POSITION_STRUCT_SIZE_BYTES,
                )
                if len(payload) != POSITION_STRUCT_SIZE_BYTES:
                    raise _MalformedPositionRead("The coordinate struct read was incomplete.")
                x, y, z = struct.unpack("<3f", payload)
                if not all(math.isfinite(value) for value in (x, y, z)):
                    raise _MalformedPositionRead(
                        "The coordinate struct contained a non-finite value."
                    )
                self._last_reading = PositionReading(
                    PositionSource.LIVE,
                    WorldPosition(float(x), float(y), float(z)),
                    sampled_at_seconds=at_seconds,
                )
                self._last_error_code = None
            except _MalformedPositionRead as error:
                self._fail(PositionReadErrorCode.MALFORMED_READ, str(error))
            except _PositionOpenError as error:
                self._fail(error.code, str(error))
            except OSError as error:
                self._fail(PositionReadErrorCode.HANDLE_LOST, str(error))
            return self._last_reading

    def close(self) -> None:
        """Release the read-only process handle. Safe to call repeatedly."""

        with self._lock:
            if self._handle is not None:
                self._api_or_raise().close(self._handle)
            self._handle = None
            self._module_base = None
            self._profile = None

    def _api_or_raise(self) -> ProcessMemoryApi:
        if self._api is None:
            try:
                self._api = WindowsProcessMemoryApi()
            except OSError as error:
                raise _PositionOpenError(
                    PositionReadErrorCode.UNSUPPORTED_PLATFORM, str(error)
                ) from error
        return self._api

    def _ensure_open(self) -> None:
        if self._handle is not None:
            return
        api = self._api_or_raise()
        try:
            process_id = api.process_id_for_window(self._window_handle)
            handle = api.open_read_process(process_id)
        except OSError as error:
            raise _PositionOpenError(
                PositionReadErrorCode.PROCESS_UNAVAILABLE, str(error)
            ) from error
        try:
            executable = api.executable_path(handle)
            if executable.name.casefold() != EXPECTED_PROCESS_NAME:
                raise _PositionOpenError(
                    PositionReadErrorCode.WRONG_PROCESS,
                    f"Expected {EXPECTED_PROCESS_NAME}, got {executable.name}.",
                )
            digest = executable_sha256(executable)
            profile = self._profiles.get(digest)
            if profile is None:
                raise _PositionOpenError(
                    PositionReadErrorCode.UNSUPPORTED_BUILD,
                    "No coordinate profile exists for client build "
                    f"SHA-256 {digest} at {executable}.",
                )
            module_base = api.main_module_base(process_id)
        except (OSError, _PositionOpenError) as error:
            api.close(handle)
            if isinstance(error, _PositionOpenError):
                raise
            raise _PositionOpenError(
                PositionReadErrorCode.PROCESS_UNAVAILABLE, str(error)
            ) from error
        self._handle = handle
        self._module_base = module_base
        self._profile = profile

    def _fail(self, code: PositionReadErrorCode, detail: str) -> None:
        self.close()
        error = PositionReadError(code, detail)
        self._last_reading = PositionReading(PositionSource.MINIMAP_FALLBACK, error=error)
        if code is self._last_error_code:
            return
        self._last_error_code = code
        self._logger.warning("Live position fallback (%s): %s", code.value, detail)
        if self._event_sink is not None:
            self._event_sink(error)


class _MalformedPositionRead(ValueError):
    pass


class _PositionOpenError(OSError):
    def __init__(self, code: PositionReadErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def executable_sha256(path: Path) -> str:
    """Return a lowercase client fingerprint for diagnostics and profile authoring."""

    with path.open("rb") as stream:
        digest = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
