"""Tests for the fingerprinted world-ID reader (US-065)."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from flyff_bot.constants import DEFAULT_CLIENT_WORLD_ID_PROFILES_PATH
from flyff_bot.features.navigation.live_world_id import (
    ClientWorldIdProfile,
    LiveWorldIdReader,
    WorldIdReadErrorCode,
    load_client_world_id_profiles,
)


class _FakeMemoryApi:
    def __init__(
        self,
        world_id: int = 0,
        *,
        executable: Path | None = None,
    ) -> None:
        self.world_id = world_id
        self.executable = executable or _FAKE_EXECUTABLE_NAME

    def process_id_for_window(self, window_handle: int) -> int:
        return 1

    def open_read_process(self, process_id: int) -> int:
        return 100

    def executable_path(self, process_handle: int) -> Path:
        return self.executable

    def main_module_base(self, process_id: int) -> int:
        return 0x400000

    def read(self, process_handle: int, address: int, size: int) -> bytes:
        return struct.pack("<i", self.world_id)

    def close(self, process_handle: int) -> None:
        pass


_FAKE_EXECUTABLE_CONTENT = b"fake-neuz-executable"
_FAKE_EXECUTABLE_NAME = Path("neuz.exe")
_DIGEST = hashlib.sha256(_FAKE_EXECUTABLE_CONTENT).hexdigest()


def test_load_profiles_from_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        f'[{{"sha256": "{_DIGEST}", "world_id_rva": 74565}}]',
        encoding="utf-8",
    )

    profiles = load_client_world_id_profiles(path)

    assert _DIGEST in profiles
    assert profiles[_DIGEST].world_id_rva == 0x12345


def test_committed_world_id_registry_is_explicitly_empty_until_an_rva_is_proven() -> None:
    assert load_client_world_id_profiles(Path(DEFAULT_CLIENT_WORLD_ID_PROFILES_PATH)) == {}


def test_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("[not json]", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid"):
        load_client_world_id_profiles(path)


def test_reader_reports_unsupported_build_without_profile(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(_FAKE_EXECUTABLE_CONTENT)
    reader = LiveWorldIdReader(
        1,
        api=_FakeMemoryApi(executable=executable),
        profiles={},
    )

    reading = reader.poll(0.0)

    assert not reading.is_available
    assert reading.error is not None
    assert reading.error.code is WorldIdReadErrorCode.UNSUPPORTED_BUILD


def test_reader_returns_world_id_with_matching_profile(tmp_path: Path) -> None:
    executable = tmp_path / "neuz.exe"
    executable.write_bytes(_FAKE_EXECUTABLE_CONTENT)
    profile = ClientWorldIdProfile(_DIGEST, world_id_rva=0x1000)
    api = _FakeMemoryApi(world_id=42, executable=executable)
    reader = LiveWorldIdReader(1, api=api, profiles={_DIGEST: profile})

    reading = reader.poll(0.0)

    assert reading.is_available
    assert reading.world_id == 42


def test_reader_fails_closed_on_wrong_process() -> None:
    class _WrongProcessApi(_FakeMemoryApi):
        def executable_path(self, process_handle: int) -> Path:
            return Path("C:/other/notepad.exe")

    profile = ClientWorldIdProfile(_DIGEST, world_id_rva=0x1000)
    reader = LiveWorldIdReader(1, api=_WrongProcessApi(), profiles={_DIGEST: profile})

    reading = reader.poll(0.0)

    assert not reading.is_available
    assert reading.error is not None
    assert reading.error.code is WorldIdReadErrorCode.WRONG_PROCESS
