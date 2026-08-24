"""Heuristic parity regression coverage for the tactical policy facade."""

import pytest

from flyff_bot.features.automation.controllers import CombatConfig, CombatController
from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.policy.heuristic import HeuristicPolicy
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext, TargetAction


def _mob(identifier: int, x: int) -> VisibleMob:
    return VisibleMob(
        class_id=identifier,
        class_name=f"Mob{identifier}",
        confidence=0.9,
        x=x,
        y=20,
        width=10,
        height=10,
        world_x=1.0,
        world_y=2.0,
        world_z=3.0,
    )


def _state(mobs: tuple[VisibleMob, ...]) -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        visible_mobs=mobs,
        viewport=Viewport(200, 200),
    )


def _context(mobs: tuple[VisibleMob, ...]) -> PolicyContext:
    candidates = tuple(
        PolicyCandidate(
            mob=mob,
            is_alive_and_recognized=True,
            is_unlocked=True,
            is_within_leash=True,
            is_navmesh_reachable=True,
            has_valid_world_position=True,
        )
        for mob in mobs
    )
    return PolicyContext(candidates, frozenset(), (False,) * len(candidates))


@pytest.mark.parametrize("mobs", [(_mob(1, 40), _mob(2, 80)), (_mob(1, 80), _mob(2, 40))])
def test_heuristic_matches_legacy_controller_selection(mobs: tuple[VisibleMob, ...]) -> None:
    legacy = CombatController(CombatConfig()).step(_state(mobs)).selected_mob
    action = HeuristicPolicy().evaluate(_state(mobs), _context(mobs))

    assert legacy is not None
    assert isinstance(action, TargetAction)
    assert action.target_id == legacy.class_id
