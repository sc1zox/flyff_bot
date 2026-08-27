"""Tests for goal-driven quest execution: goal sequences, travel, and the objective bus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtWidgets import QApplication

from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import (
    FarmingConfig,
    FarmingMode,
    FarmingOrchestrator,
    QuestGoalFailurePolicy,
)
from flyff_bot.features.automation.quest_goals import (
    kill_goal_config_for,
    leash_for,
    patrol_zones_for,
)
from flyff_bot.features.navigation.goal_travel import (
    GoalTravelConfig,
    GoalTravelMode,
    GoalTravelRefusal,
    plan_goal_travel,
)
from flyff_bot.features.navigation.live_position import (
    LivePositionReader,
    PositionReading,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.teleporter_dispatch import (
    ArrivalObservation,
    TeleporterDispatchConfig,
    TeleporterDispatcher,
    TeleporterInputAdapter,
)
from flyff_bot.features.navigation.teleporter_models import (
    TeleporterCatalog,
    TeleporterDestination,
)
from flyff_bot.features.navigation.vector_navigation import VectorZoneNavigator
from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldDimensions,
    WorldVectorMap,
)
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.features.policy.hierarchical import (
    HierarchicalObjective,
    HierarchicalObjectiveKind,
    HierarchicalPolicy,
)
from flyff_bot.features.policy.runner import PolicyRunner
from flyff_bot.features.quests.goals import (
    QuestFarmingQueue,
    QuestGoalResolver,
    QuestNpc,
    QuestResolution,
)
from flyff_bot.features.quests.models import (
    QuestCollection,
    QuestDefinition,
    QuestItemDrop,
    QuestItemRequirement,
    QuestKillRequirement,
    QuestObjectiveProgress,
)
from flyff_bot.features.quests.objectives import (
    QuestGoalFailure,
    QuestGoalIdentity,
    QuestGoalKind,
    QuestGoalSequence,
    QuestGoalState,
    QuestGoalTimeouts,
    build_goal_sequence,
)
from flyff_bot.features.telemetry.models import (
    TelemetryEventKind,
    TelemetrySessionMetadata,
)
from flyff_bot.features.telemetry.recorder import TelemetryRecorder
from flyff_bot.features.telemetry.storage import JsonlTelemetryWorker
from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.quest_panel import (
    GOAL_FAILURE_MESSAGES,
    GOAL_KIND_LABELS,
    QuestGoalPanel,
)

WINDOW_HANDLE = 42
FLAME = VisibleMob(0, "Flame", 0.9, 20, 20, 20, 20)
FLAME_ZONE = VectorSpawnZone(
    monster_id=1453,
    center_x=100.0,
    center_y=5.0,
    center_z=100.0,
    capacity=5,
    respawn_seconds=30,
    minimum_x=80.0,
    minimum_z=80.0,
    maximum_x=120.0,
    maximum_z=120.0,
    monster_name="Flame",
)
RAPRA_ZONE = VectorSpawnZone(
    monster_id=1458,
    center_x=400.0,
    center_y=5.0,
    center_z=400.0,
    capacity=5,
    respawn_seconds=30,
    minimum_x=390.0,
    minimum_z=390.0,
    maximum_x=410.0,
    maximum_z=410.0,
    monster_name="Rapra",
)
ACCEPT_NPC = QuestNpc("Wendy", WorldPosition(10.0, 5.0, 10.0))
TURN_IN_NPC = QuestNpc("Ivillness", WorldPosition(12.0, 5.0, 12.0))
FLARINE = TeleporterDestination(
    destination_id=1,
    name="Flarine",
    search_text="Flarine",
    world_id=0,
    anchor_x=100.0,
    anchor_z=100.0,
)
SAINT_MORNING = TeleporterDestination(
    destination_id=2,
    name="Saint Morning",
    search_text="Saint Morning",
    world_id=3,
    anchor_x=8000.0,
    anchor_z=8000.0,
)


def _world_map(*zones: VectorSpawnZone) -> WorldVectorMap:
    return WorldVectorMap(
        world_name="wdtest",
        dimensions=WorldDimensions(4, 4, 4.0),
        zones=zones,
    )


def _kill_quest(quest_id: str, *requirements: tuple[str, int]) -> QuestDefinition:
    return QuestDefinition(
        quest_id=quest_id,
        title=quest_id,
        collection=QuestCollection.GENERAL,
        kill_requirements=tuple(
            QuestKillRequirement(
                monster_symbol=f"MI_{monster.upper()}",
                monster_name=monster,
                required_kills=kills,
            )
            for monster, kills in requirements
        ),
    )


def _collect_quest(quest_id: str, monster: str, quantity: int) -> QuestDefinition:
    return QuestDefinition(
        quest_id=quest_id,
        title=quest_id,
        collection=QuestCollection.GENERAL,
        item_requirements=(
            QuestItemRequirement(
                item_symbol="II_TOKEN",
                item_name="Token",
                required_quantity=quantity,
                sources=(QuestItemDrop(f"MI_{monster.upper()}", monster),),
            ),
        ),
    )


def _npc_positions(quest_id: str) -> dict[str, QuestNpc]:
    return {f"{quest_id}:accept": ACCEPT_NPC, f"{quest_id}:turn_in": TURN_IN_NPC}


def _resolution(
    quest: QuestDefinition, *zones: VectorSpawnZone, npcs: bool = True
) -> QuestResolution:
    resolver = QuestGoalResolver(
        _world_map(*(zones or (FLAME_ZONE,))),
        _npc_positions(quest.quest_id) if npcs else None,
    )
    return resolver.resolve(quest)


# --------------------------------------------------------------------------------------
# Goal sequence resolution
# --------------------------------------------------------------------------------------


def test_a_kill_quest_resolves_to_an_ordered_goal_sequence() -> None:
    resolution = _resolution(_kill_quest("general:A", ("Flame", 3)))

    goals = build_goal_sequence(resolution)

    assert [goal.kind for goal in goals] == [
        QuestGoalKind.TRAVEL_TO_ACCEPT,
        QuestGoalKind.ACCEPT,
        QuestGoalKind.TRAVEL_TO_OBJECTIVE,
        QuestGoalKind.SATISFY_OBJECTIVE,
        QuestGoalKind.TRAVEL_TO_TURN_IN,
        QuestGoalKind.TURN_IN,
    ]
    assert [goal.index for goal in goals] == [0, 1, 2, 3, 4, 5]
    assert goals[0].destination == ACCEPT_NPC.position
    assert goals[2].destination == WorldPosition(100.0, 5.0, 100.0)
    assert goals[3].required_progress == 3.0
    assert goals[4].destination == TURN_IN_NPC.position


def test_a_collect_quest_states_one_kill_of_the_drop_source_per_required_item() -> None:
    resolution = _resolution(_collect_quest("general:C", "Flame", 4))

    goals = build_goal_sequence(resolution)
    satisfy = next(goal for goal in goals if goal.kind is QuestGoalKind.SATISFY_OBJECTIVE)

    assert satisfy.required_progress == 4.0
    assert satisfy.monster_name == "Flame"


def test_a_multi_objective_quest_pairs_a_travel_and_a_satisfy_goal_per_objective() -> None:
    resolution = _resolution(
        _kill_quest("general:M", ("Flame", 2), ("Rapra", 1)), FLAME_ZONE, RAPRA_ZONE
    )

    goals = build_goal_sequence(resolution)
    objectives = [goal for goal in goals if goal.objective_ordinal >= 0]

    assert [(goal.kind, goal.objective_ordinal) for goal in objectives] == [
        (QuestGoalKind.TRAVEL_TO_OBJECTIVE, 0),
        (QuestGoalKind.SATISFY_OBJECTIVE, 0),
        (QuestGoalKind.TRAVEL_TO_OBJECTIVE, 1),
        (QuestGoalKind.SATISFY_OBJECTIVE, 1),
    ]
    assert objectives[2].spawn_zone == RAPRA_ZONE


def test_a_quest_without_resolved_npcs_omits_its_npc_goals() -> None:
    resolution = _resolution(_kill_quest("general:A", ("Flame", 1)), npcs=False)

    goals = build_goal_sequence(resolution)

    assert [goal.kind for goal in goals] == [
        QuestGoalKind.TRAVEL_TO_OBJECTIVE,
        QuestGoalKind.SATISFY_OBJECTIVE,
    ]


# --------------------------------------------------------------------------------------
# The objective bus
# --------------------------------------------------------------------------------------


def test_advancing_the_active_goal_retires_every_goal_it_skipped() -> None:
    sequence = QuestGoalSequence(_resolution(_kill_quest("general:A", ("Flame", 2))))

    changed = sequence.synchronize(QuestGoalKind.SATISFY_OBJECTIVE, 1.0, objective_ordinal=0)
    identity = sequence.identity()

    assert changed
    assert identity is not None
    assert identity.kind is QuestGoalKind.SATISFY_OBJECTIVE
    assert identity.index == 3
    assert identity.goal_count == 6
    assert identity.required_progress == 2.0
    assert identity.spawn_zone_monster_id == FLAME_ZONE.monster_id
    assert identity.state is QuestGoalState.ACTIVE


def test_measured_progress_is_reported_on_the_active_goal() -> None:
    sequence = QuestGoalSequence(_resolution(_kill_quest("general:A", ("Flame", 2))))
    sequence.synchronize(QuestGoalKind.SATISFY_OBJECTIVE, 1.0, objective_ordinal=0)

    sequence.apply_progress((QuestObjectiveProgress("Flame", 1, 2),), 2.0)
    identity = sequence.identity()

    assert sequence.active_progress == 1.0
    assert identity is not None
    assert identity.progress_ratio == 0.5


def test_a_goal_that_stops_progressing_fails_with_a_timeout() -> None:
    sequence = QuestGoalSequence(
        _resolution(_kill_quest("general:A", ("Flame", 2))),
        timeouts=QuestGoalTimeouts(objective_seconds=10.0),
    )
    sequence.synchronize(QuestGoalKind.SATISFY_OBJECTIVE, 0.0, objective_ordinal=0)

    assert sequence.observe(9.0) is None
    assert sequence.observe(10.0) is QuestGoalFailure.TIMEOUT
    assert sequence.is_failed
    identity = sequence.identity()
    assert identity is not None
    assert identity.failure is QuestGoalFailure.TIMEOUT


def test_measured_progress_restarts_the_goal_timeout() -> None:
    sequence = QuestGoalSequence(
        _resolution(_kill_quest("general:A", ("Flame", 3))),
        timeouts=QuestGoalTimeouts(objective_seconds=10.0),
    )
    sequence.synchronize(QuestGoalKind.SATISFY_OBJECTIVE, 0.0, objective_ordinal=0)

    sequence.apply_progress((QuestObjectiveProgress("Flame", 1, 3),), 9.0)

    assert sequence.observe(15.0) is None
    assert sequence.observe(19.0) is QuestGoalFailure.TIMEOUT


def test_the_pending_objective_is_the_first_one_short_of_its_requirement() -> None:
    sequence = QuestGoalSequence(
        _resolution(_kill_quest("general:M", ("Flame", 1), ("Rapra", 1)), FLAME_ZONE, RAPRA_ZONE)
    )

    sequence.apply_progress(
        (QuestObjectiveProgress("Flame", 1, 1), QuestObjectiveProgress("Rapra", 0, 1)), 1.0
    )

    assert sequence.pending_objective_ordinal == 1


# --------------------------------------------------------------------------------------
# Goal travel planning
# --------------------------------------------------------------------------------------


def test_a_near_destination_in_the_players_world_is_walked_to() -> None:
    plan = plan_goal_travel(
        TeleporterCatalog((FLARINE,)),
        goal_destination=WorldPosition(100.0, 5.0, 100.0),
        player_position=WorldPosition(90.0, 5.0, 100.0),
        player_world_id=0,
    )

    assert plan.mode is GoalTravelMode.WALK
    assert plan.walk_distance_units == 10.0


def test_a_destination_beyond_the_walking_distance_is_teleported_to() -> None:
    plan = plan_goal_travel(
        TeleporterCatalog((FLARINE, SAINT_MORNING)),
        goal_destination=WorldPosition(100.0, 5.0, 100.0),
        player_position=WorldPosition(9000.0, 5.0, 9000.0),
        player_world_id=0,
        config=GoalTravelConfig(maximum_walk_distance_units=500.0),
    )

    assert plan.mode is GoalTravelMode.TELEPORT
    assert plan.destination == FLARINE
    assert plan.world_id == 0


def test_a_destination_in_another_world_is_teleported_to_even_when_it_looks_near() -> None:
    plan = plan_goal_travel(
        TeleporterCatalog((SAINT_MORNING,)),
        goal_destination=WorldPosition(8010.0, 5.0, 8000.0),
        player_position=WorldPosition(8000.0, 5.0, 8000.0),
        player_world_id=0,
    )

    assert plan.mode is GoalTravelMode.TELEPORT
    assert plan.destination == SAINT_MORNING


def test_a_destination_no_teleporter_covers_is_refused_instead_of_walked() -> None:
    plan = plan_goal_travel(
        TeleporterCatalog((FLARINE,)),
        goal_destination=WorldPosition(90000.0, 5.0, 90000.0),
        player_position=WorldPosition(0.0, 5.0, 0.0),
        player_world_id=0,
    )

    assert plan.mode is GoalTravelMode.UNREACHABLE
    assert plan.refusal is GoalTravelRefusal.NO_TELEPORTER_DESTINATION


def test_a_goal_without_a_resolved_destination_is_refused() -> None:
    plan = plan_goal_travel(
        TeleporterCatalog((FLARINE,)),
        goal_destination=None,
        player_position=WorldPosition(0.0, 5.0, 0.0),
    )

    assert plan.mode is GoalTravelMode.UNREACHABLE
    assert plan.refusal is GoalTravelRefusal.NO_DESTINATION


# --------------------------------------------------------------------------------------
# Projection onto the session's knobs
# --------------------------------------------------------------------------------------


def test_an_objective_goal_narrows_the_whitelist_zone_and_leash_to_its_own_zone() -> None:
    resolution = _resolution(
        _kill_quest("general:M", ("Flame", 1), ("Rapra", 1)), FLAME_ZONE, RAPRA_ZONE
    )
    goals = build_goal_sequence(resolution)
    first = goals[3]
    second = goals[5]

    assert [quota.class_name for quota in kill_goal_config_for(first, resolution).quotas] == [
        "Flame"
    ]
    assert [quota.class_name for quota in kill_goal_config_for(second, resolution).quotas] == [
        "Rapra"
    ]
    assert patrol_zones_for(first, resolution) == (FLAME_ZONE,)
    assert patrol_zones_for(second, resolution) == (RAPRA_ZONE,)
    first_leash = leash_for(first)
    second_leash = leash_for(second)
    assert first_leash is not None and second_leash is not None
    assert first_leash[0] == WorldPosition(100.0, 5.0, 100.0)
    assert second_leash[0] == WorldPosition(400.0, 5.0, 400.0)
    assert first_leash[1] != second_leash[1]


def test_an_npc_goal_keeps_the_whole_quest_in_scope() -> None:
    resolution = _resolution(
        _kill_quest("general:M", ("Flame", 1), ("Rapra", 1)), FLAME_ZONE, RAPRA_ZONE
    )
    accept = build_goal_sequence(resolution)[1]

    assert {quota.class_name for quota in kill_goal_config_for(accept, resolution).quotas} == {
        "Flame",
        "Rapra",
    }


# --------------------------------------------------------------------------------------
# Session integration
# --------------------------------------------------------------------------------------


class _Pipeline:
    def __init__(self, states: list[WorldState]) -> None:
        self._states = iter(states)
        self._last = states[0]

    def tick(self, _window_handle: int, _previous: WorldState) -> PerceptionTick:
        self._last = next(self._states, self._last)
        return PerceptionTick(self._last, (), frozenset())


class _InputAdapter:
    def __init__(self) -> None:
        self.released = 0

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, _window_handle: int) -> bool:
        return True

    def close_window(self, _window_handle: int) -> bool:
        return True

    def click_client(self, _window_handle: int, _x: int, _y: int) -> None:
        return None

    def send_key(self, _virtual_key: int, _duration_seconds: float) -> None:
        return None

    def send_key_while_guarded(
        self, _window_handle: int, _virtual_key: int, _duration_seconds: float
    ) -> None:
        return None

    def send_keys_while_guarded(
        self,
        _window_handle: int,
        _virtual_keys: tuple[int, ...] | list[int] | int,
        _duration_seconds: float,
    ) -> None:
        return None


class _TeleporterInput:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, _window_handle: int) -> bool:
        return True

    def pulse_teleporter_hotkey(self, _virtual_key: int, _duration_seconds: float) -> None:
        self.actions.append("hotkey")

    def type_search_text(self, _window_handle: int, text: str) -> None:
        self.actions.append(f"type:{text}")

    def click_search_field(self, _window_handle: int) -> None:
        self.actions.append("search_click")

    def select_first_result(self, _window_handle: int) -> None:
        self.actions.append("select_click")

    def click_teleport_button(self, _window_handle: int) -> None:
        self.actions.append("teleport_click")

    def close_teleporter_window(self, _window_handle: int) -> None:
        self.actions.append("close")


class _Observer:
    def __init__(self, observation: ArrivalObservation) -> None:
        self.observation = observation

    def observe(self) -> ArrivalObservation:
        return self.observation


class _LiveReader:
    def __init__(self, position: WorldPosition) -> None:
        self.position = position

    def poll(self, at_seconds: float) -> PositionReading:
        return PositionReading(PositionSource.LIVE, self.position, sampled_at_seconds=at_seconds)

    def close(self) -> None:
        return None


def _state(time: float, *, mobs: tuple[VisibleMob, ...] = ()) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=Viewport(400, 400),
    )


def _pathing(
    position: WorldPosition,
    *,
    dispatcher: TeleporterDispatcher | None = None,
    zones: tuple[VectorSpawnZone, ...] = (FLAME_ZONE, RAPRA_ZONE),
) -> PathingController:
    controller = PathingController(
        position_reader=cast(LivePositionReader, _LiveReader(position)),
        teleporter_dispatcher=dispatcher,
    )
    controller.attach_vector_navigator(VectorZoneNavigator(_world_map(*zones)))
    return controller


def _session(
    quest: QuestDefinition,
    states: list[WorldState],
    *,
    pathing: PathingController,
    catalog: TeleporterCatalog | None = None,
    config: FarmingConfig | None = None,
    zones: tuple[VectorSpawnZone, ...] = (FLAME_ZONE,),
    npcs: bool = False,
    telemetry: TelemetryRecorder | None = None,
) -> tuple[FarmingOrchestrator, QuestFarmingQueue]:
    resolution = _resolution(quest, *zones, npcs=npcs)
    queue = QuestFarmingQueue((resolution,))
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        _InputAdapter(),
        WINDOW_HANDLE,
        config=config,
        pathing=pathing,
        quest_queue=queue,
        teleporter_catalog=catalog,
        telemetry=telemetry,
    )
    orchestrator.configure_quest_queue(queue)
    return orchestrator, queue


def test_a_session_switches_whitelist_zone_and_leash_when_the_objective_changes() -> None:
    pathing = _pathing(WorldPosition(100.0, 5.0, 100.0))
    orchestrator, queue = _session(
        _kill_quest("general:M", ("Flame", 1), ("Rapra", 1)),
        [_state(index * 0.5) for index in range(8)],
        pathing=pathing,
        zones=(FLAME_ZONE, RAPRA_ZONE),
    )
    orchestrator.start()
    orchestrator.tick()
    orchestrator.tick()

    first_classes = orchestrator.kill_goals.active_class_names
    first_leash = pathing.leash_anchor
    navigator = pathing.vector_navigator
    assert navigator is not None
    first_zone = navigator.preferred_zones

    queue.record_kill("Flame")
    for _ in range(3):
        orchestrator.tick()

    sequence = orchestrator.quest_goals
    assert sequence is not None
    assert first_classes == frozenset({"Flame"})
    assert first_leash == WorldPosition(100.0, 5.0, 100.0)
    assert first_zone == (FLAME_ZONE,)
    assert orchestrator.kill_goals.active_class_names == frozenset({"Rapra"})
    assert pathing.leash_anchor == WorldPosition(400.0, 5.0, 400.0)
    assert navigator.preferred_zones == (RAPRA_ZONE,)
    identity = sequence.identity()
    assert identity is not None
    assert identity.monster_name == "Rapra"


def test_a_goal_beyond_walking_range_teleports_and_waits_for_confirmed_arrival() -> None:
    adapter = _TeleporterInput()
    observer = _Observer(ArrivalObservation(WorldPosition(9000.0, 5.0, 9000.0), 0, 0.0))
    dispatcher = TeleporterDispatcher(
        cast(TeleporterInputAdapter, adapter),
        WINDOW_HANDLE,
        observer,
        config=TeleporterDispatchConfig(combat_stable_seconds=0.1),
    )
    pathing = _pathing(
        WorldPosition(9000.0, 5.0, 9000.0), dispatcher=dispatcher, zones=(FLAME_ZONE,)
    )
    orchestrator, _ = _session(
        _kill_quest("general:A", ("Flame", 1)),
        [_state(index * 1.0) for index in range(8)],
        pathing=pathing,
        catalog=TeleporterCatalog((FLARINE,)),
        config=FarmingConfig(quest_travel=GoalTravelConfig(maximum_walk_distance_units=100.0)),
    )
    orchestrator.start()

    orchestrator.tick()
    assert orchestrator.mode is FarmingMode.TELEPORTING
    assert dispatcher.destination == FLARINE

    orchestrator.tick()
    orchestrator.tick()
    assert orchestrator.mode is FarmingMode.TELEPORTING
    assert "teleport_click" in adapter.actions

    observer.observation = ArrivalObservation(WorldPosition(100.0, 5.0, 100.0), 0, 4.0)
    orchestrator.tick()

    assert orchestrator.mode is not FarmingMode.TELEPORTING
    sequence = orchestrator.quest_goals
    assert sequence is not None
    assert sequence.world_id == 0


def test_a_goal_no_teleporter_covers_pauses_with_an_explicit_reason() -> None:
    far_zone = VectorSpawnZone(
        monster_id=1453,
        center_x=90000.0,
        center_y=5.0,
        center_z=90000.0,
        capacity=1,
        respawn_seconds=1,
        minimum_x=89990.0,
        minimum_z=89990.0,
        maximum_x=90010.0,
        maximum_z=90010.0,
        monster_name="Flame",
    )
    pathing = _pathing(WorldPosition(0.0, 5.0, 0.0), zones=(far_zone,))
    orchestrator, _ = _session(
        _kill_quest("general:A", ("Flame", 1)),
        [_state(index * 1.0) for index in range(6)],
        pathing=pathing,
        catalog=TeleporterCatalog((FLARINE,)),
        zones=(far_zone,),
    )
    orchestrator.start()
    for _ in range(2):
        orchestrator.tick()

    sequence = orchestrator.quest_goals
    assert sequence is not None
    assert sequence.failure is QuestGoalFailure.UNREACHABLE_DESTINATION
    assert orchestrator.mode is FarmingMode.PAUSED


def test_a_goal_that_times_out_pauses_the_session_with_its_failure_recorded() -> None:
    pathing = _pathing(WorldPosition(100.0, 5.0, 100.0), zones=(FLAME_ZONE,))
    orchestrator, _ = _session(
        _kill_quest("general:A", ("Flame", 5)),
        [_state(0.0), _state(1.0), _state(60.0)],
        pathing=pathing,
        config=FarmingConfig(
            quest_goal_timeouts=QuestGoalTimeouts(objective_seconds=5.0),
            quest_goal_failure_policy=QuestGoalFailurePolicy.PAUSE_SESSION,
        ),
    )
    orchestrator.start()
    orchestrator.tick()
    orchestrator.tick()
    orchestrator.tick()

    sequence = orchestrator.quest_goals
    assert sequence is not None
    assert sequence.failure is QuestGoalFailure.TIMEOUT
    assert orchestrator.mode is FarmingMode.PAUSED


def test_an_emergency_stop_during_a_goal_halts_the_session() -> None:
    pathing = _pathing(WorldPosition(100.0, 5.0, 100.0), zones=(FLAME_ZONE,))
    orchestrator, _ = _session(
        _kill_quest("general:A", ("Flame", 1)),
        [_state(index * 1.0) for index in range(4)],
        pathing=pathing,
    )
    orchestrator.start()
    orchestrator.tick()

    orchestrator.emergency_stop(reason="killswitch")

    assert orchestrator.mode is FarmingMode.EMERGENCY_STOPPED
    assert pathing.mode.value == "idle"
    sequence = orchestrator.quest_goals
    assert sequence is not None
    assert sequence.active is not None


def test_every_snapshot_and_decision_carries_the_active_goal(tmp_path: Path) -> None:
    recorder = TelemetryRecorder(
        TelemetrySessionMetadata(area_id="wdtest", session_id="goal-session"),
        lambda session_id, area_id: JsonlTelemetryWorker(session_id, area_id, root=tmp_path),
    )
    pathing = _pathing(WorldPosition(100.0, 5.0, 100.0), zones=(FLAME_ZONE,))
    orchestrator, _ = _session(
        _kill_quest("general:A", ("Flame", 1)),
        [_state(index * 1.0, mobs=(FLAME,)) for index in range(6)],
        pathing=pathing,
        telemetry=recorder,
    )
    orchestrator.start()
    for _ in range(4):
        orchestrator.tick()
    recorder.close()

    records = _records(tmp_path)
    snapshots = [
        record for record in records if record["event_kind"] == TelemetryEventKind.WORLD_SNAPSHOT
    ]
    decisions = [
        record for record in records if record["event_kind"] == TelemetryEventKind.TARGET_SELECTED
    ]
    assert snapshots
    assert decisions
    for record in snapshots + decisions:
        payload = cast(dict[str, object], record["payload"])
        goal = cast(dict[str, object], payload["active_goal"])
        assert goal["quest_id"] == "general:A"
        assert goal["goal_kind"] in {"travel_to_objective", "satisfy_objective"}
        assert isinstance(goal["goal_index"], int)
        assert goal["spawn_zone_monster_id"] == FLAME_ZONE.monster_id


def _records(directory: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for path in sorted(directory.rglob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_the_policy_is_conditioned_on_the_goal_the_session_is_pursuing() -> None:
    pathing = _pathing(WorldPosition(100.0, 5.0, 100.0), zones=(FLAME_ZONE, RAPRA_ZONE))
    orchestrator, queue = _session(
        _kill_quest("general:M", ("Flame", 1), ("Rapra", 2)),
        [_state(index * 0.5) for index in range(12)],
        pathing=pathing,
        zones=(FLAME_ZONE, RAPRA_ZONE),
    )
    orchestrator.start()
    orchestrator.tick()
    orchestrator.tick()

    first = orchestrator.policy_objective

    queue.record_kill("Flame")
    for _ in range(3):
        orchestrator.tick()

    second = orchestrator.policy_objective
    sequence = orchestrator.quest_goals
    assert sequence is not None
    assert first is not None and second is not None
    assert first.quest_id == "general:M"
    assert first.target_class_names == frozenset({"Flame"})
    assert second.target_class_names == frozenset({"Rapra"})
    assert second.objective_index == sequence.active_index
    assert second.objective_count == len(sequence.goals)


def test_a_goal_conditioned_learned_policy_receives_the_objective() -> None:
    policy = HierarchicalPolicy()
    runner = PolicyRunner(policy)
    objective = HierarchicalObjective(
        HierarchicalObjectiveKind.FARMING,
        frozenset({"Flame"}),
        quest_id="general:A",
        objective_index=1,
        objective_count=2,
        progress=1.0,
        required_progress=3.0,
    )

    accepted = runner.set_objective(objective)

    assert accepted
    assert policy.objective == objective
    assert runner.objective == objective


def test_a_policy_that_is_not_goal_conditioned_still_records_the_objective() -> None:
    runner = PolicyRunner()
    objective = HierarchicalObjective(quest_id="general:A")

    accepted = runner.set_objective(objective)

    assert not accepted
    assert runner.objective == objective


@pytest.mark.parametrize("kind", list(QuestGoalKind))
def test_every_goal_kind_has_a_distinct_localized_label(kind: QuestGoalKind) -> None:
    texts = {language: Translator(language).text(GOAL_KIND_LABELS[kind]) for language in Language}

    assert all(text.strip() for text in texts.values())
    assert len(set(texts.values())) == len(Language)


@pytest.mark.parametrize("failure", list(QuestGoalFailure))
def test_every_goal_failure_reason_has_a_distinct_localized_sentence(
    failure: QuestGoalFailure,
) -> None:
    texts = {
        language: Translator(language).text(GOAL_FAILURE_MESSAGES[failure]) for language in Language
    }

    assert all(text.strip() for text in texts.values())
    assert len(set(texts.values())) == len(Language)


def test_the_quest_panel_renders_the_active_goal_its_index_and_its_progress() -> None:
    QApplication.instance() or QApplication([])
    panel = QuestGoalPanel(Translator(Language.ENGLISH))

    panel.set_goal(
        QuestGoalIdentity(
            "general:A",
            "A",
            QuestGoalKind.SATISFY_OBJECTIVE,
            3,
            6,
            2.0,
            5.0,
            QuestGoalState.ACTIVE,
            monster_name="Flame",
        )
    )

    assert "4/6" in panel.goal_text
    assert "2/5" in panel.goal_text
    assert "Farm the objective" in panel.goal_text
