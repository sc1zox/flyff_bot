"""Offline reader for the client's packed ``.one`` / ``.hdr`` world archives (US-052).

Every client region ships one archive pair. The ``.hdr`` file is the index: a file count
followed by one record per packed file, each holding a length-prefixed identity string and
the entry's byte offset and size inside the ``.one`` payload. The identity is a 64-character
digest of the original file name, so the index alone never reveals what an entry is called.

Each entry's bytes are obfuscated with a keystream derived from the original *file name*:

    stored[i] = swap_nibbles(plain[i]) ^ ((name[i % len(name)] - 1) & 0xFF)

The name is the plain lower-case file name, so the transform is its own inverse once the
name is known. That is what makes the index's opaque identities irrelevant here: a terrain
block's name follows the client's own ``<world><xx>-<zz>.lnd`` convention, and the first
twelve plaintext bytes of such a block are known in advance (version and block coordinates),
so a caller can encode that prefix and look the entry up by its stored bytes.

Reading is strictly offline file I/O against a read-only copy of the client's own data: no
game process is opened, and no client file is ever written.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

ARCHIVE_INDEX_SUFFIX = ".hdr"
ARCHIVE_DATA_SUFFIX = ".one"

# The client writes its file names as single-byte Windows text.
ARCHIVE_NAME_ENCODING = "cp1252"
# The keystream is the file name shifted down by one, not the file name itself.
ARCHIVE_KEY_SHIFT = 1

# `.hdr` layout: `int32 count`, then per entry `int32 name_length`, the identity bytes, and
# `int32 offset` plus `int32 size`.
ARCHIVE_INDEX_COUNT_BYTES = 4
ARCHIVE_INDEX_FIELD_BYTES = 4
ARCHIVE_INDEX_ENTRY_TRAILER_BYTES = 8


class ClientArchiveError(ValueError):
    """Raised when a client archive cannot be read as the container it claims to be."""


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """One packed file: the index's opaque identity and where its bytes live."""

    identity: str
    offset: int
    size: int

    def __post_init__(self) -> None:
        if self.offset < 0 or self.size < 0:
            raise ClientArchiveError("An archive entry must have a non-negative offset and size.")


def _nibble_swap_table() -> bytes:
    return bytes(((value << 4) | (value >> 4)) & 0xFF for value in range(256))


_NIBBLE_SWAP = _nibble_swap_table()
_DECODE_TABLES = tuple(
    bytes(_NIBBLE_SWAP[value ^ ((key - ARCHIVE_KEY_SHIFT) & 0xFF)] for value in range(256))
    for key in range(256)
)
_ENCODE_TABLES = tuple(
    bytes(_NIBBLE_SWAP[value] ^ ((key - ARCHIVE_KEY_SHIFT) & 0xFF) for value in range(256))
    for key in range(256)
)


def _apply_keystream(payload: bytes, file_name: str, tables: tuple[bytes, ...]) -> bytes:
    key = file_name.lower().encode(ARCHIVE_NAME_ENCODING, errors="replace")
    if not key:
        raise ClientArchiveError("An archive entry's key is its file name and cannot be empty.")
    transformed = bytearray(len(payload))
    for index, code in enumerate(key):
        transformed[index :: len(key)] = payload[index :: len(key)].translate(tables[code])
    return bytes(transformed)


def decode_archive_payload(payload: bytes, file_name: str) -> bytes:
    """Return the original bytes of one packed file, given the name it was packed under."""

    return _apply_keystream(payload, file_name, _DECODE_TABLES)


def encode_archive_payload(payload: bytes, file_name: str) -> bytes:
    """Return the stored form of some bytes, which is how an entry is recognized.

    This never writes to the client. It exists so a caller that knows a file's leading
    plaintext can rebuild the stored bytes and find that entry in the index.
    """

    return _apply_keystream(payload, file_name, _ENCODE_TABLES)


def read_archive_index(payload: bytes) -> tuple[ArchiveEntry, ...]:
    """Return every entry declared by one ``.hdr`` index.

    The index must describe itself exactly: a record that runs past the end of the file, a
    non-positive name length, or trailing bytes after the last record all mean this is not
    the index layout read here, and are reported rather than guessed at.
    """

    if len(payload) < ARCHIVE_INDEX_COUNT_BYTES:
        raise ClientArchiveError("An archive index is too short to carry its entry count.")
    (count,) = struct.unpack_from("<i", payload, 0)
    if count < 0:
        raise ClientArchiveError("An archive index cannot declare a negative entry count.")
    entries: list[ArchiveEntry] = []
    offset = ARCHIVE_INDEX_COUNT_BYTES
    for _ in range(count):
        if offset + ARCHIVE_INDEX_FIELD_BYTES > len(payload):
            raise ClientArchiveError("An archive index ended inside an entry record.")
        (name_length,) = struct.unpack_from("<i", payload, offset)
        offset += ARCHIVE_INDEX_FIELD_BYTES
        remaining = len(payload) - offset
        if name_length <= 0 or name_length + ARCHIVE_INDEX_ENTRY_TRAILER_BYTES > remaining:
            raise ClientArchiveError("An archive index entry declared an unusable name length.")
        identity = payload[offset : offset + name_length].decode("ascii", errors="replace")
        offset += name_length
        entry_offset, entry_size = struct.unpack_from("<2i", payload, offset)
        offset += ARCHIVE_INDEX_ENTRY_TRAILER_BYTES
        entries.append(ArchiveEntry(identity, entry_offset, entry_size))
    if offset != len(payload):
        raise ClientArchiveError("An archive index carried unexpected trailing bytes.")
    return tuple(entries)


