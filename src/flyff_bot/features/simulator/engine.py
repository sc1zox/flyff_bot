"""Deterministic offline simulation of tactical farming and navigation.

One tick is a fixed budget of simulated seconds. Every action spends that budget on a named
activity - recovery, turning, travelling, fighting - and whatever is left over is idle time,
so ``elapsed_seconds`` is always exactly the sum of the recorded activity buckets. Nothing
relocates the player except :meth:`FarmingSimulator._travel_toward`, and that follows the
route the extracted obstacle geometry allows rather than a straight line.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from flyff_bot.features.navigation.vector_routing import VectorRoutePlanner
from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldCoordinate,
    WorldVectorMap,
)
from flyff_bot.features.policy.action_payloads import (
    STRATEGIC_GOAL_COUNT,
    STRATEGIC_GOAL_ORDER,
    StrategicGoalKind,
    strategic_goal_at,
)
from flyff_bot.features.rl.models import (
    CandidateObservation,
    NavMeshContext,
    ObjectiveState,
    OperationalState,
    PlayerKinematics,
    PlayerVitals,
    RlObservation,
)
from flyff_bot.features.rl.rewards import RewardEngine, RewardEvent
from flyff_bot.features.simulator.models import (
    MonsterLifecycle,
    QuestObjective,
    QuestObjectiveKind,
    SimulationMetrics,
    SimulatorConfig,
    sample_log_normal,
)

FULL_CIRCLE_RADIANS = math.tau
INTERACTION_RADIUS_UNITS = 3.0
MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS = 10.0
INITIAL_VITALS_PERCENT = 100.0
OBSERVED_CANDIDATE_SLOTS = 4
# Two positions this close together are the same place: a waypoint is reached and a route to
# it needs no further leg.
ARRIVAL_EPSILON_UNITS = 1e-3
# How much of a leg is still covered when the character catches on geometry. The rest of the
# leg is lost and a sampled recovery blocks the following ticks.
STALL_PROGRESS_FRACTION = 0.25
# A route that bends is a corridor detour; a two-point route is straight-line travel.
STRAIGHT_ROUTE_POINT_COUNT = 2


class IllegalSimulatorAction(ValueError):
    """Raised when an action that the current mask forbids is submitted to ``step``."""


@dataclass(frozen=True, slots=True)
class SimulatedMonster:
    """One independently timed and positioned simulated monster.

    ``monster_slot`` is the monster's stable index in the simulator's roster. Respawning
    replaces the record in place, so the slot - never the record - identifies a target.
    """

    monster_slot: int
    monster_id: int
    zone_index: int
    position_x: float
    position_z: float
    lifecycle: MonsterLifecycle
    available_at_seconds: float = 0.0
    combat_seconds_remaining: float = 0.0


@dataclass(frozen=True, slots=True)
class SimulationStep:
    """The complete externally observable result of one simulator tick."""

    observation: RlObservation
    reward: float
    terminated: bool
    truncated: bool
    metrics: SimulationMetrics
    events: tuple[str, ...]


@dataclass(slots=True)
class _TickAccounting:
    """How one tick's budget was spent, which is what the reward is computed from."""

    travel_seconds: float = 0.0
    combat_seconds: float = 0.0
    recovery_seconds: float = 0.0
    idle_seconds: float = 0.0
    stalled_seconds: float = 0.0
    kill_count: int = 0


