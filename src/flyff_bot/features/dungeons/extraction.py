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
DUNGEON_NAME_CATALOG_FILE = "propQuest-DungeonandPKtxt.txt"
DEFAULT_DUNGEON_LANGUAGE = "English"

_ADD_DUNGEON_PATTERN = re.compile(r'AddDungeon\(\s*"(?P<world_symbol>[^"\s]+)"\s*\)')
_MINUTES_FUNCTION_PATTERN = re.compile(r"^MIN\s*\(\s*(?P<minutes>\d+)\s*\)$", re.IGNORECASE)
_SECONDS_PER_MINUTE = 60
_NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
_COMMENT_PATTERN = re.compile(r"--\[\[.*?--\]\]|--[^\n]*", re.DOTALL)


class DungeonExtractionWarning(StrEnum):
    """Why part of the static client data was deliberately skipped."""

    NO_CLIENT_ARCHIVE = "no_client_archive"
    MISSING_DUNGEON_SCRIPT = "missing_dungeon_script"
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
    script = archives.read_text(DUNGEON_SCRIPT_FILE)
    if script is None:
        _report(
            diagnostics,
            DungeonExtractionWarning.MISSING_DUNGEON_SCRIPT,
            DUNGEON_SCRIPT_FILE,
        )
        return ()
    catalog_text = archives.read_text(DUNGEON_NAME_CATALOG_FILE)
    if catalog_text is None:
        _report(diagnostics, DungeonExtractionWarning.MISSING_NAME_CATALOG, "")
    names = _parse_dungeon_names(catalog_text or "")
    definitions: dict[int, DungeonDefinition] = {}
    for world_symbol, level, cooldown, entries in parse_dungeon_script(script):
        dungeon_id = _world_identifier(world_symbol)
        if dungeon_id is None:
            _report(
                diagnostics,
                DungeonExtractionWarning.INVALID_DUNGEON_ENTRY,
                f"{world_symbol}: unresolved world identifier",
            )
            continue
        name = names.get(world_symbol, world_symbol)
        try:
            definition = DungeonDefinition(
                dungeon_id=dungeon_id,
                name=name,
                minimum_level=level[0],
                maximum_level=level[1],
                base_cooldown_seconds=cooldown,
                daily_entry_limit=entries or 0,
            )
        except ValueError as error:
            _report(
                diagnostics,
                DungeonExtractionWarning.INVALID_DUNGEON_ENTRY,
                f"{world_symbol}: {error}",
            )
            continue
        previous = definitions.get(dungeon_id)
        if previous == definition:
            continue
        if previous is not None:
            _report(
                diagnostics,
                DungeonExtractionWarning.INVALID_DUNGEON_ENTRY,
                f"{world_symbol}: duplicate conflicting declaration",
            )
            continue
        definitions[dungeon_id] = definition
    return tuple(definitions.values())


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
