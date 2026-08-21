"""Quest goal resolution and sequential quest queue progression.

A quest states what has to die and, sometimes, where. This module turns that statement into
the two things a farming session actually needs - a per-monster kill quota and the extracted
spawn zones to patrol - and then walks a selected queue of quests through to completion.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.navigation.vector_navigation import ZoneGoal
from flyff_bot.features.navigation.world_extractor import VectorSpawnZone, WorldVectorMap
from flyff_bot.features.quests.models import (
    UNKNOWN_MONSTER_ID,
    QuestDefinition,
    QuestDestination,
    QuestObjectiveProgress,
    QuestRequirementKind,
)

# A collection objective states how many items are needed, not how many monsters. One kill of
# a declared drop source is the smallest unit of progress a session can verify, so a
# collection objective is farmed as this many kills per required item.
KILLS_PER_REQUIRED_ITEM = 1


class QuestResolutionIssue(StrEnum):
    """Why a selected quest cannot be farmed as it stands."""

    # The quest states no kill or collectible objective a farming session could work on.
    NO_FARMABLE_OBJECTIVE = "no_farmable_objective"
    # No extracted world map is loaded, so no spawn zone can be resolved at all.
    NO_WORLD_MAP = "no_world_map"
    # The loaded world map holds no spawn zone for one of the quest's monsters.
    NO_SPAWN_ZONE = "no_spawn_zone"


@dataclass(frozen=True, slots=True)
class QuestTarget:
    """One monster class a quest needs killed, bound to where it spawns."""

    monster_name: str
    required_kills: int
    kind: QuestRequirementKind
    zone: VectorSpawnZone | None = None
    destination: QuestDestination | None = None

    @property
    def is_reachable(self) -> bool:
        """Return whether an extracted spawn zone was found for this monster."""

        return self.zone is not None


@dataclass(frozen=True, slots=True)
class QuestResolution:
    """One quest together with the targets and zones it resolved to."""

    quest: QuestDefinition
    targets: tuple[QuestTarget, ...] = ()
    issues: tuple[QuestResolutionIssue, ...] = ()

    @property
    def is_farmable(self) -> bool:
        """Return whether this quest resolved to at least one reachable spawn zone."""

        return any(target.is_reachable for target in self.targets)

    @property
    def zones(self) -> tuple[VectorSpawnZone, ...]:
        """Return the distinct spawn zones this quest's targets resolved to."""

        found: list[VectorSpawnZone] = []
        for target in self.targets:
            if target.zone is not None and target.zone not in found:
                found.append(target.zone)
        return tuple(found)

    @property
    def required_kills(self) -> tuple[tuple[str, int], ...]:
        """Return the per-monster kill counts this quest imposes, in target order.

        The pairs stay in the quest vocabulary rather than the session's quota type: the
        quests feature states what a quest needs, and the automation layer turns that into
        the tracker configuration it owns.
        """

        return tuple((target.monster_name, target.required_kills) for target in self.targets)

    @property
    def zone_goals(self) -> tuple[ZoneGoal, ...]:
        """Return this quest's targets as goals the vector navigator understands."""

        return tuple(
            ZoneGoal(target.monster_name, target.required_kills) for target in self.targets
        )


