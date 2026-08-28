"""Rank candidates by expected goal value per second, not by how close they are (US-083).

Picking the nearest legal mob is a proxy that quietly optimises the wrong thing. The nearest
candidate can be the one that takes longest to kill, hits hardest, is worth no quota credit,
and stands where nothing respawns; a slightly further one can be worth several of it. Distance
is a cost term -- a real one, since walking is time -- but it is one term, and using it as the
whole objective is what this module replaces.

The objective is verified goal value divided by measured end-to-end time, plus the risks that
time estimate does not capture. "Verified" is doing real work in that sentence: goal value
counts only what the session can actually confirm, so a quota the candidate advances counts and
a declared drop does not. The client states what a mover *may* drop, never what was collected,
and paying a policy for expected loot it never picked up is how a session learns to farm a
number rather than an outcome.

Every term degrades independently. A candidate with no catalog join still ranks -- it simply
ranks on the measured terms alone, with the client-stated ones absent rather than guessed. That
is the same posture the rest of this story takes: fewer facts narrow the estimate, they do not
fabricate one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from flyff_bot.features.automation.models import VisibleMob, WorldState
from flyff_bot.features.client_data.label_mapping import JoinedMoverCandidate
from flyff_bot.features.client_data.models import MoverCombatProperties

# A candidate the session cannot time at all still has to be comparable to one it can, so the
# unmeasured terms fall back to these. They are deliberately pessimistic-but-finite: an unknown
# cost that scored as zero would win every ranking by knowing nothing.
DEFAULT_TRAVEL_SPEED_UNITS_PER_SECOND = 6.0
DEFAULT_TURN_RATE_DEGREES_PER_SECOND = 180.0
DEFAULT_COMBAT_SECONDS = 8.0
# The player's damage output is not a client-stated column, so expected combat duration is
# derived from the mover's hit points at this assumed rate. It is an estimate used only to
# compare candidates against each other, never reported as a measurement.
ASSUMED_PLAYER_DAMAGE_PER_SECOND = 40.0
# Bounds that keep one pathological term from dominating the whole objective.
MINIMUM_ENGAGEMENT_SECONDS = 1.0
MAXIMUM_RISK = 1.0
# A mover that respawns quickly in a high-capacity zone is worth returning to, so a camp is
# worth a bounded bonus over an equivalent one-off kill.
MAXIMUM_RESPAWN_BONUS = 0.25
RESPAWN_REFERENCE_SECONDS = 60.0
# Goal value of a candidate that advances no quota. It is not zero: killing anything still
# yields experience, so an unwanted mob is worth less than a wanted one, not worthless.
BASE_GOAL_VALUE = 1.0
QUOTA_GOAL_VALUE = 3.0


@dataclass(frozen=True, slots=True)
class CandidateEconomics:
    """The expected value and the measured cost of engaging one candidate.

    Time terms are seconds. Risk terms are fractions in ``[0, 1]`` that scale the value down
    rather than adding fictional seconds, so a risky candidate loses expected value without
    its duration estimate being corrupted.
    """

    candidate_index: int | None
    goal_value: float
    travel_seconds: float
    turning_seconds: float
    combat_seconds: float
    stall_risk: float
    resource_risk: float
    failed_action_risk: float
    respawn_followup_value: float
    has_client_evidence: bool

    @property
    def expected_seconds(self) -> float:
        """Return the end-to-end time one engagement is expected to occupy."""

        return max(
            MINIMUM_ENGAGEMENT_SECONDS,
            self.travel_seconds + self.turning_seconds + self.combat_seconds,
        )

    @property
    def expected_value(self) -> float:
        """Return the goal value that survives this candidate's risks."""

        survives = (
            (1.0 - self.stall_risk) * (1.0 - self.resource_risk) * (1.0 - self.failed_action_risk)
        )
        return (self.goal_value + self.respawn_followup_value) * survives

    @property
    def expected_value_per_second(self) -> float:
        """Return the objective the ranking maximizes: verified value over real time."""

        return self.expected_value / self.expected_seconds


def rank_candidates(
    candidates: tuple[VisibleMob, ...],
    state: WorldState,
    *,
    heading_degrees: float | None = None,
    quota_class_names: frozenset[str] = frozenset(),
    stall_risk_by_class: dict[str, float] | None = None,
    failed_action_risk: float = 0.0,
) -> tuple[tuple[VisibleMob, CandidateEconomics], ...]:
    """Return every candidate paired with its economics, best objective first.

    Ties break on the candidate identity so two equally valued candidates always rank in the
    same order: a ranking that reshuffles on equal evidence makes a session oscillate between
    two targets instead of committing to one.
    """

    scored = tuple(
        (
            mob,
            candidate_economics(
                mob,
                state,
                heading_degrees=heading_degrees,
                quota_class_names=quota_class_names,
                stall_risk=(stall_risk_by_class or {}).get(mob.class_name, 0.0),
                failed_action_risk=failed_action_risk,
            ),
        )
        for mob in candidates
    )
    return tuple(
        sorted(
            scored,
            key=lambda item: (
                -item[1].expected_value_per_second,
                item[1].candidate_index if item[1].candidate_index is not None else 0,
                item[0].class_id,
            ),
        )
    )


