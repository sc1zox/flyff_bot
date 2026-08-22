"""Versioned JSON persistence for the extracted quest database."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.quests.goals import DEFAULT_QUEST_INTERACTION_RADIUS_UNITS, QuestNpc
from flyff_bot.features.quests.models import QuestDatabase, QuestDefinition

QUEST_DATABASE_SCHEMA_VERSION = 1
# The operator-authored NPC locations are deliberately separate from extracted quests:
# the current client evidence names objective coordinates but not giver/finisher identity.
QUEST_NPC_SCHEMA_VERSION = 1


class QuestDatabaseError(ValueError):
    """Raised when a persisted quest database cannot be read as the schema it claims."""


def save_quest_npc_positions(positions: Mapping[str, QuestNpc], path: Path) -> Path:
    """Write explicit NPC locations as one canonical JSON document and return its path."""

    document = {
        "schema_version": QUEST_NPC_SCHEMA_VERSION,
        "positions": {
            key: _npc_document(npc)
            for key, npc in positions.items()
            if npc.is_resolved and npc.position is not None
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return path


def load_quest_npc_positions(path: Path) -> dict[str, QuestNpc]:
    """Return explicitly configured NPC locations keyed by quest and interaction role."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QuestDatabaseError(f"The quest NPC file at {path} could not be read.") from error
    if not isinstance(document, dict):
        raise QuestDatabaseError("A quest NPC document must be an object.")
    version = document.get("schema_version")
    if version != QUEST_NPC_SCHEMA_VERSION:
        raise QuestDatabaseError(
            f"The quest NPC document declares schema version {version!r}, "
            f"not {QUEST_NPC_SCHEMA_VERSION}."
        )
    raw_positions = document.get("positions")
    if not isinstance(raw_positions, dict):
        raise QuestDatabaseError("A quest NPC document needs a positions object.")
    try:
        return {
            str(key): _quest_npc(_mapping(value, f"NPC position {key}"))
            for key, value in raw_positions.items()
        }
    except (TypeError, ValueError) as error:
        raise QuestDatabaseError(f"The quest NPC document at {path} is malformed.") from error


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"A quest NPC document needs a {label} object.")
    return value


def _quest_npc(document: dict[str, object]) -> QuestNpc:
    name = document.get("name")
    x = document.get("x")
    y = document.get("y")
    z = document.get("z")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A quest NPC needs a display name.")
    raw_radius = document.get("interaction_radius_units", DEFAULT_QUEST_INTERACTION_RADIUS_UNITS)
    if any(not isinstance(value, int | float) or isinstance(value, bool) for value in (x, y, z)):
        raise ValueError("A quest NPC position must contain numeric x, y, and z values.")
    if not isinstance(raw_radius, int | float) or isinstance(raw_radius, bool) or raw_radius <= 0.0:
        raise ValueError("A quest NPC interaction radius must be positive.")
    assert isinstance(x, int | float)
    assert isinstance(y, int | float)
    assert isinstance(z, int | float)
    position = WorldPosition(float(x), float(y), float(z))
    if not all(math.isfinite(value) for value in (position.x, position.y, position.z)):
        raise ValueError("A quest NPC position must be finite.")
    return QuestNpc(
        name=name,
        position=position,
        interaction_radius_units=float(raw_radius),
    )


def _npc_document(npc: QuestNpc) -> dict[str, object]:
    position = npc.position
    if position is None:
        raise ValueError("A persisted quest NPC must have a position.")
    return {
        "name": npc.name,
        "x": position.x,
        "y": position.y,
        "z": position.z,
        "interaction_radius_units": npc.interaction_radius_units,
    }


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
