"""Deterministic offline simulation of tactical farming and navigation."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from enum import IntEnum, unique

from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldCoordinate,
    WorldVectorMap,
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
from flyff_bot.features.simulator.models import (
    MonsterLifecycle,
    QuestObjective,
    QuestObjectiveKind,
    SimulationMetrics,
    SimulatorConfig,
    sample_log_normal,
)

FULL_CIRCLE_RADIANS = math.tau
MAXIMUM_TURN_FRACTION_PER_TICK = 0.5
INTERACTION_RADIUS_UNITS = 3.0
MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS = 10.0
DEFAULT_SPAWN_ZONE_COUNT = 1
INITIAL_VITALS_PERCENT = 100.0


@unique
class TacticalAction(IntEnum):
    """Stable actions understood by the farming simulator's Gymnasium adapter."""

    TARGET_NEAREST = 0
    GO_TO_OBJECTIVE = 1
    INTERACT = 2
    WAIT = 3


@dataclass(frozen=True, slots=True)
class SimulatedMonster:
    """One independently timed and positioned simulated monster."""

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


class FarmingSimulator:
    """Run a seeded tactical episode without a client process or live input dispatch."""

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
        self._random = random.Random(seed)
        self._target: SimulatedMonster | None = None
        self._previous_kill_count = 0
        self._previous_completed_count = 0
        self._reset_state()

    @property
    def action_space_size(self) -> int:
        return len(TacticalAction)

    def reset(self, *, seed: int | None = None) -> tuple[RlObservation, dict[str, object]]:
        """Reset to the configured start state and optionally reseed the PRNG."""

        if seed is not None:
            self._random.seed(seed)
        self._reset_state()
        return self.observation, {"action_mask": self.action_mask}

    def step(self, action: int) -> tuple[RlObservation, float, bool, bool, dict[str, object]]:
        """Advance one fixed-duration tactical tick deterministically."""

        events: list[str] = []
        failed_action = False
        if action == TacticalAction.TARGET_NEAREST:
            nearest = min(
                (
                    monster
                    for monster in self._monsters
                    if monster.lifecycle is MonsterLifecycle.ALIVE
                ),
                key=lambda monster: self._distance(monster.position_x, monster.position_z),
                default=None,
            )
            if nearest is None:
                failed_action = True
            else:
                self._target = nearest
                self._previous_kill_count = self._kill_count
        elif action == TacticalAction.GO_TO_OBJECTIVE:
            destination = self._objective_destination()
            if destination is None:
                failed_action = True
            else:
                heading = self._bearing(destination.x, destination.z)
                turn_seconds = (
                    _signed_angle(heading - self._heading)
                    / self._config.turn_rate_radians_per_second
                )
                travel_seconds = max(0.0, self._config.tick_seconds - turn_seconds)
                self._advance_along(destination.x, destination.z, travel_seconds)
        elif action == TacticalAction.INTERACT:
            objective = self._active_objective()
            if objective is not None and objective.kind is QuestObjectiveKind.KILL:
                if self._target is None or self._target.lifecycle is not MonsterLifecycle.ALIVE:
                    nearest = min(
                        (
                            monster
                            for monster in self._monsters
                            if monster.lifecycle is MonsterLifecycle.ALIVE
                        ),
                        key=lambda monster: self._distance(monster.position_x, monster.position_z),
                        default=None,
                    )
                    if nearest is None:
                        failed_action = True
                    else:
                        self._target = nearest
                self._attack_target(events)
            elif objective is None:
                failed_action = True
            elif objective.kind is QuestObjectiveKind.GO_TO and not self._objective_ready(
                objective
            ):
                if objective.kind is QuestObjectiveKind.GO_TO:
                    self._advance_toward_objective()
            else:
                self._complete_interaction(objective, events)
        elif action == TacticalAction.WAIT:
            pass
        else:
            raise ValueError("Unknown simulator action index.")

        self._advance_spawns()
        self._advance_recovery()
        self._elapsed_seconds += self._config.tick_seconds
        terminated = self._all_objectives_complete()
        truncated = not terminated and self._elapsed_seconds >= (
            self._config.maximum_episode_seconds
        )
        completed_count = len([item for item in self._progress if item])
        reward = self._reward(
            kill_count_delta=self._kill_count - self._previous_kill_count,
            completed_count=completed_count,
            previous_completed_count=self._previous_completed_count,
            failed_action=failed_action,
        )
        self._previous_kill_count = self._kill_count
        self._previous_completed_count = completed_count
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
        """Return deterministic validity for each simulator action."""

        objective = self._active_objective()
        alive_monsters = any(
            monster.lifecycle is MonsterLifecycle.ALIVE for monster in self._monsters
        )
        target_selected = self._target is not None and self._target.lifecycle in (
            MonsterLifecycle.ALIVE,
            MonsterLifecycle.IN_COMBAT,
        )
        destination = self._objective_destination()
        interaction_ready = objective is not None and self._objective_ready(objective)
        return (
            alive_monsters and not target_selected,
            destination is not None and not interaction_ready,
            interaction_ready,
            True,
        )

    @property
    def metrics(self) -> SimulationMetrics:
        return SimulationMetrics(
            elapsed_seconds=self._elapsed_seconds,
            kill_count=self._kill_count,
            travel_seconds=self._travel_seconds,
            combat_seconds=self._combat_seconds,
            recovery_seconds=self._recovery_seconds,
            idle_seconds=max(
                0.0,
                self._elapsed_seconds
                - self._travel_seconds
                - self._combat_seconds
                - self._recovery_seconds,
            ),
            distance_units=self._distance_units,
            stuck_count=self._stuck_count,
        )

    @property
    def observation(self) -> RlObservation:
        target = self._target
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
                is_dead=monster.lifecycle is MonsterLifecycle.DEAD,
                is_unreachable=False,
            )
            for index, monster in enumerate(self._visible_monsters()[:4])
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
                next(
                    (
                        index
                        for index, monster in enumerate(self._visible_monsters())
                        if target is monster
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

    def _reset_state(self) -> None:
        self._x = self._start.x
        self._z = self._start.z
        self._heading = 0.0
        self._elapsed_seconds = 0.0
        self._travel_seconds = 0.0
        self._combat_seconds = 0.0
        self._recovery_seconds = 0.0
        self._distance_units = 0.0
        self._stuck_count = 0
        self._kill_count = 0
        self._monsters: list[SimulatedMonster] = []
        self._progress = [0] * len(self._objectives)
        self._completed = [False] * len(self._objectives)
        self._previous_kill_count = 0
        self._previous_completed_count = 0
        for zone_index, zone in enumerate(self._zones[:DEFAULT_SPAWN_ZONE_COUNT]):
            for _slot in range(zone.capacity):
                self._monsters.append(self._spawn_monster(zone, zone_index))

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

    def _advance_spawns(self) -> None:
        replacements: list[SimulatedMonster] = []
        for monster in self._monsters:
            if (
                monster.lifecycle is MonsterLifecycle.DEAD
                and self._elapsed_seconds >= monster.available_at_seconds
            ):
                zone = self._zones[monster.zone_index]
                replacements.append(self._spawn_monster(zone, monster.zone_index))
            else:
                replacements.append(monster)
        self._monsters = replacements

    def _attack_target(self, events: list[str]) -> None:
        target = self._target
        if target is None:
            return
        distance = self._distance(target.position_x, target.position_z)
        if distance > MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS:
            self._x = target.position_x
            self._z = target.position_z
        if target.lifecycle not in (MonsterLifecycle.ALIVE, MonsterLifecycle.IN_COMBAT):
            return
        duration = sample_log_normal(
            self._random,
            self._config.combat_time_mu,
            self._config.combat_time_sigma,
        )
        self._combat_seconds += duration
        self._kill_count += 1
        self._complete_kill_objective(target.monster_id, events)
        zone = self._zones[target.zone_index]
        if target in self._monsters:
            self._monsters[self._monsters.index(target)] = replace(
                target,
                lifecycle=MonsterLifecycle.DEAD,
                combat_seconds_remaining=duration,
                available_at_seconds=self._elapsed_seconds + zone.respawn_seconds,
            )
        events.append("kill")

    def _advance_recovery(self) -> None:
        self._recovery_seconds = max(0.0, self._recovery_seconds - self._config.tick_seconds)

    def _advance_along(self, goal_x: float, goal_z: float, available_seconds: float) -> None:
        bearing = self._bearing(goal_x, goal_z)
        self._heading = bearing
        if available_seconds <= 0.0:
            return
        leg_distance = min(available_seconds * self.nominal_speed, self._distance(goal_x, goal_z))
        stuck = self._random.random() < (self._config.stuck_probability_per_unit * leg_distance)
        if stuck:
            leg_distance *= 0.25
            recovery = sample_log_normal(
                self._random,
                self._config.recovery_time_mu,
                self._config.recovery_time_sigma,
            )
            self._recovery_seconds += recovery
            self._stuck_count += 1
        self._x += math.cos(bearing) * leg_distance
        self._z += math.sin(bearing) * leg_distance
        actual_turn_seconds = 0.0
        if leg_distance > 0.0:
            actual_turn_seconds = min(
                available_seconds,
                leg_distance / self.nominal_speed,
            )
        else:
            actual_turn_seconds = available_seconds
        self._travel_seconds += actual_turn_seconds
        self._distance_units += leg_distance

    def _advance_toward_objective(self) -> None:
        destination = self._objective_destination()
        if destination is None:
            return
        turn_seconds = (
            _signed_angle(self._bearing(destination.x, destination.z) - self._heading)
            / self._config.turn_rate_radians_per_second
        )
        available_seconds = max(0.0, self._config.tick_seconds - turn_seconds)
        self._advance_along(destination.x, destination.z, available_seconds)

    def _advance_toward_target(self) -> None:
        target = self._target
        if target is None:
            return
        turn_seconds = (
            _signed_angle(self._bearing(target.position_x, target.position_z) - self._heading)
            / self._config.turn_rate_radians_per_second
        )
        available_seconds = max(0.0, self._config.tick_seconds - turn_seconds)
        self._advance_along(
            target.position_x,
            target.position_z,
            max(0.0, available_seconds),
        )

    def _complete_interaction(self, objective: QuestObjective, events: list[str]) -> None:
        index = self._objectives.index(objective)
        self._progress[index] = objective.required_count
        self._completed[index] = True
        events.append("quest_progress")

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

    def _objective_destination(self) -> WorldCoordinate | None:
        objective = self._active_objective()
        if objective is None:
            return None
        if objective.position_x is not None and objective.position_z is not None:
            return WorldCoordinate(objective.position_x, objective.position_z)
        if objective.kind is QuestObjectiveKind.KILL and self._target is not None:
            return WorldCoordinate(self._target.position_x, self._target.position_z)
        return None

    def _objective_ready(self, objective: QuestObjective) -> bool:
        if objective.kind is QuestObjectiveKind.KILL:
            target = self._target
            if target is not None and target.lifecycle in (
                MonsterLifecycle.ALIVE,
                MonsterLifecycle.IN_COMBAT,
            ):
                return self._distance(target.position_x, target.position_z) <= (
                    MAXIMUM_COMBAT_ENGAGE_DISTANCE_UNITS
                )
            return bool(self._monsters)
        if objective.kind is QuestObjectiveKind.GO_TO:
            assert objective.position_x is not None and objective.position_z is not None
            return (
                self._distance(objective.position_x, objective.position_z) <= objective.radius_units
            )
        assert objective.position_x is not None and objective.position_z is not None
        return (
            self._distance(objective.position_x, objective.position_z) <= INTERACTION_RADIUS_UNITS
        )

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
        return all(self._completed)

    def _visible_monsters(self) -> tuple[SimulatedMonster, ...]:
        alive = [
            monster for monster in self._monsters if monster.lifecycle is MonsterLifecycle.ALIVE
        ]
        dead = [monster for monster in self._monsters if monster.lifecycle is MonsterLifecycle.DEAD]
        return tuple(alive + dead)

    def _route_distance(self) -> float | None:
        destination = self._objective_destination()
        return self._distance(destination.x, destination.z) if destination else None

    def _objective_distance(self) -> float | None:
        objective = self._active_objective()
        if objective is None:
            return None
        if objective.position_x is None or objective.position_z is None:
            return None
        return self._distance(objective.position_x, objective.position_z)

    def _reward(
        self,
        *,
        kill_count_delta: int,
        completed_count: int,
        previous_completed_count: int,
        failed_action: bool,
    ) -> float:
        return (
            kill_count_delta
            + (completed_count - previous_completed_count) * 2.0
            - float(failed_action) * 0.25
            - self._config.tick_seconds * 0.01
        )

    def _spawn_monster(self, zone: VectorSpawnZone, zone_index: int) -> SimulatedMonster:
        fraction_x = self._random.random()
        fraction_z = self._random.random()
        return SimulatedMonster(
            monster_id=zone.monster_id,
            zone_index=zone_index,
            position_x=zone.minimum_x + fraction_x * (zone.maximum_x - zone.minimum_x),
            position_z=zone.minimum_z + fraction_z * (zone.maximum_z - zone.minimum_z),
            lifecycle=MonsterLifecycle.ALIVE,
        )

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
