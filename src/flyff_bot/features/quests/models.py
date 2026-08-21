"""Typed quest definitions extracted from the client's quest scripts.

These value objects are the whole vocabulary the rest of the application uses to talk
about quests. They carry only what a farming session can act on or an operator can filter
by: what has to die, what has to drop, who it is for, and what it is called.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

# A level bound the client writes when a quest has no upper level restriction at all.
UNBOUNDED_LEVEL = 0
# A requirement that names no monster identifier resolves to this, meaning "unknown to the
# client script"; the symbolic name is still carried so an operator can see what it asked for.
UNKNOWN_MONSTER_ID = -1


class QuestCollection(StrEnum):
    """Which client quest script a definition was read from."""

    # `propQuest.inc` - the main quest body, including job and level progression.
    GENERAL = "general"
    # `propQuest-Scenario.inc` - the story line.
    SCENARIO = "scenario"
    # `propQuest-RequestBox.inc` and `propQuest-RequestBox2.inc` - the request board.
    OFFICE = "office"
    # `propQuest-DungeonandPK.inc` - dungeon and player-versus-player quests.
    DUNGEON = "dungeon"


class QuestRequirementKind(StrEnum):
    """What kind of work completes one quest objective."""

    # A number of a specific monster class must be killed.
    KILL = "kill"
    # A number of a specific item must be held, which is farmed from monster drops.
    COLLECT = "collect"


@dataclass(frozen=True, slots=True)
class QuestObjectiveProgress:
    """One quest objective as the dashboard displays it."""

    monster_name: str
    kills: int
    required_kills: int

    @property
    def is_completed(self) -> bool:
        """Return whether this objective reached its required count."""

        return self.kills >= self.required_kills


@dataclass(frozen=True, slots=True)
class QuestDestination:
    """The world position a quest script names for one objective."""

    x: float
    z: float

    def as_document(self) -> dict[str, float]:
        """Return this destination as its persisted JSON mapping."""

        return {"x": self.x, "z": self.z}

    @classmethod
    def from_document(cls, document: dict[str, object]) -> QuestDestination:
        """Return the destination one persisted JSON mapping describes."""

        return cls(_number(document.get("x"), "destination x"), _number(document.get("z"), "z"))


@dataclass(frozen=True, slots=True)
class QuestKillRequirement:
    """One monster class a quest requires the player to kill, and how many."""

    monster_symbol: str
    monster_name: str
    required_kills: int
    monster_id: int = UNKNOWN_MONSTER_ID
    destination: QuestDestination | None = None

    def __post_init__(self) -> None:
        if self.required_kills <= 0:
            raise ValueError("A quest kill requirement must ask for at least one kill.")

    @property
    def kind(self) -> QuestRequirementKind:
        """Return the objective kind this requirement represents."""

        return QuestRequirementKind.KILL

    @property
    def display_name(self) -> str:
        """Return the monster label an operator recognizes, falling back to its symbol."""

        return self.monster_name or self.monster_symbol

    def as_document(self) -> dict[str, object]:
        """Return this requirement as its persisted JSON mapping."""

        return {
            "monster_symbol": self.monster_symbol,
            "monster_name": self.monster_name,
            "required_kills": self.required_kills,
            "monster_id": self.monster_id,
            "destination": None if self.destination is None else self.destination.as_document(),
        }

    @classmethod
    def from_document(cls, document: dict[str, object]) -> QuestKillRequirement:
        """Return the kill requirement one persisted JSON mapping describes."""

        raw_destination = document.get("destination")
        return cls(
            monster_symbol=_text(document.get("monster_symbol"), "monster symbol"),
            monster_name=_text(document.get("monster_name"), "monster name", allow_empty=True),
            required_kills=_integer(document.get("required_kills"), "required kills"),
            monster_id=_integer(document.get("monster_id"), "monster id"),
            destination=(
                QuestDestination.from_document(_mapping(raw_destination, "destination"))
                if raw_destination is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class QuestItemDrop:
    """One monster class that drops a quest item, as the quest script declares it."""

    monster_symbol: str
    monster_name: str
    monster_id: int = UNKNOWN_MONSTER_ID

    @property
    def display_name(self) -> str:
        """Return the monster label an operator recognizes, falling back to its symbol."""

        return self.monster_name or self.monster_symbol

    def as_document(self) -> dict[str, object]:
        """Return this drop source as its persisted JSON mapping."""

        return {
            "monster_symbol": self.monster_symbol,
            "monster_name": self.monster_name,
            "monster_id": self.monster_id,
        }

    @classmethod
    def from_document(cls, document: dict[str, object]) -> QuestItemDrop:
        """Return the drop source one persisted JSON mapping describes."""

        return cls(
            monster_symbol=_text(document.get("monster_symbol"), "monster symbol"),
            monster_name=_text(document.get("monster_name"), "monster name", allow_empty=True),
            monster_id=_integer(document.get("monster_id"), "monster id"),
        )


@dataclass(frozen=True, slots=True)
class QuestItemRequirement:
    """One item a quest requires, together with the monsters known to drop it."""

    item_symbol: str
    item_name: str
    required_quantity: int
    sources: tuple[QuestItemDrop, ...] = ()

    def __post_init__(self) -> None:
        if self.required_quantity <= 0:
            raise ValueError("A quest item requirement must ask for at least one item.")

    @property
    def kind(self) -> QuestRequirementKind:
        """Return the objective kind this requirement represents."""

        return QuestRequirementKind.COLLECT

    @property
    def display_name(self) -> str:
        """Return the item label an operator recognizes, falling back to its symbol."""

        return self.item_name or self.item_symbol

    def as_document(self) -> dict[str, object]:
        """Return this requirement as its persisted JSON mapping."""

        return {
            "item_symbol": self.item_symbol,
            "item_name": self.item_name,
            "required_quantity": self.required_quantity,
            "sources": [source.as_document() for source in self.sources],
        }

    @classmethod
    def from_document(cls, document: dict[str, object]) -> QuestItemRequirement:
        """Return the item requirement one persisted JSON mapping describes."""

        return cls(
            item_symbol=_text(document.get("item_symbol"), "item symbol"),
            item_name=_text(document.get("item_name"), "item name", allow_empty=True),
            required_quantity=_integer(document.get("required_quantity"), "required quantity"),
            sources=tuple(
                QuestItemDrop.from_document(_mapping(entry, "quest item source"))
                for entry in _sequence(document.get("sources", ()), "sources")
            ),
        )


@dataclass(frozen=True, slots=True)
class QuestDefinition:
    """One quest exactly as the client declares it, with its text already resolved."""

    quest_id: str
    title: str
    collection: QuestCollection
    group: str = ""
    description: str = ""
    objective: str = ""
    minimum_level: int = UNBOUNDED_LEVEL
    maximum_level: int = UNBOUNDED_LEVEL
    kill_requirements: tuple[QuestKillRequirement, ...] = ()
    item_requirements: tuple[QuestItemRequirement, ...] = ()
    reward_items: tuple[str, ...] = ()
    reward_gold: int = 0
    reward_experience: int = 0

    def __post_init__(self) -> None:
        if not self.quest_id.strip():
            raise ValueError("A quest definition must carry a quest identifier.")

    @property
    def is_farmable(self) -> bool:
        """Return whether this quest states work a farming session can actually do."""

        return bool(self.kill_requirements) or any(
            requirement.sources for requirement in self.item_requirements
        )

    @property
    def display_title(self) -> str:
        """Return the quest label an operator recognizes, falling back to its identifier."""

        return self.title or self.quest_id

    def monster_names(self) -> tuple[str, ...]:
        """Return every monster this quest needs killed, in requirement order."""

        names: list[str] = []
        for kill in self.kill_requirements:
            if kill.display_name not in names:
                names.append(kill.display_name)
        for item in self.item_requirements:
            for source in item.sources:
                if source.display_name not in names:
                    names.append(source.display_name)
        return tuple(names)

    def matches(self, query: str) -> bool:
        """Return whether a free-text search query selects this quest."""

        needle = query.strip().casefold()
        if not needle:
            return True
        haystack = (
            self.quest_id,
            self.title,
            self.group,
            self.objective,
            *self.monster_names(),
        )
        return any(needle in field_value.casefold() for field_value in haystack)

    def as_document(self) -> dict[str, object]:
        """Return this quest as its persisted JSON mapping."""

        return {
            "quest_id": self.quest_id,
            "title": self.title,
            "collection": str(self.collection),
            "group": self.group,
            "description": self.description,
            "objective": self.objective,
            "minimum_level": self.minimum_level,
            "maximum_level": self.maximum_level,
            "kill_requirements": [entry.as_document() for entry in self.kill_requirements],
            "item_requirements": [entry.as_document() for entry in self.item_requirements],
            "reward_items": list(self.reward_items),
            "reward_gold": self.reward_gold,
            "reward_experience": self.reward_experience,
        }

    @classmethod
    def from_document(cls, document: dict[str, object]) -> QuestDefinition:
        """Return the quest one persisted JSON mapping describes."""

        return cls(
            quest_id=_text(document.get("quest_id"), "quest id"),
            title=_text(document.get("title"), "title", allow_empty=True),
            collection=QuestCollection(_text(document.get("collection"), "collection")),
            group=_text(document.get("group"), "group", allow_empty=True),
            description=_text(document.get("description"), "description", allow_empty=True),
            objective=_text(document.get("objective"), "objective", allow_empty=True),
            minimum_level=_integer(document.get("minimum_level"), "minimum level"),
            maximum_level=_integer(document.get("maximum_level"), "maximum level"),
            kill_requirements=tuple(
                QuestKillRequirement.from_document(_mapping(entry, "kill requirement"))
                for entry in _sequence(document.get("kill_requirements", ()), "kill requirements")
            ),
            item_requirements=tuple(
                QuestItemRequirement.from_document(_mapping(entry, "item requirement"))
                for entry in _sequence(document.get("item_requirements", ()), "item requirements")
            ),
            reward_items=tuple(
                _text(entry, "reward item", allow_empty=True)
                for entry in _sequence(document.get("reward_items", ()), "reward items")
            ),
            reward_gold=_integer(document.get("reward_gold", 0), "reward gold"),
            reward_experience=_integer(document.get("reward_experience", 0), "reward experience"),
        )


@dataclass(frozen=True, slots=True)
class QuestDatabase:
    """Every quest one extraction pass read, indexed by quest identifier."""

    quests: tuple[QuestDefinition, ...] = ()
    client_digest: str = ""
    language: str = ""
    _by_id: dict[str, QuestDefinition] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        index = {quest.quest_id: quest for quest in self.quests}
        if len(index) != len(self.quests):
            raise ValueError("A quest database must not repeat a quest identifier.")
        object.__setattr__(self, "_by_id", index)

    def get(self, quest_id: str) -> QuestDefinition | None:
        """Return one quest by identifier, or ``None`` when it was never extracted."""

        return self._by_id.get(quest_id)

    def select(self, quest_ids: Iterable[str]) -> tuple[QuestDefinition, ...]:
        """Return the named quests in the order they were asked for, skipping unknown ones."""

        found = (self._by_id.get(quest_id) for quest_id in quest_ids)
        return tuple(quest for quest in found if quest is not None)

    @property
    def farmable(self) -> tuple[QuestDefinition, ...]:
        """Return only the quests whose objectives a farming session can work on."""

        return tuple(quest for quest in self.quests if quest.is_farmable)

    @property
    def groups(self) -> tuple[str, ...]:
        """Return every quest group label that appears at least once, sorted."""

        return tuple(sorted({quest.group for quest in self.quests if quest.group}))


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"A quest document needs a {label} string.")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"A quest document needs an integer {label}.")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"A quest document needs a numeric {label}.")
    return float(value)


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"A quest document needs a {label} object.")
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"A quest document needs a {label} list.")
    return tuple(value)