class QuestGoalResolver:
    """Bind a quest's stated objectives to extracted monster spawn zones.

    The resolver measures nothing and dispatches nothing. It answers one question: given the
    world map an operator has extracted, where does this quest's work happen?
    """

    def __init__(self, world_map: WorldVectorMap | None = None) -> None:
        self._world_map = world_map

    @property
    def world_map(self) -> WorldVectorMap | None:
        """Return the extracted map spawn zones are resolved against."""

        return self._world_map

    def resolve(self, quest: QuestDefinition) -> QuestResolution:
        """Return the targets and zones one quest resolves to on the loaded map."""

        targets: list[QuestTarget] = []
        for requirement in quest.kill_requirements:
            targets.append(
                QuestTarget(
                    monster_name=requirement.display_name,
                    required_kills=requirement.required_kills,
                    kind=QuestRequirementKind.KILL,
                    zone=self._zone_for(
                        requirement.display_name, requirement.monster_id, requirement.destination
                    ),
                    destination=requirement.destination,
                )
            )
        for item in quest.item_requirements:
            for source in item.sources:
                targets.append(
                    QuestTarget(
                        monster_name=source.display_name,
                        required_kills=item.required_quantity * KILLS_PER_REQUIRED_ITEM,
                        kind=QuestRequirementKind.COLLECT,
                        zone=self._zone_for(source.display_name, source.monster_id, None),
                    )
                )

        issues: list[QuestResolutionIssue] = []
        if not targets:
            issues.append(QuestResolutionIssue.NO_FARMABLE_OBJECTIVE)
        elif self._world_map is None:
            issues.append(QuestResolutionIssue.NO_WORLD_MAP)
        elif any(target.zone is None for target in targets):
            issues.append(QuestResolutionIssue.NO_SPAWN_ZONE)
        return QuestResolution(quest, tuple(targets), tuple(issues))

    def resolve_all(self, quests: Iterable[QuestDefinition]) -> tuple[QuestResolution, ...]:
        """Return one resolution per quest, in the order the quests were given."""

        return tuple(self.resolve(quest) for quest in quests)

    def _zone_for(
        self, monster_name: str, monster_id: int, destination: QuestDestination | None
    ) -> VectorSpawnZone | None:
        world_map = self._world_map
        if world_map is None:
            return None
        candidates = [
            zone
            for zone in world_map.zones
            if (zone.monster_name or "").casefold() == monster_name.casefold()
        ]
        if not candidates and monster_id != UNKNOWN_MONSTER_ID:
            candidates = [zone for zone in world_map.zones if zone.monster_id == monster_id]
        if not candidates:
            return None
        if destination is None:
            return candidates[0]
        return min(
            candidates,
            key=lambda zone: math.hypot(
                zone.anchor.x - destination.x, zone.anchor.z - destination.z
            ),
        )


class QuestFarmingQueue:
    """Walk a selected sequence of quests, one active quest at a time.

    The queue owns the answer to "is this quest done, and what comes next". It counts only
    verified kills that the session attributes to a monster class, so an unattributable
    engagement never advances a quest.
    """

    def __init__(self, resolutions: Sequence[QuestResolution] = ()) -> None:
        self._resolutions = tuple(resolutions)
        self._index = 0
        self._kills: dict[str, int] = {}

    @property
    def resolutions(self) -> tuple[QuestResolution, ...]:
        """Return every quest this queue was configured with."""

        return self._resolutions

    @property
    def has_quests(self) -> bool:
        """Return whether the queue was given anything to farm at all."""

        return bool(self._resolutions)

    @property
    def active(self) -> QuestResolution | None:
        """Return the quest currently being farmed, or ``None`` once the queue is done."""

        if self._index >= len(self._resolutions):
            return None
        return self._resolutions[self._index]

    @property
    def remaining(self) -> int:
        """Return how many quests, including the active one, are still unfinished."""

        return max(0, len(self._resolutions) - self._index)

    @property
    def is_completed(self) -> bool:
        """Return whether every selected quest has been worked through."""

        return self.has_quests and self.active is None

    @property
    def progress(self) -> tuple[QuestObjectiveProgress, ...]:
        """Return one progress entry per objective of the active quest."""

        active = self.active
        if active is None:
            return ()
        return tuple(
            QuestObjectiveProgress(
                target.monster_name, self._kills.get(target.monster_name, 0), target.required_kills
            )
            for target in active.targets
        )

    @property
    def is_active_completed(self) -> bool:
        """Return whether the active quest's objectives are all satisfied."""

        entries = self.progress
        return bool(entries) and all(entry.is_completed for entry in entries)

    def record_kill(self, monster_name: str | None) -> bool:
        """Count one verified kill and report whether it completed the active quest."""

        if not monster_name or self.active is None:
            return False
        self._kills[monster_name] = self._kills.get(monster_name, 0) + 1
        return self.is_active_completed

    def advance(self) -> QuestResolution | None:
        """Retire the active quest and return the next one, or ``None`` when done."""

        if self._index < len(self._resolutions):
            self._index += 1
        self._kills.clear()
        return self.active
