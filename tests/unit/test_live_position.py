"""Coordinate-only ReadProcessMemory adapter tests (US-048)."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from flyff_bot.features.navigation.live_position import (
    DEFAULT_CLIENT_POSITION_PROFILES_FILE,
    POSITION_STRUCT_SIZE_BYTES,
    PROCESS_QUERY_LIMITED_INFORMATION,
    PROCESS_VM_READ,
    ClientPositionProfile,
    LivePositionReader,
    PositionReadError,
    PositionReadErrorCode,
    PositionSource,
    WorldPosition,
    load_client_position_profiles,
)

WINDOW_HANDLE = 42
PROCESS_ID = 1337
PROCESS_HANDLE = 99
MODULE_BASE = 0x140000000
PLAYER_ADDRESS = 0x220000000
PLAYER_POINTER_RVA = 0xB7C908
POSITION_OFFSET = 0x188


class FakeProcessMemoryApi:
    def __init__(self, executable: Path, profile: ClientPositionProfile) -> None:
        self.executable = executable
        self.profile = profile
        self.position = WorldPosition(120.5, 31.25, 840.75)
        self.reads: list[tuple[int, int]] = []
        self.closed: list[int] = []
        self.open_count = 0
        self.fail_read = False
        self.short_position = False

    def process_id_for_window(self, window_handle: int) -> int:
        assert window_handle == WINDOW_HANDLE
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
        if address == MODULE_BASE + self.profile.player_pointer_rva:
            return PLAYER_ADDRESS.to_bytes(self.profile.pointer_size_bytes, "little")
        assert address == PLAYER_ADDRESS + self.profile.position_offset
        payload = struct.pack("<3f", self.position.x, self.position.y, self.position.z)
        return payload[:-1] if self.short_position else payload

    def close(self, process_handle: int) -> None:
        self.closed.append(process_handle)


@pytest.fixture
def configured_reader(
    tmp_path: Path,
) -> tuple[LivePositionReader, FakeProcessMemoryApi, list[PositionReadError]]:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"entropia test build")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    profile = ClientPositionProfile(digest, PLAYER_POINTER_RVA, 8, POSITION_OFFSET)
    api = FakeProcessMemoryApi(executable, profile)
    events: list[PositionReadError] = []
    reader = LivePositionReader(
        WINDOW_HANDLE,
        api=api,
        profiles={digest: profile},
        event_sink=events.append,
    )
    return reader, api, events


def test_reader_uses_only_read_process_rights() -> None:
    assert PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ == 0x1010


def test_committed_position_registry_contains_only_the_independently_proven_x64_build() -> None:
    profiles = load_client_position_profiles(DEFAULT_CLIENT_POSITION_PROFILES_FILE)

    assert set(profiles) == {"8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5"}
    assert profiles["8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5"] == (
        ClientPositionProfile(
            "8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5",
            player_pointer_rva=0xB7C908,
            pointer_size_bytes=8,
            position_offset=0x188,
        )
    )


def test_reader_follows_the_fingerprinted_player_pointer_to_exact_xyz_struct(
    configured_reader: tuple[LivePositionReader, FakeProcessMemoryApi, list[PositionReadError]],
) -> None:
    reader, api, events = configured_reader

    reading = reader.poll(1.0)

    assert reading.source is PositionSource.LIVE
    assert reading.position == api.position
    assert events == []
    assert api.reads == [
        (MODULE_BASE + PLAYER_POINTER_RVA, 8),
        (PLAYER_ADDRESS + POSITION_OFFSET, POSITION_STRUCT_SIZE_BYTES),
    ]


def test_default_poll_rate_reuses_the_last_reading_until_ten_hertz_interval(
    configured_reader: tuple[LivePositionReader, FakeProcessMemoryApi, list[PositionReadError]],
) -> None:
    reader, api, _events = configured_reader

    first = reader.poll(1.0)
    throttled = reader.poll(1.09)
    fresh = reader.poll(1.10)

    assert first is throttled
    assert fresh.source is PositionSource.LIVE
    assert len(api.reads) == 4


def test_lost_handle_emits_one_error_transition_and_falls_back(
    configured_reader: tuple[LivePositionReader, FakeProcessMemoryApi, list[PositionReadError]],
) -> None:
    reader, api, events = configured_reader
    reader.poll(1.0)
    api.fail_read = True

    first = reader.poll(1.1)
    second = reader.poll(1.21)

    assert first.source is PositionSource.UNAVAILABLE
    assert first.error is not None
    assert first.error.code is PositionReadErrorCode.HANDLE_LOST
    assert second.source is PositionSource.UNAVAILABLE
    assert [event.code for event in events] == [PositionReadErrorCode.HANDLE_LOST]
    assert api.closed == [PROCESS_HANDLE, PROCESS_HANDLE]


def test_short_coordinate_read_is_malformed_and_closes_handle(
    configured_reader: tuple[LivePositionReader, FakeProcessMemoryApi, list[PositionReadError]],
) -> None:
    reader, api, events = configured_reader
    api.short_position = True

    reading = reader.poll(0.0)

    assert reading.source is PositionSource.UNAVAILABLE
    assert events[0].code is PositionReadErrorCode.MALFORMED_READ
    assert api.closed == [PROCESS_HANDLE]


def test_nonfinite_coordinate_is_rejected(
    configured_reader: tuple[LivePositionReader, FakeProcessMemoryApi, list[PositionReadError]],
) -> None:
    reader, api, events = configured_reader
    api.position = WorldPosition(float("nan"), 0.0, 0.0)

    reading = reader.poll(0.0)

    assert reading.source is PositionSource.UNAVAILABLE
    assert events[0].code is PositionReadErrorCode.MALFORMED_READ


def test_unknown_build_falls_back_without_reading_memory(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"unknown")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    dummy = ClientPositionProfile("0" * 64, PLAYER_POINTER_RVA, 8, POSITION_OFFSET)
    api = FakeProcessMemoryApi(executable, dummy)

    reading = LivePositionReader(WINDOW_HANDLE, api=api, profiles={}).poll(0.0)

    assert reading.source is PositionSource.UNAVAILABLE
    assert reading.error is not None
    assert reading.error.code is PositionReadErrorCode.UNSUPPORTED_BUILD
    assert api.reads == []
    assert api.closed == [PROCESS_HANDLE]
    assert digest in reading.error.detail
    assert str(executable) in reading.error.detail


def test_external_client_profile_file_is_loaded_with_an_explicit_position_offset(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"profile-configured-build")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    profiles_path = tmp_path / "client_profiles.json"
    profiles_path.write_text(
        json.dumps(
            [
                {
                    "sha256": digest.upper(),
                    "player_pointer_rva": PLAYER_POINTER_RVA,
                    "pointer_size_bytes": 8,
                    "position_offset": POSITION_OFFSET,
                }
            ]
        ),
        encoding="utf-8",
    )
    profile = ClientPositionProfile(digest, PLAYER_POINTER_RVA, 8, POSITION_OFFSET)
    api = FakeProcessMemoryApi(executable, profile)

    reading = LivePositionReader(WINDOW_HANDLE, api=api, profiles_path=profiles_path).poll(0.0)

    assert load_client_position_profiles(profiles_path)[digest].position_offset == POSITION_OFFSET
    assert reading.source is PositionSource.LIVE
    assert reading.position == api.position


def test_position_profile_requires_an_explicit_position_offset(tmp_path: Path) -> None:
    profiles_path = tmp_path / "client_profiles.json"
    profiles_path.write_text(
        json.dumps(
            [
                {
                    "sha256": "a" * 64,
                    "player_pointer_rva": PLAYER_POINTER_RVA,
                    "pointer_size_bytes": 8,
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="position_offset"):
        load_client_position_profiles(profiles_path)


def test_missing_profile_file_leaves_the_reader_unconfigured(tmp_path: Path) -> None:
    """No embedded fallback: a GPS profile only ever comes from a generated file."""

    reader = LivePositionReader(WINDOW_HANDLE, profiles_path=tmp_path / "missing.json")

    assert reader._profiles == {}
    assert reader._profile_configuration_error is None


def test_invalid_profile_file_is_an_explicit_gps_error(tmp_path: Path) -> None:
    profiles_path = tmp_path / "client_profiles.json"
    profiles_path.write_text("{}", encoding="utf-8")
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"invalid-config")
    profile = ClientPositionProfile("0" * 64, PLAYER_POINTER_RVA, 8, POSITION_OFFSET)
    api = FakeProcessMemoryApi(executable, profile)

    reading = LivePositionReader(WINDOW_HANDLE, api=api, profiles_path=profiles_path).poll(0.0)

    assert reading.source is PositionSource.UNAVAILABLE
    assert reading.error is not None
    assert reading.error.code is PositionReadErrorCode.INVALID_PROFILE_CONFIGURATION
    assert api.open_count == 0


def test_explicit_close_is_idempotent(
    configured_reader: tuple[LivePositionReader, FakeProcessMemoryApi, list[PositionReadError]],
) -> None:
    reader, api, _events = configured_reader
    reader.poll(0.0)

    reader.close()
    reader.close()

    assert api.closed == [PROCESS_HANDLE]


def test_reader_recovers_on_a_later_successful_poll(
    configured_reader: tuple[LivePositionReader, FakeProcessMemoryApi, list[PositionReadError]],
) -> None:
    reader, api, events = configured_reader
    api.fail_read = True
    assert reader.poll(0.0).source is PositionSource.UNAVAILABLE

    api.fail_read = False
    recovered = reader.poll(0.1)

    assert recovered.source is PositionSource.LIVE
    assert recovered.position == api.position
    assert [event.code for event in events] == [PositionReadErrorCode.HANDLE_LOST]


def test_module_entry_structure_matches_win32_layout() -> None:
    import ctypes
    import struct

    from flyff_bot.features.navigation.live_position import _ModuleEntry32W

    entry = _ModuleEntry32W()
    # 64-bit Windows: 1080 bytes; 32-bit Windows: 568 bytes
    expected_size = 1080 if struct.calcsize("P") == 8 else 568
    assert ctypes.sizeof(entry) == expected_size
