"""Read the local player's current world ID from the permitted client memory region.

The world ID is a single 32-bit integer stored at a build-specific offset. Unlike the
position reader, no verified offsets are shipped: an operator must author a JSON profile
keyed by client SHA-256 before any read is attempted. Without a matching profile this
reader reports ``UNSUPPORTED_BUILD`` and returns ``None`` ? it never guesses.
"""

from __future__ import annotations

import json
import logging
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock

from flyff_bot.constants import DEFAULT_CLIENT_WORLD_ID_PROFILES_PATH
from flyff_bot.features.navigation.live_position import (
    ProcessMemoryApi,
    WindowsProcessMemoryApi,
    executable_sha256,
)

WORLD_ID_STRUCT_SIZE_BYTES = 4
EXPECTED_PROCESS_NAME = "neuz.exe"


class WorldIdReadErrorCode(StrEnum):
    """Why a live world-ID read could not produce a value."""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    PROCESS_UNAVAILABLE = "process_unavailable"
    WRONG_PROCESS = "wrong_process"
    UNSUPPORTED_BUILD = "unsupported_build"
    HANDLE_LOST = "handle_lost"
    MALFORMED_READ = "malformed_read"
    INVALID_PROFILE_CONFIGURATION = "invalid_profile_configuration"


@dataclass(frozen=True, slots=True)
class WorldIdReadError:
    """Typed diagnostic naming why one world-ID read produced no value."""

    code: WorldIdReadErrorCode
    detail: str = ""


@dataclass(frozen=True, slots=True)
class WorldIdReading:
    """The result of one poll."""

    world_id: int | None = None
    error: WorldIdReadError | None = None
    sampled_at_seconds: float | None = None

    @property
    def is_available(self) -> bool:
        return self.world_id is not None and self.error is None


@dataclass(frozen=True, slots=True)
class ClientWorldIdProfile:
    """The one offset needed for one fingerprinted Entropia client build."""

    sha256: str
    world_id_rva: int

    def __post_init__(self) -> None:
        if len(self.sha256) != 64:
            raise ValueError("A client build fingerprint must be a SHA-256 digest.")
        if self.world_id_rva <= 0:
            raise ValueError("Client world ID offset must be a positive module offset.")


