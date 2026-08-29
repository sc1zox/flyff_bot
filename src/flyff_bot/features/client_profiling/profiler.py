"""Deterministic, bounded analysis of an x64 client executable on disk."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

from flyff_bot.features.client_profiling.models import (
    ClientProfilingError,
    ClientProfilingErrorCode,
    GeneratedClientProfileBundle,
)
from flyff_bot.features.client_profiling.pe import PeImage
from flyff_bot.features.client_profiling.rtti import resolve_primary_vtable
from flyff_bot.features.client_profiling.x64 import relative_call_target, resolve_rip_relative
from flyff_bot.features.dungeons.profiles import (
    BeginEndDungeonSpan,
    ClientDungeonProfile,
    DungeonFieldLayout,
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

REQUIRED_RTTI_NAMES = (
    ".?AVCMover@@",
    ".?AVCWndStatus@@",
    ".?AVCWndDungeonCooldownList@@",
    ".?AVCPlayerDataCenter@@",
)
STATUS_ANALYSIS_WINDOW_BYTES = 512
PLAYER_POSITION_COPY_BYTES = 12
# The vital helpers are located right after a ``mov edx, 100`` marker, so a wrapped helper's
# percent scale is fixed by construction rather than read from an ``imul`` immediate.
VITAL_RATIO_PERCENT_SCALE = 100.0
# A player-struct member offset large enough to be a mistake rather than a field.
_MAX_STRUCT_ACCESSOR_OFFSET = 0x100000
_WRAPPER_SCAN_BYTES = 64
_ACCESSOR_SCAN_BYTES = 48


@dataclass(frozen=True, slots=True)
class RatioEvidence:
    numerator_offset: int
    denominator_offset: int
    primitive: PlayerStatType
    scale: float


@dataclass(frozen=True, slots=True)
class DungeonSpanEvidence:
    manager_pointer_rva: int
    container_offset: int
    begin_pointer_offset: int
    end_pointer_offset: int
    record_size_bytes: int
    maximum_record_count: int
    fields: DungeonFieldLayout


class ClientBinaryProfiler:
    """Generate no output unless every existing live reader receives a complete plan."""

    def profile(self, executable: Path) -> GeneratedClientProfileBundle:
        try:
            data = executable.read_bytes()
        except OSError as error:
            raise ClientProfilingError(ClientProfilingErrorCode.INVALID_PE, str(error)) from error
        digest = hashlib.sha256(data).hexdigest()
        image = PeImage.parse(data)
        for decorated_name in REQUIRED_RTTI_NAMES:
            resolve_primary_vtable(image, decorated_name)

        player_pointer_rva, position_offset, status_rva = _discover_player(image)
        player_stats = _discover_player_stats(
            image,
            status_rva,
            digest,
            player_pointer_rva,
        )
        camera = _discover_camera(image, digest)
        dungeon = _discover_dungeon(image, digest)
        return GeneratedClientProfileBundle(
            position=ClientPositionProfile(
                digest,
                player_pointer_rva,
                8,
                position_offset,
            ),
            player_stats=player_stats,
            camera=camera,
            dungeon=dungeon,
        )


def analyze_ratio_function(code: bytes) -> RatioEvidence:
    """Decode the supported direct ``current * scale / maximum`` helper shape."""

    # mov eax,[rcx+disp32]; imul eax,eax,imm32; cdq; idiv [rcx+disp32]; ret
    prefix = b"\x8b\x81"
    offset = code.find(prefix)
    if offset < 0 or offset + 20 > len(code):
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "A vital helper does not directly expose a bounded numerator/denominator pair.",
        )
    numerator = struct.unpack_from("<i", code, offset + 2)[0]
    cursor = offset + 6
    if code[cursor : cursor + 2] != b"\x69\xc0":
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "A vital helper has no supported fixed-scale multiplication.",
        )
    scale = struct.unpack_from("<i", code, cursor + 2)[0]
    cursor += 6
    if code[cursor : cursor + 3] != b"\x99\xf7\xb9":
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "A vital helper has no direct signed denominator load.",
        )
    denominator = struct.unpack_from("<i", code, cursor + 3)[0]
    if min(numerator, denominator, scale) <= 0:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "A vital helper contains a non-positive offset or scale.",
        )
    return RatioEvidence(numerator, denominator, PlayerStatType.I32, float(scale))


@dataclass(frozen=True, slots=True)
class WrappedRatioEvidence:
    """What the wrapped ``max()`` / ``current()`` vital helper shape statically proves.

    Either side is ``None`` when that getter computes its value through further calls instead
    of a single fixed-offset load, so no bounded struct member can be named for it.
    """

    current_offset: int | None
    max_offset: int | None


def analyze_wrapped_vital_ratio(image: PeImage, wrapper_rva: int) -> WrappedRatioEvidence:
    """Decode the two-call vital helper shape newer client builds use.

    The wrapper calls a maximum getter (its result guarded ``!= 0``), then a current getter,
    then combines them with a fixed percent scale. Only a getter that is a single fixed load
    yields an offset.
    """

    body = image.read_rva(wrapper_rva, _WRAPPER_SCAN_BYTES)
    # Each getter is invoked as ``mov rcx, [rsp+disp8]; call rel32``.
    getter_calls = [
        index + 5
        for index in range(len(body) - 6)
        if body[index : index + 4] == b"\x48\x8b\x4c\x24" and body[index + 5] == 0xE8
    ]
    zero_guard = body.find(b"\x33\xc0")  # xor eax,eax on the ``max == 0`` path
    if len(getter_calls) < 2 or not getter_calls[0] < zero_guard < getter_calls[1]:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "A vital helper does not guard a maximum getter before a current getter.",
        )
    max_rva = relative_call_target(body, getter_calls[0], wrapper_rva)
    current_rva = relative_call_target(body, getter_calls[1], wrapper_rva)
    return WrappedRatioEvidence(
        _fixed_accessor_offset(image, current_rva),
        _fixed_accessor_offset(image, max_rva),
    )


def _fixed_accessor_offset(image: PeImage, accessor_rva: int) -> int | None:
    """Return the struct offset of a getter that is one fixed integer load, else ``None``."""

    try:
        body = image.read_rva(accessor_rva, _ACCESSOR_SCAN_BYTES)
    except ClientProfilingError:
        return None
    # ``movsxd rax,[rax+d32]`` / ``mov eax,[rax+d32]`` / the same from rcx.
    computed_at = min(
        (index for index in (body.find(b"\xe8"), body.find(b"\xf3\x0f\x10")) if index >= 0),
        default=len(body),
    )
    for pattern in (b"\x48\x63\x80", b"\x8b\x80", b"\x48\x63\x81", b"\x8b\x81"):
        marker = body.find(pattern)
        if marker < 0 or marker >= computed_at or marker + len(pattern) + 4 > len(body):
            continue
        offset = int(struct.unpack_from("<i", body, marker + len(pattern))[0])
        if 0 < offset < _MAX_STRUCT_ACCESSOR_OFFSET:
            return offset
    return None


def _resolve_vital_ratio_source(image: PeImage, helper_rva: int) -> RatioPlayerStatSource | None:
    """Return a proven ``current * scale / maximum`` source for one vital, or ``None``.

    ``None`` means this client build computes the vital through a path with no bounded
    numerator/denominator pair (ADR-010); the vital is then left to the visual HUD reader
    rather than guessed.
    """

    try:
        evidence = analyze_ratio_function(image.read_rva(helper_rva, 96))
        return RatioPlayerStatSource(
            evidence.numerator_offset,
            evidence.denominator_offset,
            evidence.primitive,
            evidence.scale,
        )
    except ClientProfilingError:
        pass
    try:
        wrapped = analyze_wrapped_vital_ratio(image, helper_rva)
    except ClientProfilingError:
        return None
    if wrapped.current_offset is None or wrapped.max_offset is None:
        return None
    return RatioPlayerStatSource(
        wrapped.current_offset,
        wrapped.max_offset,
        PlayerStatType.I32,
        VITAL_RATIO_PERCENT_SCALE,
    )


def analyze_dungeon_span_function(
    code: bytes,
    function_rva: int,
) -> DungeonSpanEvidence:
    """Decode one explicit begin/end span accessor and all four record fields.

    The accepted shape is intentionally narrow. Linked maps, trees, and missing fields are
    rejected rather than traversed speculatively at runtime.
    """

    # mov rax,[rip+disp32]
    global_offset = code.find(b"\x48\x8b\x05")
    if global_offset < 0 or global_offset + 7 > len(code):
        raise _incomplete_dungeon("The dungeon manager global is missing.")
    displacement = struct.unpack_from("<i", code, global_offset + 3)[0]
    manager_rva = resolve_rip_relative(function_rva + global_offset, 7, displacement)
    # mov rcx,[rax+container]; mov rdx,[rax+container+ptr]
    header_offset = code.find(b"\x48\x8b\x88", global_offset + 7)
    end_offset = code.find(b"\x48\x8b\x90", header_offset + 7)
    if header_offset < 0 or end_offset < 0:
        raise _incomplete_dungeon("The dungeon update does not expose a contiguous span header.")
    begin_member = struct.unpack_from("<i", code, header_offset + 3)[0]
    end_member = struct.unpack_from("<i", code, end_offset + 3)[0]
    if end_member <= begin_member:
        raise _incomplete_dungeon("The dungeon span begin/end offsets are unordered.")
    container_offset = begin_member
    begin_pointer_offset = 0
    end_pointer_offset = end_member - begin_member

    stride_marker = code.find(b"\x48\x6b", end_offset + 7)
    bound_marker = code.find(b"\x81\xf9", end_offset + 7)
    if stride_marker < 0 or stride_marker + 4 > len(code) or bound_marker < 0:
        raise _incomplete_dungeon("The dungeon span stride or hard record bound is missing.")
    record_size = code[stride_marker + 3]
    maximum_count = struct.unpack_from("<I", code, bound_marker + 2)[0]
    field_offsets = _four_record_field_offsets(code, max(stride_marker, bound_marker))
    return DungeonSpanEvidence(
        manager_rva,
        container_offset,
        begin_pointer_offset,
        end_pointer_offset,
        record_size,
        maximum_count,
        DungeonFieldLayout(*field_offsets),
    )


def _discover_player(image: PeImage) -> tuple[int, int, int]:
    text = image.section_named(".text")
    code = image.section_bytes(".text")
    getters: dict[int, int] = {}
    cursor = 0
    while True:
        cursor = code.find(b"\x48\x8b\x05", cursor)
        if cursor < 0:
            break
        if cursor + 8 <= len(code) and code[cursor + 7] == 0xC3:
            instruction_rva = text.virtual_address + cursor
            displacement = struct.unpack_from("<i", code, cursor + 3)[0]
            target = resolve_rip_relative(instruction_rva, 7, displacement)
            section = image.section_for_rva(target, 8)
            if section is not None and section.writable:
                getters[instruction_rva] = target
        cursor += 1

    status_candidates: list[tuple[int, int]] = []
    for offset, opcode in enumerate(code):
        if opcode != 0xE8 or offset + 5 > len(code):
            continue
        target = relative_call_target(code, offset, text.virtual_address)
        if target not in getters:
            continue
        window = code[offset + 5 : offset + 5 + STATUS_ANALYSIS_WINDOW_BYTES]
        if window.count(b"\xba\x64\x00\x00\x00") >= 3 and window.count(b"\xf3\x0f\x2a\xc0") >= 3:
            status_candidates.append((text.virtual_address + offset, target))
    unique_status = set(status_candidates)
    if len(unique_status) != 1:
        raise ClientProfilingError(
            ClientProfilingErrorCode.AMBIGUOUS_EVIDENCE,
            "The CWndStatus call path does not identify one authoritative GetPlayer helper.",
        )
    status_rva, getter_rva = next(iter(unique_status))
    position_offsets: set[int] = set()
    for offset, opcode in enumerate(code):
        if opcode != 0xE8 or offset + 5 > len(code):
            continue
        if relative_call_target(code, offset, text.virtual_address) != getter_rva:
            continue
        window = code[offset + 5 : offset + 5 + 160]
        add_offset = window.find(b"\x48\x05")
        if add_offset >= 0 and add_offset + 6 <= len(window):
            member_offset = struct.unpack_from("<I", window, add_offset + 2)[0]
            if b"\xb9\x0c\x00\x00\x00\xf3\xa4" in window or b"\xf3\x0f\x10" in window:
                position_offsets.add(member_offset)
    if len(position_offsets) != 1:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_POSITION,
            "The player coordinate member is missing or ambiguous.",
        )
    return getters[getter_rva], next(iter(position_offsets)), status_rva


def _discover_player_stats(
    image: PeImage,
    status_call_rva: int,
    digest: str,
    player_pointer_rva: int,
) -> ClientPlayerStatsProfile:
    text = image.section_named(".text")
    code = image.section_bytes(".text")
    status_offset = status_call_rva - text.virtual_address
    window = code[status_offset : status_offset + STATUS_ANALYSIS_WINDOW_BYTES]
    helper_rvas: list[int] = []
    cursor = 0
    while len(helper_rvas) < 3:
        marker = window.find(b"\xba\x64\x00\x00\x00", cursor)
        if marker < 0:
            break
        call_offset = window.find(b"\xe8", marker + 5, marker + 40)
        if call_offset >= 0:
            helper_rvas.append(relative_call_target(window, call_offset, status_call_rva))
        cursor = marker + 5
    if len(helper_rvas) != 3:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "The status routine does not expose three ordered vital helpers.",
        )
    fields: list[PlayerStatFieldProfile] = []
    for name, helper_rva in zip(("hp", "mp", "fp"), helper_rvas, strict=True):
        source = _resolve_vital_ratio_source(image, helper_rva)
        if source is not None:
            fields.append(PlayerStatFieldProfile(name, source, 0.0, 100.0))
    # A complete profile must also contain direct level and experience evidence. The target
    # build's helpers calculate these through additional data-center calls, so absence is a
    # hard failure rather than an adjacent-offset guess.
    direct_helpers = _direct_stat_helpers(image, window, status_call_rva, after=cursor)
    if len(direct_helpers) != 2:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "Level and experience are not both exposed as direct bounded fields.",
        )
    experience_offset, level_offset = direct_helpers
    fields.extend(
        (
            PlayerStatFieldProfile(
                "level",
                DirectPlayerStatSource(level_offset, PlayerStatType.I32),
                1.0,
                1000.0,
            ),
            PlayerStatFieldProfile(
                "experience",
                DirectPlayerStatSource(experience_offset, PlayerStatType.U64),
                0.0,
                float(2**63 - 1),
            ),
        )
    )
    monster_kills_rva = _discover_monster_kills(image)
    return ClientPlayerStatsProfile(
        digest,
        player_pointer_rva,
        8,
        tuple(fields),
        monster_kills_rva=monster_kills_rva,
    )


def _discover_monster_kills(image: PeImage) -> int | None:
    """Locate the session monster kill counter RVA via the CWndCounterStat format string."""
    target_string = b"Monster Kills: %d"
    text = image.section_named(".text")
    code = image.section_bytes(".text")
    string_rva: int | None = None
    for section in image.sections:
        data = image.section_bytes(section.name)
        offset = data.find(target_string)
        if offset >= 0:
            string_rva = section.virtual_address + offset
            break
    if string_rva is None:
        return None

    cursor = 0
    while cursor < len(code) - 7:
        if code[cursor : cursor + 3] == b"\x48\x8d\x15":
            disp = struct.unpack_from("<i", code, cursor + 3)[0]
            instr_rva = text.virtual_address + cursor
            if instr_rva + 7 + disp == string_rva:
                window_start = max(0, cursor - 16)
                window = code[window_start:cursor]
                mov_offset = window.rfind(b"\x44\x8b\x05")
                if mov_offset >= 0:
                    mov_rva = text.virtual_address + window_start + mov_offset
                    mov_disp = struct.unpack_from("<i", window, mov_offset + 3)[0]
                    target_var_rva: int = int(mov_rva + 7 + mov_disp)
                    sec = image.section_for_rva(target_var_rva, 4)
                    if sec is not None and sec.writable:
                        return target_var_rva
        cursor += 1
    return None


def _direct_stat_helpers(
    image: PeImage,
    status_window: bytes,
    status_rva: int,
    *,
    after: int,
) -> tuple[int, ...]:
    offsets: list[int] = []
    cursor = after
    while len(offsets) < 2:
        call_offset = status_window.find(b"\xe8", cursor)
        if call_offset < 0:
            break
        helper_rva = relative_call_target(status_window, call_offset, status_rva)
        try:
            helper = image.read_rva(helper_rva, 16)
        except ClientProfilingError:
            cursor = call_offset + 5
            continue
        direct_offset: int | None = None
        if helper.startswith(b"\x8b\x81") and helper[6] == 0xC3:
            direct_offset = struct.unpack_from("<i", helper, 2)[0]
        elif helper.startswith(b"\x48\x8b\x81") and helper[7] == 0xC3:
            direct_offset = struct.unpack_from("<i", helper, 3)[0]
        if direct_offset is not None and direct_offset >= 0:
            offsets.append(direct_offset)
        cursor = call_offset + 5
    return tuple(offsets)


def _discover_camera(image: PeImage, digest: str) -> ClientCameraProfile:
    text = image.section_named(".text")
    code = image.section_bytes(".text")
    pairs: list[tuple[int, int, int]] = []
    cursor = 0
    while True:
        cursor = code.find(b"\x48\x8b\x05", cursor)
        if cursor < 0:
            break
        if cursor + 7 > len(code):
            break
        camera_rva = resolve_rip_relative(
            text.virtual_address + cursor,
            7,
            struct.unpack_from("<i", code, cursor + 3)[0],
        )
        window = code[cursor + 7 : cursor + 128]
        projection_marker = window.find(b"\x4c\x8d\x0d")
        add_marker = window.find(b"\x48\x83\xc0")
        if (
            projection_marker >= 0
            and add_marker >= 0
            and projection_marker + 7 <= len(window)
            and add_marker + 4 <= len(window)
        ):
            projection_instruction_rva = text.virtual_address + cursor + 7 + projection_marker
            projection_rva = resolve_rip_relative(
                projection_instruction_rva,
                7,
                struct.unpack_from("<i", window, projection_marker + 3)[0],
            )
            pairs.append((camera_rva, projection_rva, window[add_marker + 3]))
        cursor += 1
    counts: dict[tuple[int, int, int], int] = {}
    for pair in pairs:
        counts[pair] = counts.get(pair, 0) + 1
    repeated = [pair for pair, count in counts.items() if count >= 2]
    if len(repeated) != 1:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_CAMERA,
            "The view/projection call path is missing or ambiguous.",
        )
    camera_rva, projection_rva, view_offset = repeated[0]
    member_offsets = _camera_member_offsets(code, text.virtual_address, camera_rva)
    if view_offset not in member_offsets or len(member_offsets) != 3:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_CAMERA,
            "The camera eye, view, and look-at members are not uniquely proven.",
        )
    eye_offset = min(member_offsets)
    look_at_offset = max(member_offsets)
    return ClientCameraProfile(
        digest,
        camera_rva,
        8,
        eye_offset,
        view_offset,
        look_at_offset,
        projection_rva,
    )


def _camera_member_offsets(code: bytes, code_rva: int, camera_rva: int) -> set[int]:
    offsets: set[int] = set()
    cursor = 0
    while True:
        cursor = code.find(b"\x48\x8b", cursor)
        if cursor < 0 or cursor + 7 > len(code):
            break
        modrm = code[cursor + 2]
        if modrm not in {0x05, 0x0D}:
            cursor += 1
            continue
        target = resolve_rip_relative(
            code_rva + cursor,
            7,
            struct.unpack_from("<i", code, cursor + 3)[0],
        )
        if target != camera_rva:
            cursor += 1
            continue
        following = code[cursor + 7 : cursor + 20]
        for prefix in (b"\x48\x83\xc0", b"\x48\x83\xc1"):
            if following.startswith(prefix):
                offsets.add(following[3])
        for prefix in (b"\x48\x05", b"\x48\x81\xc1", b"\x48\x8d\x80", b"\x48\x8d\x88"):
            if following.startswith(prefix) and len(following) >= len(prefix) + 4:
                offsets.add(struct.unpack_from("<I", following, len(prefix))[0])
        cursor += 1
    return {offset for offset in offsets if 0 < offset <= 0x1000}


def _discover_dungeon(image: PeImage, digest: str) -> ClientDungeonProfile:
    dungeon_rtti = resolve_primary_vtable(image, ".?AVCWndDungeonCooldownList@@")
    vtable_entries = struct.unpack("<8Q", image.read_rva(dungeon_rtti.primary_vtable_rva, 64))
    evidence: list[DungeonSpanEvidence] = []
    for entry in vtable_entries:
        function_rva = entry - image.image_base
        try:
            code = image.read_rva(function_rva, 512)
            evidence.append(analyze_dungeon_span_function(code, function_rva))
        except ClientProfilingError:
            continue
    unique = set(evidence)
    if len(unique) != 1:
        raise _incomplete_dungeon(
            "The dungeon VTable does not expose one complete bounded contiguous container."
        )
    item = next(iter(unique))
    return ClientDungeonProfile(
        digest,
        item.manager_pointer_rva,
        8,
        BeginEndDungeonSpan(
            item.container_offset,
            item.begin_pointer_offset,
            item.end_pointer_offset,
            item.record_size_bytes,
            item.maximum_record_count,
        ),
        item.fields,
    )


def _four_record_field_offsets(code: bytes, start: int) -> tuple[int, int, int, int]:
    candidates: list[int] = []
    cursor = start
    prefixes = (b"\x44\x8b\x81", b"\x8b\x81", b"\xf3\x0f\x10\x81")
    while cursor < len(code) and len(candidates) < 4:
        matches = [(code.find(prefix, cursor), prefix) for prefix in prefixes]
        matches = [(offset, prefix) for offset, prefix in matches if offset >= 0]
        if not matches:
            break
        offset, prefix = min(matches, key=lambda match: match[0])
        displacement_offset = offset + len(prefix)
        if displacement_offset + 4 > len(code):
            break
        candidates.append(struct.unpack_from("<i", code, displacement_offset)[0])
        cursor = displacement_offset + 4
    if len(candidates) != 4 or min(candidates) < 0:
        raise _incomplete_dungeon("The dungeon record does not expose four ordered fields.")
    return tuple(candidates)  # type: ignore[return-value]


def _incomplete_dungeon(detail: str) -> ClientProfilingError:
    return ClientProfilingError(ClientProfilingErrorCode.INCOMPLETE_DUNGEON, detail)
