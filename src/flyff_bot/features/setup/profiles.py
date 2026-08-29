"""Executable identity helper shared by static setup stages."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

_PE_HEADER_OFFSET = 0x3C
_PE_MACHINE_OFFSET = 4
_MACHINE_X86 = 0x14C
_MACHINE_X64 = 0x8664


@dataclass(frozen=True, slots=True)
class ExecutableFingerprint:
    """The exact binary identity and declared architecture."""

    sha256: str
    machine_type: int | None

    @property
    def architecture(self) -> str:
        if self.machine_type == _MACHINE_X86:
            return "x86"
        if self.machine_type == _MACHINE_X64:
            return "x64"
        return "unknown"


def fingerprint_executable(path: Path) -> ExecutableFingerprint:
    """Hash the executable and inspect its PE machine field without writing it."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return ExecutableFingerprint(digest.hexdigest(), _pe_machine_type(path))


def _pe_machine_type(path: Path) -> int | None:
    try:
        with path.open("rb") as stream:
            stream.seek(_PE_HEADER_OFFSET)
            offset_bytes = stream.read(4)
            if len(offset_bytes) != 4:
                return None
            stream.seek(struct.unpack("<I", offset_bytes)[0] + _PE_MACHINE_OFFSET)
            machine_bytes = stream.read(2)
            return struct.unpack("<H", machine_bytes)[0] if len(machine_bytes) == 2 else None
    except OSError:
        return None
