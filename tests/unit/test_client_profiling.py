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


def _call_rel32(instruction_rva: int, target_rva: int) -> bytes:
    return b"\xe8" + struct.pack("<i", target_rva - (instruction_rva + 5))


def test_analyze_wrapped_vital_ratio_extracts_current_offset_and_leaves_computed_max_unknown() -> (
    None
):
    from flyff_bot.features.client_profiling.profiler import analyze_wrapped_vital_ratio

    wrapper_rva, current_rva, max_rva = 0x1000, 0x1100, 0x1200
    reload_rcx = b"\x48\x8b\x4c\x24\x40"
    wrapper = (
        reload_rcx
        + _call_rel32(wrapper_rva + 5, max_rva)  # guarded maximum getter
        + b"\x83\x7c\x24\x20\x00\x75\x04\x33\xc0\xeb\x00"  # cmp/jne/xor eax,eax/jmp
        + reload_rcx
        + _call_rel32(wrapper_rva + 26, current_rva)  # current getter
        + b"\xc3"
    )
    # current getter: mov rax,[rsp+0x40]; movsxd rax,[rax+0x12FC]; ret
    current_getter = b"\x48\x89\x4c\x24\x08\x48\x83\xec\x38\x48\x8b\x44\x24\x40" + (
        b"\x48\x63\x80" + struct.pack("<i", 0x12FC) + b"\xc3"
    )
    # maximum getter: loads a float constant and calls onward -> no fixed offset
    max_getter = b"\x48\x89\x4c\x24\x08\x48\x83\xec\x38\xf3\x0f\x10\x05\x00\x00\x00\x00" + (
        _call_rel32(max_rva + 17, max_rva + 40) + b"\xc3"
    )

    text = bytearray(b"\x90" * 0x260)
    text[0x000 : len(wrapper)] = wrapper
    text[0x100 : 0x100 + len(current_getter)] = current_getter
    text[0x200 : 0x200 + len(max_getter)] = max_getter

    image = _build_synthetic_pe(text_payload=bytes(text))
    evidence = analyze_wrapped_vital_ratio(image, wrapper_rva)

    assert evidence.current_offset == 0x12FC
    assert evidence.max_offset is None


def test_analyze_wrapped_vital_ratio_rejects_a_helper_without_a_guarded_getter_pair() -> None:
    from flyff_bot.features.client_profiling.profiler import analyze_wrapped_vital_ratio

    # One getter call, no ``xor eax,eax`` zero guard, no second call.
    text_payload = (b"\x48\x8b\x4c\x24\x40" + _call_rel32(0x1005, 0x1100) + b"\xc3").ljust(
        64, b"\x90"
    )

    with pytest.raises(ClientProfilingError) as error:
        analyze_wrapped_vital_ratio(_build_synthetic_pe(text_payload=text_payload), 0x1000)
    assert error.value.code is ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS


def _member_load_getter(offset: int, *, wide: bool) -> bytes:
    # mov [rsp+8],rcx; mov rax,[rsp+8]; mov (r|e)ax,[rax+disp32]; ret
    load = (b"\x48\x8b\x80" if wide else b"\x8b\x80") + struct.pack("<i", offset)
    return b"\x48\x89\x4c\x24\x08\x48\x8b\x44\x24\x08" + load + b"\xc3"


def test_analyze_hp_xor_pair_recovers_the_offset_and_both_keys() -> None:
    from flyff_bot.features.client_profiling.profiler import analyze_hp_xor_pair

    getter_rva, adder_rva, decoder_rva = 0x1000, 0x1100, 0x1200
    key_a, key_b = 0x5A3C9E17C4D2F8B1, 0x2D74B1C9A6E03F5D

    getter = b"\x48\x8b\x4c\x24\x40" + _call_rel32(getter_rva + 5, adder_rva) + b"\xc3"
    adder = (
        b"\x48\x8b\x44\x24\x40"  # mov rax,[rsp+0x40]
        + b"\x48\x05"
        + struct.pack("<i", 0x1304)  # add rax, 0x1304
        + _call_rel32(adder_rva + 11, decoder_rva)
        + b"\xc3"
    )
    decoder = (
        b"\x48\xb8"
        + struct.pack("<Q", key_a)  # movabs rax, key_a
        + b"\x48\x33\xc8"  # xor rcx, rax
        + b"\x48\xb8"
        + struct.pack("<Q", key_b)  # movabs rax, key_b
        + b"\x48\x33\xc8\xc3"
    )
    text = bytearray(b"\x90" * 0x400)
    text[0x000 : len(getter)] = getter
    text[0x100 : 0x100 + len(adder)] = adder
    text[0x200 : 0x200 + len(decoder)] = decoder

    evidence = analyze_hp_xor_pair(_build_synthetic_pe(text_payload=bytes(text)), getter_rva)

    assert evidence is not None
    assert (evidence.offset, evidence.key_a, evidence.key_b) == (0x1304, key_a, key_b)


def test_discover_level_experience_reads_the_exp_wrapper_member_getters() -> None:
    from flyff_bot.features.client_profiling.profiler import _discover_level_experience

    status_rva, exp_wrapper_rva, level_rva, exp_getter_rva = 0x1000, 0x1100, 0x1200, 0x1300
    # status window: one gauge call followed by cvtsi2ss xmm0, eax, with no `mov edx, 100`.
    status = (
        b"\x48\x8b\x4c\x24\x38" + _call_rel32(status_rva + 5, exp_wrapper_rva) + b"\xf3\x0f\x2a\xc0"
    ).ljust(0x40, b"\x90")
    exp_wrapper = (
        b"\x48\x8b\x4c\x24\x40"
        + _call_rel32(exp_wrapper_rva + 5, level_rva)
        + b"\x48\x8b\x4c\x24\x40"
        + _call_rel32(exp_wrapper_rva + 15, exp_getter_rva)
        + b"\xc3"
    )
    text = bytearray(b"\x90" * 0x340)
    text[0x000 : len(status)] = status
    text[0x100 : 0x100 + len(exp_wrapper)] = exp_wrapper
    text[0x200 : 0x200 + 0x20] = _member_load_getter(0x12C0, wide=False)
    text[0x300 : 0x300 + 0x20] = _member_load_getter(0x12C8, wide=True)

    level_offset, experience_offset = _discover_level_experience(
        _build_synthetic_pe(text_payload=bytes(text)), status, status_rva
    )

    assert (level_offset, experience_offset) == (0x12C0, 0x12C8)
