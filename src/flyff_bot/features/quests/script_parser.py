"""Parser for the client's ``propQuest*.inc`` quest scripts.

The scripts are a small declarative language: a quest identifier, a brace-delimited body,
and calls that state the quest's title, its begin and end conditions, and its rewards.
Only the calls a farming session or an operator can act on are read here; dialogue lines,
party rules, and script hooks are deliberately ignored rather than half-modelled.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from flyff_bot.features.quests.models import (
    UNBOUNDED_LEVEL,
    UNKNOWN_MONSTER_ID,
    QuestCollection,
    QuestDefinition,
    QuestDestination,
    QuestItemDrop,
    QuestItemRequirement,
    QuestKillRequirement,
)

# Calls the parser acts on. Everything else in a quest body is skipped.
TITLE_CALL = "settitle"
DESCRIPTION_CALL = "setdesc"
OBJECTIVE_CALL = "setcond"
HEAD_QUEST_CALL = "setheadquest"
BEGIN_LEVEL_CALL = "setbegincondlevel"
END_LEVEL_CALL = "setendcondlevel"
KILL_CALL = "setendcondkillnpc"
ITEM_CALL = "setendconditem"
ONE_ITEM_CALL = "setendcondoneitem"
QUEST_DROP_CALL = "questitem"
REWARD_ITEM_CALL = "setendrewarditem"
REWARD_GOLD_CALL = "setendrewardgold"
REWARD_EXP_CALL = "setendrewardexp"

# Argument positions inside the calls above, named so the offsets are not bare numbers.
KILL_MONSTER_ARGUMENT = 1
KILL_COUNT_ARGUMENT = 2
KILL_DESTINATION_X_ARGUMENT = 3
KILL_DESTINATION_Z_ARGUMENT = 4
KILL_MINIMUM_ARGUMENTS = 3
ITEM_SYMBOL_ARGUMENT = 3
ITEM_COUNT_ARGUMENT = 4
ITEM_MINIMUM_ARGUMENTS = 5
DROP_MONSTER_ARGUMENT = 0
DROP_ITEM_ARGUMENT = 1
DROP_MINIMUM_ARGUMENTS = 2
REWARD_ITEM_SYMBOL_ARGUMENT = 3
REWARD_ITEM_COUNT_ARGUMENT = 4
REWARD_ITEM_MINIMUM_ARGUMENTS = 5
LEVEL_MINIMUM_ARGUMENT = 0
LEVEL_MAXIMUM_ARGUMENT = 1
LEVEL_ARGUMENTS = 2
REWARD_AMOUNT_ARGUMENT = 0

_CALL_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)", re.DOTALL)
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")


@dataclass(frozen=True, slots=True)
class ScriptCall:
    """One parsed ``Name( argument, ... )`` call from a quest body."""

    name: str
    arguments: tuple[str, ...]

    def argument(self, index: int) -> str | None:
        """Return one argument by position, or ``None`` when the call is shorter."""

        if index >= len(self.arguments):
            return None
        return self.arguments[index]


@dataclass(frozen=True, slots=True)
class ScriptBlock:
    """One top-level ``<identifier> { ... }`` block of a quest script."""

    identifier: str
    body: str

    @property
    def is_numeric(self) -> bool:
        """Return whether the identifier is a bare number, as quest groups are."""

        return self.identifier.isdigit()

    def calls(self) -> tuple[ScriptCall, ...]:
        """Return every call in this block, in source order."""

        return tuple(
            ScriptCall(match.group(1).casefold(), _split_arguments(match.group(2)))
            for match in _CALL_PATTERN.finditer(self.body)
        )


def strip_comments(text: str) -> str:
    """Return the script with block and line comments removed, honouring string literals."""

    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character == '"':
            end = text.find('"', index + 1)
            if end == -1:
                out.append(text[index:])
                break
            out.append(text[index : end + 1])
            index = end + 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = length if end == -1 else end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        out.append(character)
        index += 1
    return "".join(out)


def read_blocks(text: str) -> Iterator[ScriptBlock]:
    """Yield every top-level identifier/body block a quest script declares."""

    source = strip_comments(text)
    index = 0
    length = len(source)
    while index < length:
        opening = source.find("{", index)
        if opening == -1:
            return
        identifier = _trailing_identifier(source, opening)
        closing = _matching_brace(source, opening)
        if closing == -1:
            return
        if identifier:
            yield ScriptBlock(identifier, source[opening + 1 : closing])
        index = closing + 1


def parse_quest_script(
    text: str,
    collection: QuestCollection,
    *,
    strings: Mapping[str, str] | None = None,
    monster_names: Mapping[str, str] | None = None,
    monster_ids: Mapping[str, int] | None = None,
    item_names: Mapping[str, str] | None = None,
) -> tuple[QuestDefinition, ...]:
    """Return every quest one client quest script declares.

    ``strings`` resolves the script's ``IDS_...`` references into localized text, while the
    monster and item maps resolve its symbolic identifiers. A missing entry leaves the
    symbol in place rather than inventing a label.
    """

    catalog = strings or {}
    blocks = tuple(read_blocks(text))
    groups = _group_titles(blocks, catalog)
    quests: list[QuestDefinition] = []
    for block in blocks:
        calls = block.calls()
        if _is_group_block(block, calls):
            continue
        quests.append(
            _build_quest(
                block,
                calls,
                collection,
                catalog,
                groups,
                monster_names or {},
                monster_ids or {},
                item_names or {},
            )
        )
    return tuple(quests)


def _build_quest(
    block: ScriptBlock,
    calls: tuple[ScriptCall, ...],
    collection: QuestCollection,
    catalog: Mapping[str, str],
    groups: Mapping[str, str],
    monster_names: Mapping[str, str],
    monster_ids: Mapping[str, int],
    item_names: Mapping[str, str],
) -> QuestDefinition:
    title = ""
    description = ""
    objective = ""
    group = ""
    minimum_level = UNBOUNDED_LEVEL
    maximum_level = UNBOUNDED_LEVEL
    kills: list[QuestKillRequirement] = []
    items: list[QuestItemRequirement] = []
    drops: dict[str, list[QuestItemDrop]] = {}
    reward_items: list[str] = []
    reward_gold = 0
    reward_experience = 0

    for call in calls:
        first = call.argument(0)
        if call.name == TITLE_CALL and not title and first:
            title = catalog.get(first, "")
        elif call.name == DESCRIPTION_CALL and not description and first:
            description = catalog.get(first, "")
        elif call.name == OBJECTIVE_CALL and not objective and first:
            objective = catalog.get(first, "")
        elif call.name == HEAD_QUEST_CALL and not group and first:
            group = groups.get(first, "")
        elif call.name == BEGIN_LEVEL_CALL and len(call.arguments) >= LEVEL_ARGUMENTS:
            minimum_level = _integer(call.arguments[LEVEL_MINIMUM_ARGUMENT], UNBOUNDED_LEVEL)
            maximum_level = _integer(call.arguments[LEVEL_MAXIMUM_ARGUMENT], UNBOUNDED_LEVEL)
        elif call.name == END_LEVEL_CALL and minimum_level == UNBOUNDED_LEVEL:
            if len(call.arguments) >= LEVEL_ARGUMENTS:
                minimum_level = _integer(call.arguments[LEVEL_MINIMUM_ARGUMENT], UNBOUNDED_LEVEL)
        elif call.name == KILL_CALL:
            kill = _kill_requirement(call, monster_names, monster_ids)
            if kill is not None:
                kills.append(kill)
        elif call.name in (ITEM_CALL, ONE_ITEM_CALL):
            item = _item_requirement(call, item_names)
            if item is not None:
                items.append(item)
        elif call.name == QUEST_DROP_CALL:
            _collect_drop(call, drops, monster_names, monster_ids)
        elif call.name == REWARD_ITEM_CALL:
            reward = _reward_item(call, item_names)
            if reward:
                reward_items.append(reward)
        elif call.name == REWARD_GOLD_CALL and call.arguments:
            reward_gold = max(
                reward_gold, _integer(call.arguments[REWARD_AMOUNT_ARGUMENT], reward_gold)
            )
        elif call.name == REWARD_EXP_CALL and call.arguments:
            reward_experience = max(
                reward_experience,
                _integer(call.arguments[REWARD_AMOUNT_ARGUMENT], reward_experience),
            )

    resolved_items = tuple(
        QuestItemRequirement(
            item_symbol=requirement.item_symbol,
            item_name=requirement.item_name,
            required_quantity=requirement.required_quantity,
            sources=tuple(drops.get(requirement.item_symbol, ())),
        )
        for requirement in items
    )
    return QuestDefinition(
        quest_id=f"{collection}:{block.identifier}",
        title=title,
        collection=collection,
        group=group,
        description=description,
        objective=objective,
        minimum_level=minimum_level,
        maximum_level=maximum_level,
        kill_requirements=tuple(kills),
        item_requirements=resolved_items,
        reward_items=tuple(reward_items),
        reward_gold=reward_gold,
        reward_experience=reward_experience,
    )


def _kill_requirement(
    call: ScriptCall,
    monster_names: Mapping[str, str],
    monster_ids: Mapping[str, int],
) -> QuestKillRequirement | None:
    if len(call.arguments) < KILL_MINIMUM_ARGUMENTS:
        return None
    symbol = call.arguments[KILL_MONSTER_ARGUMENT]
    required = _integer(call.arguments[KILL_COUNT_ARGUMENT], 0)
    if required <= 0:
        return None
    destination = None
    x = call.argument(KILL_DESTINATION_X_ARGUMENT)
    z = call.argument(KILL_DESTINATION_Z_ARGUMENT)
    if x is not None and z is not None and _is_number(x) and _is_number(z):
        destination = QuestDestination(float(x), float(z))
    return QuestKillRequirement(
        monster_symbol=symbol,
        monster_name=monster_names.get(symbol, ""),
        required_kills=required,
        monster_id=_monster_id(symbol, monster_ids),
        destination=destination,
    )


def _item_requirement(
    call: ScriptCall, item_names: Mapping[str, str]
) -> QuestItemRequirement | None:
    if len(call.arguments) < ITEM_MINIMUM_ARGUMENTS:
        return None
    symbol = call.arguments[ITEM_SYMBOL_ARGUMENT]
    quantity = _integer(call.arguments[ITEM_COUNT_ARGUMENT], 0)
    if quantity <= 0:
        return None
    return QuestItemRequirement(
        item_symbol=symbol,
        item_name=item_names.get(symbol, ""),
        required_quantity=quantity,
    )


def _collect_drop(
    call: ScriptCall,
    drops: dict[str, list[QuestItemDrop]],
    monster_names: Mapping[str, str],
    monster_ids: Mapping[str, int],
) -> None:
    if len(call.arguments) < DROP_MINIMUM_ARGUMENTS:
        return
    monster = call.arguments[DROP_MONSTER_ARGUMENT]
    item = call.arguments[DROP_ITEM_ARGUMENT]
    source = QuestItemDrop(
        monster_symbol=monster,
        monster_name=monster_names.get(monster, ""),
        monster_id=_monster_id(monster, monster_ids),
    )
    sources = drops.setdefault(item, [])
    if source not in sources:
        sources.append(source)


def _reward_item(call: ScriptCall, item_names: Mapping[str, str]) -> str:
    if len(call.arguments) < REWARD_ITEM_MINIMUM_ARGUMENTS:
        return ""
    symbol = call.arguments[REWARD_ITEM_SYMBOL_ARGUMENT]
    count = _integer(call.arguments[REWARD_ITEM_COUNT_ARGUMENT], 1)
    label = item_names.get(symbol, symbol)
    return f"{count}x {label}"


def _group_titles(blocks: tuple[ScriptBlock, ...], catalog: Mapping[str, str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for block in blocks:
        if not block.is_numeric:
            continue
        for call in block.calls():
            first = call.argument(0)
            if call.name == TITLE_CALL and first:
                titles[block.identifier] = catalog.get(first, "")
                break
    return titles


def _is_group_block(block: ScriptBlock, calls: tuple[ScriptCall, ...]) -> bool:
    """Return whether a block declares a quest group rather than a quest.

    Groups are the numbered headings the client lists quests under. They carry a title and
    at most a parent heading, so a numbered block that states any real condition is treated
    as a quest instead.
    """

    if not block.is_numeric:
        return False
    substantive = {
        BEGIN_LEVEL_CALL,
        END_LEVEL_CALL,
        KILL_CALL,
        ITEM_CALL,
        ONE_ITEM_CALL,
        QUEST_DROP_CALL,
        REWARD_ITEM_CALL,
    }
    return not any(call.name in substantive for call in calls)


def _monster_id(symbol: str, monster_ids: Mapping[str, int]) -> int:
    if symbol.isdigit():
        return int(symbol)
    return monster_ids.get(symbol, UNKNOWN_MONSTER_ID)


def _split_arguments(raw: str) -> tuple[str, ...]:
    parts = [part.strip().strip('"').strip() for part in raw.split(",")]
    return tuple(part for part in parts if part)


def _integer(raw: str, fallback: int) -> int:
    try:
        return int(raw, 0)
    except ValueError:
        return fallback


def _is_number(raw: str) -> bool:
    try:
        float(raw)
    except ValueError:
        return False
    return True


def _trailing_identifier(source: str, opening: int) -> str:
    tail = source[max(0, opening - 128) : opening].rstrip()
    if not tail or tail[-1] in "{};":
        return ""
    matches = list(_IDENTIFIER_PATTERN.finditer(tail))
    if not matches or matches[-1].end() != len(tail):
        return ""
    return matches[-1].group(0)


def _matching_brace(source: str, opening: int) -> int:
    depth = 0
    index = opening
    length = len(source)
    while index < length:
        character = source[index]
        if character == '"':
            end = source.find('"', index + 1)
            index = length if end == -1 else end + 1
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1
