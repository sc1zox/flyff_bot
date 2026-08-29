"""Fingerprint-bound, read-only extraction of live client dungeon cooldowns."""

from __future__ import annotations

import struct
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from flyff_bot.constants import DEFAULT_CLIENT_DUNGEON_PROFILES_PATH
from flyff_bot.features.dungeons.models import (
    UNKNOWN_DUNGEON_ID,
    DungeonDefinition,
    DungeonRuntimeState,
    DungeonStateSnapshot,
    DungeonStatus,
)
from flyff_bot.features.dungeons.profiles import (
    BeginEndDungeonSpan,
    ClientDungeonProfile,
    FixedDungeonArray,
    load_client_dungeon_profiles,
)
from flyff_bot.features.navigation.live_position import (
    EXPECTED_PROCESS_NAME,
    ProcessMemoryApi,
    executable_sha256,
)

DEFAULT_DUNGEON_POLL_HERTZ = 1.0
SECONDS_PER_DAY = 86_400.0
UINT32_SIZE_BYTES = 4
UINT32_FORMAT = "<I"
FLOAT32_FORMAT = "<f"


class DungeonReadStatus(StrEnum):
    """Typed reason a live dungeon poll could not produce authoritative state."""

    UNCONFIGURED_PROFILE = "unconfigured_profile"
    WINDOW_NOT_FOREGROUND = "window_not_foreground"
    PROCESS_UNAVAILABLE = "process_unavailable"
    HANDLE_LOST = "handle_lost"


@dataclass(frozen=True, slots=True)
class DungeonReadDiagnostic:
    """One non-fatal live-read failure with its stable operator diagnostic code."""

    status: DungeonReadStatus
    detail: str = ""


class ForegroundProcessMemoryApi(ProcessMemoryApi, Protocol):
    """The read-only process boundary needed for foreground-gated polling."""

    def is_window_foreground(self, window_handle: int) -> bool: ...


