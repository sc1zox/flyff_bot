"""Read-only extraction of client dungeon declarations from keyed archives."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from flyff_bot.features.dungeons.models import DungeonDefinition
from flyff_bot.features.quests.extraction import ClientDataArchives

CLIENT_SYSTEM_DIRECTORY = "System2"
DUNGEON_SCRIPT_FILE = "PartyDungeon.lua"
# Clients that ship no dungeon script still declare every dungeon world in their ranking
# table, one numeric world identifier per rewarded block (BUG-036).
DUNGEON_RANKING_FILE = "DungeonRanking.inc"
DUNGEON_NAME_CATALOG_FILE = "propQuest-DungeonandPKtxt.txt"
DEFAULT_DUNGEON_LANGUAGE = "English"

_ADD_DUNGEON_PATTERN = re.compile(r'AddDungeon\(\s*"(?P<world_symbol>[^"\s]+)"\s*\)')
_RANKING_ENTRY_PATTERN = re.compile(r"^(?P<world_identifier>\d+)\s*//\s*(?P<label>\S.*?)\s*$")
_LINE_COMMENT_PREFIX = "//"
_BLOCK_OPEN = "{"
_BLOCK_CLOSE = "}"
_MINUTES_FUNCTION_PATTERN = re.compile(r"^MIN\s*\(\s*(?P<minutes>\d+)\s*\)$", re.IGNORECASE)
_SECONDS_PER_MINUTE = 60
_NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
_COMMENT_PATTERN = re.compile(r"--\[\[.*?--\]\]|--[^\n]*", re.DOTALL)


class DungeonExtractionWarning(StrEnum):
    """Why part of the static client data was deliberately skipped."""

    NO_CLIENT_ARCHIVE = "no_client_archive"
    MISSING_DUNGEON_SCRIPT = "missing_dungeon_script"
    MISSING_DUNGEON_RANKING = "missing_dungeon_ranking"
    INVALID_DUNGEON_ENTRY = "invalid_dungeon_entry"
    MISSING_NAME_CATALOG = "missing_name_catalog"


@dataclass(frozen=True, slots=True)
class DungeonExtractionDiagnostic:
    """A named skipped input so extraction remains traceable and lossless at source."""

    warning: DungeonExtractionWarning
    detail: str


@dataclass(frozen=True, slots=True)
class _ScriptCall:
    """One Lua setter invocation with its raw argument text."""

    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class _DungeonDeclaration:
    """One client-declared dungeon, normalized across the sources that can declare it."""

    dungeon_id: int
    label: str
    minimum_level: int | None = None
    maximum_level: int | None = None
    cooldown_seconds: int | None = None
    daily_entry_limit: int = 0


def extract_dungeon_definitions(
    client_data_root: Path,
    *,
    language: str = DEFAULT_DUNGEON_LANGUAGE,
    diagnostics: list[DungeonExtractionDiagnostic] | None = None,
) -> tuple[DungeonDefinition, ...]:
    """Return every complete dungeon declaration found in the client's own data."""

    archives = ClientDataArchives.open_directory(client_data_root / CLIENT_SYSTEM_DIRECTORY)
    if archives.is_empty:
        _report(
            diagnostics,
            DungeonExtractionWarning.NO_CLIENT_ARCHIVE,
            str(client_data_root / CLIENT_SYSTEM_DIRECTORY),
        )
        return ()
    declarations = _client_declarations(archives, diagnostics)
    if not declarations:
        return ()
    catalog_text = archives.read_text(DUNGEON_NAME_CATALOG_FILE)
    if catalog_text is None:
        _report(diagnostics, DungeonExtractionWarning.MISSING_NAME_CATALOG, "")
    names = _parse_dungeon_names(catalog_text or "")
    definitions: dict[int, DungeonDefinition] = {}
    for declaration in declarations:
        dungeon_id = declaration.dungeon_id
        label = declaration.label
        name = names.get(label, label)
        try:
            definition = DungeonDefinition(
                dungeon_id=dungeon_id,
                name=name,
                minimum_level=declaration.minimum_level,
                maximum_level=declaration.maximum_level,
                base_cooldown_seconds=declaration.cooldown_seconds,
                daily_entry_limit=declaration.daily_entry_limit,
            )
        except ValueError as error:
            _report(
                diagnostics,
                DungeonExtractionWarning.INVALID_DUNGEON_ENTRY,
                f"{label}: {error}",
            )
            continue
        previous = definitions.get(dungeon_id)
        if previous == definition:
            continue
        if previous is not None:
            _report(
                diagnostics,
                DungeonExtractionWarning.INVALID_DUNGEON_ENTRY,
                f"{label}: duplicate conflicting declaration",
            )
            continue
        definitions[dungeon_id] = definition
    return tuple(definitions.values())


