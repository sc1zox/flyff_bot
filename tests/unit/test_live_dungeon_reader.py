"""Fingerprinted read-only dungeon cooldown reader tests (US-063)."""

from __future__ import annotations

import hashlib
import json
import struct
import time
from pathlib import Path
from unittest.mock import patch

from flyff_bot.features.dungeons.live_reader import (
    DungeonReadStatus,
    LiveDungeonCooldownReader,
)
from flyff_bot.features.dungeons.models import DungeonDefinition, DungeonStatus, format_cooldown
from flyff_bot.features.dungeons.profiles import ClientDungeonProfile
from flyff_bot.features.navigation.live_position import (
    PROCESS_QUERY_LIMITED_INFORMATION,
    PROCESS_VM_READ,
)

WINDOW_HANDLE = 42
PROCESS_ID = 1337
PROCESS_HANDLE = 99
MODULE_BASE = 0x140000000
ARRAY_ADDRESS = 0x220000000
POINTER_RVA = 0xB7C908
RECORD_SIZE = 32


class FakeDungeonMemoryApi:
    def __init__(self, executable: Path) -> None:
        self.executable = executable
        self.reads: list[tuple[int, int]] = []
        self.closed: list[int] = []
        self.open_count = 0
        self.executable_hash_calls = 0
        self.module_base_calls = 0
        self.foreground = True
        self.fail_open = False
        self.short_pointer = False
        self.null_pointer = False

    def process_id_for_window(self, window_handle: int) -> int:
        assert window_handle == WINDOW_HANDLE
        return PROCESS_ID

    def is_window_foreground(self, window_handle: int) -> bool:
        assert window_handle == WINDOW_HANDLE
        return self.foreground

    def open_read_process(self, process_id: int) -> int:
        assert process_id == PROCESS_ID
        self.open_count += 1
        if self.fail_open:
            raise OSError("denied")
        return PROCESS_HANDLE

    def executable_path(self, process_handle: int) -> Path:
        assert process_handle == PROCESS_HANDLE
        return self.executable

    def main_module_base(self, process_id: int) -> int:
        assert process_id == PROCESS_ID
        self.module_base_calls += 1
        return MODULE_BASE

    def read(self, process_handle: int, address: int, size: int) -> bytes:
        assert process_handle == PROCESS_HANDLE
        self.reads.append((address, size))
        if address == MODULE_BASE + POINTER_RVA:
            if self.null_pointer:
                return b"\x00" * size
            payload = ARRAY_ADDRESS.to_bytes(size, "little")
            return payload[:-1] if self.short_pointer else payload
        now = time.monotonic()
        records = bytearray(size)
        struct.pack_into("<I", records, 0, 101)
        struct.pack_into("<f", records, 16, now + 3661.5)
        struct.pack_into("<I", records, 24, 3)
        struct.pack_into("<I", records, 28, 2)
        struct.pack_into("<I", records, RECORD_SIZE, 102)
        struct.pack_into("<I", records, RECORD_SIZE + 28, 4)
        struct.pack_into("<I", records, RECORD_SIZE + 24, 4)
        struct.pack_into("<I", records, RECORD_SIZE * 2, 103)
        struct.pack_into("<f", records, RECORD_SIZE * 2 + 16, now - 10.0)
        struct.pack_into("<I", records, RECORD_SIZE * 3, 104)
        return bytes(records)

    def close(self, process_handle: int) -> None:
        self.closed.append(process_handle)


def _definitions() -> dict[int, DungeonDefinition]:
    return {
        dungeon_id: DungeonDefinition(
            dungeon_id,
            f"Dungeon {dungeon_id}",
            60,
            100,
            3600,
        )
        for dungeon_id in (101, 102, 103)
    }


def test_reader_uses_only_read_process_rights() -> None:
    assert PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ == 0x1010


def _reader(
    api: FakeDungeonMemoryApi,
) -> tuple[LiveDungeonCooldownReader, ClientDungeonProfile]:
    executable = api.executable
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    profile = ClientDungeonProfile(
        digest,
        runtime_state_pointer_rva=POINTER_RVA,
        pointer_size_bytes=8,
        record_size_bytes=RECORD_SIZE,
        record_count=4,
        cooldown_end_timestamp_offset=16,
        entries_used_offset=28,
        daily_entry_limit_offset=24,
    )
    definitions = _definitions()
    return (
        LiveDungeonCooldownReader(WINDOW_HANDLE, definitions, api=api, profiles={digest: profile}),
        profile,
    )


def test_reader_reads_one_fixed_array_and_calculates_all_statuses(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"entropia dungeon build")
    api = FakeDungeonMemoryApi(executable)
    reader, profile = _reader(api)

    snapshots = reader.poll()

    assert [snapshot.status for snapshot in snapshots] == [
        DungeonStatus.ON_COOLDOWN,
        DungeonStatus.ENTRY_LIMIT_REACHED,
        DungeonStatus.READY,
    ]
    assert snapshots[0].definition.dungeon_id == 101
    remaining_seconds = round(snapshots[0].remaining_cooldown_seconds)
    assert remaining_seconds in {3661, 3662}
    assert format_cooldown(float(remaining_seconds)) in {"01:01:01", "01:01:02"}
    assert (snapshots[1].entries_used, snapshots[1].daily_entry_limit) == (4, 4)
    assert all(snapshot.diagnostic_code is None for snapshot in snapshots)
    assert api.reads == [
        (MODULE_BASE + POINTER_RVA, 8),
        (ARRAY_ADDRESS, profile.array_read_size_bytes),
    ]
    assert reader.is_open
    assert api.closed == []