class _DungeonOpenError(Exception):
    """Client attachment failed before a verified read-only read could occur."""

    def __init__(self, status: DungeonReadStatus, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class LiveDungeonCooldownReader:
    """Poll one exact client build's fixed cooldown array without scanning or writing."""

    def __init__(
        self,
        window_handle: int,
        definitions: Mapping[int, DungeonDefinition],
        *,
        api: ForegroundProcessMemoryApi | None = None,
        profiles: Mapping[str, ClientDungeonProfile] | None = None,
        profiles_path: Path = Path(DEFAULT_CLIENT_DUNGEON_PROFILES_PATH),
        poll_hertz: float = DEFAULT_DUNGEON_POLL_HERTZ,
    ) -> None:
        if poll_hertz <= 0.0:
            raise ValueError("Live dungeon poll rate must be positive.")
        if not all(definition.dungeon_id in definitions for definition in definitions.values()):
            raise ValueError("Dungeon reader definitions must be keyed by their own IDs.")
        self._window_handle = window_handle
        self._definitions = dict(definitions)
        self._api = api
        self._profiles: Mapping[str, ClientDungeonProfile] = {} if profiles is None else profiles
        self._profiles_path = profiles_path
        self._profile_configuration_error: str | None = None
        if profiles is None:
            try:
                self._profiles = load_client_dungeon_profiles(profiles_path)
            except ValueError as error:
                self._profile_configuration_error = str(error)
        self._poll_interval_seconds = 1.0 / poll_hertz
        self._polled_at_seconds: float | None = None
        self._handle: int | None = None
        self._module_base: int | None = None
        self._profile: ClientDungeonProfile | None = None
        self._last_snapshot: tuple[DungeonStateSnapshot, ...] | None = None
        self._last_diagnostic: DungeonReadDiagnostic | None = None

    @property
    def last_diagnostic(self) -> DungeonReadDiagnostic | None:
        """Return why the most recent poll degraded to unknown rows, if it did."""

        return self._last_diagnostic

    @property
    def is_open(self) -> bool:
        """Return whether a verified read-only client session remains attached."""

        return self._handle is not None

    def poll(self, at_seconds: float | None = None) -> tuple[DungeonStateSnapshot, ...]:
        """Return immutable state for every extracted definition at a bounded rate."""

        monotonic_seconds = time.monotonic() if at_seconds is None else at_seconds
        if (
            self._last_snapshot is not None
            and self._polled_at_seconds is not None
            and monotonic_seconds - self._polled_at_seconds < self._poll_interval_seconds
        ):
            return self._last_snapshot
        self._polled_at_seconds = monotonic_seconds
        states, diagnostic = self._read_states()
        snapshots = tuple(
            self._snapshot(definition, states.get(definition.dungeon_id))
            for definition in self._definitions.values()
        )
        self._last_snapshot = snapshots
        self._last_diagnostic = diagnostic
        return snapshots

    def close(self) -> None:
        """Release the read-only process handle. Repeated close calls are safe."""

        self._close_handle()
        self._last_snapshot = None
        self._polled_at_seconds = None

    def reload_profiles(self, _profile_update: object | None = None) -> None:
        """Drop every cached address and reload the configured registry fail-closed."""

        self.close()
        try:
            self._profiles = load_client_dungeon_profiles(self._profiles_path)
            self._profile_configuration_error = None
        except ValueError as error:
            self._profiles = {}
            self._profile_configuration_error = str(error)
        self._last_diagnostic = DungeonReadDiagnostic(DungeonReadStatus.UNCONFIGURED_PROFILE)

    def _close_handle(self) -> None:
        # A handle only ever exists once the platform API resolved, so an absent API here
        # means there is nothing left to release.
        if self._handle is not None and self._api is not None:
            self._api.close(self._handle)
        self._handle = None
        self._module_base = None
        self._profile = None

    def _read_states(
        self,
    ) -> tuple[dict[int, DungeonRuntimeState], DungeonReadDiagnostic | None]:
        if self._profile_configuration_error is not None:
            return {}, DungeonReadDiagnostic(
                DungeonReadStatus.UNCONFIGURED_PROFILE,
                self._profile_configuration_error,
            )
        if not self._profiles:
            return {}, DungeonReadDiagnostic(DungeonReadStatus.UNCONFIGURED_PROFILE)
        api = self._api_or_raise()
        if api is None:
            return {}, DungeonReadDiagnostic(
                DungeonReadStatus.PROCESS_UNAVAILABLE,
                "Live dungeon reading is only available on Windows.",
            )
        if not api.is_window_foreground(self._window_handle):
            return {}, DungeonReadDiagnostic(
                DungeonReadStatus.WINDOW_NOT_FOREGROUND,
                "The game window is not foregrounded.",
            )
        try:
            handle, module_base, profile = self._ensure_open(api)
            pointer_bytes = api.read(
                handle,
                module_base + profile.runtime_state_pointer_rva,
                profile.pointer_size_bytes,
            )
            if len(pointer_bytes) != profile.pointer_size_bytes:
                self._close_handle()
                return {}, DungeonReadDiagnostic(
                    DungeonReadStatus.HANDLE_LOST,
                    "The runtime-state pointer read was incomplete.",
                )
            pointer_format = "<I" if profile.pointer_size_bytes == UINT32_SIZE_BYTES else "<Q"
            array_address = int(struct.unpack(pointer_format, pointer_bytes)[0])
            if array_address == 0:
                self._close_handle()
                return {}, DungeonReadDiagnostic(
                    DungeonReadStatus.HANDLE_LOST,
                    "The runtime-state pointer is null.",
                )
            payload, record_count = self._read_container_payload(
                api,
                handle,
                array_address,
                profile,
            )
        except (OSError, ValueError, struct.error) as error:
            self._close_handle()
            return {}, DungeonReadDiagnostic(DungeonReadStatus.HANDLE_LOST, str(error))
        except _DungeonOpenError as error:
            return {}, DungeonReadDiagnostic(error.status, error.detail)
        return self._decode(profile, payload, record_count), None

    @staticmethod
    def _read_container_payload(
        api: ForegroundProcessMemoryApi,
        handle: int,
        manager_address: int,
        profile: ClientDungeonProfile,
    ) -> tuple[bytes, int]:
        container = profile.container
        if isinstance(container, FixedDungeonArray):
            read_size = container.record_size_bytes * container.record_count
            payload = api.read(handle, manager_address + container.records_offset, read_size)
            if len(payload) != read_size:
                raise ValueError("The fixed dungeon-array read was incomplete.")
            return payload, container.record_count

        if not isinstance(container, BeginEndDungeonSpan):
            raise TypeError("Unsupported dungeon container profile.")
        header_size = (
            max(
                container.begin_pointer_offset,
                container.end_pointer_offset,
            )
            + profile.pointer_size_bytes
        )
        header = api.read(handle, manager_address + container.container_offset, header_size)
        if len(header) != header_size:
            raise ValueError("The dungeon span header read was incomplete.")
        pointer_format = "<I" if profile.pointer_size_bytes == UINT32_SIZE_BYTES else "<Q"
        begin = int(struct.unpack_from(pointer_format, header, container.begin_pointer_offset)[0])
        end = int(struct.unpack_from(pointer_format, header, container.end_pointer_offset)[0])
        if begin <= 0 or end < begin:
            raise ValueError("The dungeon span pointers are null or unordered.")
        span_size = end - begin
        if span_size % container.record_size_bytes:
            raise ValueError("The dungeon span size is not aligned to its proven record size.")
        record_count = span_size // container.record_size_bytes
        if record_count > container.maximum_record_count:
            raise ValueError("The dungeon span exceeds its statically proven record bound.")
        payload = api.read(handle, begin, span_size)
        if len(payload) != span_size:
            raise ValueError("The bounded dungeon span read was incomplete.")
        return payload, record_count

    def _ensure_open(
        self,
        api: ForegroundProcessMemoryApi,
    ) -> tuple[int, int, ClientDungeonProfile]:
        """Return the open handle, module base, and profile, opening the process on demand.

        Returning the triple keeps the read path from re-narrowing three optional attributes
        that only ever exist together.
        """

        if self._handle is not None and self._module_base is not None and self._profile is not None:
            return self._handle, self._module_base, self._profile
        try:
            process_id = api.process_id_for_window(self._window_handle)
            handle = api.open_read_process(process_id)
        except OSError as error:
            raise _DungeonOpenError(DungeonReadStatus.PROCESS_UNAVAILABLE, str(error)) from error
        try:
            executable = api.executable_path(handle)
            if executable.name.casefold() != EXPECTED_PROCESS_NAME:
                raise _DungeonOpenError(
                    DungeonReadStatus.PROCESS_UNAVAILABLE,
                    f"Expected {EXPECTED_PROCESS_NAME}, got {executable.name}.",
                )
            digest = executable_sha256(executable)
            profile = self._profiles.get(digest)
            if profile is None:
                raise _DungeonOpenError(
                    DungeonReadStatus.UNCONFIGURED_PROFILE,
                    f"No dungeon profile exists for SHA-256 {digest}.",
                )
            module_base = api.main_module_base(process_id)
        except (OSError, _DungeonOpenError) as error:
            api.close(handle)
            if isinstance(error, _DungeonOpenError):
                raise
            raise _DungeonOpenError(DungeonReadStatus.PROCESS_UNAVAILABLE, str(error)) from error
        self._handle = handle
        self._module_base = module_base
        self._profile = profile
        return handle, module_base, profile

    def _api_or_raise(self) -> ForegroundProcessMemoryApi | None:
        if self._api is None:
            from flyff_bot.features.navigation.live_position import WindowsProcessMemoryApi

            try:
                self._api = WindowsProcessMemoryApi()
            except OSError:
                return None
        return self._api

    def _decode(
        self,
        profile: ClientDungeonProfile,
        payload: bytes,
        record_count: int,
    ) -> dict[int, DungeonRuntimeState]:
        states: dict[int, DungeonRuntimeState] = {}
        fields = profile.fields
        record_size = profile.container.record_size_bytes
        for index in range(record_count):
            start = index * record_size
            record = payload[start : start + record_size]
            dungeon_id = int(struct.unpack_from(UINT32_FORMAT, record, fields.dungeon_id_offset)[0])
            if dungeon_id == UNKNOWN_DUNGEON_ID or dungeon_id not in self._definitions:
                continue
            if dungeon_id in states:
                raise ValueError("The dungeon container repeats a known dungeon ID.")
            raw_timestamp = struct.unpack_from(
                FLOAT32_FORMAT,
                record,
                fields.cooldown_end_timestamp_offset,
            )[0]
            entries_used = int(
                struct.unpack_from(UINT32_FORMAT, record, fields.entries_used_offset)[0]
            )
            daily_limit = int(
                struct.unpack_from(UINT32_FORMAT, record, fields.daily_entry_limit_offset)[0]
            )
            timestamp = float(raw_timestamp)
            now_seconds = time.monotonic()
            if timestamp <= 0.0 or timestamp > now_seconds + SECONDS_PER_DAY:
                timestamp_value: float | None = None
            else:
                timestamp_value = timestamp
            states[dungeon_id] = DungeonRuntimeState(
                dungeon_id=dungeon_id,
                cooldown_ends_at_monotonic_seconds=timestamp_value,
                entries_used=entries_used,
                daily_entry_limit=daily_limit,
            )
        return states

    def _snapshot(
        self,
        definition: DungeonDefinition,
        state: DungeonRuntimeState | None,
    ) -> DungeonStateSnapshot:
        diagnostic = self._last_diagnostic
        if state is None:
            return DungeonStateSnapshot(
                definition,
                DungeonStatus.UNKNOWN,
                diagnostic_code=diagnostic.status.value if diagnostic else None,
            )
        entries_used = state.entries_used
        daily_limit = state.daily_entry_limit
        limit_reached = (
            entries_used is not None
            and daily_limit is not None
            and daily_limit > 0
            and entries_used >= daily_limit
        )
        if limit_reached:
            return DungeonStateSnapshot(
                definition,
                DungeonStatus.ENTRY_LIMIT_REACHED,
                entries_used=entries_used,
                daily_entry_limit=daily_limit,
            )
        remaining = 0.0
        if state.cooldown_ends_at_monotonic_seconds is not None:
            remaining = max(0.0, state.cooldown_ends_at_monotonic_seconds - time.monotonic())
        status = DungeonStatus.ON_COOLDOWN if remaining > 0.0 else DungeonStatus.READY
        return DungeonStateSnapshot(
            definition,
            status,
            remaining_cooldown_seconds=remaining,
            entries_used=entries_used,
            daily_entry_limit=daily_limit,
        )