def _client_declarations(
    archives: ClientDataArchives,
    diagnostics: list[DungeonExtractionDiagnostic] | None,
) -> Sequence[_DungeonDeclaration]:
    """Return the dungeons this client declares, from whichever source it ships.

    The dungeon script carries level ranges and cooldowns and is preferred. A client that
    packs no such script is not empty of dungeons: its ranking table still names every
    dungeon world, so those are read with their undeclared fields left undeclared.
    """

    script = archives.read_text(DUNGEON_SCRIPT_FILE)
    if script is not None:
        return _script_declarations(script, diagnostics)
    _report(diagnostics, DungeonExtractionWarning.MISSING_DUNGEON_SCRIPT, DUNGEON_SCRIPT_FILE)
    ranking = archives.read_text(DUNGEON_RANKING_FILE)
    if ranking is None:
        _report(diagnostics, DungeonExtractionWarning.MISSING_DUNGEON_RANKING, DUNGEON_RANKING_FILE)
        return ()
    return tuple(
        _DungeonDeclaration(dungeon_id=dungeon_id, label=label)
        for dungeon_id, label in parse_dungeon_ranking(ranking)
    )


def parse_dungeon_ranking(text: str) -> Sequence[tuple[int, str]]:
    """Return `(world identifier, client label)` for every block of one ranking table.

    A declaration is a numeric world identifier whose commented label is followed by a
    reward block. The table's leading reset period has no block, and a commented-out block
    is not a declaration, so neither is mistaken for a dungeon.
    """

    declarations: list[tuple[int, str]] = []
    pending: tuple[int, str] | None = None
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(_LINE_COMMENT_PREFIX):
            continue
        opened = stripped.count(_BLOCK_OPEN)
        if depth == 0:
            if opened and pending is not None:
                declarations.append(pending)
                pending = None
            elif not opened:
                match = _RANKING_ENTRY_PATTERN.match(stripped)
                pending = (
                    (int(match.group("world_identifier")), match.group("label"))
                    if match is not None
                    else None
                )
        depth = max(0, depth + opened - stripped.count(_BLOCK_CLOSE))
    return tuple(declarations)


def _script_declarations(
    script: str,
    diagnostics: list[DungeonExtractionDiagnostic] | None,
) -> Sequence[_DungeonDeclaration]:
    declarations: list[_DungeonDeclaration] = []
    for world_symbol, level, cooldown, entries in parse_dungeon_script(script):
        identifier = _world_identifier(world_symbol)
        if identifier is None:
            _report(
                diagnostics,
                DungeonExtractionWarning.INVALID_DUNGEON_ENTRY,
                f"{world_symbol}: unresolved world identifier",
            )
            continue
        declarations.append(
            _DungeonDeclaration(
                dungeon_id=identifier,
                label=world_symbol,
                minimum_level=level[0],
                maximum_level=level[1],
                cooldown_seconds=cooldown,
                daily_entry_limit=entries,
            )
        )
    return tuple(declarations)


