"""Fingerprint-bound, read-only polling of Entropia player statistics."""

from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from flyff_bot.constants import DEFAULT_CLIENT_PLAYER_STATS_PROFILES_PATH
from flyff_bot.features.navigation.live_position import (
    EXPECTED_PROCESS_NAME,
    ProcessMemoryApi,
    WindowsProcessMemoryApi,
    executable_sha256,
)
from flyff_bot.features.player_stats.models import (
    ClientPlayerStatsSnapshot,
    PlayerStatField,
    PlayerStatsReadError,
    PlayerStatsReadErrorCode,
    PlayerStatsSource,
)
from flyff_bot.features.player_stats.profiles import (
    ClientPlayerStatsProfile,
    load_client_player_stats_profiles,
)

DEFAULT_PLAYER_STATS_POLL_HERTZ = 10.0


def load_configured_profiles(
    profiles: Mapping[str, ClientPlayerStatsProfile] | None,
    profiles_path: Path,
) -> tuple[Mapping[str, ClientPlayerStatsProfile], str | None]:
    """Resolve explicit, operator-file, or empty profile registries safely."""

    if profiles is not None:
        return profiles, None
    if not profiles_path.is_file():
        return {}, None
    try:
        return load_client_player_stats_profiles(profiles_path), None
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {}, str(error)


class PlayerStatsProcessMemoryApi(ProcessMemoryApi, Protocol):
    """The process-memory boundary with foreground awareness."""

    def is_window_foreground(self, window_handle: int) -> bool: ...


class _PlayerStatsOpenError(OSError):
    def __init__(self, code: PlayerStatsReadErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True, slots=True)
class _PointerPlan:
    format: str
    size_bytes: int


_POINTER_PLANS = {
    4: _PointerPlan("<I", 4),
    8: _PointerPlan("<Q", 8),
}


