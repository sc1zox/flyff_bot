"""Typed contract and deterministic mask tests for US-067."""

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.policy.heuristic import HeuristicPolicy
from flyff_bot.features.policy.models import (
    PolicyCandidate,
    PolicyContext,
    TacticalAction,
    TargetAction,
)


def _mob(
    identifier: int,
    *,
    navmesh_reachable: bool | None = True,
    navmesh_within_leash: bool | None = True,
    has_world_position: bool = True,
) -> VisibleMob:
    return VisibleMob(
        class_id=identifier,
        class_name=f"Mob{identifier}",
        confidence=0.9,
        x=10 + identifier * 5,
        y=20,
        width=10,
        height=10,
        world_x=1.0 if has_world_position else None,
        world_y=2.0 if has_world_position else None,
        world_z=3.0 if has_world_position else None,
        navmesh_reachable=navmesh_reachable,
        navmesh_within_leash=navmesh_within_leash,
    )


def _state(mobs: tuple[VisibleMob, ...]) -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        visible_mobs=mobs,
        viewport=Viewport(100, 100),
    )


def _context(mobs: tuple[VisibleMob, ...]) -> PolicyContext:
    candidates = tuple(
        PolicyCandidate(
            mob=mob,
            is_alive_and_recognized=True,
            is_unlocked=True,
            is_within_leash=mob.navmesh_within_leash is not False,
            is_navmesh_reachable=mob.navmesh_reachable is not False,
            has_valid_world_position=(
                mob.world_x is not None and mob.world_y is not None and mob.world_z is not None
            ),
        )
        for mob in mobs
    )
    return PolicyContext(
        candidates, frozenset(), tuple(candidate.is_unlocked for candidate in candidates)
    )


def test_tactical_policy_returns_a_typed_target_action() -> None:
    mobs = (_mob(1),)
    action = HeuristicPolicy().evaluate(_state(mobs), _context(mobs))

    assert isinstance(action, TargetAction)
    assert isinstance(action, TacticalAction)
    assert action.target_id == 1


def test_policy_cannot_select_an_invalid_masked_candidate() -> None:
    invalid = (
        _mob(1, navmesh_reachable=False),
        _mob(2, navmesh_within_leash=False),
        _mob(3, has_world_position=False),
    )
    action = HeuristicPolicy().evaluate(_state(invalid), _context(invalid))

    assert action is not None
    assert action.kind.value == "wait"