def candidate_economics(
    mob: VisibleMob,
    state: WorldState,
    *,
    heading_degrees: float | None = None,
    quota_class_names: frozenset[str] = frozenset(),
    stall_risk: float = 0.0,
    failed_action_risk: float = 0.0,
) -> CandidateEconomics:
    """Estimate one candidate's expected value and end-to-end cost."""

    join = state.catalog_join(mob.candidate_index)
    combat = None if join is None else join.combat
    return CandidateEconomics(
        candidate_index=mob.candidate_index,
        goal_value=(QUOTA_GOAL_VALUE if mob.class_name in quota_class_names else BASE_GOAL_VALUE),
        travel_seconds=_travel_seconds(mob),
        turning_seconds=_turning_seconds(mob, state, heading_degrees),
        combat_seconds=_combat_seconds(combat),
        stall_risk=_clamp_risk(stall_risk),
        resource_risk=_resource_risk(state, combat),
        failed_action_risk=_clamp_risk(failed_action_risk),
        respawn_followup_value=_respawn_followup_value(join),
        has_client_evidence=join is not None,
    )


def _travel_seconds(mob: VisibleMob) -> float:
    """Return the measured route time, or zero when no route was measured.

    Zero rather than a penalty: an unmeasured route means the NavMesh could not price this
    candidate, and inventing a distance would rank it on a number nothing observed.
    """

    distance = mob.navmesh_path_distance
    if distance is None or not math.isfinite(distance) or distance < 0.0:
        return 0.0
    return distance / DEFAULT_TRAVEL_SPEED_UNITS_PER_SECOND


def _turning_seconds(mob: VisibleMob, state: WorldState, heading_degrees: float | None) -> float:
    """Return the time spent rotating onto the candidate before moving.

    Turning is real elapsed time that pure distance ignores, which is how a candidate directly
    behind the character reads as "close" while costing a full rotation to reach.
    """

    if heading_degrees is None or mob.world_x is None or mob.world_z is None:
        return 0.0
    live = state.observation_interval
    if not live.is_coherent:
        return 0.0
    bearing = math.degrees(math.atan2(mob.world_x, mob.world_z))
    delta = abs((bearing - heading_degrees + 180.0) % 360.0 - 180.0)
    return delta / DEFAULT_TURN_RATE_DEGREES_PER_SECOND


def _combat_seconds(combat: MoverCombatProperties | None) -> float:
    """Return how long this mover is expected to take to kill.

    Derived from the client's own hit-point column when it stated one. Without it the estimate
    falls back to a fixed duration rather than to zero, because a mover that costs nothing to
    kill would win every ranking on the strength of a missing column.
    """

    hit_points = None if combat is None else combat.hit_points
    if hit_points is None or hit_points <= 0:
        return DEFAULT_COMBAT_SECONDS
    return max(MINIMUM_ENGAGEMENT_SECONDS, float(hit_points) / ASSUMED_PLAYER_DAMAGE_PER_SECOND)


def _resource_risk(state: WorldState, combat: MoverCombatProperties | None) -> float:
    """Return how much of the player's remaining health this engagement threatens.

    Uses the mover's declared maximum hit against the health actually left, so the same mover
    is a small risk at full health and a large one at low health.
    """

    attack_maximum = None if combat is None else combat.attack_maximum
    hp_percentage = state.player_vitals.hp_percentage
    if attack_maximum is None or attack_maximum <= 0 or hp_percentage <= 0.0:
        return 0.0
    # Expressed against the health that remains rather than the maximum: the question is what
    # this fight costs from here, not what it would cost from full.
    threatened = float(attack_maximum) / max(hp_percentage, 1.0)
    return _clamp_risk(threatened / 100.0)


def _respawn_followup_value(join: JoinedMoverCandidate | None) -> float:
    """Return the bounded bonus for a mover the world replaces quickly and in numbers.

    A camp is worth more than an equivalent one-off kill because the next engagement costs no
    travel. The bonus is capped so follow-up value can shade a ranking without overturning a
    candidate that is simply worth more.
    """

    spawn = None if join is None else join.spawn
    if spawn is None or spawn.total_capacity <= 0:
        return 0.0
    respawn = spawn.minimum_respawn_seconds
    if respawn is None or respawn <= 0:
        return 0.0
    density = min(1.0, spawn.total_capacity / 10.0)
    speed = min(1.0, RESPAWN_REFERENCE_SECONDS / float(respawn))
    return MAXIMUM_RESPAWN_BONUS * density * speed


def _clamp_risk(value: float) -> float:
    """Return a risk fraction inside ``[0, 1]``, treating a bad number as no risk."""

    if not math.isfinite(value) or value <= 0.0:
        return 0.0
    return min(value, MAXIMUM_RISK)
