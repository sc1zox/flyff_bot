"""Offline extraction of the client's quest database into a repository artifact.

Reading is strictly offline file I/O against a read-only copy of the client's own data
(ADR-005): no game process is opened, and no client file is written. The pass unpacks the
quest scripts, the monster and item property tables, and one language's text catalogs, then
parses them into :class:`QuestDatabase`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from flyff_bot.features.navigation.client_archive import (
    ARCHIVE_INDEX_SUFFIX,
    ClientArchiveError,
    KeyedClientArchive,
)
from flyff_bot.features.quests.client_tables import (
    ITEM_SYMBOL_PREFIX,
    MONSTER_SYMBOL_PREFIX,
    decode_client_text,
    parse_symbol_names,
    parse_text_catalog,
)
from flyff_bot.features.quests.models import QuestCollection, QuestDatabase, QuestDefinition
from flyff_bot.features.quests.script_parser import parse_quest_script

# Where the client keeps its property tables, quest scripts, and language catalogs.
CLIENT_SYSTEM_DIRECTORY = "System2"
CLIENT_LANGUAGE_DIRECTORY = "Lang"
# The language folders the client ships; the catalog inside is named after the folder.
DEFAULT_QUEST_LANGUAGE = "English"

# Quest scripts declared by `masquerade.prj`, paired with the collection they belong to.
QUEST_SCRIPTS: tuple[tuple[str, QuestCollection], ...] = (
    ("propQuest.inc", QuestCollection.GENERAL),
    ("propQuest-Scenario.inc", QuestCollection.SCENARIO),
    ("propQuest-RequestBox.inc", QuestCollection.OFFICE),
    ("propQuest-RequestBox2.inc", QuestCollection.OFFICE),
    ("propQuest-DungeonandPK.inc", QuestCollection.DUNGEON),
)
# The language catalog belonging to each quest script.
QUEST_TEXT_CATALOGS: Mapping[str, str] = {
    "propQuest.inc": "propQuest.txt.txt",
    "propQuest-Scenario.inc": "propQuest-Scenario.txt.txt",
    "propQuest-RequestBox.inc": "propQuest-RequestBox.txt.txt",
    "propQuest-RequestBox2.inc": "propQuest-RequestBox2.txt.txt",
    "propQuest-DungeonandPK.inc": "propQuest-DungeonandPK.txt.txt",
}
MONSTER_TABLE_FILE = "propMover.txt"
MONSTER_TEXT_CATALOG = "propMover.txt.txt"
ITEM_TABLE_FILE = "Spec_Item.txt"
ITEM_TEXT_CATALOG = "propItem.txt.txt"


class QuestExtractionWarning(StrEnum):
    """Why one part of the client's quest data was skipped instead of extracted."""

    # The client directory holds no keyed archive to read quest data from.
    NO_CLIENT_ARCHIVE = "no_client_archive"
    # One declared quest script is not packed in any archive that was opened.
    MISSING_QUEST_SCRIPT = "missing_quest_script"
    # One property table or language catalog is missing, so labels stay symbolic.
    MISSING_CLIENT_TABLE = "missing_client_table"
    # One archive declared an index this reader cannot describe.
    UNREADABLE_ARCHIVE = "unreadable_archive"


@dataclass(frozen=True, slots=True)
class QuestExtractionDiagnostic:
    """One skipped part of the quest data, named so the operator can see what was lost."""

    warning: QuestExtractionWarning
    detail: str


