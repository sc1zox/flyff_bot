"""Small standard-library PE32+ parser used by the offline profiler."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from itertools import pairwise

from flyff_bot.features.client_profiling.models import (
    ClientProfilingError,
    ClientProfilingErrorCode,
)

AMD64_MACHINE = 0x8664
PE32_PLUS_MAGIC = 0x20B
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_WRITE = 0x80000000
SECTION_HEADER_SIZE = 40
RUNTIME_FUNCTION_SIZE = 12


@dataclass(frozen=True, slots=True)
class PeSection:
    """One validated PE section and its file-backed extent."""

    name: str
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int
    characteristics: int

    @property
    def mapped_size(self) -> int:
        return max(self.virtual_size, self.raw_size)

    @property
    def executable(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_EXECUTE)

    @property
    def writable(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_WRITE)

    def contains_rva(self, rva: int, size: int = 1) -> bool:
        return self.virtual_address <= rva and rva + size <= self.virtual_address + self.mapped_size

    def contains_file_backed_rva(self, rva: int, size: int = 1) -> bool:
        return self.virtual_address <= rva and rva + size <= self.virtual_address + self.raw_size


@dataclass(frozen=True, slots=True)
class RuntimeFunction:
    begin_rva: int
    end_rva: int


@dataclass(frozen=True, slots=True)
class PeImage:
    """Validated x64 PE image backed by one immutable byte buffer."""

    data: bytes
    image_base: int
    sections: tuple[PeSection, ...]
    data_directories: tuple[tuple[int, int], ...]

    @classmethod
    def parse(cls, data: bytes) -> PeImage:
        try:
            if data[:2] != b"MZ" or len(data) < 0x40:
                raise ValueError("Missing DOS header.")
            pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
            if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
                raise ValueError("Missing or truncated PE signature.")
            machine, section_count, _timestamp, _symbols, _symbol_count, optional_size, _flags = (
                struct.unpack_from("<HHIIIHH", data, pe_offset + 4)
            )
            if machine != AMD64_MACHINE:
                raise ClientProfilingError(
                    ClientProfilingErrorCode.UNSUPPORTED_MACHINE,
                    f"Expected AMD64 machine 0x{AMD64_MACHINE:04X}, got 0x{machine:04X}.",
                )
            optional_offset = pe_offset + 24
            if optional_offset + optional_size > len(data) or optional_size < 112:
                raise ValueError("The optional header is truncated.")
            if struct.unpack_from("<H", data, optional_offset)[0] != PE32_PLUS_MAGIC:
                raise ValueError("The executable is not PE32+.")
            image_base = struct.unpack_from("<Q", data, optional_offset + 24)[0]
            directory_count = min(struct.unpack_from("<I", data, optional_offset + 108)[0], 16)
            directories = tuple(
                struct.unpack_from("<II", data, optional_offset + 112 + index * 8)
                for index in range(directory_count)
                if optional_offset + 120 + index * 8 <= optional_offset + optional_size
            )
            section_offset = optional_offset + optional_size
            if section_count == 0 or section_offset + section_count * SECTION_HEADER_SIZE > len(
                data
            ):
                raise ValueError("The section table is empty or truncated.")
            sections: list[PeSection] = []
            for index in range(section_count):
                offset = section_offset + index * SECTION_HEADER_SIZE
                raw_name, virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                    "<8sIIII", data, offset
                )
                characteristics = struct.unpack_from("<I", data, offset + 36)[0]
                name = raw_name.split(b"\0", 1)[0].decode("ascii", errors="strict")
                if raw_size and (raw_offset <= 0 or raw_offset + raw_size > len(data)):
                    raise ValueError(f"Section {name} extends outside the executable.")
                sections.append(
                    PeSection(
                        name,
                        virtual_address,
                        virtual_size,
                        raw_offset,
                        raw_size,
                        characteristics,
                    )
                )
            _validate_non_overlapping_sections(sections)
            image = cls(data, image_base, tuple(sections), directories)
            for required in (".text", ".rdata", ".data"):
                image.section_named(required)
            return image
        except ClientProfilingError:
            raise
        except (UnicodeDecodeError, ValueError, struct.error) as error:
            raise ClientProfilingError(ClientProfilingErrorCode.INVALID_PE, str(error)) from error

    def section_named(self, name: str) -> PeSection:
        for section in self.sections:
            if section.name == name:
                return section
        raise ClientProfilingError(
            ClientProfilingErrorCode.MISSING_SECTION,
            f"The executable has no required {name} section.",
        )

    def section_for_rva(self, rva: int, size: int = 1) -> PeSection | None:
        return next((section for section in self.sections if section.contains_rva(rva, size)), None)

    def rva_to_offset(self, rva: int, size: int = 1) -> int:
        section = self.section_for_rva(rva, size)
        if section is None or not section.contains_file_backed_rva(rva, size):
            raise ClientProfilingError(
                ClientProfilingErrorCode.INVALID_PE,
                f"RVA 0x{rva:X} is not backed by {size} executable bytes.",
            )
        return section.raw_offset + rva - section.virtual_address

    def read_rva(self, rva: int, size: int) -> bytes:
        offset = self.rva_to_offset(rva, size)
        return self.data[offset : offset + size]

    def section_bytes(self, name: str) -> bytes:
        section = self.section_named(name)
        return self.data[section.raw_offset : section.raw_offset + section.raw_size]

    def function_ranges(self) -> tuple[RuntimeFunction, ...]:
        try:
            self.section_named(".pdata")
        except ClientProfilingError:
            return ()
        ranges: list[RuntimeFunction] = []
        payload = self.section_bytes(".pdata")
        for offset in range(0, len(payload) - RUNTIME_FUNCTION_SIZE + 1, RUNTIME_FUNCTION_SIZE):
            begin, end, _unwind = struct.unpack_from("<III", payload, offset)
            section = self.section_for_rva(begin, max(0, end - begin))
            if begin < end and section is not None and section.executable:
                ranges.append(RuntimeFunction(begin, end))
        return tuple(ranges)


def _validate_non_overlapping_sections(sections: list[PeSection]) -> None:
    ordered = sorted(sections, key=lambda section: section.virtual_address)
    for previous, current in pairwise(ordered):
        if previous.virtual_address + previous.mapped_size > current.virtual_address:
            raise ValueError(f"PE sections {previous.name} and {current.name} overlap in memory.")
