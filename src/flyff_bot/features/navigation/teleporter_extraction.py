"""Offline extraction of the client's declared teleporter destinations."""

from __future__ import annotations

import json
import re
from collections.abc import MutableSequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from flyff_bot.features.navigation.client_archive import (
    ARCHIVE_INDEX_SUFFIX,
    ClientArchiveError,
    KeyedClientArchive,
)
from flyff_bot.features.navigation.teleporter_models import (
    TeleporterCatalog,
    TeleporterDestination,
)

TELEPORTER_ASSET_NAME = "TeleportOption.inc"
CLIENT_SYSTEM_DIRECTORY = "System3"
UTF16_BYTE_ORDER_MARKS = (b"\xff\xfe", b"\xfe\xff")
CLIENT_TEXT_FALLBACK_ENCODING = "cp1252"
TELEPORTER_DATABASE_SCHEMA_VERSION = 1

# The public Flyff source declares destinations with `AddTeleportOption`; the Entropia
# binary additionally exposes the plural spelling. Accepted forms are 3, 7, 8, and 10
# fields: the three-field form has identifier/name/world; seven adds description/level/
# category; eight adds search text; ten adds arrival-anchor X/Z. Only the ten-field form
# carries coordinates, and those remain unverified until a live client confirms them.
TELEPORTER_CALL_PATTERN = re.compile(
    r"\bAddTeleportOptions?\s*\((?P<arguments>[^)]*)\)", re.IGNORECASE
)


class TeleporterExtractionWarning(StrEnum):
    """Why teleporter data was skipped instead of guessed."""

    MISSING_CLIENT_ARCHIVE = "missing_client_archive"
    MISSING_TELEPORTER_ASSET = "missing_teleporter_asset"
    UNREADABLE_ARCHIVE = "unreadable_archive"
    MALFORMED_RECORD = "malformed_record"


@dataclass(frozen=True, slots=True)
class TeleporterExtractionDiagnostic:
    """One skipped archive or declaration, named for operator diagnosis."""

    warning: TeleporterExtractionWarning
    detail: str


def _strip_comments(source: str) -> str:
    """Remove C-style comments while preserving comment-like text inside literals."""

    result: list[str] = []
    index = 0
    in_string = False
    while index < len(source):
        character = source[index]
        if in_string:
            result.append(character)
            if character == "\\" and index + 1 < len(source):
                result.append(source[index + 1])
                index += 2
                continue
            if character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            result.append(character)
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index)
            index = len(source) if newline < 0 else newline
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        result.append(character)
        index += 1
    return "".join(result)


