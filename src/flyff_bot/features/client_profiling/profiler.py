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
    ClientDungeonProfile,
    GlobalDungeonLockout,
)
from flyff_bot.features.navigation.live_camera import ClientCameraProfile
from flyff_bot.features.navigation.live_position import ClientPositionProfile
from flyff_bot.features.player_stats.profiles import (
    ClientPlayerStatsProfile,
    DirectPlayerStatSource,
    PlayerStatFieldProfile,
    PlayerStatType,
    RatioPlayerStatSource,
    XorPairPlayerStatSource,
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
# The obfuscated-HP decoder loads both 64-bit keys within the first ~0x70 bytes.
_XOR_DECODER_SCAN_BYTES = 160
_POSITION_COPY_SETUP = b"\x48\x8b\xc8\xe8"  # mov rcx, rax; call position helper
_POSITION_COPY_DESTINATION = b"\x48\x8d\x4c\x24"  # lea rcx, [rsp+imm8]
_POSITION_COPY_DESTINATION_REGISTER = b"\x48\x8b\xf9"  # mov rdi, rcx
_POSITION_COPY_SOURCE_REGISTER = b"\x48\x8b\xf0"  # mov rsi, rax
_POSITION_COPY_LENGTH = b"\xb9\x0c\x00\x00\x00\xf3\xa4"  # mov ecx, 12; rep movsb
_POSITION_HELPER_STACK_ARGUMENT = b"\x48\x89\x4c\x24\x08\x48\x8b\x44\x24\x08"
_POSITION_HELPER_ADD_RAX = b"\x48\x05"
_POSITION_HELPER_LEA_RAX_RCX = b"\x48\x8d\x81"
_POSITION_MEMBER_ALIGNMENT_BYTES = 4


@dataclass(frozen=True, slots=True)
class RatioEvidence:
    numerator_offset: int
    denominator_offset: int
    primitive: PlayerStatType
    scale: float


@dataclass(frozen=True, slots=True)
class DungeonLockoutEvidence:
    """The player global and member offset of the account-wide dungeon lockout time."""

    runtime_state_pointer_rva: int
    lockout_timestamp_offset: int


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

    An ``*_offset`` is ``None`` when that getter computes its value through further calls
    instead of a single fixed-offset load, so no bounded struct member can be named for it.
    """

    current_getter_rva: int
    max_getter_rva: int
    current_offset: int | None
    max_offset: int | None


@dataclass(frozen=True, slots=True)
class XorPairEvidence:
    """The struct offset and two 64-bit keys of an XOR-obfuscated player statistic."""

    offset: int
    key_a: int
    key_b: int


def _relative_call_sites(body: bytes) -> list[int]:
    return [index for index in range(len(body) - 4) if body[index] == 0xE8]


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
        current_rva,
        max_rva,
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


def analyze_hp_xor_pair(image: PeImage, current_getter_rva: int) -> XorPairEvidence | None:
    """Decode the ``[player+disp] ^ key_a`` / ``^ key_b`` obfuscated-HP shape.

    From the HP current getter, follow one callee that adds a fixed displacement to the
    player pointer and hands it to a decoder holding two sequential 64-bit XOR keys.
    """

    try:
        outer = image.read_rva(current_getter_rva, 96)
    except ClientProfilingError:
        return None
    for call_at in _relative_call_sites(outer):
        adder_rva = relative_call_target(outer, call_at, current_getter_rva)
        evidence = _xor_pair_from_adder(image, adder_rva)
        if evidence is not None:
            return evidence
    return None


def _xor_pair_from_adder(image: PeImage, adder_rva: int) -> XorPairEvidence | None:
    try:
        body = image.read_rva(adder_rva, 64)
    except ClientProfilingError:
        return None
    add_at = body.find(b"\x48\x05")  # add rax, imm32
    if add_at < 0 or add_at + 6 > len(body):
        return None
    offset = int(struct.unpack_from("<i", body, add_at + 2)[0])
    if not 0 < offset < _MAX_STRUCT_ACCESSOR_OFFSET:
        return None
    call_at = body.find(b"\xe8", add_at + 6)
    if call_at < 0 or call_at + 5 > len(body):
        return None
    keys = _sequential_imm64_keys(image, relative_call_target(body, call_at, adder_rva))
    if len(keys) != 2:
        return None
    return XorPairEvidence(offset, keys[0], keys[1])


def _sequential_imm64_keys(image: PeImage, decoder_rva: int) -> tuple[int, ...]:
    try:
        body = image.read_rva(decoder_rva, _XOR_DECODER_SCAN_BYTES)
    except ClientProfilingError:
        return ()
    if b"\x48\x33" not in body:  # no ``xor r64, r64`` -> not an XOR decoder
        return ()
    keys: list[int] = []
    cursor = 0
    while cursor + 10 <= len(body):
        if body[cursor] == 0x48 and 0xB8 <= body[cursor + 1] <= 0xBF:  # movabs r64, imm64
            keys.append(int(struct.unpack_from("<Q", body, cursor + 2)[0]))
            cursor += 10
            continue
        cursor += 1
    return tuple(keys)


# ``mov [rsp+8], rcx; mov rax, [rsp+8]`` -> a getter that loads one fixed ``this`` member.
_MEMBER_LOAD_PROLOGUE = b"\x48\x89\x4c\x24\x08\x48\x8b\x44\x24\x08"


def _member_load_evidence(image: PeImage, rva: int) -> tuple[int, PlayerStatType] | None:
    try:
        body = image.read_rva(rva, 32)
    except ClientProfilingError:
        return None
    if not body.startswith(_MEMBER_LOAD_PROLOGUE):
        return None
    cursor = len(_MEMBER_LOAD_PROLOGUE)
    if body[cursor : cursor + 3] == b"\x48\x8b\x80":  # mov rax, [rax+d32]
        primitive, disp_at = PlayerStatType.U64, cursor + 3
    elif body[cursor : cursor + 2] == b"\x8b\x80":  # mov eax, [rax+d32]
        primitive, disp_at = PlayerStatType.I32, cursor + 2
    else:
        return None
    if disp_at + 4 > len(body):
        return None
    offset = int(struct.unpack_from("<i", body, disp_at)[0])
    if not 0 < offset < _MAX_STRUCT_ACCESSOR_OFFSET:
        return None
    return offset, primitive


# The lockout helper's fixed prologue: ``mov [rsp+8], rcx`` / ``sub rsp, imm8`` /
# ``mov rax, [rsp+imm8]`` (load ``this``) then one 64-bit member load handed straight to a
# constructor call. ADR-011: this build exposes no per-dungeon container, so the account-wide
# lockout timestamp the dungeon UI itself reads is the only bounded dungeon datum.
_LOCKOUT_HELPER_PROLOGUE = b"\x48\x89\x4c\x24\x08"
_LOCKOUT_SUB_RSP = b"\x48\x83\xec"
_LOCKOUT_LOAD_THIS = b"\x48\x8b\x44\x24"
_LOCKOUT_MEMBER_LOADS = (b"\x48\x8b\x90", b"\x48\x8b\x80")  # mov r/e dx|ax, [rax+disp32]
_LOCKOUT_LEA_RCX_STACK = b"\x48\x8d\x4c\x24"
_LOCKOUT_TIMESTAMP_ALIGN = 8


def analyze_dungeon_lockout_helper(image: PeImage, helper_rva: int) -> int | None:
    """Return the ``__time64_t`` member offset a dungeon lockout helper reads, else ``None``.

    The accepted shape is ``mov rax,[rsp+x]; mov r64,[rax+disp32]; lea rcx,[rsp+y]; call`` —
    a single bounded 64-bit ``this`` member handed straight to a time constructor. Anything
    that indexes, chases a pointer, or reads a 32-bit field is rejected.
    """

    try:
        body = image.read_rva(helper_rva, 32)
    except ClientProfilingError:
        return None
    if not body.startswith(_LOCKOUT_HELPER_PROLOGUE):
        return None
    if body[5:8] != _LOCKOUT_SUB_RSP or body[9:13] != _LOCKOUT_LOAD_THIS:
        return None
    cursor = 14
    if body[cursor : cursor + 3] not in _LOCKOUT_MEMBER_LOADS:
        return None
    offset = int(struct.unpack_from("<i", body, cursor + 3)[0])
    cursor += 7
    if body[cursor : cursor + 4] != _LOCKOUT_LEA_RCX_STACK or body[cursor + 5] != 0xE8:
        return None
    if not 0 < offset < _MAX_STRUCT_ACCESSOR_OFFSET or offset % _LOCKOUT_TIMESTAMP_ALIGN:
        return None
    return offset


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
        member_offset = _position_copy_member_offset(
            image,
            code,
            call_offset=offset,
            text_rva=text.virtual_address,
        )
        if member_offset is not None:
            position_offsets.add(member_offset)
    if len(position_offsets) != 1:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_POSITION,
            "The player coordinate member is missing or ambiguous.",
        )
    return getters[getter_rva], next(iter(position_offsets)), status_rva


def _position_copy_member_offset(
    image: PeImage,
    code: bytes,
    *,
    call_offset: int,
    text_rva: int,
) -> int | None:
    """Return a player member offset only for the proven 12-byte copy shape.

    ``GetPlayer`` returns the ``CMover`` in ``rax``.  The accepted call site forwards that
    exact value through ``rcx`` to a tiny accessor, then copies the accessor return from
    ``rsi`` with ``rep movsb``.  Searching for the bytes of ``add rax, imm32`` anywhere in
    a nearby window is not instruction decoding and can turn arbitrary operand bytes into a
    live-memory address (BUG-039).
    """

    cursor = call_offset + 5
    if code[cursor : cursor + len(_POSITION_COPY_SETUP)] != _POSITION_COPY_SETUP:
        return None
    helper_call_offset = cursor + len(_POSITION_COPY_SETUP) - 1
    helper_rva = relative_call_target(code, helper_call_offset, text_rva)
    cursor += len(_POSITION_COPY_SETUP) + 4  # remaining rel32 bytes of the helper call
    if code[cursor : cursor + len(_POSITION_COPY_DESTINATION)] != _POSITION_COPY_DESTINATION:
        return None
    cursor += len(_POSITION_COPY_DESTINATION) + 1  # stack displacement
    if (
        code[cursor : cursor + len(_POSITION_COPY_DESTINATION_REGISTER)]
        != _POSITION_COPY_DESTINATION_REGISTER
    ):
        return None
    cursor += len(_POSITION_COPY_DESTINATION_REGISTER)
    if (
        code[cursor : cursor + len(_POSITION_COPY_SOURCE_REGISTER)]
        != _POSITION_COPY_SOURCE_REGISTER
    ):
        return None
    cursor += len(_POSITION_COPY_SOURCE_REGISTER)
    if code[cursor : cursor + len(_POSITION_COPY_LENGTH)] != _POSITION_COPY_LENGTH:
        return None
    return _position_accessor_member_offset(image, helper_rva)


def _position_accessor_member_offset(image: PeImage, helper_rva: int) -> int | None:
    """Decode the bounded accessor that returns ``CMover + position_offset``."""

    try:
        helper = image.read_rva(helper_rva, 24)
    except ClientProfilingError:
        return None
    cursor = 0
    if helper.startswith(_POSITION_HELPER_STACK_ARGUMENT):
        cursor = len(_POSITION_HELPER_STACK_ARGUMENT)
    if helper[cursor : cursor + 2] == _POSITION_HELPER_ADD_RAX:
        offset = struct.unpack_from("<i", helper, cursor + 2)[0]
        instruction_size = 6
    elif helper[cursor : cursor + 3] == _POSITION_HELPER_LEA_RAX_RCX:
        offset = struct.unpack_from("<i", helper, cursor + 3)[0]
        instruction_size = 7
    else:
        return None
    if helper[cursor + instruction_size : cursor + instruction_size + 1] != b"\xc3":
        return None
    offset = int(offset)
    if (
        offset <= 0
        or offset >= _MAX_STRUCT_ACCESSOR_OFFSET
        or offset % _POSITION_MEMBER_ALIGNMENT_BYTES
    ):
        return None
    return offset


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
        field = _resolve_vital_field(image, name, helper_rva)
        if field is not None:
            fields.append(field)
    # Level and experience are proven through the experience-gauge wrapper's fixed member
    # getters; this build calculates the maxima through data-center calls, so a missing
    # member read is a hard failure rather than an adjacent-offset guess.
    level_offset, experience_offset = _discover_level_experience(image, window, status_call_rva)
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


def _resolve_vital_field(
    image: PeImage, name: str, helper_rva: int
) -> PlayerStatFieldProfile | None:
    """Return one vital field, or ``None`` when this build proves no bounded source for it.

    A proven ``current * scale / maximum`` ratio is emitted under ``name``; when only the
    current value has a bounded source (the maximum is computed at runtime, ADR-010) it is
    emitted under ``current_<name>`` and the percentage is left to the visual HUD reader.
    """

    try:
        evidence = analyze_ratio_function(image.read_rva(helper_rva, 96))
        return PlayerStatFieldProfile(
            name,
            RatioPlayerStatSource(
                evidence.numerator_offset,
                evidence.denominator_offset,
                evidence.primitive,
                evidence.scale,
            ),
            0.0,
            100.0,
        )
    except ClientProfilingError:
        pass
    try:
        wrapped = analyze_wrapped_vital_ratio(image, helper_rva)
    except ClientProfilingError:
        return None
    if wrapped.current_offset is not None and wrapped.max_offset is not None:
        return PlayerStatFieldProfile(
            name,
            RatioPlayerStatSource(
                wrapped.current_offset,
                wrapped.max_offset,
                PlayerStatType.I32,
                VITAL_RATIO_PERCENT_SCALE,
            ),
            0.0,
            100.0,
        )
    if name == "hp":
        xor = analyze_hp_xor_pair(image, wrapped.current_getter_rva)
        if xor is not None:
            return PlayerStatFieldProfile(
                "current_hp",
                XorPairPlayerStatSource(xor.offset, xor.key_a, xor.key_b, PlayerStatType.I64),
                0.0,
                float(2**31 - 1),
            )
    if wrapped.current_offset is not None:
        return PlayerStatFieldProfile(
            f"current_{name}",
            DirectPlayerStatSource(wrapped.current_offset, PlayerStatType.I32),
            0.0,
            float(2**31 - 1),
        )
    return None


# ``cvtsi2ss xmm0, eax`` follows every integer gauge percent; ``mov edx, 100`` precedes only
# the three vital wrappers, so the experience gauge wrapper is the one without it.
_CVTSI2SS_XMM0_EAX = b"\xf3\x0f\x2a\xc0"
_MOV_EDX_100 = b"\xba\x64\x00\x00\x00"


def _discover_level_experience(
    image: PeImage, status_window: bytes, status_call_rva: int
) -> tuple[int, int]:
    """Return ``(level_offset, experience_offset)`` from the experience-gauge wrapper."""

    exp_wrapper_rva: int | None = None
    search = 0
    while (marker := status_window.find(_CVTSI2SS_XMM0_EAX, search)) >= 0:
        search = marker + 1
        call_at = marker - 5
        if call_at < 0 or status_window[call_at] != 0xE8:
            continue
        if status_window[max(0, call_at - 10) : call_at - 5] == _MOV_EDX_100:
            continue  # an hp/mp/fp vital wrapper
        exp_wrapper_rva = relative_call_target(status_window, call_at, status_call_rva)
        break
    if exp_wrapper_rva is None:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "The status routine does not expose an experience gauge wrapper.",
        )
    members: dict[PlayerStatType, int] = {}
    try:
        body = image.read_rva(exp_wrapper_rva, 128)
    except ClientProfilingError as error:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "The experience gauge wrapper is unreadable.",
        ) from error
    for call_at in _relative_call_sites(body):
        evidence = _member_load_evidence(
            image, relative_call_target(body, call_at, exp_wrapper_rva)
        )
        if evidence is not None:
            members.setdefault(evidence[1], evidence[0])
    if PlayerStatType.I32 not in members or PlayerStatType.U64 not in members:
        raise ClientProfilingError(
            ClientProfilingErrorCode.INCOMPLETE_PLAYER_STATS,
            "Level and experience are not both exposed as fixed member reads.",
        )
    return members[PlayerStatType.I32], members[PlayerStatType.U64]


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


_DUNGEON_LOCKOUT_RTTI_NAMES = (
    ".?AVCWndDungeonCooldownList@@",
    ".?AVCWndDungeonCooldownQuick@@",
)
_DUNGEON_VTABLE_ENTRY_COUNT = 24
_DUNGEON_RENDER_SCAN_BYTES = 0x2000
# mov rcx,[rip+disp32]; call rel32  -> a helper invoked with a single pointer global as this.
_MOV_RCX_RIP = b"\x48\x8b\x0d"


def _discover_dungeon(image: PeImage, digest: str) -> ClientDungeonProfile:
    """Prove the account-wide dungeon lockout timestamp the cooldown UI reads (ADR-011).

    Per-dungeon cooldowns on this client family live only in transient UI-owned vectors with
    no fingerprint anchor, so the profiler binds the one bounded read the dungeon windows
    themselves perform: ``now < *(player + lockout_offset)``.
    """

    candidates: set[DungeonLockoutEvidence] = set()
    for decorated_name in _DUNGEON_LOCKOUT_RTTI_NAMES:
        try:
            rtti = resolve_primary_vtable(image, decorated_name)
        except ClientProfilingError:
            continue
        entries = struct.unpack(
            f"<{_DUNGEON_VTABLE_ENTRY_COUNT}Q",
            image.read_rva(rtti.primary_vtable_rva, _DUNGEON_VTABLE_ENTRY_COUNT * 8),
        )
        for entry in entries:
            candidates.update(_lockout_evidence_in(image, entry - image.image_base))
    if len(candidates) != 1:
        raise _incomplete_dungeon(
            "The dungeon cooldown windows do not expose one proven account lockout member."
        )
    item = next(iter(candidates))
    return ClientDungeonProfile(
        digest,
        item.runtime_state_pointer_rva,
        8,
        GlobalDungeonLockout(item.lockout_timestamp_offset),
    )


def _lockout_evidence_in(image: PeImage, function_rva: int) -> set[DungeonLockoutEvidence]:
    """Yield ``(player_global_rva, offset)`` for every proven lockout call in one function."""

    section = image.section_for_rva(function_rva, 1)
    if section is None or not section.executable:
        return set()
    try:
        start = image.rva_to_offset(function_rva)
    except ClientProfilingError:
        return set()
    end = min(start + _DUNGEON_RENDER_SCAN_BYTES, section.raw_offset + section.raw_size)
    body = image.data[start:end]
    found: set[DungeonLockoutEvidence] = set()
    cursor = 0
    while True:
        cursor = body.find(_MOV_RCX_RIP, cursor)
        if cursor < 0 or cursor + 12 > len(body):
            break
        if body[cursor + 7] == 0xE8:
            displacement = struct.unpack_from("<i", body, cursor + 3)[0]
            global_rva = resolve_rip_relative(function_rva + cursor, 7, displacement)
            section = image.section_for_rva(global_rva, 8)
            if section is not None and section.writable:
                helper_rva = relative_call_target(body, cursor + 7, function_rva)
                offset = analyze_dungeon_lockout_helper(image, helper_rva)
                if offset is not None:
                    found.add(DungeonLockoutEvidence(global_rva, offset))
        cursor += 1
    return found


def _incomplete_dungeon(detail: str) -> ClientProfilingError:
    return ClientProfilingError(ClientProfilingErrorCode.INCOMPLETE_DUNGEON, detail)