class FarmingSimulator:
    """Run a seeded tactical episode without a client process or live input dispatch."""

    # Reward deltas are measured against the previous tick, so both counters are read before
    # ``_reset_state`` establishes them on the first episode.
    _previous_progress_total: int
    _previous_completed_count: int

    def __init__(
        self,
        world_map: WorldVectorMap,
        *,
        start: WorldCoordinate,
        objectives: tuple[QuestObjective, ...] = (),
        config: SimulatorConfig | None = None,
        seed: int | None = None,
    ) -> None:
        self._world_map = world_map
        self._config = config or SimulatorConfig()
        self._objectives = objectives
        self._start = start
        self._zones = world_map.zones
        if not self._zones:
            raise ValueError("A farming simulation needs at least one extracted spawn zone.")
        if not world_map.dimensions.contains(start):
            raise ValueError("Simulation start must lie inside the extracted map bounds.")
        self._validate_objectives()
        self._planner = VectorRoutePlanner(world_map.obstacles)
        self._rewards = RewardEngine(self._config.reward)
        self._random = random.Random(seed)
        self._reset_state()

    @property
    def action_space_size(self) -> int:
        return STRATEGIC_GOAL_COUNT

    def reset(self, *, seed: int | None = None) -> tuple[RlObservation, dict[str, object]]:
        """Reset to the configured start state and optionally reseed the PRNG."""

        if seed is not None:
            self._random.seed(seed)
        self._reset_state()
        return self.observation, {"action_mask": self.action_mask}

    def step(self, action: int) -> tuple[RlObservation, float, bool, bool, dict[str, object]]:
        """Advance one fixed-duration tactical tick deterministically."""

        goal = strategic_goal_at(action)
        mask = self.action_mask
        if not mask[action]:
            raise IllegalSimulatorAction(f"Goal {goal.value} is masked out.")

        events: list[str] = []
        tick = _TickAccounting()
        budget = self._spend_recovery(self._config.tick_seconds, tick)
        budget = self._perform(goal, budget, tick, events)
        tick.idle_seconds = max(0.0, budget)
        self._idle_seconds += tick.idle_seconds

        self._elapsed_seconds += self._config.tick_seconds
        self._advance_spawns()
        self._refresh_route()

        completed_count = sum(1 for complete in self._completed if complete)
        progress_total = sum(self._progress)
        reward = self._rewards.reward(
            RewardEvent(
                verified_kill=tick.kill_count > 0,
                quest_progress_delta=float(progress_total - self._previous_progress_total),
                objective_completed=completed_count > self._previous_completed_count,
                travel_seconds=tick.travel_seconds,
                idle_seconds=tick.idle_seconds,
                stuck_seconds=tick.stalled_seconds,
                recovery_seconds=tick.recovery_seconds,
            )
        )
        self._previous_progress_total = progress_total
        self._previous_completed_count = completed_count

        terminated = self._all_objectives_complete()
        truncated = not terminated and self._elapsed_seconds >= (
            self._config.maximum_episode_seconds
        )
        step = self.step_result(reward, terminated, truncated, tuple(events))
        return (
            step.observation,
            step.reward,
            step.terminated,
            step.truncated,
            {
                "action_mask": self.action_mask,
                "events": step.events,
            },
        )

    def step_result(
        self, reward: float, terminated: bool, truncated: bool, events: tuple[str, ...]
    ) -> SimulationStep:
        return SimulationStep(
            self.observation,
            reward,
            terminated,
            truncated,
            self.metrics,
            events,
        )

    @property
    def action_mask(self) -> tuple[bool, ...]:
        """Return deterministic validity per strategic goal, in the shared wire order."""

        if self._recovery_remaining > 0.0:
            return tuple(goal is StrategicGoalKind.WAIT for goal in STRATEGIC_GOAL_ORDER)
        target_selected = self._target is not None
        destination = self._travel_destination()
        interaction_ready = self._interaction_ready()
        travel_allowed = (
            destination is not None
            and not self._route_blocked
            and not interaction_ready
            and self._distance(destination.x, destination.z) > ARRIVAL_EPSILON_UNITS
        )
        allowed = {
            StrategicGoalKind.TARGET: bool(self._visible_monsters()) and not target_selected,
            StrategicGoalKind.NAVIGATE: travel_allowed,
            StrategicGoalKind.INTERACT: interaction_ready,
            StrategicGoalKind.WAIT: True,
        }
        return tuple(allowed[goal] for goal in STRATEGIC_GOAL_ORDER)

    @property
    def metrics(self) -> SimulationMetrics:
        return SimulationMetrics(
            elapsed_seconds=self._elapsed_seconds,
            kill_count=self._kill_count,
            travel_seconds=self._travel_seconds,
            combat_seconds=self._combat_seconds,
            recovery_seconds=self._recovery_seconds,
            idle_seconds=self._idle_seconds,
            distance_units=self._distance_units,
            stuck_count=self._stuck_count,
        )

    @property
    def has_route_detour(self) -> bool:
        """Return whether the current route bends around extracted obstacle geometry."""

        return len(self._route) > STRAIGHT_ROUTE_POINT_COUNT - 1

    @property
    def is_combat_engagement(self) -> bool:
        """Return whether an ``INTERACT`` right now would attack a monster."""

        target = self._target
        return target is not None and self._distance(target.position_x, target.position_z) <= (
            MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS
        )

    @property
    def observation(self) -> RlObservation:
        visible = self._visible_monsters()
        candidates = tuple(
            CandidateObservation(
                index,
                monster.monster_id,
                1.0,
                monster.position_x,
                self._height_at(monster.position_x, monster.position_z) or 0.0,
                monster.position_z,
                self._distance(monster.position_x, monster.position_z),
                0.0,
                is_dead=False,
                is_unreachable=False,
            )
            for index, monster in enumerate(visible[:OBSERVED_CANDIDATE_SLOTS])
        )
        progress_values: list[tuple[int, float]] = []
        for item, progress in zip(self._objectives, self._progress, strict=True):
            required = item.required_count
            progress_values.append(
                (
                    required,
                    float(progress)
                    if item.kind is QuestObjectiveKind.KILL
                    else (float(required) if progress > 0 else 0.0),
                )
            )
        target = self._target
        return RlObservation(
            PlayerKinematics(
                self._x,
                self._height_at(self._x, self._z) or 0.0,
                self._z,
                self._heading,
                math.cos(self._heading) * self.nominal_speed,
                0.0,
                math.sin(self._heading) * self.nominal_speed,
            ),
            PlayerVitals(INITIAL_VITALS_PERCENT, INITIAL_VITALS_PERCENT, INITIAL_VITALS_PERCENT),
            NavMeshContext(None, None, self._route_distance()),
            candidates,
            OperationalState(
                None
                if target is None
                else next(
                    (
                        index
                        for index, monster in enumerate(visible[:OBSERVED_CANDIDATE_SLOTS])
                        if monster.monster_slot == target.monster_slot
                    ),
                    None,
                ),
                self._kill_count * 60.0 / self._elapsed_seconds if self._elapsed_seconds else 0.0,
                self._stuck_count,
                "farming",
            ),
            ObjectiveState(
                str(len(self._objectives)) if self._objectives else None,
                tuple(progress_values),
                self._objective_distance(),
            ),
        )

    # -- Episode state ------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._x: float = self._start.x
        self._z: float = self._start.z
        self._heading: float = 0.0
        self._elapsed_seconds: float = 0.0
        self._travel_seconds: float = 0.0
        self._combat_seconds: float = 0.0
        self._recovery_seconds: float = 0.0
        self._idle_seconds: float = 0.0
        self._distance_units: float = 0.0
        self._stuck_count: int = 0
        self._kill_count: int = 0
        self._recovery_remaining: float = 0.0
        self._target_slot: int | None = None
        self._route: tuple[WorldCoordinate, ...] = ()
        self._route_goal: WorldCoordinate | None = None
        self._route_blocked: bool = False
        self._monsters: list[SimulatedMonster] = []
        self._progress: list[int] = [0] * len(self._objectives)
        self._completed: list[bool] = [False] * len(self._objectives)
        self._previous_progress_total = 0
        self._previous_completed_count = 0
        for zone_index, zone in enumerate(self._zones):
            for _slot in range(zone.capacity):
                self._monsters.append(self._spawn_monster(zone, zone_index, len(self._monsters)))
        self._refresh_route()

    @property
    def nominal_speed(self) -> float:
        return self._config.nominal_speed_units_per_second

    def _validate_objectives(self) -> None:
        for objective in self._objectives:
            if objective.kind is QuestObjectiveKind.GO_TO and (
                objective.position_x is None
                or objective.position_z is None
                or not self._world_map.dimensions.contains(
                    WorldCoordinate(objective.position_x, objective.position_z)
                )
            ):
                raise ValueError("Movement objective lies outside the loaded world map.")

    # -- Tick execution -----------------------------------------------------------------

    def _spend_recovery(self, budget: float, tick: _TickAccounting) -> float:
        """Consume a pending stall recovery first: it blocks every other activity."""

        if self._recovery_remaining <= 0.0:
            return budget
        spent = min(budget, self._recovery_remaining)
        self._recovery_remaining -= spent
        self._recovery_seconds += spent
        tick.recovery_seconds += spent
        return budget - spent

    def _perform(
        self,
        goal: StrategicGoalKind,
        budget: float,
        tick: _TickAccounting,
        events: list[str],
    ) -> float:
        if budget <= 0.0 or goal is StrategicGoalKind.WAIT:
            return budget
        if goal is StrategicGoalKind.TARGET:
            self._target_slot = self._visible_monsters()[0].monster_slot
            return budget
        if goal is StrategicGoalKind.NAVIGATE:
            return self._travel_toward(budget, tick)
        return self._interact(budget, tick, events)

    def _interact(self, budget: float, tick: _TickAccounting, events: list[str]) -> float:
        if self.is_combat_engagement:
            return self._attack(budget, tick, events)
        objective = self._active_objective()
        if objective is None or objective.kind is QuestObjectiveKind.KILL:
            return budget
        index = self._objectives.index(objective)
        self._progress[index] = objective.required_count
        self._completed[index] = True
        events.append("quest_progress")
        return budget

    def _attack(self, budget: float, tick: _TickAccounting, events: list[str]) -> float:
        target = self._target
        if target is None:
            return budget
        if target.combat_seconds_remaining <= 0.0:
            target = self._store(
                target,
                lifecycle=MonsterLifecycle.IN_COMBAT,
                combat_seconds_remaining=sample_log_normal(
                    self._random,
                    self._config.combat_time_mu,
                    self._config.combat_time_sigma,
                ),
            )
        spent = min(budget, target.combat_seconds_remaining)
        self._combat_seconds += spent
        tick.combat_seconds += spent
        remaining = target.combat_seconds_remaining - spent
        if remaining > 0.0:
            self._store(target, combat_seconds_remaining=remaining)
            return budget - spent
        zone = self._zones[target.zone_index]
        self._store(
            target,
            lifecycle=MonsterLifecycle.DEAD,
            combat_seconds_remaining=0.0,
            available_at_seconds=self._elapsed_seconds + zone.respawn_seconds,
        )
        self._target_slot = None
        self._kill_count += 1
        tick.kill_count += 1
        self._complete_kill_objective(target.monster_id, events)
        events.append("kill")
        return budget - spent

    def _travel_toward(self, budget: float, tick: _TickAccounting) -> float:
        """Walk the planned corridor, spending the tick's remaining seconds on it."""

        route = list(self._route)
        while budget > 0.0 and route:
            waypoint = route[0]
            budget = self._turn_toward(waypoint, budget, tick)
            if budget <= 0.0:
                break
            remaining = self._distance(waypoint.x, waypoint.z)
            leg = min(budget * self.nominal_speed, remaining)
            stalled = self._random.random() < (self._config.stuck_probability_per_unit * leg)
            if stalled:
                leg *= STALL_PROGRESS_FRACTION
            seconds = leg / self.nominal_speed if self.nominal_speed > 0.0 else budget
            self._x += math.cos(self._heading) * leg
            self._z += math.sin(self._heading) * leg
            self._travel_seconds += seconds
            tick.travel_seconds += seconds
            self._distance_units += leg
            budget -= seconds
            if stalled:
                recovery = sample_log_normal(
                    self._random,
                    self._config.recovery_time_mu,
                    self._config.recovery_time_sigma,
                )
                self._recovery_remaining += recovery
                self._stuck_count += 1
                tick.stalled_seconds += recovery
                route = []
                self._route_goal = None
                break
            if self._distance(waypoint.x, waypoint.z) <= ARRIVAL_EPSILON_UNITS:
                route.pop(0)
            else:
                break
        self._route = tuple(route)
        return max(0.0, budget)

    def _turn_toward(
        self, waypoint: WorldCoordinate, budget: float, tick: _TickAccounting
    ) -> float:
        bearing = self._bearing(waypoint.x, waypoint.z)
        turn_seconds = min(
            budget,
            _signed_angle(bearing - self._heading) / self._config.turn_rate_radians_per_second,
        )
        self._heading = bearing
        self._travel_seconds += turn_seconds
        tick.travel_seconds += turn_seconds
        return budget - turn_seconds

    def _advance_spawns(self) -> None:
        for slot, monster in enumerate(self._monsters):
            if (
                monster.lifecycle is MonsterLifecycle.DEAD
                and self._elapsed_seconds >= monster.available_at_seconds
            ):
                zone = self._zones[monster.zone_index]
                self._monsters[slot] = self._spawn_monster(zone, monster.zone_index, slot)

    # -- Routing ------------------------------------------------------------------------

    def _refresh_route(self) -> None:
        """Keep the planned corridor to the current destination current and cached."""

        destination = self._travel_destination()
        if destination is None:
            self._route = ()
            self._route_goal = None
            self._route_blocked = False
            return
        if self._distance(destination.x, destination.z) <= ARRIVAL_EPSILON_UNITS:
            self._route = ()
            self._route_goal = destination
            self._route_blocked = False
            return
        if (
            self._route
            and self._route_goal is not None
            and _same_point(self._route_goal, destination)
        ):
            return
        plan = self._planner.plan(WorldCoordinate(self._x, self._z), destination)
        self._route_goal = destination
        self._route_blocked = plan.blocked
        self._route = () if plan.blocked else plan.waypoints

    def _route_distance(self) -> float | None:
        if not self._route:
            destination = self._travel_destination()
            return None if destination is None else self._distance(destination.x, destination.z)
        total = self._distance(self._route[0].x, self._route[0].z)
        for origin, goal in zip(self._route, self._route[1:], strict=False):
            total += math.hypot(goal.x - origin.x, goal.z - origin.z)
        return total

    # -- Objectives and targets ---------------------------------------------------------

    @property
    def _target(self) -> SimulatedMonster | None:
        if self._target_slot is None:
            return None
        monster = self._monsters[self._target_slot]
        if monster.lifecycle not in (MonsterLifecycle.ALIVE, MonsterLifecycle.IN_COMBAT):
            self._target_slot = None
            return None
        return monster

    def _store(self, monster: SimulatedMonster, **changes: object) -> SimulatedMonster:
        updated = replace(monster, **changes)  # type: ignore[arg-type]
        self._monsters[monster.monster_slot] = updated
        return updated

    def _travel_destination(self) -> WorldCoordinate | None:
        """Return where movement should head: the objective, the target, or the camp."""

        objective = self._active_objective()
        if objective is not None:
            if objective.position_x is not None and objective.position_z is not None:
                return WorldCoordinate(objective.position_x, objective.position_z)
            if objective.kind is QuestObjectiveKind.KILL:
                return self._monster_destination(objective.monster_id)
        return self._monster_destination(None)

    def _monster_destination(self, monster_id: int | None) -> WorldCoordinate | None:
        target = self._target
        if target is not None and (monster_id is None or target.monster_id == monster_id):
            return WorldCoordinate(target.position_x, target.position_z)
        visible = [
            monster
            for monster in self._visible_monsters()
            if monster_id is None or monster.monster_id == monster_id
        ]
        if visible:
            return WorldCoordinate(visible[0].position_x, visible[0].position_z)
        zones = [
            zone for zone in self._zones if monster_id is None or zone.monster_id == monster_id
        ]
        if not zones:
            return None
        nearest = min(zones, key=lambda zone: self._distance(zone.anchor.x, zone.anchor.z))
        return nearest.anchor

    def _interaction_ready(self) -> bool:
        """Return whether ``INTERACT`` has something legal to do right now."""

        if self.is_combat_engagement:
            return True
        objective = self._active_objective()
        if objective is None or objective.kind is QuestObjectiveKind.KILL:
            return False
        assert objective.position_x is not None and objective.position_z is not None
        radius = (
            objective.radius_units
            if objective.kind is QuestObjectiveKind.GO_TO
            else INTERACTION_RADIUS_UNITS
        )
        return self._distance(objective.position_x, objective.position_z) <= radius

    def _complete_kill_objective(self, monster_id: int, events: list[str]) -> None:
        changed = False
        for index, objective in enumerate(self._objectives):
            if (
                objective.kind is QuestObjectiveKind.KILL
                and objective.monster_id == monster_id
                and self._progress[index] < objective.required_count
            ):
                self._progress[index] += 1
                changed = True
                if self._progress[index] == objective.required_count:
                    self._completed[index] = True
        if changed:
            events.append("quest_progress")

    def _active_objective(self) -> QuestObjective | None:
        return next(
            (
                item
                for item, complete in zip(self._objectives, self._completed, strict=True)
                if not complete
            ),
            None,
        )

    def _all_objectives_complete(self) -> bool:
        return bool(self._objectives) and all(self._completed)

    def _objective_distance(self) -> float | None:
        objective = self._active_objective()
        if objective is None or objective.position_x is None or objective.position_z is None:
            return None
        return self._distance(objective.position_x, objective.position_z)

    # -- Monsters -----------------------------------------------------------------------

    def _visible_monsters(self) -> tuple[SimulatedMonster, ...]:
        """Return the live monsters inside recognition range, nearest first."""

        radius = self._config.visibility_radius_units
        live = [
            monster
            for monster in self._monsters
            if monster.lifecycle in (MonsterLifecycle.ALIVE, MonsterLifecycle.IN_COMBAT)
            and self._distance(monster.position_x, monster.position_z) <= radius
        ]
        return tuple(
            sorted(live, key=lambda monster: self._distance(monster.position_x, monster.position_z))
        )

    def _spawn_monster(
        self, zone: VectorSpawnZone, zone_index: int, monster_slot: int
    ) -> SimulatedMonster:
        fraction_x = self._random.random()
        fraction_z = self._random.random()
        return SimulatedMonster(
            monster_slot=monster_slot,
            monster_id=zone.monster_id,
            zone_index=zone_index,
            position_x=zone.minimum_x + fraction_x * (zone.maximum_x - zone.minimum_x),
            position_z=zone.minimum_z + fraction_z * (zone.maximum_z - zone.minimum_z),
            lifecycle=MonsterLifecycle.ALIVE,
        )

    # -- Geometry -----------------------------------------------------------------------

    def _distance(self, x: float, z: float) -> float:
        return math.hypot(x - self._x, z - self._z)

    def _bearing(self, x: float, z: float) -> float:
        return math.atan2(z - self._z, x - self._x) % FULL_CIRCLE_RADIANS

    def _height_at(self, x: float, z: float) -> float | None:
        return self._world_map.terrain.height_at(WorldCoordinate(x, z))


def _signed_angle(angle: float) -> float:
    """Return the absolute shortest angular distance in radians."""

    wrapped = (angle + math.pi) % FULL_CIRCLE_RADIANS - math.pi
    return abs(wrapped)


def _same_point(first: WorldCoordinate, second: WorldCoordinate) -> bool:
    return math.hypot(first.x - second.x, first.z - second.z) <= ARRIVAL_EPSILON_UNITS