class ClientWorldArchive:
    """Random-access reader over one client region's ``.hdr`` / ``.one`` archive pair."""

    def __init__(self, index_path: Path, data_path: Path) -> None:
        self.world_stem = data_path.stem
        self._data_path = data_path
        self._data_size = data_path.stat().st_size
        self._entries = read_archive_index(index_path.read_bytes())
        self._stream: BinaryIO | None = None
        self._stored_prefixes: dict[int, dict[bytes, ArchiveEntry]] = {}

    @classmethod
    def find(cls, world_directory: Path) -> ClientWorldArchive | None:
        """Open the region's archive pair, or return ``None`` when it ships no archive."""

        index_paths = sorted(
            path
            for path in world_directory.iterdir()
            if path.is_file() and path.suffix.lower() == ARCHIVE_INDEX_SUFFIX
        )
        for index_path in index_paths:
            data_path = index_path.with_suffix(ARCHIVE_DATA_SUFFIX)
            if data_path.is_file():
                return cls(index_path, data_path)
        return None

    @property
    def entries(self) -> tuple[ArchiveEntry, ...]:
        """Return every entry the index declares."""

        return self._entries

    def read(self, file_name: str, stored_prefix: bytes) -> bytes | None:
        """Return one entry's decoded bytes, found by the stored form of its leading bytes.

        ``None`` means the archive holds no entry that starts with those bytes, which is the
        normal answer for a terrain block the region simply does not have.
        """

        if not stored_prefix:
            raise ClientArchiveError("Locating an archive entry needs a non-empty prefix.")
        entry = self._prefix_index(len(stored_prefix)).get(stored_prefix)
        if entry is None:
            return None
        return decode_archive_payload(self._read_stored(entry.offset, entry.size), file_name)

    def close(self) -> None:
        """Release the archive's file handle."""

        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def __enter__(self) -> ClientWorldArchive:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _prefix_index(self, prefix_length: int) -> dict[bytes, ArchiveEntry]:
        cached = self._stored_prefixes.get(prefix_length)
        if cached is not None:
            return cached
        index: dict[bytes, ArchiveEntry] = {}
        for entry in self._entries:
            if entry.size < prefix_length:
                continue
            index.setdefault(self._read_stored(entry.offset, prefix_length), entry)
        self._stored_prefixes[prefix_length] = index
        return index

    def _read_stored(self, offset: int, size: int) -> bytes:
        if offset + size > self._data_size:
            raise ClientArchiveError("An archive entry reaches past the end of its payload.")
        if self._stream is None:
            self._stream = self._data_path.open("rb")
        self._stream.seek(offset)
        payload = self._stream.read(size)
        if len(payload) != size:
            raise ClientArchiveError("An archive entry was shorter than the index declared.")
        return payload


# --- Keyed archive generation (US-061) ------------------------------------------------
#
# Newer Entropia archives ship a second `.hdr` layout and a second payload transform. The
# index record gains a leading `int32 -1` marker, its offset field stores the negated start
# of the entry region, and its size field stores the file length minus the fixed region
# header. Entry payloads are no longer keyed by the plain file name; the keystream advances
# with the byte position and is seeded from the file name's adjacent-character XOR:
#
#     seed      = (length - 1 + (name[i % n] ^ name[(i + 1) % n]) + i) & 0xFF
#     stored[i] = swap_nibbles(plain[i]) ^ seed
#
# The index identity is a salted digest of the lower-case file name, so an entry can be
# addressed by name instead of by a known plaintext prefix. Reading stays offline and
# read-only; nothing here writes to the client.

# Marker that opens every record of the keyed index layout.
KEYED_ARCHIVE_RECORD_MARKER = -1
# Bytes each keyed entry reserves ahead of the length its index record declares.
KEYED_ARCHIVE_REGION_HEADER_BYTES = 10
# Salt the client mixes into the file name before digesting it into the index identity.
KEYED_ARCHIVE_IDENTITY_SALT = b"m1k3d3RS945TI!"
# Length of the hexadecimal identity the index stores per entry.
KEYED_ARCHIVE_IDENTITY_LENGTH = 64


def keyed_archive_identity(file_name: str) -> str:
    """Return the index identity one keyed archive stores for a file name."""

    lowered = file_name.lower().encode(ARCHIVE_NAME_ENCODING, errors="replace")
    return hashlib.sha256(KEYED_ARCHIVE_IDENTITY_SALT + lowered).hexdigest()


