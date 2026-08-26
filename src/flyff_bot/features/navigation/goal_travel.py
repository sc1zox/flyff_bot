"""Decide whether a goal destination is walked to, teleported to, or unreachable.

Long-range travel used to exist only as emergency recovery (US-051). A quest goal states a
destination that may lie in another world or hundreds of units of terrain away, so this module
answers the one question the session needs before it starts moving: is this destination worth
walking to, does a client teleporter destination cover it, or is it out of reach entirely.

The planner reads the extracted teleporter catalog and the live position only. It never
dispatches anything: the guarded UI sequence and the arrival confirmation stay in
`TeleporterDispatcher`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.teleporter_models import (
    TeleporterCatalog,
    TeleporterDestination,
)

# Beyond this ground distance a walk costs more than a guarded teleporter dispatch. It is a
# travel policy, not a routing limit: the navigator still walks the remainder after arrival.
DEFAULT_MAXIMUM_WALK_DISTANCE_UNITS = 1500.0
# A teleporter destination only counts as covering a goal when its anchor is this close to it.
# Farther away the arrival would leave the walk just as long as it was before.
DEFAULT_DESTINATION_COVERAGE_RADIUS_UNITS = 3000.0


class GoalTravelMode(StrEnum):
    """How a goal destination is to be reached."""

    WALK = "walk"
    TELEPORT = "teleport"
    UNREACHABLE = "unreachable"


class GoalTravelRefusal(StrEnum):
    """Why a goal destination cannot be reached at all."""

    # The goal resolved to no world position, so there is nothing to travel towards.
    NO_DESTINATION = "no_destination"
    # Live GPS is unavailable, so no walking distance can be measured.
    POSITION_UNAVAILABLE = "position_unavailable"
    # The destination is out of walking range and no extracted teleporter destination covers it.
    NO_TELEPORTER_DESTINATION = "no_teleporter_destination"


@dataclass(frozen=True, slots=True)
class GoalTravelConfig:
    """The bounded travel policy a session applies to every goal destination."""

    maximum_walk_distance_units: float = DEFAULT_MAXIMUM_WALK_DISTANCE_UNITS
    destination_coverage_radius_units: float = DEFAULT_DESTINATION_COVERAGE_RADIUS_UNITS

    def __post_init__(self) -> None:
        if self.maximum_walk_distance_units <= 0.0:
            raise ValueError("The maximum walking distance must be positive.")
        if self.destination_coverage_radius_units <= 0.0:
            raise ValueError("The teleporter coverage radius must be positive.")


@dataclass(frozen=True, slots=True)
class GoalTravelPlan:
    """How one goal destination is reached, and why."""

    mode: GoalTravelMode
    destination: TeleporterDestination | None = None
    refusal: GoalTravelRefusal | None = None
    walk_distance_units: float | None = None

    def __post_init__(self) -> None:
        if self.mode is GoalTravelMode.TELEPORT and self.destination is None:
            raise ValueError("A teleport plan must name a teleporter destination.")
        if self.mode is GoalTravelMode.UNREACHABLE and self.refusal is None:
            raise ValueError("An unreachable travel plan must state its refusal reason.")

    @property
    def world_id(self) -> int | None:
        """Return the world identifier this plan travels into, when one is known."""

        return None if self.destination is None else self.destination.world_id


def plan_goal_travel(
    catalog: TeleporterCatalog,
    *,
    goal_destination: WorldPosition | None,
    player_position: WorldPosition | None,
    player_world_id: int | None = None,
    config: GoalTravelConfig | None = None,
) -> GoalTravelPlan:
    """Return how a session should reach one goal destination.

    A destination in the player's own world and within the configured walking distance is
    walked to. Otherwise the nearest extracted teleporter destination that covers it is
    dispatched. When neither holds, the plan refuses explicitly rather than starting an
    unbounded walk.
    """

    config = config or GoalTravelConfig()
    if goal_destination is None:
        return GoalTravelPlan(GoalTravelMode.UNREACHABLE, refusal=GoalTravelRefusal.NO_DESTINATION)
    mapped = _nearest_destination(catalog, goal_destination)
    walk_distance = (
        None
        if player_position is None
        else math.hypot(
            goal_destination.x - player_position.x, goal_destination.z - player_position.z
        )
    )
    in_player_world = (
        player_world_id is None or mapped is None or mapped[0].world_id == player_world_id
    )
    if (
        in_player_world
        and walk_distance is not None
        and walk_distance <= config.maximum_walk_distance_units
    ):
        return GoalTravelPlan(GoalTravelMode.WALK, walk_distance_units=walk_distance)
    if mapped is not None and mapped[1] <= config.destination_coverage_radius_units:
        return GoalTravelPlan(
            GoalTravelMode.TELEPORT,
            destination=mapped[0],
            walk_distance_units=walk_distance,
        )
    refusal = (
        GoalTravelRefusal.POSITION_UNAVAILABLE
        if walk_distance is None
        else GoalTravelRefusal.NO_TELEPORTER_DESTINATION
    )
    return GoalTravelPlan(
        GoalTravelMode.UNREACHABLE, refusal=refusal, walk_distance_units=walk_distance
    )


def _nearest_destination(
    catalog: TeleporterCatalog, goal_destination: WorldPosition
) -> tuple[TeleporterDestination, float] | None:
    """Return the catalog destination closest to a goal, with its anchor distance."""

    best: tuple[TeleporterDestination, float] | None = None
    for destination in catalog.destinations:
        distance = math.hypot(
            destination.anchor_x - goal_destination.x,
            destination.anchor_z - goal_destination.z,
        )
        if best is None or distance < best[1]:
            best = (destination, distance)
    return best
