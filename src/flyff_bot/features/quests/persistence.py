"""Versioned JSON persistence for the extracted quest database."""

from __future__ import annotations

import json
from pathlib import Path

from flyff_bot.features.quests.models import QuestDatabase, QuestDefinition

QUEST_DATABASE_SCHEMA_VERSION = 1


class QuestDatabaseError(ValueError):
    """Raised when a persisted quest database cannot be read as the schema it claims."""


def save_quest_database(database: QuestDatabase, path: Path) -> Path:
    """Write the quest database as one canonical JSON document and return its path."""

    document = {
        "schema_version": QUEST_DATABASE_SCHEMA_VERSION,
        "language": database.language,
        "client_digest": database.client_digest,
        "quests": [quest.as_document() for quest in database.quests],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return path


def load_quest_database(path: Path) -> QuestDatabase:
    """Return the quest database stored at one path, validating its schema version."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QuestDatabaseError(f"The quest database at {path} could not be read.") from error
    if not isinstance(document, dict):
        raise QuestDatabaseError("A quest database document must be an object.")
    version = document.get("schema_version")
    if version != QUEST_DATABASE_SCHEMA_VERSION:
        raise QuestDatabaseError(
            f"The quest database declares schema version {version!r}, "
            f"not {QUEST_DATABASE_SCHEMA_VERSION}."
        )
    raw_quests = document.get("quests", [])
    if not isinstance(raw_quests, list):
        raise QuestDatabaseError("A quest database document needs a quests list.")
    try:
        quests = tuple(QuestDefinition.from_document(entry) for entry in raw_quests)
    except (ValueError, TypeError) as error:
        raise QuestDatabaseError(f"The quest database at {path} is malformed.") from error
    return QuestDatabase(
        quests=quests,
        client_digest=str(document.get("client_digest", "")),
        language=str(document.get("language", "")),
    )