def load_client_world_id_profiles(path: Path) -> Mapping[str, ClientWorldIdProfile]:
    """Load validated operator-maintained profiles from one JSON document.

    A malformed operator file is rejected explicitly: silently substituting offsets would
    defeat the fingerprint safety boundary.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"World ID profile configuration {path} is invalid: {error}") from error
    if not isinstance(payload, list):
        raise ValueError(f"World ID profile configuration {path} must contain a JSON list.")

    profiles: dict[str, ClientWorldIdProfile] = {}
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"World ID profile entry {index} must be an object.")
        required = {"sha256", "world_id_rva"}
        if missing := required.difference(item):
            raise ValueError(
                f"World ID profile entry {index} is missing {', '.join(sorted(missing))}."
            )
        rva = item["world_id_rva"]
        if not isinstance(rva, int) or isinstance(rva, bool):
            raise ValueError(f"World ID profile entry {index} has a non-integer RVA.")
        sha256 = item["sha256"]
        if not isinstance(sha256, str):
            raise ValueError(f"World ID profile entry {index} has a non-string SHA-256 digest.")
        normalized = sha256.lower()
        if any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError(f"World ID profile entry {index} has an invalid SHA-256 digest.")
        try:
            profile = ClientWorldIdProfile(normalized, world_id_rva=rva)
        except ValueError as error:
            raise ValueError(f"World ID profile entry {index} is invalid: {error}") from error
        if normalized in profiles:
            raise ValueError(f"World ID profile configuration repeats SHA-256 {normalized}.")
        profiles[normalized] = profile
    return profiles


class LiveWorldIdReader:
    """Poll a fingerprinted Entropia build's world ID at a configurable rate."""

    def __init__(
        self,
        window_handle: int,
        *,
        api: ProcessMemoryApi | None = None,
        profiles: Mapping[str, ClientWorldIdProfile] | None = None,
        profiles_path: Path = Path(DEFAULT_CLIENT_WORLD_ID_PROFILES_PATH),
        event_sink: Callable[[WorldIdReadError], None] | None = None,
    ) -> None:
        self._window_handle = window_handle
        self._api = api
        self._profiles: Mapping[str, ClientWorldIdProfile] = {} if profiles is None else profiles
        self._profiles_path = profiles_path
        self._profile_configuration_error: str | None = None
        if profiles is None and profiles_path.is_file():
            try:
                self._profiles = load_client_world_id_profiles(profiles_path)
            except ValueError as error:
                self._profiles = {}
                self._profile_configuration_error = str(error)
        self._event_sink = event_sink
        self._handle: int | None = None
        self._module_base: int | None = None
        self._profile: ClientWorldIdProfile | None = None
        self._last_reading = WorldIdReading()
        self._last_error_code: WorldIdReadErrorCode | None = None
        self._lock = RLock()
        self._logger = logging.getLogger(__name__)

    @property
    def last_reading(self) -> WorldIdReading:
        return self._last_reading

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def poll(self, at_seconds: float) -> WorldIdReading:
        """Return the newest world ID reading (no throttling; caller controls rate)."""

        with self._lock:
            try:
                if self._profile_configuration_error is not None:
                    raise _WorldIdOpenError(
                        WorldIdReadErrorCode.INVALID_PROFILE_CONFIGURATION,
                        self._profile_configuration_error,
                    )
                self._ensure_open()
                assert self._handle is not None
                assert self._module_base is not None
                assert self._profile is not None
                payload = self._api_or_raise().read(
                    self._handle,
                    self._module_base + self._profile.world_id_rva,
                    WORLD_ID_STRUCT_SIZE_BYTES,
                )
                if len(payload) != WORLD_ID_STRUCT_SIZE_BYTES:
                    raise _MalformedWorldIdRead("The world ID read was incomplete.")
                (world_id,) = struct.unpack("<i", payload)
                self._last_reading = WorldIdReading(
                    world_id=world_id,
                    sampled_at_seconds=at_seconds,
                )
                self._last_error_code = None
            except _MalformedWorldIdRead as error:
                self._fail(WorldIdReadErrorCode.MALFORMED_READ, str(error))
            except _WorldIdOpenError as error:
                self._fail(error.code, str(error))
            except OSError as error:
                self._fail(WorldIdReadErrorCode.HANDLE_LOST, str(error))
            return self._last_reading

    def close(self) -> None:
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
                raise _WorldIdOpenError(
                    WorldIdReadErrorCode.UNSUPPORTED_PLATFORM, str(error)
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
            raise _WorldIdOpenError(WorldIdReadErrorCode.PROCESS_UNAVAILABLE, str(error)) from error
        try:
            executable = api.executable_path(handle)
            if executable.name.casefold() != EXPECTED_PROCESS_NAME:
                raise _WorldIdOpenError(
                    WorldIdReadErrorCode.WRONG_PROCESS,
                    f"Expected {EXPECTED_PROCESS_NAME}, got {executable.name}.",
                )
            digest = executable_sha256(executable)
            profile = self._profiles.get(digest)
            if profile is None:
                raise _WorldIdOpenError(
                    WorldIdReadErrorCode.UNSUPPORTED_BUILD,
                    "No world ID profile exists for client build "
                    f"SHA-256 {digest} at {executable}.",
                )
            module_base = api.main_module_base(process_id)
        except (OSError, _WorldIdOpenError) as error:
            api.close(handle)
            if isinstance(error, _WorldIdOpenError):
                raise
            raise _WorldIdOpenError(WorldIdReadErrorCode.PROCESS_UNAVAILABLE, str(error)) from error
        self._handle = handle
        self._module_base = module_base
        self._profile = profile

    def _fail(self, code: WorldIdReadErrorCode, detail: str) -> None:
        self.close()
        error = WorldIdReadError(code, detail)
        self._last_reading = WorldIdReading(error=error)
        if code is self._last_error_code:
            return
        self._last_error_code = code
        self._logger.warning("Live world ID fallback (%s): %s", code.value, detail)
        if self._event_sink is not None:
            self._event_sink(error)


class _MalformedWorldIdRead(ValueError):
    pass


class _WorldIdOpenError(OSError):
    def __init__(self, code: WorldIdReadErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