class LivePlayerStatsReader:
    """Poll proven statistics through fixed bounded reads at a bounded cadence."""

    def __init__(
        self,
        window_handle: int | Callable[[], int | None],
        *,
        profiles: Mapping[str, ClientPlayerStatsProfile] | None = None,
        profiles_path: Path = Path(DEFAULT_CLIENT_PLAYER_STATS_PROFILES_PATH),
        api: PlayerStatsProcessMemoryApi | None = None,
        poll_hertz: float = DEFAULT_PLAYER_STATS_POLL_HERTZ,
        event_sink: Callable[[PlayerStatsReadError], None] | None = None,
    ) -> None:
        if poll_hertz <= 0.0:
            raise ValueError("Player-stats poll rate must be positive.")
        self._window_handle_provider = (
            window_handle if callable(window_handle) else lambda: window_handle
        )
        self._api = api
        self._profile_configuration_error: str | None = None
        self._profiles, self._profile_configuration_error = load_configured_profiles(
            profiles,
            profiles_path,
        )
        self._poll_interval_seconds = 1.0 / poll_hertz
        self._event_sink = event_sink
        self._window_handle: int | None = None
        self._handle: int | None = None
        self._module_base: int | None = None
        self._profile: ClientPlayerStatsProfile | None = None
        self._polled_at_seconds: float | None = None
        self._last_snapshot = _no_profile_snapshot()
        self._last_valid_field_names: tuple[str, ...] = ()
        self._last_error_code: PlayerStatsReadErrorCode | None = PlayerStatsReadErrorCode.NO_PROFILE
        self._lock = RLock()

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def poll(self, at_seconds: float) -> ClientPlayerStatsSnapshot:
        """Return the latest immutable snapshot or an explicit typed diagnostic."""

        with self._lock:
            if (
                self._polled_at_seconds is not None
                and at_seconds - self._polled_at_seconds < self._poll_interval_seconds
            ):
                return self._last_snapshot
            self._polled_at_seconds = at_seconds
            if self._profile_configuration_error is not None:
                self._fail(
                    PlayerStatsReadErrorCode.INVALID_PROFILE_CONFIGURATION,
                    self._profile_configuration_error,
                )
                return self._last_snapshot
            if not self._profiles:
                self._fail(
                    PlayerStatsReadErrorCode.NO_PROFILE,
                    "No verified player-stats client profile is configured.",
                )
                return self._last_snapshot
            try:
                window_handle = self._window_handle_provider()
                if window_handle is None or window_handle == 0:
                    raise _PlayerStatsOpenError(
                        PlayerStatsReadErrorCode.PROCESS_UNAVAILABLE,
                        "No game window is available.",
                    )
                api = self._api_or_raise()
                if not api.is_window_foreground(window_handle):
                    raise _PlayerStatsOpenError(
                        PlayerStatsReadErrorCode.WINDOW_NOT_FOREGROUND,
                        "The game window is not foregrounded.",
                    )
                if self._window_handle != window_handle:
                    self.close()
                    self._window_handle = window_handle
                handle, module_base, profile = self._ensure_open(window_handle)
                fields = self._read_fields(api, handle, module_base, profile)
                self._last_snapshot = ClientPlayerStatsSnapshot(
                    PlayerStatsSource.CLIENT_MEMORY,
                    sampled_at_seconds=at_seconds,
                    client_sha256=profile.sha256,
                    fields=tuple(
                        PlayerStatField(
                            name=field.name,
                            value=float(fields[field.name]),
                            is_unknown=field.is_unknown,
                        )
                        for field in profile.fields
                    ),
                )
                self._last_error_code = None
                self._last_valid_field_names = tuple(field.name for field in profile.fields)
            except _PlayerStatsOpenError as error:
                self._fail(error.code, str(error))
            except _InvalidPlayerPointer as error:
                self._fail(PlayerStatsReadErrorCode.INVALID_POINTER, str(error))
            except (_MalformedStatsRead, ValueError) as error:
                self._fail(PlayerStatsReadErrorCode.MALFORMED_READ, str(error))
            except (OSError, struct.error) as error:
                self._fail(PlayerStatsReadErrorCode.HANDLE_LOST, str(error))
            return self._last_snapshot

    def close(self) -> None:
        """Release the read-only handle; repeated calls are safe."""

        with self._lock:
            if self._handle is not None:
                self._api_or_raise().close(self._handle)
            self._handle = None
            self._module_base = None
            self._profile = None

    def _api_or_raise(self) -> PlayerStatsProcessMemoryApi:
        if self._api is None:
            try:
                self._api = WindowsProcessMemoryApi()
            except OSError as error:
                raise _PlayerStatsOpenError(
                    PlayerStatsReadErrorCode.UNSUPPORTED_PLATFORM,
                    str(error),
                ) from error
        return self._api

    def _ensure_open(self, window_handle: int) -> tuple[int, int, ClientPlayerStatsProfile]:
        """Return the open handle, module base, and profile, opening the process on demand.

        Returning the triple keeps the read path from re-narrowing three optional attributes
        that only ever exist together.
        """

        if self._handle is not None and self._module_base is not None and self._profile is not None:
            return self._handle, self._module_base, self._profile
        api = self._api_or_raise()
        try:
            process_id = api.process_id_for_window(window_handle)
            handle = api.open_read_process(process_id)
        except OSError as error:
            raise _PlayerStatsOpenError(
                PlayerStatsReadErrorCode.PROCESS_UNAVAILABLE,
                str(error),
            ) from error
        try:
            executable = api.executable_path(handle)
            if executable.name.casefold() != EXPECTED_PROCESS_NAME:
                raise _PlayerStatsOpenError(
                    PlayerStatsReadErrorCode.WRONG_PROCESS,
                    f"Expected {EXPECTED_PROCESS_NAME}, got {executable.name}.",
                )
            digest = executable_sha256(executable)
            profile = self._profiles.get(digest)
            if profile is None:
                raise _PlayerStatsOpenError(
                    PlayerStatsReadErrorCode.UNSUPPORTED_BUILD,
                    f"No verified stats profile exists for SHA-256 {digest} at {executable}.",
                )
            module_base = api.main_module_base(process_id)
        except (OSError, _PlayerStatsOpenError) as error:
            api.close(handle)
            if isinstance(error, _PlayerStatsOpenError):
                raise
            raise _PlayerStatsOpenError(
                PlayerStatsReadErrorCode.PROCESS_UNAVAILABLE,
                str(error),
            ) from error
        self._handle = handle
        self._module_base = module_base
        self._profile = profile
        return handle, module_base, profile

    def _read_fields(
        self,
        api: PlayerStatsProcessMemoryApi,
        handle: int,
        module_base: int,
        profile: ClientPlayerStatsProfile,
    ) -> dict[str, float]:
        pointer_plan = _POINTER_PLANS[profile.pointer_size_bytes]
        pointer_address = module_base + profile.player_pointer_rva
        pointer_bytes = api.read(handle, pointer_address, pointer_plan.size_bytes)
        if len(pointer_bytes) != pointer_plan.size_bytes:
            raise _MalformedStatsRead("The player pointer read was incomplete.")
        player_address = int(struct.unpack(pointer_plan.format, pointer_bytes)[0])
        if player_address <= 0:
            raise _InvalidPlayerPointer("The player pointer is null.")
        payload = api.read(
            handle,
            player_address + profile.read_start_offset,
            profile.read_size_bytes,
        )
        return {
            name: float(value)
            for name, value in profile.decode(payload).items()
            if isinstance(value, float)
        }

    def _fail(self, code: PlayerStatsReadErrorCode, detail: str) -> None:
        error = PlayerStatsReadError(code, detail)
        unavailable_names = self._last_valid_field_names
        self.close()
        self._last_snapshot = ClientPlayerStatsSnapshot(
            PlayerStatsSource.UNAVAILABLE,
            error=error,
            unavailable_field_names=unavailable_names,
        )
        if code is self._last_error_code:
            return
        self._last_error_code = code
        if self._event_sink is not None:
            self._event_sink(error)


class _MalformedStatsRead(ValueError):
    pass


class _InvalidPlayerPointer(ValueError):
    pass


def _fake_test_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _no_profile_snapshot() -> ClientPlayerStatsSnapshot:
    return ClientPlayerStatsSnapshot(
        PlayerStatsSource.UNAVAILABLE,
        error=PlayerStatsReadError(
            PlayerStatsReadErrorCode.NO_PROFILE,
            "No verified player-stat profiles are configured.",
        ),
    )