class ClientDataArchives:
    """The keyed archives of one client directory, addressed by packed file name."""

    def __init__(self, archives: Sequence[KeyedClientArchive]) -> None:
        self._archives = tuple(archives)

    @classmethod
    def open_directory(
        cls,
        directory: Path,
        diagnostics: list[QuestExtractionDiagnostic] | None = None,
    ) -> ClientDataArchives:
        """Open every keyed archive one directory ships, skipping the other layouts."""

        opened: list[KeyedClientArchive] = []
        if directory.is_dir():
            for index_path in sorted(directory.iterdir()):
                if not index_path.is_file() or index_path.suffix.lower() != ARCHIVE_INDEX_SUFFIX:
                    continue
                try:
                    archive = KeyedClientArchive.open_pair(index_path)
                except ClientArchiveError as error:
                    if diagnostics is not None:
                        diagnostics.append(
                            QuestExtractionDiagnostic(
                                QuestExtractionWarning.UNREADABLE_ARCHIVE,
                                f"{index_path.name}: {error}",
                            )
                        )
                    continue
                if archive is not None:
                    opened.append(archive)
        return cls(opened)

    @property
    def is_empty(self) -> bool:
        """Return whether no keyed archive was opened at all."""

        return not self._archives

    def read(self, file_name: str) -> bytes | None:
        """Return one packed file's decoded bytes from whichever archive holds it."""

        for archive in self._archives:
            payload = archive.read(file_name)
            if payload is not None:
                return payload
        return None

    def read_text(self, file_name: str) -> str | None:
        """Return one packed text file's decoded contents."""

        payload = self.read(file_name)
        return None if payload is None else decode_client_text(payload)


def language_archive_directory(client_data_root: Path, language: str) -> Path:
    """Return the directory holding one language's packed text catalogs."""

    return client_data_root / CLIENT_SYSTEM_DIRECTORY / CLIENT_LANGUAGE_DIRECTORY / language


def extract_quest_database(
    client_data_root: Path,
    *,
    language: str = DEFAULT_QUEST_LANGUAGE,
    diagnostics: list[QuestExtractionDiagnostic] | None = None,
) -> QuestDatabase:
    """Return every quest the client declares, with its text and symbols resolved."""

    system = ClientDataArchives.open_directory(
        client_data_root / CLIENT_SYSTEM_DIRECTORY, diagnostics
    )
    if system.is_empty:
        _report(
            diagnostics,
            QuestExtractionWarning.NO_CLIENT_ARCHIVE,
            str(client_data_root / CLIENT_SYSTEM_DIRECTORY),
        )
        return QuestDatabase(language=language)
    catalogs = ClientDataArchives.open_directory(
        language_archive_directory(client_data_root, language), diagnostics
    )

    monster_names = _symbol_names(
        system,
        catalogs,
        MONSTER_TABLE_FILE,
        MONSTER_TEXT_CATALOG,
        MONSTER_SYMBOL_PREFIX,
        diagnostics,
    )
    item_names = _symbol_names(
        system, catalogs, ITEM_TABLE_FILE, ITEM_TEXT_CATALOG, ITEM_SYMBOL_PREFIX, diagnostics
    )

    quests: list[QuestDefinition] = []
    seen: set[str] = set()
    for script_name, collection in QUEST_SCRIPTS:
        script = system.read_text(script_name)
        if script is None:
            _report(diagnostics, QuestExtractionWarning.MISSING_QUEST_SCRIPT, script_name)
            continue
        catalog_name = QUEST_TEXT_CATALOGS[script_name]
        catalog_text = catalogs.read_text(catalog_name)
        if catalog_text is None:
            _report(diagnostics, QuestExtractionWarning.MISSING_CLIENT_TABLE, catalog_name)
        strings = parse_text_catalog(catalog_text or "")
        for quest in parse_quest_script(
            script,
            collection,
            strings=strings,
            monster_names=monster_names,
            item_names=item_names,
        ):
            if quest.quest_id in seen:
                continue
            seen.add(quest.quest_id)
            quests.append(quest)
    return QuestDatabase(quests=tuple(quests), language=language)


def _symbol_names(
    system: ClientDataArchives,
    catalogs: ClientDataArchives,
    table_file: str,
    catalog_file: str,
    prefix: str,
    diagnostics: list[QuestExtractionDiagnostic] | None,
) -> dict[str, str]:
    table = system.read_text(table_file)
    if table is None:
        _report(diagnostics, QuestExtractionWarning.MISSING_CLIENT_TABLE, table_file)
        return {}
    catalog_text = catalogs.read_text(catalog_file)
    if catalog_text is None:
        _report(diagnostics, QuestExtractionWarning.MISSING_CLIENT_TABLE, catalog_file)
        return {}
    return parse_symbol_names(table, prefix, parse_text_catalog(catalog_text))


def _report(
    diagnostics: list[QuestExtractionDiagnostic] | None,
    warning: QuestExtractionWarning,
    detail: str,
) -> None:
    if diagnostics is not None:
        diagnostics.append(QuestExtractionDiagnostic(warning, detail))