def test_empty_profile_configuration_reports_unconfigured_without_memory_access(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"unused")
    api = FakeDungeonMemoryApi(executable)
    reader = LiveDungeonCooldownReader(WINDOW_HANDLE, _definitions(), api=api, profiles={})

    snapshots = reader.poll()

    assert len(snapshots) == 3
    assert all(snapshot.status is DungeonStatus.UNKNOWN for snapshot in snapshots)
    assert reader.last_diagnostic is not None
    assert reader.last_diagnostic.status is DungeonReadStatus.UNCONFIGURED_PROFILE
    assert api.reads == []


def test_missing_profile_file_is_reported_and_never_guesses_offsets(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"unused")
    api = FakeDungeonMemoryApi(executable)
    reader = LiveDungeonCooldownReader(
        WINDOW_HANDLE,
        _definitions(),
        api=api,
        profiles_path=tmp_path / "missing.json",
    )

    reader.poll()

    assert reader.last_diagnostic is not None
    assert reader.last_diagnostic.status is DungeonReadStatus.UNCONFIGURED_PROFILE
    assert "No such file" in reader.last_diagnostic.detail or "could not be read" in (
        reader.last_diagnostic.detail
    )
    assert api.reads == []


def test_process_open_failure_is_typed_and_closes_nothing(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"dungeon build")
    api = FakeDungeonMemoryApi(executable)
    api.fail_open = True
    reader, _profile = _reader(api)

    reader.poll()

    assert reader.last_diagnostic is not None
    assert reader.last_diagnostic.status is DungeonReadStatus.PROCESS_UNAVAILABLE
    assert api.reads == []
    assert api.closed == []


def test_background_client_is_rejected_without_memory_access(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"unused")
    api = FakeDungeonMemoryApi(executable)
    api.foreground = False
    reader, _profile = _reader(api)

    snapshots = reader.poll()

    assert len(snapshots) == 3
    assert all(snapshot.status is DungeonStatus.UNKNOWN for snapshot in snapshots)
    assert reader.last_diagnostic is not None
    assert reader.last_diagnostic.status is DungeonReadStatus.WINDOW_NOT_FOREGROUND
    assert "not foregrounded" in reader.last_diagnostic.detail
    assert api.open_count == 0
    assert api.reads == []
    assert api.closed == []


def test_verified_handle_and_module_base_are_cached_across_polls(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"dungeon cached build")
    api = FakeDungeonMemoryApi(executable)
    reader, _profile = _reader(api)
    original_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    hash_calls = 0

    def count_hash(_path: Path) -> str:
        nonlocal hash_calls
        hash_calls += 1
        return original_digest

    first_time = time.monotonic()

    with patch(
        "flyff_bot.features.dungeons.live_reader.executable_sha256",
        side_effect=count_hash,
    ):
        first = reader.poll(at_seconds=first_time)
        second = reader.poll(at_seconds=first_time + 10.0)

    assert [snapshot.status for snapshot in first] == [
        DungeonStatus.ON_COOLDOWN,
        DungeonStatus.ENTRY_LIMIT_REACHED,
        DungeonStatus.READY,
    ]
    assert second[1].entries_used == first[1].entries_used
    assert hash_calls == 1
    assert api.open_count == 1
    assert api.module_base_calls == 1
    assert api.closed == []


def test_malformed_runtime_pointer_closes_the_cached_handle(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"dungeon pointer build")
    api = FakeDungeonMemoryApi(executable)
    reader, _profile = _reader(api)
    assert reader.poll()
    assert reader.is_open

    api.short_pointer = True

    degraded = reader.poll(at_seconds=time.monotonic() + 10.0)

    assert len(degraded) == 3
    assert all(snapshot.status is DungeonStatus.UNKNOWN for snapshot in degraded)
    assert reader.last_diagnostic is not None
    assert reader.last_diagnostic.status is DungeonReadStatus.HANDLE_LOST
    assert not reader.is_open
    assert api.closed == [PROCESS_HANDLE]


def test_close_releases_an_open_handle_idempotently(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(b"dungeon close build")
    api = FakeDungeonMemoryApi(executable)
    reader, _profile = _reader(api)
    reader.poll()
    assert reader.is_open

    reader.close()
    reader.close()

    assert not reader.is_open
    assert api.closed == [PROCESS_HANDLE]


def test_client_dungeon_profiles_round_trip_normalizes_fingerprints(tmp_path: Path) -> None:
    from flyff_bot.features.dungeons.profiles import load_client_dungeon_profiles

    path = tmp_path / "profiles.json"
    digest = "a" * 64
    path.write_text(
        json.dumps(
            [
                {
                    "sha256": digest.upper(),
                    "runtime_state_pointer_rva": POINTER_RVA,
                    "pointer_size_bytes": 8,
                }
            ]
        ),
        encoding="utf-8",
    )

    profile = load_client_dungeon_profiles(path)[digest]

    assert profile.sha256 == digest
    assert profile.runtime_state_pointer_rva == POINTER_RVA
