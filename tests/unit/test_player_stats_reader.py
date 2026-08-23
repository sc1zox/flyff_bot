"""Synthetic tests for exact-profile player-stat memory reads."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from flyff_bot.features.navigation.live_position import EXPECTED_PROCESS_NAME
from flyff_bot.features.player_stats.models import (
    PlayerStatField,
    PlayerStatsReadError,
    PlayerStatsReadErrorCode,
    PlayerStatsSource,
)
from flyff_bot.features.player_stats.profiles import (
    ClientPlayerStatsProfile,
    PlayerStatFieldProfile,
    PlayerStatType,
    load_client_player_stats_profiles,
)
from flyff_bot.features.player_stats.reader import LivePlayerStatsReader

WINDOW_HANDLE = 42
PROCESS_ID = 1337
PROCESS_HANDLE = 99
MODULE_BASE = 0x140000000
PLAYER_ADDRESS = 0x220000000
PLAYER_POINTER_RVA = 0xB7C908

_FIELDS = (
    PlayerStatFieldProfile("hp", 0, PlayerStatType.F32, 0.0, 100.0),
    PlayerStatFieldProfile("mp", 4, PlayerStatType.F32, 0.0, 100.0),
)

_VALID_PAYLOAD = struct.pack("<2f", 70.0, 70.0)


def _executable_digest() -> str:
    return hashlib.sha256(b"synthetic entropia client").hexdigest()


def _profile() -> ClientPlayerStatsProfile:
    return ClientPlayerStatsProfile(
        sha256=_executable_digest(),
        player_pointer_rva=PLAYER_POINTER_RVA,
        pointer_size_bytes=8,
        fields=_FIELDS,
    )


class FakeStatsMemoryApi:
    def __init__(self) -> None:
        self.profile_sha256 = _executable_digest()
        executable_path = Path(__file__).with_name(EXPECTED_PROCESS_NAME)
        executable_path.write_bytes(b"synthetic entropia client")
        self.executable = executable_path
        self.foreground = True
        self.pointer_size = 8
        self.fail_read = False
        self.short_payload = False
        self.nonfinite_payload = True
        self.null_pointer = False
        self.reads: list[tuple[int, int]] = []
        self.closed: list[int] = []

    def process_id_for_window(self, window_handle: int) -> int:
        return PROCESS_ID + window_handle - WINDOW_HANDLE

    def open_read_process(self, process_id: int) -> int:
        return PROCESS_HANDLE + process_id - PROCESS_ID

    def executable_path(self, process_handle: int) -> Path:
        return self.executable

    def main_module_base(self, process_id: int) -> int:
        return MODULE_BASE

    def is_window_foreground(self, window_handle: int) -> bool:
        return self.foreground

    def read(self, process_handle: int, address: int, size: int) -> bytes:
        self.reads.append((address, size))
        if self.fail_read:
            raise OSError("lost")
        if address == MODULE_BASE + PLAYER_POINTER_RVA:
            if self.null_pointer:
                return b"\0" * self.pointer_size
            return PLAYER_ADDRESS.to_bytes(self.pointer_size, "little")
        payload = struct.pack("<2f", 70.0, math.nan) if self.nonfinite_payload else _VALID_PAYLOAD
        if self.short_payload:
            return payload[:-1]
        return payload

    def close(self, process_handle: int) -> None:
        self.closed.append(process_handle)


@pytest.fixture
def profile() -> ClientPlayerStatsProfile:
    return _profile()


def test_profile_rejects_overlapping_and_out_of_order_ranges() -> None:
    with pytest.raises(ValueError, match="overlaps"):
        ClientPlayerStatsProfile(
            sha256=_executable_digest(),
            player_pointer_rva=1,
            pointer_size_bytes=4,
            fields=(
                PlayerStatFieldProfile("hp", 4, PlayerStatType.F32),
                PlayerStatFieldProfile("mp", 4, PlayerStatType.F32),
            ),
        )


def test_profile_loader_rejects_duplicates_before_a_handle_opens(tmp_path: Path) -> None:
    digest = _executable_digest()
    payload = [
        {
            "sha256": digest,
            "player_pointer_rva": PLAYER_POINTER_RVA,
            "pointer_size_bytes": 8,
            "fields": [
                {
                    "name": "hp",
                    "offset": 0,
                    "type": "f32",
                    "minimum": 0,
                    "maximum": 100,
                }
            ],
        },
        {
            "sha256": digest.upper(),
            "player_pointer_rva": PLAYER_POINTER_RVA,
            "pointer_size_bytes": 8,
            "fields": [
                {
                    "name": "mp",
                    "offset": 0,
                    "type": "f32",
                    "minimum": 0,
                    "maximum": 100,
                }
            ],
        },
    ]
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="repeat"):
        load_client_player_stats_profiles(path)


def test_no_configured_profile_is_typed_without_opening_the_process() -> None:
    api = FakeStatsMemoryApi()

    snapshot = LivePlayerStatsReader(WINDOW_HANDLE, profiles={}, api=api).poll(0.0)

    assert snapshot.source is PlayerStatsSource.UNAVAILABLE
    assert snapshot.error is not None
    assert snapshot.error.code is PlayerStatsReadErrorCode.NO_PROFILE
    assert api.open_count == 0 if hasattr(api, "open_count") else api.closed == []


def test_background_client_is_rejected_without_reading_memory() -> None:
    api = FakeStatsMemoryApi()
    api.foreground = False

    snapshot = LivePlayerStatsReader(
        WINDOW_HANDLE,
        profiles={_executable_digest(): _profile()},
        api=api,
    ).poll(0.0)

    assert snapshot.error is not None
    assert snapshot.error.code is PlayerStatsReadErrorCode.WINDOW_NOT_FOREGROUND
    assert api.reads == []
    assert api.closed == []


def test_nonfinite_value_is_rejected_without_field_markers(
    profile: ClientPlayerStatsProfile,
) -> None:
    api = FakeStatsMemoryApi()
    api.nonfinite_payload = True
    reader = LivePlayerStatsReader(
        WINDOW_HANDLE,
        profiles={profile.sha256: profile},
        api=api,
    )

    snapshot = reader.poll(0.0)

    assert snapshot.source is PlayerStatsSource.UNAVAILABLE
    assert snapshot.unavailable_field_names == ()
    assert api.closed == [PROCESS_HANDLE]


def test_short_structure_read_uses_the_malformed_read_code(
    profile: ClientPlayerStatsProfile,
) -> None:
    api = FakeStatsMemoryApi()
    api.nonfinite_payload = False
    api.short_payload = True
    reader = LivePlayerStatsReader(
        WINDOW_HANDLE,
        profiles={profile.sha256: profile},
        api=api,
    )

    snapshot = reader.poll(0.0)

    assert snapshot.source is PlayerStatsSource.UNAVAILABLE
    assert snapshot.error is not None
    assert snapshot.error.code is PlayerStatsReadErrorCode.MALFORMED_READ
    assert api.closed == [PROCESS_HANDLE]


def test_null_player_pointer_uses_the_invalid_pointer_code(
    profile: ClientPlayerStatsProfile,
) -> None:
    api = FakeStatsMemoryApi()
    api.nonfinite_payload = False
    api.null_pointer = True
    events: list[PlayerStatsReadError] = []
    reader = LivePlayerStatsReader(
        WINDOW_HANDLE,
        profiles={profile.sha256: profile},
        api=api,
        event_sink=events.append,
    )

    snapshot = reader.poll(0.0)

    assert snapshot.error is not None
    assert snapshot.error.code is PlayerStatsReadErrorCode.INVALID_POINTER
    assert [event.code for event in events] == [PlayerStatsReadErrorCode.INVALID_POINTER]
    assert api.closed == [PROCESS_HANDLE]


def test_failed_fields_are_preserved_across_repeated_failures(
    profile: ClientPlayerStatsProfile,
) -> None:
    api = FakeStatsMemoryApi()
    api.nonfinite_payload = False
    reader = LivePlayerStatsReader(WINDOW_HANDLE, profiles={profile.sha256: profile}, api=api)
    valid = reader.poll(0.0)

    api.fail_read = True
    first_failure = reader.poll(0.11)
    second_failure = reader.poll(0.22)

    expected_names = tuple(field.name for field in valid.fields)
    assert first_failure.unavailable_field_names == expected_names
    assert second_failure.unavailable_field_names == expected_names


def test_profile_bounds_accept_negative_signed_values() -> None:
    profile = ClientPlayerStatsProfile(
        sha256=_executable_digest(),
        player_pointer_rva=PLAYER_POINTER_RVA,
        pointer_size_bytes=8,
        fields=(
            PlayerStatFieldProfile("alignment", 0, PlayerStatType.I32, -100.0, 100.0),
            PlayerStatFieldProfile("delta", 4, PlayerStatType.I32, -10.0, 10.0),
        ),
    )

    decoded = profile.decode(struct.pack("<2i", -25, -5))
    fields = tuple(PlayerStatField(name, value, False) for name, value in decoded.items())

    assert [field.value for field in fields] == [-25.0, -5.0]


def test_polling_is_throttled_and_recovery_emits_one_transition(
    profile: ClientPlayerStatsProfile,
) -> None:
    valid_fields = (
        PlayerStatFieldProfile("hp", 0, PlayerStatType.F32, 0.0, 100.0),
        PlayerStatFieldProfile("mp", 4, PlayerStatType.F32, 0.0, 100.0),
    )
    valid_profile = ClientPlayerStatsProfile(
        sha256=profile.sha256,
        player_pointer_rva=PLAYER_POINTER_RVA,
        pointer_size_bytes=8,
        fields=valid_fields,
    )
    api = FakeStatsMemoryApi()
    api.nonfinite_payload = False
    events: list[object] = []
    reader = LivePlayerStatsReader(
        WINDOW_HANDLE,
        profiles={valid_profile.sha256: valid_profile},
        api=api,
        event_sink=events.append,
    )
    first = reader.poll(0.0)
    throttled = reader.poll(0.05)

    assert first.source is PlayerStatsSource.CLIENT_MEMORY
    assert throttled is first
    assert len(api.reads) == 2

    api.fail_read = True
    failed = reader.poll(0.11)
    repeated_failure = reader.poll(0.12)

    assert failed.source is PlayerStatsSource.UNAVAILABLE
    assert repeated_failure.source is PlayerStatsSource.UNAVAILABLE
    assert len(events) == 1

    api.fail_read = False
    recovered = reader.poll(0.22)

    assert recovered.source is PlayerStatsSource.CLIENT_MEMORY


def test_window_change_closes_the_previous_read_only_handle(
    profile: ClientPlayerStatsProfile,
) -> None:
    api = FakeStatsMemoryApi()
    api.nonfinite_payload = False
    window_handles = iter((WINDOW_HANDLE, WINDOW_HANDLE + 1))
    reader = LivePlayerStatsReader(
        lambda: next(window_handles),
        profiles={profile.sha256: profile},
        api=api,
    )

    first = reader.poll(0.0)
    second = reader.poll(1.1)

    assert first.source is PlayerStatsSource.CLIENT_MEMORY
    assert second.source is PlayerStatsSource.CLIENT_MEMORY
    assert reader.is_open
    assert PROCESS_HANDLE in api.closed
    assert len(api.reads) == 4
    reader.close()
    assert api.closed[-1] == PROCESS_HANDLE + 1


def test_malformed_profile_is_typed_without_opening_a_handle(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text("{}", encoding="utf-8")
    api = FakeStatsMemoryApi()

    snapshot = LivePlayerStatsReader(
        WINDOW_HANDLE,
        profiles_path=profiles_path,
        api=api,
    ).poll(0.0)

    assert snapshot.source is PlayerStatsSource.UNAVAILABLE
    assert snapshot.error is not None
    assert snapshot.error.code is PlayerStatsReadErrorCode.INVALID_PROFILE_CONFIGURATION
    assert api.reads == []
    assert api.closed == []


def test_snapshot_is_immutable(profile: ClientPlayerStatsProfile) -> None:
    valid_fields = (
        PlayerStatFieldProfile("hp", 0, PlayerStatType.F32, 0.0, 100.0),
        PlayerStatFieldProfile("mp", 4, PlayerStatType.F32, 0.0, 100.0),
    )
    valid_profile = ClientPlayerStatsProfile(
        sha256=profile.sha256,
        player_pointer_rva=PLAYER_POINTER_RVA,
        pointer_size_bytes=8,
        fields=valid_fields,
    )
    reader = LivePlayerStatsReader(
        WINDOW_HANDLE,
        profiles={valid_profile.sha256: valid_profile},
        api=FakeStatsMemoryApi(),
    )
    api = reader._api
    assert isinstance(api, FakeStatsMemoryApi)
    api.nonfinite_payload = False
    first = reader.poll(0.0)
    second = reader.poll(0.11)

    with pytest.raises(FrozenInstanceError):
        first.sampled_at_seconds = 99.0  # type: ignore[misc]

    assert first is not second
    assert second.field_values == {"hp": 70.0, "mp": 70.0}


def test_supported_executable_digest_is_bound_to_the_profile() -> None:
    executable = b"entropia stats build"
    assert hashlib.sha256(executable).hexdigest() == hashlib.sha256(executable).hexdigest()
