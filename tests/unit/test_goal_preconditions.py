"""Which strategic goals are grounded before a policy ranks them (US-083 AC6)."""

from __future__ import annotations

from flyff_bot.features.automation.readiness import SessionCapability
from flyff_bot.features.policy.goal_preconditions import (
    SessionGrounding,
    can_engage_targets,
    can_enter_dungeon,
    can_interact,
    can_navigate,
)

WORLD_ID = 1
OBJECTIVE_ID = "quest-7:objective-2"


def _grounded() -> SessionGrounding:
    """Return a session where every goal is grounded, so a test can remove one fact."""

    return SessionGrounding(
        world_id=WORLD_ID,
        objective_id=OBJECTIVE_ID,
        has_route=True,
        dungeon_available=True,
    )


def test_a_fully_grounded_session_offers_every_goal() -> None:
    grounding = _grounded()

    assert can_engage_targets(grounding)
    assert can_navigate(grounding)
    assert can_interact(grounding)
    assert can_enter_dungeon(grounding)


def test_a_blocked_navigation_capability_does_not_remove_combat() -> None:
    # The criterion's core rule: optional unrelated data must not block an independent
    # capability. A mob in front of the character is still fightable without a route.
    grounding = SessionGrounding(
        world_id=WORLD_ID,
        has_route=True,
        blocked_capabilities=frozenset({SessionCapability.NAVIGATION}),
    )

    assert not can_navigate(grounding)
    assert can_engage_targets(grounding)


def test_a_blocked_combat_capability_does_not_remove_navigation() -> None:
    grounding = SessionGrounding(
        world_id=WORLD_ID,
        has_route=True,
        blocked_capabilities=frozenset({SessionCapability.COMBAT}),
    )

    assert not can_engage_targets(grounding)
    assert can_navigate(grounding)


def test_an_absent_quest_objective_does_not_stop_farming() -> None:
    # An install with no readable quest database still farms.
    grounding = SessionGrounding(world_id=WORLD_ID, has_route=True, objective_id=None)

    assert not can_interact(grounding)
    assert can_engage_targets(grounding)
    assert can_navigate(grounding)


def test_navigation_needs_a_readable_world() -> None:
    # Routing without knowing the map is how a session walks another world's route.
    grounding = SessionGrounding(world_id=None, has_route=True)

    assert not can_navigate(grounding)


def test_navigation_needs_an_actual_route() -> None:
    assert not can_navigate(SessionGrounding(world_id=WORLD_ID, has_route=False))


def test_an_exhausted_resource_floor_makes_engagement_ungrounded() -> None:
    grounding = SessionGrounding(world_id=WORLD_ID, has_route=True, has_skill_resources=False)

    assert not can_engage_targets(grounding)
    # Travelling does not need the casting resource, so it stays available.
    assert can_navigate(grounding)


def test_a_teleport_in_flight_suspends_every_grounded_goal() -> None:
    grounding = SessionGrounding(
        world_id=WORLD_ID,
        objective_id=OBJECTIVE_ID,
        has_route=True,
        dungeon_available=True,
        teleport_in_progress=True,
    )

    assert not can_engage_targets(grounding)
    assert not can_navigate(grounding)
    assert not can_interact(grounding)


def test_an_active_engagement_suspends_travel_but_not_the_fight() -> None:
    grounding = SessionGrounding(
        world_id=WORLD_ID, objective_id=OBJECTIVE_ID, has_route=True, is_engaged=True
    )

    assert can_engage_targets(grounding)
    assert not can_navigate(grounding)
    assert not can_interact(grounding)


def test_an_empty_dungeon_registry_never_offers_the_goal() -> None:
    assert not can_enter_dungeon(SessionGrounding(world_id=WORLD_ID, dungeon_available=False))


def test_unmeasured_facts_default_to_the_least_capable_reading() -> None:
    # A caller that measured nothing offers fewer options rather than claiming capabilities.
    empty = SessionGrounding()

    assert not can_navigate(empty)
    assert not can_interact(empty)
    assert not can_enter_dungeon(empty)
