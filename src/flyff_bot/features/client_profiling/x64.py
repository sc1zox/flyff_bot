"""Targeted x64 instruction helpers; this is deliberately not a general disassembler."""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RipRelativeReference:
    instruction_rva: int
    instruction_size: int
    target_rva: int


def resolve_rip_relative(instruction_rva: int, instruction_size: int, displacement: int) -> int:
    """Resolve a signed x64 RIP displacement from the following instruction."""

    return instruction_rva + instruction_size + displacement


def find_rip_relative_pattern(
    code: bytes,
    code_rva: int,
    prefix: bytes,
    *,
    instruction_size: int,
) -> tuple[RipRelativeReference, ...]:
    """Resolve exact instructions whose disp32 begins immediately after ``prefix``."""

    references: list[RipRelativeReference] = []
    offset = 0
    while True:
        offset = code.find(prefix, offset)
        if offset < 0:
            break
        displacement_offset = offset + len(prefix)
        if displacement_offset + 4 <= len(code):
            displacement = struct.unpack_from("<i", code, displacement_offset)[0]
            instruction_rva = code_rva + offset
            references.append(
                RipRelativeReference(
                    instruction_rva,
                    instruction_size,
                    resolve_rip_relative(instruction_rva, instruction_size, displacement),
                )
            )
        offset += 1
    return tuple(references)


def relative_call_target(code: bytes, instruction_offset: int, code_rva: int) -> int:
    """Resolve one validated ``call rel32`` instruction."""

    if instruction_offset < 0 or instruction_offset + 5 > len(code):
        raise ValueError("The relative call is truncated.")
    if code[instruction_offset] != 0xE8:
        raise ValueError("The instruction is not call rel32.")
    displacement = struct.unpack_from("<i", code, instruction_offset + 1)[0]
    return resolve_rip_relative(code_rva + instruction_offset, 5, displacement)