def _split_arguments(arguments: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    in_string = False
    escaped = False
    for character in arguments:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if in_string and character == "\\":
            current.append(character)
            escaped = True
            continue
        if character == '"':
            in_string = not in_string
            current.append(character)
            continue
        if character == "," and not in_string:
            fields.append("".join(current).strip())
            current.clear()
            continue
        current.append(character)
    fields.append("".join(current).strip())
    return fields


def _decode_field(field: str) -> str | int | float:
    if len(field) >= 2 and field.startswith('"') and field.endswith('"'):
        return field[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    try:
        return int(field)
    except ValueError:
        return float(field)


def parse_teleporter_destinations(
    source: str,
    diagnostics: MutableSequence[TeleporterExtractionDiagnostic] | None = None,
) -> tuple[TeleporterDestination, ...]:
    """Return every well-formed destination declaration in one decoded client asset."""

    destinations: list[TeleporterDestination] = []
    for match in TELEPORTER_CALL_PATTERN.finditer(_strip_comments(source)):
        raw_fields = _split_arguments(match["arguments"])
        try:
            values = [_decode_field(field) for field in raw_fields]
        except ValueError as error:
            if diagnostics is not None:
                diagnostics.append(
                    TeleporterExtractionDiagnostic(
                        TeleporterExtractionWarning.MALFORMED_RECORD,
                        f"column {match.start()}: {error}",
                    )
                )
            continue
        if len(values) == 10:
            (
                destination_id,
                name,
                world_id,
                description,
                minimum,
                maximum,
                category,
                search,
                anchor_x,
                anchor_z,
            ) = values
            numeric_values: tuple[object, ...] = (
                destination_id,
                world_id,
                minimum,
                maximum,
                anchor_x,
                anchor_z,
            )
        elif len(values) == 8:
            destination_id, name, world_id, description, minimum, maximum, category, search = values
            numeric_values = (destination_id, world_id, minimum, maximum, 0.0, 0.0)
        elif len(values) == 7:
            (
                destination_id,
                name,
                world_id,
                description,
                minimum,
                maximum,
                category_value,
            ) = values
            category = str(category_value)
            search = str(name)
            numeric_values = (destination_id, world_id, minimum, maximum, 0.0, 0.0)
        elif len(values) == 3:
            destination_id, name, world_id = values
            description = ""
            minimum = 0
            maximum = None
            category = "general"
            search = str(name)
            numeric_values = (destination_id, world_id, 0.0, 0.0)
        else:
            if diagnostics is not None:
                diagnostics.append(
                    TeleporterExtractionDiagnostic(
                        TeleporterExtractionWarning.MALFORMED_RECORD,
                        f"expected 3, 7, 8, or 10 fields, found {len(values)}",
                    )
                )
            continue
        if any(isinstance(value, str) for value in numeric_values):
            if diagnostics is not None:
                diagnostics.append(
                    TeleporterExtractionDiagnostic(
                        TeleporterExtractionWarning.MALFORMED_RECORD,
                        f"destination {name!r} has non-numeric metadata",
                    )
                )
            continue
        try:
            destinations.append(
                TeleporterDestination(
                    destination_id=int(destination_id),
                    name=str(name),
                    search_text=str(search),
                    world_id=int(world_id),
                    anchor_x=(
                        float(anchor_x)
                        if len(values) == 10 and isinstance(anchor_x, (int, float))
                        else 0.0
                    ),
                    anchor_z=(
                        float(anchor_z)
                        if len(values) == 10 and isinstance(anchor_z, (int, float))
                        else 0.0
                    ),
                    description=str(description),
                    minimum_level=int(minimum),
                    maximum_level=(
                        None
                        if isinstance(maximum, int) and maximum < 0
                        else (None if maximum is None else int(maximum))
                    ),
                    category=str(category),
                )
            )
        except ValueError as error:
            if diagnostics is not None:
                diagnostics.append(
                    TeleporterExtractionDiagnostic(
                        TeleporterExtractionWarning.MALFORMED_RECORD, str(error)
                    )
                )
    return tuple(destinations)


def _decode_client_text(payload: bytes) -> str:
    if payload[:2] in UTF16_BYTE_ORDER_MARKS:
        return payload.decode("utf-16", errors="replace")
    return payload.decode(CLIENT_TEXT_FALLBACK_ENCODING, errors="replace")


def extract_teleporter_catalog(
    client_data_root: Path,
    *,
    diagnostics: MutableSequence[TeleporterExtractionDiagnostic] | None = None,
) -> TeleporterCatalog:
    """Return destinations from the loose asset or the keyed System3 archives."""

    loose_path = client_data_root / CLIENT_SYSTEM_DIRECTORY / TELEPORTER_ASSET_NAME
    if loose_path.is_file():
        destinations = parse_teleporter_destinations(
            _decode_client_text(loose_path.read_bytes()), diagnostics
        )
        return TeleporterCatalog(destinations)

    directory = client_data_root / CLIENT_SYSTEM_DIRECTORY
    archives = [
        archive
        for path in sorted(directory.glob(f"*{ARCHIVE_INDEX_SUFFIX}"))
        if (archive := KeyedClientArchive.open_pair(path)) is not None
    ]
    if not archives:
        if diagnostics is not None:
            diagnostics.append(
                TeleporterExtractionDiagnostic(
                    TeleporterExtractionWarning.MISSING_CLIENT_ARCHIVE, str(directory)
                )
            )
        return TeleporterCatalog(())

    payload: bytes | None = None
    for archive in archives:
        try:
            candidate = archive.read(TELEPORTER_ASSET_NAME)
        except ClientArchiveError as error:
            if diagnostics is not None:
                diagnostics.append(
                    TeleporterExtractionDiagnostic(
                        TeleporterExtractionWarning.UNREADABLE_ARCHIVE,
                        f"{archive.name}: {error}",
                    )
                )
            continue
        if candidate is not None:
            payload = candidate
            break
    if payload is None:
        if diagnostics is not None:
            diagnostics.append(
                TeleporterExtractionDiagnostic(
                    TeleporterExtractionWarning.MISSING_TELEPORTER_ASSET,
                    str(loose_path),
                )
            )
        return TeleporterCatalog(())
    destinations = parse_teleporter_destinations(
        _decode_client_text(payload),
        diagnostics,
    )
    return TeleporterCatalog(destinations)


def save_teleporter_catalog(catalog: TeleporterCatalog, path: Path) -> Path:
    """Write the catalog as canonical schema-v1 JSON."""

    document = {
        "schema_version": TELEPORTER_DATABASE_SCHEMA_VERSION,
        "destinations": [
            {
                "destination_id": item.destination_id,
                "name": item.name,
                "search_text": item.search_text,
                "world_id": item.world_id,
                "anchor_x": item.anchor_x,
                "anchor_z": item.anchor_z,
                "description": item.description,
                "minimum_level": item.minimum_level,
                "maximum_level": item.maximum_level,
                "category": item.category,
            }
            for item in catalog.destinations
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return path


def load_teleporter_catalog(path: Path) -> TeleporterCatalog:
    """Load a canonical schema-v1 catalog, or an empty catalog when it is absent."""

    if not path.is_file():
        return TeleporterCatalog(())
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        records = document["destinations"]
        if document["schema_version"] != TELEPORTER_DATABASE_SCHEMA_VERSION or not isinstance(
            records,
            list,
        ):
            raise ValueError("Unsupported teleporter catalog")
        destinations = tuple(
            TeleporterDestination(
                destination_id=int(record["destination_id"]),
                name=str(record["name"]),
                search_text=str(record["search_text"]),
                world_id=int(record["world_id"]),
                anchor_x=float(record.get("anchor_x", 0.0)),
                anchor_z=float(record.get("anchor_z", 0.0)),
                description=str(record.get("description", "")),
                minimum_level=int(record.get("minimum_level", 0)),
                maximum_level=(
                    None if record.get("maximum_level") is None else int(record["maximum_level"])
                ),
                category=str(record.get("category", "general")),
            )
            for record in records
            if isinstance(record, dict)
        )
        return TeleporterCatalog(destinations)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return TeleporterCatalog(())
