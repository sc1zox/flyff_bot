"""US-079: one goal-conditioned, versioned decision contract for offline and live decisions.

These tests pin the four properties the contract exists for: an observation states *which*
objective is being pursued, the offline and the live encoder produce the very same vector for
the same world state, exactly one versioned reward configuration is used and stamped into
everything it produced, and an artifact from another contract is refused rather than shimmed.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.navigation.world_extractor import (
    VectorSpawnZone,
    WorldCoordinate,
    WorldVectorMap,
)
from flyff_bot.features.policy.action_payloads import ObjectiveKind
from flyff_bot.features.policy.contract import (
    CONTRACT_DOCUMENT_KEY,
    DECISION_CONTRACT_VERSION,
    ContractIncompatibility,
    ContractVersionError,
    current_contract_stamp,
    verify_contract_document,
)
from flyff_bot.features.policy.hierarchical import (
    HierarchicalObjective,
    HierarchicalObjectiveKind,
)
from flyff_bot.features.policy.hierarchical_onnx import live_observation
from flyff_bot.features.policy.hierarchical_training import (
    HIERARCHICAL_METADATA_SCHEMA_VERSION,
    read_hierarchical_metadata,
)
from flyff_bot.features.policy.models import (
    LiveObservationState,
    PolicyCandidate,
    PolicyContext,
)
from flyff_bot.features.policy.runner import PolicyFault
from flyff_bot.features.rl.exporter import (
    CONTRACT_METADATA_KEY,
    RL_TRANSITIONS_FILE,
    TelemetryTransitionExporter,
    read_transition_contract,
)
from flyff_bot.features.rl.models import (
    CandidateObservation,
    NavMeshContext,
    ObjectiveState,
    ObservationSpace,
    OperationalState,
    PlayerKinematics,
    PlayerVitals,
    RlObservation,
)
from flyff_bot.features.rl.rewards import (
    DEFAULT_REWARD_CONFIG,
    REWARD_CONFIG_VERSION,
    RewardConfig,
)
from flyff_bot.features.simulator import FarmingSimulator, QuestObjective, SimulatorConfig
from flyff_bot.features.simulator.engine import SIMULATED_QUEST_ID
from flyff_bot.features.tactical_parameters import (
    DEFAULT_TACTICAL_PARAMETERS,
    TACTICAL_PARAMETER_SCHEMA_VERSION,
)
from flyff_bot.features.telemetry import SqliteTelemetryStore
from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.main_window_parts.combat_settings import (
    _CONTRACT_MESSAGES,
    policy_fault_text,
)

MONSTER_ID = 7
MONSTER_NAME = "SmallAibatt"
MONSTER_X = 30.0
MONSTER_Z = 25.0
START = WorldCoordinate(10.0, 10.0)
QUEST_OBJECTIVE_ID = "simulated-quest:0"
REQUIRED_KILLS = 2


@pytest.fixture
def transition_store(tmp_path: Path) -> SqliteTelemetryStore:
    """Return a telemetry store holding exactly one complete recorded decision interval."""

    store = SqliteTelemetryStore(tmp_path / "telemetry.sqlite3")
    store.persist(
        {
            "event_kind": "session_header",
            "session_id": "one",
            "timestamp_ns": 0,
            "payload": {"tactical_parameter_digest": DEFAULT_TACTICAL_PARAMETERS.content_digest},
        }
    )
    snapshot = {
        "player_position": {"x": 1, "y": 2, "z": 3},
        "player_velocity": {"x": 0, "y": 0, "z": 0},
        "hp_percentage": 100,
        "mp_percentage": 90,
        "fp_percentage": 80,
    }
    store.persist(
        {
            "event_kind": "world_snapshot",
            "session_id": "one",
            "timestamp_ns": 1,
            "payload": snapshot,
        }
    )
    store.persist(
        {
            "event_kind": "target_selected",
            "session_id": "one",
            "timestamp_ns": 2,
            "payload": {
                "selected_candidate_index": 0,
                "decision_reason": "nearest",
                "decision_latency_ms": 1.0,
                "tactical_parameter_digest": DEFAULT_TACTICAL_PARAMETERS.content_digest,
                "candidates": [
                    {
                        "candidate_index": 0,
                        "class_id": 1,
                        "class_name": "Aibatt",
                        "confidence": 0.9,
                        "x": 1,
                        "y": 2,
                        "width": 3,
                        "height": 4,
                    }
                ],
            },
        }
    )
    store.persist(
        {
            "event_kind": "world_snapshot",
            "session_id": "one",
            "timestamp_ns": 3,
            "payload": snapshot,
        }
    )
    return store


# --------------------------------------------------------------------------------------
# Goal-conditioned observation columns
# --------------------------------------------------------------------------------------


def _observation(objective: ObjectiveState) -> RlObservation:
    return RlObservation(
        PlayerKinematics(120.0, 5.0, -60.0, 0.75),
        PlayerVitals(100.0, 100.0, 100.0),
        NavMeshContext("poly-7", 12.0, 340.0),
        (CandidateObservation(0, 3, 0.9, 140.0, 9.0, -20.0, 45.0, 4.0),),
        OperationalState(0, 4.0, 1, "quest"),
        objective,
    )


def _encoded(objective: ObjectiveState) -> np.ndarray:
    return ObservationSpace.encode(_observation(objective))


def _pursued() -> ObjectiveState:
    return ObjectiveState(
        "quest-1", ((2, 0.0),), 250.0, "quest-1:0", ObjectiveKind.KILL, 0, 3, 0.0, 2.0
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"objective_id": "quest-1:2"},
        {"objective_kind": ObjectiveKind.TALK_TO_NPC},
        {"objective_index": 2},
        {"measured_progress": 1.0},
        {"objective_target_distance": 40.0},
    ],
)
def test_the_same_state_under_two_different_goals_encodes_differently(
    changed: dict[str, object],
) -> None:
    pursued = _pursued()
    other = replace(pursued, **changed)  # type: ignore[arg-type]

    assert not np.array_equal(_encoded(pursued), _encoded(other))


def test_an_unpursued_objective_never_encodes_like_a_measured_one() -> None:
    absent = ObjectiveState(None, (), None)
    measured = ObjectiveState(None, (), 0.0, "quest-1:0", ObjectiveKind.FARM, 0, 1, 0.0, 1.0)

    assert not np.array_equal(_encoded(absent), _encoded(measured))


def test_an_objective_identity_encodes_the_same_way_in_every_process() -> None:
    first = _encoded(_pursued())
    second = _encoded(_pursued())

    assert np.array_equal(first, second)


def test_an_objective_index_outside_its_own_sequence_is_rejected() -> None:
    with pytest.raises(ValueError, match="objective index"):
        ObjectiveState("quest-1", (), None, "quest-1:3", ObjectiveKind.KILL, 3, 3)


# --------------------------------------------------------------------------------------
# Simulator versus live encoder parity
# --------------------------------------------------------------------------------------


def _parity_world(world_map: WorldVectorMap) -> WorldVectorMap:
    """Return the test region with one monster whose position no seed can move."""

    zone = VectorSpawnZone(
        MONSTER_ID,
        MONSTER_X,
        0.0,
        MONSTER_Z,
        MONSTER_X,
        MONSTER_Z,
        MONSTER_X,
        MONSTER_Z,
        capacity=1,
        respawn_seconds=1,
        monster_name=MONSTER_NAME,
    )
    return WorldVectorMap(
        world_map.world_name,
        world_map.dimensions,
        zones=(zone,),
        terrain_blocks=world_map.terrain_blocks,
    )


def test_the_simulator_and_live_encoders_produce_one_identical_vector(
    world_map: WorldVectorMap,
) -> None:
    parity_map = _parity_world(world_map)
    config = SimulatorConfig(tick_seconds=0.5)
    objective = QuestObjective(
        ObjectiveKind.KILL,
        identifier=QUEST_OBJECTIVE_ID,
        monster_id=MONSTER_ID,
        required_count=REQUIRED_KILLS,
    )
    simulation = FarmingSimulator(
        parity_map, start=START, objectives=(objective,), config=config, seed=1
    )

    # The live inputs are derived from the same world facts the simulator was built from,
    # never from the simulator's own observation.
    player_height = parity_map.terrain.height_at(START) or 0.0
    monster_height = parity_map.terrain.height_at(WorldCoordinate(MONSTER_X, MONSTER_Z)) or 0.0
    distance = math.hypot(MONSTER_X - START.x, MONSTER_Z - START.z)
    kinematics = PlayerKinematics(
        START.x, player_height, START.z, 0.0, config.nominal_speed_units_per_second, 0.0, 0.0
    )
    mob = VisibleMob(
        class_id=MONSTER_ID,
        class_name=MONSTER_NAME,
        confidence=1.0,
        x=10,
        y=10,
        width=6,
        height=6,
        world_x=MONSTER_X,
        world_y=monster_height,
        world_z=MONSTER_Z,
        navmesh_path_distance=distance,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    state = WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=1,
        progress_marker=0,
        selected_target=SelectedTarget(TargetState.NONE, None, 0),
        visible_mobs=(mob,),
        viewport=Viewport(100, 100),
    )
    context = PolicyContext(
        (PolicyCandidate(mob, True, True, True, True, True, 0),),
        frozenset(),
        (False,),
        live_state=LiveObservationState(
            kinematics, NavMeshContext(None, None, distance), None, 0.0, 0, distance
        ),
    )
    live_goal = HierarchicalObjective(
        HierarchicalObjectiveKind.QUEST,
        frozenset({MONSTER_NAME}),
        quest_id=SIMULATED_QUEST_ID,
        objective_index=0,
        objective_count=1,
        progress=0.0,
        required_progress=float(REQUIRED_KILLS),
        objective_id=QUEST_OBJECTIVE_ID,
        objective_kind=ObjectiveKind.KILL,
    )

    offline = ObservationSpace.encode(simulation.observation)
    served = ObservationSpace.encode(live_observation(state, context, live_goal))

    assert np.array_equal(offline, served)


# --------------------------------------------------------------------------------------
# One versioned reward configuration
# --------------------------------------------------------------------------------------


def test_simulator_and_exporter_score_with_the_same_reward_configuration(
    transition_store: SqliteTelemetryStore,
) -> None:
    exporter = TelemetryTransitionExporter(transition_store)

    assert SimulatorConfig().reward is DEFAULT_REWARD_CONFIG
    assert exporter.reward_config is DEFAULT_REWARD_CONFIG
    assert DEFAULT_REWARD_CONFIG.version == REWARD_CONFIG_VERSION


def test_a_reward_configuration_that_changes_a_weight_needs_its_own_version() -> None:
    with pytest.raises(ValueError, match="own version"):
        RewardConfig(kill_weight=2.0)

    declared = RewardConfig(kill_weight=2.0, version="experiment-v1")

    assert declared.version != REWARD_CONFIG_VERSION


def test_an_exported_dataset_and_its_provenance_carry_the_reward_version(
    tmp_path: Path, transition_store: SqliteTelemetryStore
) -> None:
    exporter = TelemetryTransitionExporter(transition_store)

    transitions_path, provenance_path = exporter.export(tmp_path / "rl")

    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    table = pq.read_table(transitions_path)
    stamp = json.loads((table.schema.metadata or {})[CONTRACT_METADATA_KEY].decode("utf-8"))

    assert provenance["reward_config_version"] == REWARD_CONFIG_VERSION
    assert provenance[CONTRACT_DOCUMENT_KEY] == current_contract_stamp().as_document()
    assert stamp["reward_config_version"] == REWARD_CONFIG_VERSION
    assert stamp["tactical_parameter_schema_version"] == TACTICAL_PARAMETER_SCHEMA_VERSION
    assert set(table.column("reward_config_version").to_pylist()) == {REWARD_CONFIG_VERSION}
    assert read_transition_contract(transitions_path) == current_contract_stamp()


# --------------------------------------------------------------------------------------
# Contract version rejection
# --------------------------------------------------------------------------------------


def _stale_document() -> dict[str, object]:
    document = current_contract_stamp().as_document()
    document["contract_version"] = "bug031-v1"
    return document


def test_an_artifact_from_another_contract_is_refused_with_both_versions_named() -> None:
    with pytest.raises(ContractVersionError) as error:
        verify_contract_document(_stale_document())

    assert error.value.incompatibility is ContractIncompatibility.CONTRACT_VERSION
    assert error.value.expected == DECISION_CONTRACT_VERSION
    assert error.value.found == "bug031-v1"


@pytest.mark.parametrize(
    ("field_name", "value", "incompatibility"),
    [
        ("observation_schema_version", "bug031-v1", ContractIncompatibility.OBSERVATION_SCHEMA),
        ("observation_width", 75, ContractIncompatibility.OBSERVATION_WIDTH),
        ("strategic_goal_order", ["wait"], ContractIncompatibility.GOAL_VOCABULARY),
        ("objective_kind_order", ["farm"], ContractIncompatibility.GOAL_VOCABULARY),
        ("tactical_action_count", 4, ContractIncompatibility.ACTION_VOCABULARY),
        ("reward_config_version", "us070-v1", ContractIncompatibility.REWARD_CONFIG),
        (
            "tactical_parameter_schema_version",
            "missing-v1",
            ContractIncompatibility.TACTICAL_PARAMETERS,
        ),
    ],
)
def test_every_contract_field_is_checked_on_its_own(
    field_name: str, value: object, incompatibility: ContractIncompatibility
) -> None:
    document = current_contract_stamp().as_document()
    document[field_name] = value

    with pytest.raises(ContractVersionError) as error:
        verify_contract_document(document)

    assert error.value.incompatibility is incompatibility


def test_an_artifact_without_a_contract_stamp_is_refused() -> None:
    with pytest.raises(ContractVersionError) as error:
        verify_contract_document(None)

    assert error.value.incompatibility is ContractIncompatibility.CONTRACT_MISSING


def test_a_policy_artifact_from_another_contract_is_never_loaded(tmp_path: Path) -> None:
    metadata_path = tmp_path / "hierarchical-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": HIERARCHICAL_METADATA_SCHEMA_VERSION,
                CONTRACT_DOCUMENT_KEY: _stale_document(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractVersionError) as error:
        read_hierarchical_metadata(metadata_path)

    assert error.value.incompatibility is ContractIncompatibility.CONTRACT_VERSION


def test_a_dataset_from_another_contract_is_never_read(
    tmp_path: Path, transition_store: SqliteTelemetryStore
) -> None:
    directory = tmp_path / "rl"
    TelemetryTransitionExporter(transition_store).export(directory)
    transitions_path = directory / RL_TRANSITIONS_FILE
    table = pq.read_table(transitions_path)
    stale = table.replace_schema_metadata(
        {CONTRACT_METADATA_KEY: json.dumps(_stale_document()).encode("utf-8")}
    )
    pq.write_table(stale, transitions_path)

    with pytest.raises(ContractVersionError) as error:
        read_transition_contract(transitions_path)

    assert error.value.incompatibility is ContractIncompatibility.CONTRACT_VERSION


# --------------------------------------------------------------------------------------
# Localized incompatibility diagnostics
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("incompatibility", list(ContractIncompatibility))
def test_every_contract_incompatibility_reads_as_one_localized_sentence(
    incompatibility: ContractIncompatibility,
) -> None:
    fault = PolicyFault.from_contract_error(
        ContractVersionError(incompatibility, expected="us079-v1", found="bug031-v1")
    )

    texts = {language: policy_fault_text(Translator(language), fault) for language in Language}

    names_both_versions = incompatibility is not ContractIncompatibility.CONTRACT_MISSING

    assert incompatibility in _CONTRACT_MESSAGES
    assert len(set(texts.values())) == len(Language)
    assert all("us079-v1" in text for text in texts.values())
    assert all(("bug031-v1" in text) is names_both_versions for text in texts.values())
    assert all("{" not in text for text in texts.values())
