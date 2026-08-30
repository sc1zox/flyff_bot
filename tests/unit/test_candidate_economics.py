"""Ranking by expected goal value per second rather than by distance (US-083 AC8)."""

from __future__ import annotations

from flyff_bot.features.automation.models import (
    Position,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.client_data.label_mapping import JoinedMoverCandidate, SpawnEvidence
from flyff_bot.features.client_data.models import MoverCombatProperties
from flyff_bot.features.policy.candidate_economics import (
    candidate_economics,
    rank_candidates,
)

CLIENT_DIGEST = "b" * 64
MAPPING_VERSION = "1"
NEAR_DISTANCE = 10.0
FAR_DISTANCE = 40.0
TOUGH_HIT_POINTS = 4000
EASY_HIT_POINTS = 200
HARD_HITTING_ATTACK = 900


def _mob(
    candidate_index: int,
    class_name: str,
    *,
    class_id: int = 1,
    path_distance: float | None = None,
) -> VisibleMob:
    return VisibleMob(
        class_id,
        class_name,
        0.9,
        10,
        10,
        20,
        20,
        navmesh_path_distance=path_distance,
        candidate_index=candidate_index,
    )


def _join(
    candidate_index: int,
    class_name: str,
    *,
    mover_id: int = 1,
    hit_points: int | None = None,
    attack_maximum: int | None = None,
    spawn: SpawnEvidence | None = None,
) -> JoinedMoverCandidate:
    return JoinedMoverCandidate(
        candidate_index=candidate_index,
        detector_label=class_name,
        mover_id=mover_id,
        mover_symbol=f"MI_{class_name.upper()}",
        display_name=class_name,
        combat=MoverCombatProperties(hit_points=hit_points, attack_maximum=attack_maximum),
        drops=(),
        mapping_version=MAPPING_VERSION,
        client_digest=CLIENT_DIGEST,
        spawn=spawn,
    )


def _state(
    joins: tuple[JoinedMoverCandidate, ...] = (), hp_percentage: float = 100.0
) -> WorldState:
    from flyff_bot.features.vision.models import PlayerVitals

    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=2,
        progress_marker=0,
        player_vitals=PlayerVitals(hp_percentage, 100.0, 100.0),
        mob_catalog_joins=joins,
    )


def test_a_nearer_but_far_tougher_candidate_loses_to_a_further_easy_one() -> None:
    # The whole point of the criterion: minimum walking distance is one cost component,
    # not a substitute for total farming yield.
    tough_near = _mob(0, "Tough", class_id=1, path_distance=NEAR_DISTANCE)
    easy_far = _mob(1, "Easy", class_id=2, path_distance=FAR_DISTANCE)
    state = _state(
        (
            _join(0, "Tough", mover_id=1, hit_points=TOUGH_HIT_POINTS),
            _join(1, "Easy", mover_id=2, hit_points=EASY_HIT_POINTS),
        )
    )

    ranked = rank_candidates((tough_near, easy_far), state)

    assert ranked[0][0] is easy_far


def test_a_candidate_that_advances_a_quota_outranks_an_equivalent_one_that_does_not() -> None:
    wanted = _mob(0, "Wanted", class_id=1, path_distance=FAR_DISTANCE)
    unwanted = _mob(1, "Unwanted", class_id=2, path_distance=NEAR_DISTANCE)
    state = _state(
        (
            _join(0, "Wanted", mover_id=1, hit_points=EASY_HIT_POINTS),
            _join(1, "Unwanted", mover_id=2, hit_points=EASY_HIT_POINTS),
        )
    )

    ranked = rank_candidates((wanted, unwanted), state, quota_class_names=frozenset({"Wanted"}))

    assert ranked[0][0] is wanted


def test_a_hard_hitting_mover_is_a_larger_risk_at_low_health() -> None:
    mob = _mob(0, "Brute", path_distance=NEAR_DISTANCE)
    join = (_join(0, "Brute", hit_points=EASY_HIT_POINTS, attack_maximum=HARD_HITTING_ATTACK),)

    healthy = candidate_economics(mob, _state(join, hp_percentage=100.0))
    wounded = candidate_economics(mob, _state(join, hp_percentage=10.0))

    assert wounded.resource_risk > healthy.resource_risk
    assert wounded.expected_value < healthy.expected_value


def test_a_densely_respawning_mover_earns_a_bounded_follow_up_bonus() -> None:
    mob = _mob(0, "Camper", path_distance=NEAR_DISTANCE)
    camped = candidate_economics(
        mob,
        _state(
            (
                _join(
                    0,
                    "Camper",
                    hit_points=EASY_HIT_POINTS,
                    spawn=SpawnEvidence(zone_count=2, total_capacity=20, minimum_respawn_seconds=5),
                ),
            )
        ),
    )
    lone = candidate_economics(mob, _state((_join(0, "Camper", hit_points=EASY_HIT_POINTS),)))

    assert camped.respawn_followup_value > lone.respawn_followup_value
    # Bounded, so follow-up value shades a ranking without overturning real value.
    assert camped.respawn_followup_value <= 0.25


def test_a_declared_drop_is_never_counted_as_yield() -> None:
    # The client states what a mover may drop, never what was collected. Two candidates
    # differing only in declared drops must rank identically.
    mob = _mob(0, "Dropper", path_distance=NEAR_DISTANCE)
    join = _join(0, "Dropper", hit_points=EASY_HIT_POINTS)
    state = _state((join,))

    assert candidate_economics(mob, state).goal_value == 1.0


def test_a_candidate_without_a_catalog_join_still_ranks_on_measured_terms() -> None:
    unjoined = _mob(0, "Unknown", path_distance=NEAR_DISTANCE)

    economics = candidate_economics(unjoined, _state())

    assert not economics.has_client_evidence
    assert economics.travel_seconds > 0.0
    # An unknown fight falls back to a finite duration rather than to zero, which would
    # otherwise let a missing column win every ranking.
    assert economics.combat_seconds > 0.0


def test_stall_and_failure_risk_reduce_expected_value() -> None:
    mob = _mob(0, "Stally", path_distance=NEAR_DISTANCE)
    state = _state((_join(0, "Stally", hit_points=EASY_HIT_POINTS),))

    clean = candidate_economics(mob, state)
    risky = candidate_economics(mob, state, stall_risk=0.5, failed_action_risk=0.5)

    assert risky.expected_value < clean.expected_value
    assert risky.expected_value_per_second < clean.expected_value_per_second


def test_equal_candidates_rank_in_a_stable_order() -> None:
    # A ranking that reshuffles on equal evidence makes a session oscillate between targets.
    first = _mob(0, "Same", class_id=1, path_distance=NEAR_DISTANCE)
    second = _mob(1, "Same", class_id=2, path_distance=NEAR_DISTANCE)
    state = _state(
        (
            _join(0, "Same", mover_id=1, hit_points=EASY_HIT_POINTS),
            _join(1, "Same", mover_id=2, hit_points=EASY_HIT_POINTS),
        )
    )

    assert rank_candidates((first, second), state) == rank_candidates((second, first), state)
