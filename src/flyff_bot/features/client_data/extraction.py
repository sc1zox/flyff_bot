"""Offline normalization of the client's static gameplay tables into one catalog (US-083).

Reading is strictly offline file I/O against a read-only copy of the client's own data
(ADR-005): no game process is opened and no client file is written. The pass reuses the
keyed-archive reader the quest extraction already owns rather than opening the archives a
second way.

A table that is absent, undecodable, or laid out differently than this build can read is
recorded as a typed rejection. Finding a file name is not ingestion: a table contributes to
the catalog only through rows this module actually parsed.
"""

from __future__ import annotations

from pathlib import Path

from flyff_bot.features.client_data.models import (
    CatalogRejection,
    CatalogRejectionReason,
    CatalogTable,
    ClientCatalog,
)
from flyff_bot.features.client_data.tables import (
    parse_drop_declarations,
    parse_item_table,
    parse_mover_table,
    parse_npc_table,
    parse_skill_table,
)
from flyff_bot.features.quests.client_tables import parse_text_catalog
from flyff_bot.features.quests.extraction import (
    CLIENT_SYSTEM_DIRECTORY,
    DEFAULT_QUEST_LANGUAGE,
    ClientDataArchives,
    language_archive_directory,
)

# The static tables this pass normalizes, and the language catalog naming each one's rows.
MOVER_TABLE_FILE = "propMover.txt"
MOVER_TEXT_CATALOG = "propMover.txt.txt"
DROP_TABLE_FILE = "PropMoverEx.inc"
ITEM_TABLE_FILE = "Spec_Item.txt"
ITEM_TEXT_CATALOG = "propItem.txt.txt"
SKILL_TABLE_FILE = "propSkill.txt"
SKILL_TEXT_CATALOG = "propSkill.txt.txt"
NPC_TABLE_FILE = "propCtrl.txt"
NPC_TEXT_CATALOG = "propCtrl.txt.txt"
# Named so the handlers below stay single-name `except` clauses. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
ARCHIVE_READ_ERRORS = (OSError, ValueError)


def _table_text(
    archives: ClientDataArchives,
    file_name: str,
    table: CatalogTable,
    rejections: list[CatalogRejection],
) -> str | None:
    """Return one packed table's text, recording why it is unavailable when it is not."""

    try:
        text = archives.read_text(file_name)
    except ARCHIVE_READ_ERRORS:
        rejections.append(
            CatalogRejection(table, CatalogRejectionReason.TABLE_UNREADABLE, file_name)
        )
        return None
    if text is None:
        rejections.append(CatalogRejection(table, CatalogRejectionReason.TABLE_MISSING, file_name))
        return None
    return text


def _text_catalog(archives: ClientDataArchives, file_name: str) -> dict[str, str]:
    """Return one language catalog, empty when the client ships none for that table."""

    try:
        text = archives.read_text(file_name)
    except ARCHIVE_READ_ERRORS:
        return {}
    return parse_text_catalog(text or "")


def extract_client_catalog(
    client_data_root: Path,
    *,
    language: str = DEFAULT_QUEST_LANGUAGE,
) -> ClientCatalog:
    """Return every static gameplay record this build can normalize from one client."""

    rejections: list[CatalogRejection] = []
    system = ClientDataArchives.open_directory(client_data_root / CLIENT_SYSTEM_DIRECTORY)
    catalogs = ClientDataArchives.open_directory(
        language_archive_directory(client_data_root, language)
    )

    mover_text = _table_text(system, MOVER_TABLE_FILE, CatalogTable.MOVERS, rejections)
    movers = (
        ()
        if mover_text is None
        else parse_mover_table(mover_text, _text_catalog(catalogs, MOVER_TEXT_CATALOG), rejections)
    )

    known_movers = frozenset(mover.symbol for mover in movers)
    drop_text = _table_text(system, DROP_TABLE_FILE, CatalogTable.DROPS, rejections)
    drops = (
        () if drop_text is None else parse_drop_declarations(drop_text, known_movers, rejections)
    )

    item_text = _table_text(system, ITEM_TABLE_FILE, CatalogTable.ITEMS, rejections)
    items = (
        ()
        if item_text is None
        else parse_item_table(item_text, _text_catalog(catalogs, ITEM_TEXT_CATALOG), rejections)
    )

    skill_text = _table_text(system, SKILL_TABLE_FILE, CatalogTable.SKILLS, rejections)
    skills = (
        ()
        if skill_text is None
        else parse_skill_table(skill_text, _text_catalog(catalogs, SKILL_TEXT_CATALOG), rejections)
    )

    npc_text = _table_text(system, NPC_TABLE_FILE, CatalogTable.NPCS, rejections)
    npcs = (
        ()
        if npc_text is None
        else parse_npc_table(npc_text, _text_catalog(catalogs, NPC_TEXT_CATALOG), rejections)
    )

    return ClientCatalog(
        movers=movers,
        drops=drops,
        items=items,
        skills=skills,
        npcs=npcs,
        rejections=tuple(rejections),
    )
