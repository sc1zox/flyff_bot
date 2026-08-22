"""Versioned JSON persistence for the extracted dungeon database."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from flyff_bot.features.dungeons.models import DungeonDefinition

DUNGEON_DATABASE_SCHEMA_VERSION = 1


class DungeonDatabaseError(ValueError):
    """Raised when a persisted dungeon artifact does not match its declared schema."""


def save_dungeon_database(
    dungeons: Sequence[DungeonDefinition],
    path: Path,
    *,
    language: str,
    client_digest: str,
) -> Path:
    """Write definitions canonically without copying any raw client asset."""

    document = {
        "schema_version": DUNGEON_DATABASE_SCHEMA_VERSION,
        "language": language,
        "client_digest": client_digest,
        "dungeons": [dungeon.as_document() for dungeon in dungeons],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def load_dungeon_database(path: Path) -> tuple[DungeonDefinition, ...]:
    """Return validated definitions from the packaged/operator artifact."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DungeonDatabaseError(f"The dungeon database at {path} could not be read.") from error
    if not isinstance(document, dict):
        raise DungeonDatabaseError("A dungeon database document must be an object.")
    if document.get("schema_version") != DUNGEON_DATABASE_SCHEMA_VERSION:
        raise DungeonDatabaseError(
            f"The dungeon database at {path} declares schema version "
            f"{document.get('schema_version')!r}, not {DUNGEON_DATABASE_SCHEMA_VERSION}."
        )
    documents = document.get("dungeons")
    if not isinstance(documents, list):
        raise DungeonDatabaseError("A dungeon database needs a dungeons array.")
    seen: set[int] = set()
    dungeons: list[DungeonDefinition] = []
    for index, item in enumerate(documents):
        if not isinstance(item, dict):
            raise DungeonDatabaseError(f"Dungeon entry {index} must be an object.")
        try:
            dungeon = DungeonDefinition.from_document(item)
        except ValueError as error:
            raise DungeonDatabaseError(f"Dungeon entry {index} is invalid: {error}") from error
        if dungeon.dungeon_id in seen:
            raise DungeonDatabaseError(
                f"The dungeon database repeats dungeon ID {dungeon.dungeon_id}."
            )
        seen.add(dungeon.dungeon_id)
        dungeons.append(dungeon)
    return tuple(dungeons)
