"""Unit tests for offline client profiling, PE parsing, and MSVC RTTI resolution."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from flyff_bot.features.client_profiling.models import (
    ClientProfilingError,
    ClientProfilingErrorCode,
    GeneratedClientProfileBundle,
)
from flyff_bot.features.client_profiling.pe import PeImage, PeSection
from flyff_bot.features.client_profiling.persistence import persist_profile_bundle
from flyff_bot.features.client_profiling.rtti import (
    COL_SIZE_BYTES,
    POINTER_SIZE_BYTES,
    TYPE_DESCRIPTOR_HEADER_BYTES,
    _valid_vtable,
    resolve_primary_vtable,
)
from flyff_bot.features.dungeons.profiles import (
    ClientDungeonProfile,
    DungeonFieldLayout,
    FixedDungeonArray,
)
from flyff_bot.features.navigation.live_camera import ClientCameraProfile
from flyff_bot.features.navigation.live_position import ClientPositionProfile
from flyff_bot.features.player_stats.profiles import (
    ClientPlayerStatsProfile,
    DirectPlayerStatSource,
    PlayerStatFieldProfile,
    PlayerStatType,
    RatioPlayerStatSource,
)

IMAGE_BASE = 0x140000000


def _build_synthetic_pe(
    *,
    text_payload: bytes = b"\x90" * 64,
    rdata_payload: bytes = b"",
    data_payload: bytes = b"",
) -> PeImage:
    data = bytearray(0x1000)
    data[0x400 : 0x400 + len(text_payload)] = text_payload
    data[0x600 : 0x600 + len(rdata_payload)] = rdata_payload
    data[0x800 : 0x800 + len(data_payload)] = data_payload
    sections = (
        PeSection(
            ".text",
            0x1000,
            max(len(text_payload), 64),
            0x400,
            max(len(text_payload), 64),
            0x60000020,
        ),
        PeSection(
            ".rdata",
            0x2000,
            max(len(rdata_payload), 64),
            0x600,
            max(len(rdata_payload), 64),
            0x40000040,
        ),
        PeSection(
            ".data",
            0x3000,
            max(len(data_payload), 64),
            0x800,
            max(len(data_payload), 64),
            0xC0000040,
        ),
    )
    return PeImage(bytes(data), IMAGE_BASE, sections, ())


def test_resolve_primary_vtable_finds_type_descriptor_in_data_section() -> None:
    decorated_name = ".?AVCMover@@"
    name_bytes = decorated_name.encode("ascii") + b"\0"
    type_descriptor = b"\x00" * TYPE_DESCRIPTOR_HEADER_BYTES + name_bytes
    data_payload = type_descriptor.ljust(64, b"\x00")
    type_rva = 0x3000

    col_rva = 0x2000
    col_struct = struct.pack(
        "<IIIIII",
        1,  # signature
        0,  # object_offset
        0,  # cd_offset
        type_rva,  # type_ref
        0,  # hierarchy
        col_rva,  # self_ref
    )
    assert len(col_struct) == COL_SIZE_BYTES

    vfunc_rva = 0x1010
    vfunc_ptr = struct.pack("<Q", IMAGE_BASE + vfunc_rva)

    col_ptr = struct.pack("<Q", IMAGE_BASE + col_rva)
    rdata_payload = col_struct + b"\x00" * 8 + col_ptr + vfunc_ptr
    vtable_rva = 0x2000 + len(col_struct) + 8 + POINTER_SIZE_BYTES

    pe = _build_synthetic_pe(
        text_payload=b"\xc3" * 64,
        rdata_payload=rdata_payload,
        data_payload=data_payload,
    )

    rtti = resolve_primary_vtable(pe, decorated_name)
    assert rtti.decorated_name == decorated_name
    assert rtti.type_descriptor_rva == type_rva
    assert rtti.complete_object_locator_rva == col_rva
    assert rtti.primary_vtable_rva == vtable_rva


def test_resolve_primary_vtable_finds_type_descriptor_in_rdata_section() -> None:
    decorated_name = ".?AVCWndStatus@@"
    name_bytes = decorated_name.encode("ascii") + b"\0"
    type_descriptor = b"\x00" * TYPE_DESCRIPTOR_HEADER_BYTES + name_bytes
    type_rva = 0x2000

    col_rva = 0x2040
    col_struct = struct.pack(
        "<IIIIII",
        1,
        0,
        0,
        type_rva,
        0,
        col_rva,
    )

    vfunc_rva = 0x1000
    vfunc_ptr = struct.pack("<Q", IMAGE_BASE + vfunc_rva)
    col_ptr = struct.pack("<Q", IMAGE_BASE + col_rva)

    rdata_payload = type_descriptor.ljust(0x40, b"\x00") + col_struct + col_ptr + vfunc_ptr
    vtable_rva = 0x2040 + len(col_struct) + POINTER_SIZE_BYTES

    pe = _build_synthetic_pe(
        text_payload=b"\xc3" * 64,
        rdata_payload=rdata_payload,
    )

    rtti = resolve_primary_vtable(pe, decorated_name)
    assert rtti.decorated_name == decorated_name
    assert rtti.type_descriptor_rva == type_rva
    assert rtti.complete_object_locator_rva == col_rva
    assert rtti.primary_vtable_rva == vtable_rva


def test_resolve_primary_vtable_missing_raises_error() -> None:
    pe = _build_synthetic_pe(
        text_payload=b"\xc3" * 64,
        rdata_payload=b"\x00" * 64,
        data_payload=b"\x00" * 64,
    )
    with pytest.raises(ClientProfilingError) as exc:
        resolve_primary_vtable(pe, ".?AVMissingClass@@")
    assert exc.value.code == ClientProfilingErrorCode.MISSING_RTTI


def test_valid_vtable_accepts_single_method_class() -> None:
    pe = _build_synthetic_pe(
        text_payload=b"\xc3" * 64,
        rdata_payload=struct.pack("<Q", IMAGE_BASE + 0x1000) + b"\x00" * 8,
    )
    assert _valid_vtable(pe, 0x2000)


def test_valid_vtable_rejects_non_executable_pointer() -> None:
    pe = _build_synthetic_pe(
        text_payload=b"\xc3" * 64,
        rdata_payload=struct.pack("<Q", IMAGE_BASE + 0x2000),
    )
    assert not _valid_vtable(pe, 0x2000)


def test_persist_profile_bundle_writes_canonical_json_profiles(tmp_path: Path) -> None:
    digest = "c" * 64
    fields = (
        PlayerStatFieldProfile(
            "hp", RatioPlayerStatSource(0x10, 0x14, PlayerStatType.I32), 0.0, 100.0
        ),
        PlayerStatFieldProfile(
            "level", DirectPlayerStatSource(0x20, PlayerStatType.I32), 1.0, 1000.0
        ),
    )
    bundle = GeneratedClientProfileBundle(
        ClientPositionProfile(digest, 0x1000, 8, 0x188),
        ClientPlayerStatsProfile(digest, 0x1000, 8, fields),
        ClientCameraProfile(digest, 0x2000, 8, 8, 0x14, 0x94, 0x3000),
        ClientDungeonProfile(
            digest,
            0x4000,
            8,
            FixedDungeonArray(0x20, 32, 4),
            DungeonFieldLayout(0, 8, 12, 16),
        ),
    )
    pos_path = tmp_path / "pos.json"
    stats_path = tmp_path / "stats.json"
    cam_path = tmp_path / "cam.json"
    dung_path = tmp_path / "dung.json"

    persist_profile_bundle(
        bundle,
        position_path=pos_path,
        player_stats_path=stats_path,
        camera_path=cam_path,
        dungeon_path=dung_path,
    )

    assert pos_path.is_file()
    assert stats_path.is_file()
    assert cam_path.is_file()
    assert dung_path.is_file()


def test_discover_monster_kills_finds_counter_in_synthetic_pe() -> None:
    from flyff_bot.features.client_profiling.profiler import _discover_monster_kills

    string_rva = 0x2010
    target_var_rva = 0x3020

    instr1_rva = 0x1000
    disp1 = target_var_rva - (instr1_rva + 7)
    instr1 = b"\x44\x8b\x05" + struct.pack("<i", disp1)

    instr2_rva = 0x1007
    disp2 = string_rva - (instr2_rva + 7)
    instr2 = b"\x48\x8d\x15" + struct.pack("<i", disp2)

    text_payload = (instr1 + instr2).ljust(64, b"\x90")
    rdata_payload = b"\x00" * 0x10 + b"Monster Kills: %d\x00"
    data_payload = b"\x00" * 0x40

    pe = _build_synthetic_pe(
        text_payload=text_payload,
        rdata_payload=rdata_payload,
        data_payload=data_payload,
    )

    discovered = _discover_monster_kills(pe)
    assert discovered == target_var_rva
