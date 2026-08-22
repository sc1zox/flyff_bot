"""Tests for quest goal resolution, quest queue progression, and quest farming sessions."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.orchestrator import FarmingMode, FarmingOrchestrator
from flyff_bot.features.automation.quest_execution import QuestInputDispatcher
from flyff_bot.features.automation.quest_execution_models import (
    DialogueObservation,
    DialoguePerceiver,
    QuestInputKind,
    QuestInteractionConfig,
    QuestInteractionController,
    QuestInteractionDecision,
    QuestInteractionMode,
)
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.pathing import PathingConfig, PathingController
from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldDimensions,
    WorldVectorMap,
)
from flyff_bot.features.perception.pipeline import PerceptionPipeline, PerceptionTick
from flyff_bot.features.quests.goals import (
    QuestFarmingQueue,
    QuestGoalResolver,
    QuestNpc,
    QuestResolutionIssue,
)
from flyff_bot.features.quests.models import (
    QuestCollection,
    QuestDefinition,
    QuestDestination,
    QuestItemDrop,
    QuestItemRequirement,
    QuestKillRequirement,
)
from flyff_bot.features.quests.persistence import (
    QuestDatabaseError,
    load_quest_npc_positions,
    save_quest_npc_positions,
)

WINDOW_HANDLE = 42
FLAME = VisibleMob(0, "Flame", 0.9, 20, 20, 20, 20)
FLAME_ZONE_NEAR = VectorSpawnZone(
    monster_id=1453,
    center_x=100.0,
    center_y=0.0,
    center_z=100.0,
    capacity=5,
    respawn_seconds=30,
    minimum_x=80.0,
    minimum_z=80.0,
    maximum_x=120.0,
    maximum_z=120.0,
    monster_name="Flame",
)
FLAME_ZONE_FAR = VectorSpawnZone(
    monster_id=1453,
    center_x=900.0,
    center_y=0.0,
    center_z=900.0,
    capacity=5,
    respawn_seconds=30,
    minimum_x=880.0,
    minimum_z=880.0,
    maximum_x=920.0,
    maximum_z=920.0,
    monster_name="Flame",
)
RAPRA_ZONE = VectorSpawnZone(
    monster_id=1458,
    center_x=400.0,
    center_y=0.0,
    center_z=400.0,
    capacity=5,
    respawn_seconds=30,
    minimum_x=380.0,
    minimum_z=380.0,
    maximum_x=420.0,
    maximum_z=420.0,
    monster_name="Rapra",
)


def _world_map(*zones: VectorSpawnZone) -> WorldVectorMap:
    return WorldVectorMap(
        world_name="wdtest",
        dimensions=WorldDimensions(4, 4, 4.0),
        zones=zones,
    )


def _kill_quest(
    quest_id: str,
    monster: str,
    kills: int,
    destination: QuestDestination | None = None,
) -> QuestDefinition:
    return QuestDefinition(
        quest_id=quest_id,
        title=quest_id,
        collection=QuestCollection.GENERAL,
        kill_requirements=(
            QuestKillRequirement(
                monster_symbol=f"MI_{monster.upper()}",
                monster_name=monster,
                required_kills=kills,
                destination=destination,
            ),
        ),
    )


def test_resolver_binds_a_kill_requirement_to_its_monster_spawn_zone() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR, RAPRA_ZONE))

    resolution = resolver.resolve(_kill_quest("general:A", "Flame", 3))

    assert resolution.issues == (
        QuestResolutionIssue.MISSING_ACCEPT_NPC,
        QuestResolutionIssue.MISSING_TURN_IN_NPC,
    )
    assert resolution.is_farmable
    assert resolution.zones == (FLAME_ZONE_NEAR,)
    assert resolution.required_kills == (("Flame", 3),)
    assert resolution.zone_goals[0].kill_quota == 3


def test_resolver_prefers_the_zone_nearest_the_quest_destination() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_FAR, FLAME_ZONE_NEAR))

    resolution = resolver.resolve(
        _kill_quest("general:A", "Flame", 1, QuestDestination(110.0, 110.0))
    )

    assert resolution.zones == (FLAME_ZONE_NEAR,)


def test_resolver_falls_back_to_the_numeric_monster_identifier() -> None:
    unnamed = VectorSpawnZone(
        monster_id=1453,
        center_x=10.0,
        center_y=0.0,
        center_z=10.0,
        capacity=1,
        respawn_seconds=1,
        minimum_x=0.0,
        minimum_z=0.0,
        maximum_x=20.0,
        maximum_z=20.0,
    )
    quest = QuestDefinition(
        quest_id="general:A",
        title="A",
        collection=QuestCollection.GENERAL,
        kill_requirements=(QuestKillRequirement("MI_FLAME", "Flame", 2, monster_id=1453),),
    )

    resolution = QuestGoalResolver(_world_map(unnamed)).resolve(quest)

    assert resolution.zones == (unnamed,)


def test_resolver_reports_a_quest_whose_monster_has_no_spawn_zone() -> None:
    resolver = QuestGoalResolver(_world_map(RAPRA_ZONE))

    resolution = resolver.resolve(_kill_quest("general:A", "Flame", 1))

    assert resolution.issues == (
        QuestResolutionIssue.NO_SPAWN_ZONE,
        QuestResolutionIssue.MISSING_ACCEPT_NPC,
        QuestResolutionIssue.MISSING_TURN_IN_NPC,
    )
    assert not resolution.is_farmable
    assert resolution.zones == ()


def test_resolver_reports_a_selection_made_without_an_extracted_world_map() -> None:
    resolution = QuestGoalResolver().resolve(_kill_quest("general:A", "Flame", 1))

    assert resolution.issues == (
        QuestResolutionIssue.NO_WORLD_MAP,
        QuestResolutionIssue.MISSING_ACCEPT_NPC,
        QuestResolutionIssue.MISSING_TURN_IN_NPC,
    )


def test_resolver_reports_a_quest_that_states_no_farmable_objective() -> None:
    quest = QuestDefinition(quest_id="general:A", title="A", collection=QuestCollection.GENERAL)

    resolution = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR)).resolve(quest)

    assert resolution.issues == (QuestResolutionIssue.NO_FARMABLE_OBJECTIVE,)


def test_resolver_turns_a_collection_objective_into_kills_of_its_drop_sources() -> None:
    quest = QuestDefinition(
        quest_id="general:A",
        title="A",
        collection=QuestCollection.GENERAL,
        item_requirements=(
            QuestItemRequirement(
                item_symbol="II_STONE",
                item_name="Stone",
                required_quantity=4,
                sources=(QuestItemDrop("MI_FLAME", "Flame"),),
            ),
        ),
    )

    resolution = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR)).resolve(quest)

    assert resolution.targets[0].monster_name == "Flame"
    assert resolution.targets[0].required_kills == 4
    assert resolution.is_farmable


def test_queue_reports_progress_and_completion_of_the_active_quest() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR, RAPRA_ZONE))
    queue = QuestFarmingQueue(
        resolver.resolve_all(
            (_kill_quest("general:A", "Flame", 2), _kill_quest("general:B", "Rapra", 1))
        )
    )

    assert queue.remaining == 2
    assert queue.progress[0].kills == 0
    assert not queue.record_kill("Flame")
    assert queue.progress[0].kills == 1
    assert not queue.is_active_completed
    assert queue.record_kill("Flame")
    assert queue.is_active_completed


def test_queue_advances_to_the_next_quest_and_resets_its_counters() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR, RAPRA_ZONE))
    queue = QuestFarmingQueue(
        resolver.resolve_all(
            (_kill_quest("general:A", "Flame", 1), _kill_quest("general:B", "Rapra", 1))
        )
    )
    queue.record_kill("Flame")

    following = queue.advance()

    assert following is not None
    assert following.quest.quest_id == "general:B"
    assert queue.progress[0].monster_name == "Rapra"
    assert queue.progress[0].kills == 0
    assert not queue.is_completed


def test_queue_completes_once_every_selected_quest_is_worked_through() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR))
    queue = QuestFarmingQueue(resolver.resolve_all((_kill_quest("general:A", "Flame", 1),)))

    queue.record_kill("Flame")

    assert queue.advance() is None
    assert queue.is_completed
    assert queue.progress == ()


def test_queue_ignores_an_unattributable_kill_and_an_empty_selection() -> None:
    empty = QuestFarmingQueue()
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR))
    queue = QuestFarmingQueue(resolver.resolve_all((_kill_quest("general:A", "Flame", 1),)))

    assert not empty.has_quests
    assert not empty.is_completed
    assert not empty.record_kill("Flame")
    assert not queue.record_kill(None)
    assert queue.progress[0].kills == 0


def _npc_positions() -> dict[str, QuestNpc]:
    position = WorldPosition(100.0, 0.0, 100.0)
    return {
        "general:A:accept": QuestNpc("Quest Giver", position),
        "general:A:turn_in": QuestNpc("Quest Giver", position),
    }


def _client_quest() -> QuestDefinition:
    quest = _kill_quest("general:A", "Flame", 1)
    return replace(
        quest,
        accept_npc_symbol="MaFl_Test",
        turn_in_npc_symbol="MaFl_TurnIn",
    )


def test_resolver_binds_explicit_npc_locations_by_quest_and_role() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR), _npc_positions())

    resolution = resolver.resolve(_kill_quest("general:A", "Flame", 1))

    assert resolution.issues == ()
    assert resolution.accept_npc is not None
    assert resolution.turn_in_npc is not None
    if resolution.accept_npc is None or resolution.turn_in_npc is None:
        raise AssertionError("Resolved NPCs must exist.")
    assert resolution.accept_npc.position == WorldPosition(100.0, 0.0, 100.0)
    assert resolution.accept_npc.is_interactable_from(WorldPosition(102.0, 0.0, 100.0))
    assert not resolution.accept_npc.is_interactable_from(WorldPosition(105.0, 0.0, 100.0))


def test_resolver_prefers_client_npc_symbols_and_placements() -> None:
    positions = {
        "MaFl_Test": QuestNpc(
            "Client Accept",
            WorldPosition(10.0, 20.0, 30.0),
        ),
        "MaFl_TurnIn": QuestNpc(
            "Client Turn In",
            WorldPosition(40.0, 50.0, 60.0),
        ),
    }
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR), positions)

    resolution = resolver.resolve(_client_quest())

    assert resolution.issues == ()
    assert resolution.accept_npc is not None and resolution.turn_in_npc is not None
    assert resolution.accept_npc.position == WorldPosition(10.0, 20.0, 30.0)
    assert resolution.turn_in_npc.position == WorldPosition(40.0, 50.0, 60.0)


def test_explicit_npc_locations_round_trip_through_versioned_json(tmp_path: Path) -> None:
    path = tmp_path / "npc.json"

    save_quest_npc_positions(_npc_positions(), path)
    loaded = load_quest_npc_positions(path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert loaded == _npc_positions()


def test_malformed_explicit_npc_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "npc.json"
    path.write_text(
        '{"schema_version":1,"positions":{"x":{"name":"N","x":"bad"}}}', encoding="utf-8"
    )

    try:
        load_quest_npc_positions(path)
    except QuestDatabaseError:
        pass
    else:
        raise AssertionError("Expected malformed NPC positions to be rejected.")


class _Dialogue:
    def __init__(self, observations: list[DialogueObservation]) -> None:
        self._observations = iter(observations)

    def observe_dialogue(self, _state: WorldState, _frame: object) -> DialogueObservation:
        return next(self._observations)


def _interaction_resolution() -> object:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR), _npc_positions())
    return resolver.resolve(_kill_quest("general:A", "Flame", 1))


def test_interaction_requires_observed_option_before_clicking_it() -> None:
    from flyff_bot.features.quests.goals import QuestResolution

    controller = QuestInteractionController(
        cast("QuestResolution", _interaction_resolution()),
        dialogue_perceiver=cast(
            "DialoguePerceiver",
            _Dialogue([DialogueObservation(True, True, False, False, Position(30, 40))]),
        ),
    )
    controller.begin_interaction(1.0)
    decision = controller.step(_state(1.1))

    assert controller.mode is QuestInteractionMode.AWAITING_ACCEPT_CONFIRMATION
    assert decision.input_kind is QuestInputKind.CLICK
    if decision.position is None:
        raise AssertionError("Observed dialogue option must produce a click.")
    assert (decision.position.x, decision.position.y) == (30, 40)


def test_dialogue_unavailable_does_not_click_a_menu() -> None:
    from flyff_bot.features.quests.goals import QuestResolution

    controller = QuestInteractionController(cast("QuestResolution", _interaction_resolution()))
    controller.begin_interaction(1.0)

    decision = controller.step(_state(1.1))

    assert decision.input_kind is QuestInputKind.KEY
    assert decision.position is None
    assert decision.virtual_key is not None


def test_interaction_timeout_retries_with_backoff_then_fails_safely() -> None:
    from flyff_bot.features.quests.goals import QuestResolution

    config = QuestInteractionConfig(
        interaction_timeout_seconds=1.0,
        retry_base_seconds=2.0,
        maximum_attempts=2,
        key_press_duration_seconds=0.1,
    )
    controller = QuestInteractionController(
        cast("QuestResolution", _interaction_resolution()), config=config
    )
    controller.observe_navigation(None, False, True, 0.0)
    assert not controller.timeout_navigation(0.5)
    assert controller.timeout_navigation(1.0)

    assert controller.mode is QuestInteractionMode.RETREATING
    assert controller.retry_ready_at_seconds == 3.0
    assert not controller.retry_if_due(2.0)
    assert controller.retry_if_due(3.0)
    controller.observe_navigation(None, False, True, 4.0)
    assert not controller.timeout_navigation(4.5)
    assert controller.timeout_navigation(5.0)
    assert controller.is_failed


def test_position_approach_routes_to_an_exact_npc_and_reports_range(
    monkeypatch: object,
) -> None:
    del monkeypatch
    controller = PathingController(config=PathingConfig())
    target = WorldPosition(100.0, 100.0, 100.0)

    assert not controller.begin_position_approach(target, 0.0)
    assert not controller.position_target_in_interaction_range()


class _RecordingInputAdapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.clicks: list[tuple[int, int, int]] = []
        self.keys: list[tuple[int, float]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))


def test_quest_input_dispatcher_refuses_abort_and_lost_focus() -> None:
    adapter = _RecordingInputAdapter(aborted=True)
    dispatcher = QuestInputDispatcher(adapter, WINDOW_HANDLE)
    decision = QuestInteractionDecision(
        QuestInteractionMode.INTERACTING,
        QuestInputKind.KEY,
        virtual_key=67,
        key_press_duration_seconds=0.1,
    )

    blocked = dispatcher.dispatch(decision)

    adapter.aborted = False
    adapter.foreground = False
    unfocused = dispatcher.dispatch(decision)

    adapter.foreground = True
    dispatched = dispatcher.dispatch(decision)

    assert not blocked
    assert not unfocused
    assert dispatched
    assert adapter.keys == [(67, 0.1)]


class _Pipeline:
    def __init__(self, states: list[WorldState]) -> None:
        self._states = iter(states)

    def tick(self, _window_handle: int, _previous: WorldState) -> PerceptionTick:
        return PerceptionTick(next(self._states), (), frozenset())


class _InputAdapter:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int, int]] = []

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, _window_handle: int) -> bool:
        return True

    def close_window(self, window_handle: int) -> bool:
        return True

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        return None

    def send_key_while_guarded(
        self, _window_handle: int, virtual_key: int, duration_seconds: float
    ) -> None:
        return None

    def send_keys_while_guarded(
        self,
        _window_handle: int,
        virtual_keys: tuple[int, ...] | list[int] | int,
        duration_seconds: float,
    ) -> None:
        return None


def _state(
    time: float,
    *,
    target: SelectedTarget | None = None,
    mobs: tuple[VisibleMob, ...] = (),
) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        selected_target=target or SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=mobs,
        viewport=Viewport(400, 400),
    )


def _kill_states(start_seconds: float, name: str, mobs: tuple[VisibleMob, ...]) -> list[WorldState]:
    return [
        _state(start_seconds, mobs=mobs),
        _state(start_seconds + 1.0, target=SelectedTarget(TargetState.VALID, name, 100)),
        _state(start_seconds + 2.0, target=SelectedTarget(TargetState.VALID, name, 50)),
        _state(start_seconds + 3.0, target=SelectedTarget(TargetState.NONE, None, 0)),
    ]


def _quest_orchestrator(queue: QuestFarmingQueue, states: list[WorldState]) -> FarmingOrchestrator:
    return FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline(states)),
        _InputAdapter(),
        WINDOW_HANDLE,
        quest_queue=queue,
    )


def test_a_quest_session_switches_to_the_next_quest_when_the_active_one_is_met() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR, RAPRA_ZONE))
    queue = QuestFarmingQueue(
        resolver.resolve_all(
            (_kill_quest("general:A", "Flame", 1), _kill_quest("general:B", "Rapra", 1))
        )
    )
    orchestrator = _quest_orchestrator(
        queue, [*_kill_states(1.0, "Flame", (FLAME,)), _state(5.0), _state(6.0)]
    )
    orchestrator.configure_quest_queue(queue)
    orchestrator.start()

    for _ in range(5):
        orchestrator.tick()

    active = queue.active
    assert active is not None
    assert active.quest.quest_id == "general:B"
    assert orchestrator.mode is not FarmingMode.COMPLETED
    assert orchestrator.kill_goals.config.quotas[0].class_name == "Rapra"


def test_a_quest_session_completes_once_the_whole_queue_is_worked_through() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR))
    queue = QuestFarmingQueue(resolver.resolve_all((_kill_quest("general:A", "Flame", 1),)))
    orchestrator = _quest_orchestrator(
        queue, [*_kill_states(1.0, "Flame", (FLAME,)), _state(5.0, mobs=(FLAME,))]
    )
    orchestrator.configure_quest_queue(queue)
    orchestrator.start()

    for _ in range(4):
        orchestrator.tick()
    result = orchestrator.tick()

    assert queue.is_completed
    assert result.mode is FarmingMode.COMPLETED


def test_binding_a_quest_restricts_combat_to_that_quest_s_monsters() -> None:
    resolver = QuestGoalResolver(_world_map(FLAME_ZONE_NEAR, RAPRA_ZONE))
    queue = QuestFarmingQueue(resolver.resolve_all((_kill_quest("general:A", "Flame", 5),)))
    orchestrator = _quest_orchestrator(queue, [_state(1.0)])

    orchestrator.configure_quest_queue(queue)

    assert orchestrator.quest_queue is queue
    assert orchestrator.kill_goals.active_class_names == frozenset({"Flame"})


def test_clearing_the_quest_queue_leaves_the_session_on_its_own_quotas() -> None:
    orchestrator = _quest_orchestrator(QuestFarmingQueue(), [_state(1.0)])

    orchestrator.configure_quest_queue(None)

    assert orchestrator.quest_queue is None