def decode_keyed_payload(payload: bytes, file_name: str) -> bytes:
    """Return the original bytes of one entry stored by the keyed archive generation."""

    key = file_name.lower().encode(ARCHIVE_NAME_ENCODING, errors="replace")
    if not key:
        raise ClientArchiveError(
            "A keyed archive entry's seed is its file name and cannot be empty."
        )
    span = len(key)
    seed = (len(payload) - 1) & 0xFF
    plain = bytearray(len(payload))
    for position, stored in enumerate(payload):
        mixed = key[position % span] ^ key[(position + 1) % span]
        plain[position] = _NIBBLE_SWAP[stored ^ ((seed + mixed + position) & 0xFF)]
    return bytes(plain)


def read_keyed_archive_index(payload: bytes) -> tuple[ArchiveEntry, ...]:
    """Return every entry declared by one keyed ``.hdr`` index.

    Offsets are stored negated and sizes exclude the fixed region header, so both are
    normalized here into the absolute start and the true byte length of the packed file.
    """

    if len(payload) < ARCHIVE_INDEX_COUNT_BYTES:
        raise ClientArchiveError("An archive index is too short to carry its entry count.")
    (count,) = struct.unpack_from("<i", payload, 0)
    if count < 0:
        raise ClientArchiveError("An archive index cannot declare a negative entry count.")
    entries: list[ArchiveEntry] = []
    offset = ARCHIVE_INDEX_COUNT_BYTES
    for _ in range(count):
        if offset + 2 * ARCHIVE_INDEX_FIELD_BYTES > len(payload):
            raise ClientArchiveError("An archive index ended inside an entry record.")
        (marker,) = struct.unpack_from("<i", payload, offset)
        if marker != KEYED_ARCHIVE_RECORD_MARKER:
            raise ClientArchiveError("An archive index record is not in the keyed layout.")
        offset += ARCHIVE_INDEX_FIELD_BYTES
        (name_length,) = struct.unpack_from("<i", payload, offset)
        offset += ARCHIVE_INDEX_FIELD_BYTES
        remaining = len(payload) - offset
        if name_length <= 0 or name_length + ARCHIVE_INDEX_ENTRY_TRAILER_BYTES > remaining:
            raise ClientArchiveError("An archive index entry declared an unusable name length.")
        identity = payload[offset : offset + name_length].decode("ascii", errors="replace")
        offset += name_length
        stored_offset, stored_size = struct.unpack_from("<2i", payload, offset)
        offset += ARCHIVE_INDEX_ENTRY_TRAILER_BYTES
        length = stored_size + KEYED_ARCHIVE_REGION_HEADER_BYTES
        if length < 0:
            # A retired entry declares a negative length; it holds no file at all.
            continue
        entries.append(ArchiveEntry(identity, -stored_offset, length))
    if offset != len(payload):
        raise ClientArchiveError("An archive index carried unexpected trailing bytes.")
    return tuple(entries)


class KeyedClientArchive:
    """Name-addressed reader over one keyed ``.hdr`` / ``.one`` archive pair."""

    def __init__(self, index_path: Path, data_path: Path) -> None:
        self.name = data_path.stem
        self._data_path = data_path
        self._data_size = data_path.stat().st_size
        self._entries = {
            entry.identity: entry for entry in read_keyed_archive_index(index_path.read_bytes())
        }

    @staticmethod
    def is_keyed_index(payload: bytes) -> bool:
        """Return whether one ``.hdr`` payload opens with a keyed index record."""

        if len(payload) < ARCHIVE_INDEX_COUNT_BYTES + ARCHIVE_INDEX_FIELD_BYTES:
            return False
        (marker,) = struct.unpack_from("<i", payload, ARCHIVE_INDEX_COUNT_BYTES)
        return bool(marker == KEYED_ARCHIVE_RECORD_MARKER)

    @classmethod
    def open_pair(cls, index_path: Path) -> KeyedClientArchive | None:
        """Open the pair an index belongs to, or return ``None`` when it is not keyed."""

        data_path = index_path.with_suffix(ARCHIVE_DATA_SUFFIX)
        if not data_path.is_file():
            return None
        if not cls.is_keyed_index(index_path.read_bytes()):
            return None
        return cls(index_path, data_path)

    @property
    def entry_count(self) -> int:
        """Return how many packed files this archive declares."""

        return len(self._entries)

    def read(self, file_name: str) -> bytes | None:
        """Return one packed file's decoded bytes, or ``None`` when it is not held here."""

        entry = self._entries.get(keyed_archive_identity(file_name))
        if entry is None:
            return None
        if entry.offset + entry.size > self._data_size:
            raise ClientArchiveError("An archive entry reaches past the end of its payload.")
        with self._data_path.open("rb") as stream:
            stream.seek(entry.offset)
            stored = stream.read(entry.size)
        if len(stored) != entry.size:
            raise ClientArchiveError("An archive entry was shorter than the index declared.")
        return decode_keyed_payload(stored, file_name)