def parse_dungeon_script(
    text: str,
) -> Sequence[tuple[str, tuple[int, int], int, int]]:
    """Return the fields this feature can verify from one `PartyDungeon.lua` body.

    A missing call means "the client does not declare it", not zero. The parser therefore
    skips entries lacking level or cooldown rather than inventing defaults.
    """

    clean = _COMMENT_PATTERN.sub(" ", text)
    matches = list(_ADD_DUNGEON_PATTERN.finditer(clean))
    declarations: list[tuple[str, tuple[int, int], int, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(clean)
        body = clean[match.end() : end]
        levels = [_numbers(arguments) for arguments in _call_arguments(body, "SetLevel")]
        cooldowns = _call_arguments(body, "SetCoolTime")
        entry_values = [_numbers(arguments) for arguments in _call_arguments(body, "SetEntryCount")]
        if not levels or not cooldowns:
            continue
        level_values = levels[0]
        if len(level_values) < 2:
            continue
        cooldown_value = _cooldown_seconds(cooldowns[0])
        if level_values is None or cooldown_value is None:
            continue
        level_pair = (int(level_values[0]), int(level_values[1]))
        entry_count = int(entry_values[0][0]) if entry_values and entry_values[0] else 0
        declarations.append((match.group("world_symbol"), level_pair, cooldown_value, entry_count))
    return declarations


def _find_calls(text: str, name: str) -> Sequence[_ScriptCall]:
    return tuple(call for call in _script_calls(text) if call.name.casefold() == name.casefold())


def _call_arguments(text: str, name: str) -> Sequence[str]:
    return tuple(call.arguments for call in _find_calls(text, name))


def _script_calls(text: str) -> Sequence[_ScriptCall]:
    pattern = re.compile(r"\b(Set[A-Za-z0-9_]*)\s*\(")
    calls: list[_ScriptCall] = []
    position = 0
    while match := pattern.search(text, position):
        opening = match.end() - 1
        closing = _matching_parenthesis_end(text, opening)
        if closing is None:
            break
        calls.append(_ScriptCall(match.group(1), text[opening + 1 : closing - 1]))
        position = closing
    return calls


def _matching_parenthesis_end(text: str, opening_index: int) -> int | None:
    depth = 0
    quoted: str | None = None
    escaped = False
    for index in range(opening_index, len(text)):
        character = text[index]
        if quoted is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quoted:
                quoted = None
            continue
        if character in {'"', "'"}:
            quoted = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _numbers(arguments: str) -> tuple[float, ...]:
    return tuple(float(value) for value in _NUMBER_PATTERN.findall(arguments))


def _cooldown_seconds(argument: str) -> int | None:
    stripped = argument.strip()
    minutes = _MINUTES_FUNCTION_PATTERN.fullmatch(stripped)
    if minutes is not None:
        return int(minutes.group("minutes")) * _SECONDS_PER_MINUTE
    values = _NUMBER_PATTERN.findall(stripped)
    return int(float(values[0])) if len(values) == 1 else None


def _report(
    diagnostics: list[DungeonExtractionDiagnostic] | None,
    warning: DungeonExtractionWarning,
    detail: str,
) -> None:
    if diagnostics is not None:
        diagnostics.append(DungeonExtractionDiagnostic(warning, detail))


def _world_identifier(world_symbol: str) -> int | None:
    """Return the client's stable world ID from its project symbol.

    Entropia names instance symbols with the world number as the final numeric segment;
    an unresolvable symbol is skipped rather than hashed into a fake ID.
    """

    suffix = world_symbol.rsplit("_", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _parse_dungeon_names(catalog_text: str) -> dict[str, str]:
    """Read both `IDS_*` references and direct world-symbol rows from the client table."""

    names: dict[str, str] = {}
    for line in catalog_text.splitlines():
        columns = line.split("\t")
        if len(columns) < 2:
            continue
        key, value = columns[0].strip(), columns[1].strip()
        if key and value and key not in names:
            names[key] = value
    resolved = {
        symbol: names[symbol]
        for symbol in names
        if symbol.startswith("WI_") and not names[symbol].startswith("WI_")
    }
    resolved.update(
        {
            key.removeprefix("IDS_"): value
            for key, value in names.items()
            if key.startswith("IDS_WI_")
        }
    )
    return resolved
