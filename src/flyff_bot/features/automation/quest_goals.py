"""Project the active quest goal onto the knobs a farming session actually turns.

The quests feature states the goal; this module states what that goal means for the session:
which monsters may be targeted, which spawn zone is patrolled, where the leash is anchored,
and which objective the tactical policy is conditioned on. Keeping the projection here is what
lets the quests feature stay free of any automation import.
"""

from __future__ import annotations

from flyff_bot.features.automation.kill_goals import KillGoalConfig, MobKillQuota
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.vector_navigation import ZoneGoal
from flyff_bot.features.navigation.world_extractor import VectorSpawnZone
from flyff_bot.features.policy.action_payloads import ObjectiveKind
from flyff_bot.features.policy.hierarchical import (
    HierarchicalObjective,
    HierarchicalObjectiveKind,
)
from flyff_bot.features.quests.goals import QuestResolution, QuestTarget
from flyff_bot.features.quests.objectives import (
    INTERACTION_GOAL_KINDS,
    OBJECTIVE_GOAL_KINDS,
    TRAVEL_GOAL_KINDS,
    QuestGoal,
    QuestGoalIdentity,
    QuestGoalKind,
)

# The patrol leash has to admit the whole spawn rectangle plus the approach a mob at its edge
# pulls the character into, and never collapse to a radius smaller than one engagement.
QUEST_GOAL_LEASH_MARGIN_UNITS = 40.0
MINIMUM_QUEST_GOAL_LEASH_UNITS = 60.0
QUEST_INTERACTION_TYPE = "quest"


def active_targets(goal: QuestGoal, resolution: QuestResolution) -> tuple[QuestTarget, ...]:
    """Return the quest targets one goal restricts the session to.

    An objective goal narrows the session to its own target; every other goal keeps the whole
    quest in scope, so travelling to or from an NPC never stops the session defending itself.
    """

    if goal.kind in OBJECTIVE_GOAL_KINDS and goal.target is not None:
        return (goal.target,)
    return resolution.targets


def kill_goal_config_for(goal: QuestGoal, resolution: QuestResolution) -> KillGoalConfig:
    """Return the per-monster quotas the active goal imposes on combat."""

    required: dict[str, int] = {}
    for target in active_targets(goal, resolution):
        required[target.monster_name] = required.get(target.monster_name, 0) + target.required_kills
    return KillGoalConfig(
        quotas=tuple(MobKillQuota(monster, count) for monster, count in required.items())
    )


def patrol_zones_for(goal: QuestGoal, resolution: QuestResolution) -> tuple[VectorSpawnZone, ...]:
    """Return the resolved spawn zones the active goal patrols, in target order."""

    zones: list[VectorSpawnZone] = []
    for target in active_targets(goal, resolution):
        if target.zone is not None and target.zone not in zones:
            zones.append(target.zone)
    return tuple(zones)


def zone_goals_for(goal: QuestGoal, resolution: QuestResolution) -> tuple[ZoneGoal, ...]:
    """Return the active goal's targets as goals the vector navigator understands."""

    return tuple(
        ZoneGoal(target.monster_name, target.required_kills)
        for target in active_targets(goal, resolution)
    )


def leash_for(goal: QuestGoal) -> tuple[WorldPosition, float] | None:
    """Return the leash anchor and radius the active objective's spawn zone implies."""

    zone = goal.spawn_zone
    if zone is None:
        return None
    anchor = zone.anchor
    radius = max(
        MINIMUM_QUEST_GOAL_LEASH_UNITS,
        zone.radius_units + QUEST_GOAL_LEASH_MARGIN_UNITS,
    )
    return WorldPosition(anchor.x, zone.center_y, anchor.z), radius


def hierarchical_objective_for(
    goal: QuestGoal,
    identity: QuestGoalIdentity,
    *,
    destination_reached: bool = False,
) -> HierarchicalObjective:
    """Return the active goal as the objective the tactical policy is conditioned on."""

    destination = (
        None
        if goal.destination is None
        else (goal.destination.x, goal.destination.y, goal.destination.z)
    )
    kind = _objective_kind(goal, destination is not None)
    interaction_target_id = (
        goal.npc.name
        if goal.kind in {QuestGoalKind.ACCEPT, QuestGoalKind.TURN_IN}
        and goal.npc is not None
        and goal.npc.name
        else None
    )
    return HierarchicalObjective(
        kind,
        None if goal.monster_name is None else frozenset({goal.monster_name}),
        destination,
        identity.quest_id,
        identity.index,
        identity.goal_count,
        min(identity.progress, identity.required_progress),
        identity.required_progress,
        destination_reached,
        interaction_target_id,
        QUEST_INTERACTION_TYPE,
        f"{identity.quest_id}:{identity.index}",
        _encoded_objective_kind(goal),
    )


def _encoded_objective_kind(goal: QuestGoal) -> ObjectiveKind:
    """Return what this goal asks for, in the vocabulary the observation is conditioned on."""

    if goal.kind in TRAVEL_GOAL_KINDS:
        return ObjectiveKind.GO_TO
    if goal.kind in INTERACTION_GOAL_KINDS:
        return ObjectiveKind.TALK_TO_NPC
    return ObjectiveKind.KILL


def _objective_kind(goal: QuestGoal, has_destination: bool) -> HierarchicalObjectiveKind:
    if goal.kind in TRAVEL_GOAL_KINDS and has_destination:
        return HierarchicalObjectiveKind.NAVIGATION
    if goal.kind is QuestGoalKind.SATISFY_OBJECTIVE:
        return HierarchicalObjectiveKind.FARMING
    return HierarchicalObjectiveKind.QUEST
