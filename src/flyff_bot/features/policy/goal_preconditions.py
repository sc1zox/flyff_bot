"""Decide which strategic goals are legal before a policy ranks any of them (US-083).

A policy that is offered a goal it cannot ground will rank it anyway. Ranking is the wrong
place to discover that there is no route, no readable world, no spawn zone to farm, or no
resource left to cast with -- by then the choice has already been made and the deterministic
mask can only reject it after the fact, which shows up as a session that repeatedly picks an
action and has it thrown away.

So the grounding facts decide the option set first. World identity, the quest objective
identity, route and teleport state, dungeon availability, whether the session is already
engaged, the configured skill and resource constraints, and per-capability readiness all
narrow what is offered; the policy then ranks whatever survives.

The active spawn zone is deliberately not among them. It reaches a decision as spawn evidence
on the catalog join and as the reason a route exists at all, so it shapes what the policy
*ranks*; it does not make a goal legal or illegal on its own, and a field carried here that no
predicate reads would be exactly the silently-unused column this story forbids elsewhere.

The one rule that shapes the whole module: capabilities are independent. A blocked navigation
source must not remove the option to fight something standing in front of the character, and an
unreadable quest database must not stop farming. Anything else turns one optional missing source
into a dead session, which is the failure mode this criterion exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from flyff_bot.features.automation.readiness import SessionCapability

# WAIT is always offered. It is the only goal that needs nothing to be true, and removing it
# would leave a mask with no legal entry, which a masked argmax cannot resolve at all.
ALWAYS_LEGAL_GOALS = frozenset({"wait"})


@dataclass(frozen=True, slots=True)
class SessionGrounding:
    """The live session facts that decide which goals can be grounded this tick.

    Everything is optional and defaults to the least-capable reading, so a caller that has not
    measured something offers fewer options rather than accidentally claiming a capability. A
    field that is unknown never *enables* a goal.
    """

    world_id: int | None = None
    objective_id: str | None = None
    has_route: bool = False
    teleport_in_progress: bool = False
    dungeon_available: bool = False
    is_engaged: bool = False
    has_skill_resources: bool = True
    blocked_capabilities: frozenset[SessionCapability] = field(default_factory=frozenset)

    def is_available(self, capability: SessionCapability) -> bool:
        """Return whether one capability is usable, independently of every other."""

        return capability not in self.blocked_capabilities


def can_engage_targets(grounding: SessionGrounding) -> bool:
    """Return whether attacking something is a grounded option.

    Deliberately independent of navigation: a mob standing in front of the character can be
    fought whether or not the route planner has anything to say, and a blocked GPS is not a
    reason to stop defending. It does require the resources the operator configured, because
    an engagement that cannot cast is an engagement that stalls.
    """

    return (
        grounding.is_available(SessionCapability.COMBAT)
        and grounding.has_skill_resources
        and not grounding.teleport_in_progress
    )


def can_navigate(grounding: SessionGrounding) -> bool:
    """Return whether travelling is a grounded option.

    Requires a readable world: routing through geometry without knowing which map the
    character is standing in is how a session walks a route belonging to another world.
    """

    return (
        grounding.is_available(SessionCapability.NAVIGATION)
        and grounding.world_id is not None
        and grounding.has_route
        and not grounding.teleport_in_progress
        and not grounding.is_engaged
    )


def can_interact(grounding: SessionGrounding) -> bool:
    """Return whether interacting with a quest objective is a grounded option."""

    # Objective progress is not re-checked here: the strategic mask already gates interaction
    # on it, and stating one rule in two places is how the two drift apart.
    return (
        grounding.objective_id is not None
        and not grounding.teleport_in_progress
        and not grounding.is_engaged
    )


def can_enter_dungeon(grounding: SessionGrounding) -> bool:
    """Return whether a dungeon run is offered at all.

    The dungeon registry is intentionally empty until one is extracted, so this stays false
    for every ordinary session rather than offering a goal nothing can ground.
    """

    return (
        grounding.dungeon_available
        and grounding.is_available(SessionCapability.DUNGEON_AUTOMATION)
        and not grounding.is_engaged
    )
