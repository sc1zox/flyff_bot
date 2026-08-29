"""MSVC x64 RTTI TypeDescriptor and primary-VTable resolution."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from flyff_bot.features.client_profiling.models import (
    ClientProfilingError,
    ClientProfilingErrorCode,
)
from flyff_bot.features.client_profiling.pe import PeImage

COL_SIZE_BYTES = 24
TYPE_DESCRIPTOR_HEADER_BYTES = 16
POINTER_SIZE_BYTES = 8


@dataclass(frozen=True, slots=True)
class RttiType:
    decorated_name: str
    type_descriptor_rva: int
    complete_object_locator_rva: int
    primary_vtable_rva: int


def resolve_primary_vtable(image: PeImage, decorated_name: str) -> RttiType:
    """Return one uniquely validated primary table for an MSVC x64 class."""

    rdata = image.section_named(".rdata")
    payload = image.section_bytes(".rdata")
    name_bytes = decorated_name.encode("ascii") + b"\0"
    candidates: list[RttiType] = []
    for section in image.sections:
        section_bytes = image.section_bytes(section.name)
        search_offset = 0
        while True:
            search_offset = section_bytes.find(name_bytes, search_offset)
            if search_offset < 0:
                break
            if search_offset >= TYPE_DESCRIPTOR_HEADER_BYTES:
                type_rva = section.virtual_address + search_offset - TYPE_DESCRIPTOR_HEADER_BYTES
                for col_offset in range(0, len(payload) - COL_SIZE_BYTES + 1, 4):
                    signature, object_offset, _cd_offset, type_ref, _hierarchy, self_ref = (
                        struct.unpack_from("<IIIIII", payload, col_offset)
                    )
                    col_rva = rdata.virtual_address + col_offset
                    if (
                        signature != 1
                        or object_offset != 0
                        or type_ref != type_rva
                        or self_ref != col_rva
                    ):
                        continue
                    col_pointer = struct.pack("<Q", image.image_base + col_rva)
                    pointer_offset = 0
                    while True:
                        pointer_offset = payload.find(col_pointer, pointer_offset)
                        if pointer_offset < 0:
                            break
                        vtable_rva = rdata.virtual_address + pointer_offset + POINTER_SIZE_BYTES
                        if _valid_vtable(image, vtable_rva):
                            candidates.append(
                                RttiType(decorated_name, type_rva, col_rva, vtable_rva)
                            )
                        pointer_offset += 1
            search_offset += 1
    unique = {candidate.primary_vtable_rva: candidate for candidate in candidates}
    if len(unique) != 1:
        detail = "missing" if not unique else "ambiguous"
        raise ClientProfilingError(
            ClientProfilingErrorCode.MISSING_RTTI
            if not unique
            else ClientProfilingErrorCode.AMBIGUOUS_EVIDENCE,
            f"The primary VTable for {decorated_name} is {detail}.",
        )
    return next(iter(unique.values()))


def _valid_vtable(image: PeImage, vtable_rva: int) -> bool:
    try:
        entry = struct.unpack("<Q", image.read_rva(vtable_rva, POINTER_SIZE_BYTES))[0]
    except ClientProfilingError, struct.error:
        return False
    section = image.section_for_rva(entry - image.image_base)
    return section is not None and section.executable
