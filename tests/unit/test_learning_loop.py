"""BUG-031 regression coverage: recorded experience is trainable and a model can act.

Each test here pins one of the loop's broken links: session and episode integrity of the
exported dataset, loss-free parameterized actions, complete reward attribution, a learned
artifact reaching the live decision through a supported application boundary, shadow versus
active execution, train/serve observation parity, missing versus measured-zero encoding, and
failing closed instead of quietly running the heuristic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flyff_bot.features.automation.models import Position, VisibleMob
from flyff_bot.features.ml.export import (
    GRAPH_INPUT_NAME,
    METADATA_FILENAME,
    METADATA_SCHEMA_VERSION,
    artifact_filename,
    export_linear_model,
)
from flyff_bot.features.ml.features import FEATURE_NAMES
from flyff_bot.features.ml.models import LinearValueModel, ValueModelKind
from flyff_bot.features.navigation.live_position import PositionSource, WorldPosition
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    ObjectiveKind,
    TacticalAction,
    TargetAction,
    WaitAction,
)
from flyff_bot.features.policy.hierarchical import HierarchicalObjective
from flyff_bot.features.policy.hierarchical_onnx import live_observation
from flyff_bot.features.policy.insights import POLICY_MODULATED_PARAMETERS
from flyff_bot.features.policy.learned import LearnedPolicy
from flyff_bot.features.policy.models import (
    LiveObservationState,
    PolicyCandidate,
    PolicyContext,
)
from flyff_bot.features.policy.runner import PolicyFaultCode, PolicyRunner
from flyff_bot.features.rl.actions import (
    ParameterizedAction,
    TacticalActionCatalog,
    TacticalActionMask,
)
from flyff_bot.features.rl.exporter import TelemetryTransitionExporter, interval_reward_event
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
from flyff_bot.features.rl.rewards import RewardConfig, RewardEngine
from flyff_bot.features.tactical_parameters import DEFAULT_TACTICAL_PARAMETERS
from flyff_bot.features.telemetry import SqliteTelemetryStore
from flyff_bot.features.telemetry.models import (
    CombatOutcome,
    NavigationOutcome,
    TelemetryEventKind,
)
from flyff_bot.i18n import Language, Message, Translator

SECOND_NS = 1_000_000_000


# --------------------------------------------------------------------------------------
# Telemetry fixtures
# --------------------------------------------------------------------------------------


def _snapshot_payload(x: float = 10.0) -> dict[str, Any]:
    return {
        "player_position": {"x": x, "y": 0.0, "z": 0.0},
        "player_velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
        "hp_percentage": 100.0,
        "mp_percentage": 90.0,
        "fp_percentage": 80.0,
        "readiness_state": "ready",
        "readiness_primary_reason": None,
        "failed_source_codes": [],
        "sample_ages_seconds": [["gps", 0.1]],
        "action_blocked": False,
    }


def _candidate(index: int, class_id: int, *, path_distance: float | None = 5.0) -> dict[str, Any]:
    return {
        "candidate_index": index,
        "class_id": class_id,
        "class_name": f"Mob{class_id}",
        "confidence": 0.9,
        "x": 10 + index,
        "y": 20,
        "width": 4,
        "height": 4,
        "path_distance": path_distance,
        "is_locked_out": False,
    }


def _decision_payload(selected: int, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "selected_candidate_index": selected,
        "decision_reason": "policy_ml_active",
        "decision_latency_ms": 1.0,
        "tactical_parameter_digest": DEFAULT_TACTICAL_PARAMETERS.content_digest,
        "candidates": candidates,
    }


def _persist(
    store: SqliteTelemetryStore, session: str, kind: str, timestamp_ns: int, payload: object
) -> None:
    if kind == "session_header" and payload == {}:
        payload = {"tactical_parameter_digest": DEFAULT_TACTICAL_PARAMETERS.content_digest}
    store.persist(
        {
            "event_kind": kind,
            "session_id": session,
            "timestamp_ns": timestamp_ns,
            "payload": payload,
        }
    )


def _two_overlapping_sessions(path: Path) -> SqliteTelemetryStore:
    """Record two sessions whose timestamps interleave in exactly the same range."""

    store = SqliteTelemetryStore(path)
    for session, class_id in (("alpha", 1), ("beta", 2)):
        _persist(store, session, "session_header", 0, {})
        _persist(store, session, "world_snapshot", 1 * SECOND_NS, _snapshot_payload())
        _persist(
            store,
            session,
            "target_selected",
            2 * SECOND_NS,
            _decision_payload(1, [_candidate(0, class_id), _candidate(1, class_id)]),
        )
        _persist(store, session, "world_snapshot", 3 * SECOND_NS, _snapshot_payload())
        _persist(
            store,
            session,
            "target_selected",
            4 * SECOND_NS,
            _decision_payload(0, [_candidate(0, class_id)]),
        )
        _persist(store, session, "world_snapshot", 5 * SECOND_NS, _snapshot_payload())
    # Only session "alpha" ever verified a kill, and only for its first decision.
    _persist(
        store,
        "alpha",
        "kill_cycle",
        3 * SECOND_NS,
        {"target_decision_timestamp_ns": 2 * SECOND_NS, "verified_kill": True, "reward": 1.0},
    )
    return store


# --------------------------------------------------------------------------------------
# 1. Session, episode, and decision integrity
# --------------------------------------------------------------------------------------


def test_no_transition_crosses_a_session_episode_or_decision_boundary(tmp_path: Path) -> None:
    store = _two_overlapping_sessions(tmp_path / "telemetry.sqlite3")

    transitions = TelemetryTransitionExporter(store).transitions()

    assert [item.session_id for item in transitions] == ["alpha", "alpha", "beta", "beta"]
    by_session = {"alpha": transitions[:2], "beta": transitions[2:]}
    for session, class_id in (("alpha", 1), ("beta", 2)):
        for transition in by_session[session]:
            assert transition.action.target_class_id == class_id
            for candidate in transition.observation.candidates:
                assert candidate.class_id == class_id
            for candidate in transition.next_observation.candidates:
                assert candidate.class_id == class_id
    # The kill belongs to alpha's first interval alone: no other interval may claim its reward.
    rewarded = [item for item in transitions if item.reward > 0.0]
    assert len(rewarded) == 1
    assert rewarded[0].session_id == "alpha"
    assert rewarded[0].action.candidate_index == 1
    # A kill does not end a farming episode; only the end of the recorded session truncates it.
    assert [item.terminated for item in transitions] == [False] * 4
    assert [item.truncated for item in transitions] == [False, True, False, True]
    assert {item.episode_index for item in transitions} == {0}


# --------------------------------------------------------------------------------------
# 2. Parameterized actions and the mask that rejects them
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        TargetAction(7, None, None, None, candidate_index=2),
        TargetAction(
            7, None, None, AttackPointAction(7, (1.0, 2.0, 3.0), 0.25, 2), candidate_index=2
        ),
        NavigateAction((4.0, 5.0, 6.0), "objective_destination"),
        AttackPointAction(7, (1.0, 2.0, 3.0), 0.25, 2),
        CorridorAction(7, "corridor-1", 2),
        InteractAction("npc-1", "quest"),
        InteractAction("npc-1", "npc"),
        WaitAction(0.1, "no_legal_subgoal"),
    ],
)
def test_a_parameterized_action_round_trips_without_losing_its_parameters(
    payload: object,
) -> None:
    encoded = TacticalActionCatalog.encode(payload)  # type: ignore[arg-type]

    assert TacticalActionCatalog.decode(encoded) == payload
    assert TacticalActionCatalog.encode(TacticalActionCatalog.decode(encoded)) == encoded


def test_the_exported_action_names_the_candidate_the_mask_can_reject(tmp_path: Path) -> None:
    store = _two_overlapping_sessions(tmp_path / "telemetry.sqlite3")

    first = TelemetryTransitionExporter(store).transitions()[0]

    assert first.action.action is TacticalAction.SELECT_TARGET
    assert first.action.candidate_index == 1
    assert first.action_mask.allows(first.action)
    # Masking exactly that candidate rejects exactly that choice, while the sibling stays legal.
    rejecting = TacticalActionMask(first.action_mask.actions, (True, False))
    assert not rejecting.allows(first.action)
    assert rejecting.allows(ParameterizedAction(TacticalAction.SELECT_TARGET, candidate_index=0))


def test_the_exporter_preserves_the_selected_instance_between_same_class_candidates(
    tmp_path: Path,
) -> None:
    store = SqliteTelemetryStore(tmp_path / "telemetry.sqlite3")
    _persist(store, "one", "session_header", 0, {})
    _persist(store, "one", "world_snapshot", SECOND_NS, _snapshot_payload())
    _persist(
        store,
        "one",
        "target_selected",
        2 * SECOND_NS,
        _decision_payload(1, [_candidate(0, 5), _candidate(1, 5)]),
    )
    _persist(store, "one", "world_snapshot", 3 * SECOND_NS, _snapshot_payload())

    action = TelemetryTransitionExporter(store).transitions()[0].action

    assert (action.candidate_index, action.target_class_id) == (1, 5)


# --------------------------------------------------------------------------------------
# 3. Reward completeness
# --------------------------------------------------------------------------------------


def _reward_events() -> dict[TelemetryEventKind, list[dict[str, Any]]]:
    return {
        TelemetryEventKind.KILL_CYCLE: [
            {"timestamp_ns": 5 * SECOND_NS, "payload": {"verified_kill": True}},
            # Outside the interval: it belongs to the following decision, not this one.
            {"timestamp_ns": 40 * SECOND_NS, "payload": {"verified_kill": True}},
        ],
        TelemetryEventKind.NAVIGATION_EPISODE: [
            {
                "timestamp_ns": 6 * SECOND_NS,
                "payload": {
                    "started_at_ns": 2 * SECOND_NS,
                    "ended_at_ns": 6 * SECOND_NS,
                    "stall_duration_seconds": 1.5,
                    "evasion_seconds": 0.75,
                    "outcome": NavigationOutcome.ROUTE_UNAVAILABLE.value,
                },
            }
        ],
        TelemetryEventKind.COMBAT_EPISODE: [
            {
                "timestamp_ns": 9 * SECOND_NS,
                "payload": {
                    "started_at_ns": 6 * SECOND_NS,
                    "ended_at_ns": 9 * SECOND_NS,
                    "outcome": CombatOutcome.KILL_VERIFIED.value,
                },
            }
        ],
        TelemetryEventKind.OBJECTIVE_PROGRESS: [
            {
                "timestamp_ns": 8 * SECOND_NS,
                "payload": {"progress_delta": 1.0, "objective_completed": True},
            }
        ],
    }


def test_every_configured_reward_component_is_populated_from_its_own_interval() -> None:
    events = _reward_events()

    event = interval_reward_event(events, start_ns=SECOND_NS, end_ns=11 * SECOND_NS)

    assert event.verified_kill is True
    assert event.quest_progress_delta == 1.0
    assert event.objective_completed is True
    assert event.travel_seconds == 4.0
    assert event.stuck_seconds == 1.5
    assert event.recovery_seconds == 0.75
    assert event.failed_action is True
    # Ten observed seconds minus four travelling and three fighting leaves three idle.
    assert event.idle_seconds == pytest.approx(3.0)
    assert set(RewardConfig().__dataclass_fields__) - {"version"} == {
        f"{name}_weight" for name in ("kill", "quest_step", "objective_complete")
    } | {f"{name}_weight" for name in ("travel", "idle", "stuck", "recovery", "failed_action")}
    assert RewardEngine().reward(event) == pytest.approx(
        1.0 + 0.5 + 2.0 - (0.01 * 4.0 + 0.02 * 3.0 + 0.05 * 1.5 + 0.05 * 0.75 + 0.25)
    )


def test_an_episode_is_awarded_to_exactly_one_interval() -> None:
    events = _reward_events()

    first = interval_reward_event(events, start_ns=SECOND_NS, end_ns=7 * SECOND_NS)
    second = interval_reward_event(events, start_ns=7 * SECOND_NS, end_ns=11 * SECOND_NS)

    assert (first.travel_seconds, second.travel_seconds) == (4.0, 0.0)
    assert (first.stuck_seconds, second.stuck_seconds) == (1.5, 0.0)
    assert (first.recovery_seconds, second.recovery_seconds) == (0.75, 0.0)
    assert (first.objective_completed, second.objective_completed) == (False, True)


# --------------------------------------------------------------------------------------
# 4-5. A real artifact acting through the supported application boundary
# --------------------------------------------------------------------------------------


def _constant_head(value: float, driving_column: int | None = None) -> LinearValueModel:
    weights = np.zeros(2 * len(FEATURE_NAMES), dtype=np.float64)
    if driving_column is not None:
        weights[driving_column] = 1.0
    return LinearValueModel(
        feature_names=FEATURE_NAMES,
        medians=np.zeros(len(FEATURE_NAMES), dtype=np.float64),
        weights=weights,
        intercept=value,
        logistic=False,
    )


def write_minimal_value_model(directory: Path) -> Path:
    """Write a real, loadable five-head artifact that prefers the closer candidate."""

    directory.mkdir(parents=True, exist_ok=True)
    heads = {
        ValueModelKind.TRAVEL_TIME: _constant_head(0.0, FEATURE_NAMES.index("relative_distance")),
        ValueModelKind.STUCK_RISK: _constant_head(0.0),
        ValueModelKind.RECOVERY_TIME: _constant_head(0.0),
        ValueModelKind.KILL_TIME: _constant_head(1.0),
        ValueModelKind.FOLLOWUP_VALUE: _constant_head(0.0),
    }
    for kind, model in heads.items():
        export_linear_model(model, directory / artifact_filename(kind))
    directory.joinpath(METADATA_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": METADATA_SCHEMA_VERSION,
                "feature_schema": {
                    "raw_features": list(FEATURE_NAMES),
                    "input_name": GRAPH_INPUT_NAME,
                },
                "models": {
                    kind.value: {"file": artifact_filename(kind), "trained": True} for kind in heads
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


def _pathing_at_origin() -> PathingController:
    """Return a pathing controller reporting measured live GPS at the world origin."""

    pathing = PathingController()
    pathing._live_position = WorldPosition(0.0, 0.0, 0.0)
    pathing._position_source = PositionSource.LIVE
    return pathing


def _diverging_pair() -> tuple[VisibleMob, VisibleMob]:
    """Return two same-class mobs the heuristic and the learned model rank differently.

    The deterministic controller ranks by measured NavMesh path distance; the trained value
    head above ranks by world separation. Making the two disagree is what proves ML_SHADOW and
    ML_ACTIVE are not the same behaviour under different labels.
    """

    heuristic_choice = VisibleMob(
        class_id=3,
        class_name="Aibatt",
        confidence=0.9,
        x=10,
        y=10,
        width=6,
        height=6,
        world_x=90.0,
        world_y=0.0,
        world_z=0.0,
        navmesh_path_distance=1.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    learned_choice = VisibleMob(
        class_id=3,
        class_name="Aibatt",
        confidence=0.9,
        x=60,
        y=60,
        width=6,
        height=6,
        world_x=5.0,
        world_y=0.0,
        world_z=0.0,
        navmesh_path_distance=99.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    return heuristic_choice, learned_choice


def _centre(mob: VisibleMob) -> tuple[int, int]:
    return mob.x + mob.width // 2, mob.y + mob.height // 2


def _same_class_pair() -> tuple[VisibleMob, VisibleMob]:
    far = VisibleMob(
        class_id=3,
        class_name="Aibatt",
        confidence=0.9,
        x=10,
        y=10,
        width=6,
        height=6,
        world_x=90.0,
        world_y=0.0,
        world_z=0.0,
        navmesh_path_distance=90.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    near = VisibleMob(
        class_id=3,
        class_name="Aibatt",
        confidence=0.9,
        x=60,
        y=60,
        width=6,
        height=6,
        world_x=5.0,
        world_y=0.0,
        world_z=0.0,
        navmesh_path_distance=5.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    return far, near


def test_a_real_artifact_selects_the_intended_instance_of_two_same_class_candidates(
    tmp_path: Path,
) -> None:
    from typing import cast

    from test_orchestrator import WINDOW_HANDLE, _InputAdapter, _Pipeline, _state

    from flyff_bot.features.automation.orchestrator import (
        FarmingConfig,
        FarmingOrchestrator,
    )
    from flyff_bot.features.perception.pipeline import PerceptionPipeline
    from flyff_bot.features.policy.models import PolicyRuntimeMode

    directory = write_minimal_value_model(tmp_path / "model")
    far, near = _same_class_pair()
    state = _state(1.0, mobs=(far, near))
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline([state])),
        _InputAdapter(),
        WINDOW_HANDLE,
        pathing=_pathing_at_origin(),
        config=FarmingConfig(
            policy_mode=PolicyRuntimeMode.ML_ACTIVE, policy_model_directory=str(directory)
        ),
    )

    assert orchestrator.learned_policy_available
    orchestrator._state = state
    selected = orchestrator._evaluate_policy_target()

    assert orchestrator.policy_fault is None
    assert selected is near
    action = orchestrator._last_policy_action
    assert isinstance(action, TargetAction)
    assert action.candidate_index == 1


def test_shadow_records_the_learned_choice_while_active_executes_it(tmp_path: Path) -> None:
    from typing import cast

    from test_orchestrator import WINDOW_HANDLE, _InputAdapter, _Pipeline, _state

    from flyff_bot.features.automation.orchestrator import (
        FarmingConfig,
        FarmingOrchestrator,
    )
    from flyff_bot.features.perception.pipeline import PerceptionPipeline
    from flyff_bot.features.policy.models import PolicyRuntimeMode

    directory = write_minimal_value_model(tmp_path / "model")
    heuristic_choice, learned_choice = _diverging_pair()
    state = _state(1.0, mobs=(heuristic_choice, learned_choice))

    def _session(mode: PolicyRuntimeMode) -> tuple[FarmingOrchestrator, _InputAdapter]:
        adapter = _InputAdapter()
        session = FarmingOrchestrator(
            cast(PerceptionPipeline, _Pipeline([state, state])),
            adapter,
            WINDOW_HANDLE,
            pathing=_pathing_at_origin(),
            config=FarmingConfig(policy_mode=mode, policy_model_directory=str(directory)),
        )
        session.start()
        session._state = state
        return session, adapter

    shadow, shadow_adapter = _session(PolicyRuntimeMode.ML_SHADOW)
    active, active_adapter = _session(PolicyRuntimeMode.ML_ACTIVE)

    shadow._advance()
    active._advance()

    # Shadow keeps the executed-action provenance on the canonical baseline while its
    # insight snapshot separately records and compares the learned decision.
    assert isinstance(shadow._last_policy_action, TargetAction)
    assert shadow._last_policy_action.candidate_index == 0
    assert shadow_adapter.clicks == [(WINDOW_HANDLE, *_centre(heuristic_choice))]
    # Active dispatches the learned instance instead, so the two modes are observably distinct.
    assert active_adapter.clicks == [(WINDOW_HANDLE, *_centre(learned_choice))]
    assert shadow_adapter.clicks != active_adapter.clicks
    assert shadow.policy_fault is None and active.policy_fault is None


def test_a_shadow_session_publishes_candidate_reward_and_agreement_telemetry(
    tmp_path: Path,
) -> None:
    """The dashboard receives one frozen snapshot per tick, built off the tick thread."""

    from typing import cast

    from test_orchestrator import WINDOW_HANDLE, _InputAdapter, _Pipeline, _state

    from flyff_bot.features.automation.orchestrator import (
        FarmingConfig,
        FarmingOrchestrator,
    )
    from flyff_bot.features.perception.pipeline import PerceptionPipeline
    from flyff_bot.features.policy.insights import CandidateVerdict
    from flyff_bot.features.policy.models import PolicyRuntimeMode
    from flyff_bot.ui.dashboard import DashboardFeed, DashboardUpdate

    directory = write_minimal_value_model(tmp_path / "model")
    heuristic_choice, learned_choice = _diverging_pair()
    state = _state(1.0, mobs=(heuristic_choice, learned_choice))
    feed = DashboardFeed()
    updates: list[DashboardUpdate] = []
    feed.update_available.connect(updates.append)
    session = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline([state, state])),
        _InputAdapter(),
        WINDOW_HANDLE,
        pathing=_pathing_at_origin(),
        config=FarmingConfig(
            policy_mode=PolicyRuntimeMode.ML_SHADOW,
            policy_model_directory=str(directory),
        ),
        dashboard_feed=feed,
    )
    session.start()
    session._state = state

    session._advance()
    snapshot = session._policy_insight_snapshot()

    assert snapshot.mode is PolicyRuntimeMode.ML_SHADOW
    assert snapshot.artifact.is_loaded
    assert len(snapshot.artifact.sha256) == 64
    assert snapshot.inference_latency_seconds is not None
    assert [item.verdict for item in snapshot.candidates] == [
        CandidateVerdict.ALLOWED,
        CandidateVerdict.ALLOWED,
    ]
    assert snapshot.chosen is not None and snapshot.chosen.candidate_index == 1
    assert snapshot.shadow is not None and snapshot.shadow.comparisons == 1
    assert snapshot.shadow.heuristic_candidate_index == 0
    assert [override.parameter for override in snapshot.parameter_overrides] == list(
        POLICY_MODULATED_PARAMETERS
    )


def test_a_heuristic_session_publishes_the_canonical_baseline_ranking() -> None:
    """The operator can inspect the same canonical decision the controller executed."""

    from typing import cast

    from test_orchestrator import WINDOW_HANDLE, _InputAdapter, _Pipeline, _state

    from flyff_bot.features.automation.orchestrator import (
        FarmingConfig,
        FarmingOrchestrator,
    )
    from flyff_bot.features.perception.pipeline import PerceptionPipeline
    from flyff_bot.features.policy.models import PolicyRuntimeMode

    heuristic_choice, learned_choice = _diverging_pair()
    state = _state(1.0, mobs=(heuristic_choice, learned_choice))
    session = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline([state])),
        _InputAdapter(),
        WINDOW_HANDLE,
        pathing=_pathing_at_origin(),
        config=FarmingConfig(policy_mode=PolicyRuntimeMode.HEURISTIC),
    )
    session.start()
    session._state = state

    session._advance()
    snapshot = session._policy_insight_snapshot()

    assert len(snapshot.candidates) == 2
    assert snapshot.chosen is not None and snapshot.chosen.candidate_index == 0
    assert snapshot.shadow is None
    assert snapshot.inference_latency_seconds is None
    assert not snapshot.artifact.is_loaded


# --------------------------------------------------------------------------------------
# 6. Train/serve observation parity
# --------------------------------------------------------------------------------------


def test_the_live_and_training_observation_encoders_agree_for_one_state() -> None:
    from test_orchestrator import _state

    kinematics = PlayerKinematics(120.0, 5.0, -60.0, 0.75)
    navmesh = NavMeshContext("poly-7", 12.0, 340.0)
    mob = VisibleMob(
        class_id=3,
        class_name="Aibatt",
        confidence=0.9,
        x=10,
        y=10,
        width=6,
        height=6,
        world_x=140.0,
        world_y=9.0,
        world_z=-20.0,
        navmesh_path_distance=45.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    state = _state(1.0, mobs=(mob,))
    context = PolicyContext(
        (PolicyCandidate(mob, True, True, True, True, True, 0),),
        frozenset(),
        (False,),
        live_state=LiveObservationState(kinematics, navmesh, 0, 4.0, 1, 250.0),
    )
    objective = HierarchicalObjective(quest_id="quest-1", progress=0.0, required_progress=2.0)

    served = ObservationSpace.encode(live_observation(state, context, objective))
    trained = ObservationSpace.encode(
        RlObservation(
            kinematics,
            PlayerVitals(
                state.player_vitals.hp_percentage,
                state.player_vitals.mp_percentage,
                state.player_vitals.fp_percentage,
            ),
            navmesh,
            (CandidateObservation(0, 3, 0.9, 140.0, 9.0, -20.0, 45.0, 4.0),),
            OperationalState(0, 4.0, 1, "farming"),
            ObjectiveState(
                "quest-1", ((2, 0.0),), 250.0, "quest-1:0", ObjectiveKind.FARM, 0, 1, 0.0, 2.0
            ),
        )
    )

    assert np.array_equal(served, trained)


def test_a_learned_policy_without_live_world_facts_fails_closed() -> None:
    from test_orchestrator import _state

    mob = VisibleMob(class_id=3, class_name="Aibatt", confidence=0.9, x=1, y=1, width=2, height=2)
    context = PolicyContext(
        (PolicyCandidate(mob, True, True, True, True, True, 0),), frozenset(), (False,)
    )

    with pytest.raises(ValueError, match="live_observation_unavailable"):
        live_observation(_state(1.0, mobs=(mob,)), context, HierarchicalObjective())


# --------------------------------------------------------------------------------------
# 7. Missing versus measured zero
# --------------------------------------------------------------------------------------


def _observation_with(candidate: CandidateObservation, slope: float | None) -> RlObservation:
    return RlObservation(
        PlayerKinematics(0.0, 0.0, 0.0, 0.0),
        PlayerVitals(100.0, 100.0, 100.0),
        NavMeshContext("poly-1", slope, None),
        (candidate,),
        OperationalState(None, 0.0, 0, "farming"),
        ObjectiveState(None, (), None),
    )


def test_a_missing_measurement_never_encodes_like_a_measured_zero() -> None:
    missing = _observation_with(CandidateObservation(0, 1, 0.9, None, None, None, None, None), None)
    measured = _observation_with(CandidateObservation(0, 1, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0)

    assert not np.array_equal(ObservationSpace.encode(missing), ObservationSpace.encode(measured))


def test_a_negative_measurement_never_encodes_like_a_zero_one() -> None:
    negative = _observation_with(
        CandidateObservation(0, 1, 0.9, -500.0, -20.0, 0.0, 0.0, -8.0), -30.0
    )
    zero = _observation_with(CandidateObservation(0, 1, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0)

    assert not np.array_equal(ObservationSpace.encode(negative), ObservationSpace.encode(zero))


# --------------------------------------------------------------------------------------
# 8. Failing closed with a synchronized diagnostic
# --------------------------------------------------------------------------------------


def test_an_unusable_model_halts_the_session_instead_of_running_the_heuristic(
    tmp_path: Path,
) -> None:
    from typing import cast

    from test_orchestrator import WINDOW_HANDLE, _InputAdapter, _Pipeline, _state

    from flyff_bot.features.automation.orchestrator import (
        FarmingConfig,
        FarmingMode,
        FarmingOrchestrator,
    )
    from flyff_bot.features.perception.pipeline import PerceptionPipeline
    from flyff_bot.features.policy.models import PolicyRuntimeMode

    broken = tmp_path / "broken"
    broken.mkdir()
    broken.joinpath(METADATA_FILENAME).write_text("{}", encoding="utf-8")
    far, near = _same_class_pair()
    state = _state(1.0, mobs=(far, near))
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline([state])),
        _InputAdapter(),
        WINDOW_HANDLE,
        config=FarmingConfig(
            policy_mode=PolicyRuntimeMode.ML_ACTIVE, policy_model_directory=str(broken)
        ),
    )
    orchestrator.start()
    orchestrator._state = state

    assert orchestrator._evaluate_policy_target() is None
    fault = orchestrator.policy_fault
    assert fault is not None and fault.code is PolicyFaultCode.MODEL_UNAVAILABLE
    assert orchestrator.mode is FarmingMode.PAUSED
    assert orchestrator._policy_mode is PolicyRuntimeMode.HEURISTIC


def test_selecting_a_learned_mode_without_a_model_fails_closed(tmp_path: Path) -> None:
    from typing import cast

    from test_orchestrator import WINDOW_HANDLE, _InputAdapter, _Pipeline, _state

    from flyff_bot.features.automation.orchestrator import (
        FarmingConfig,
        FarmingMode,
        FarmingOrchestrator,
    )
    from flyff_bot.features.perception.pipeline import PerceptionPipeline
    from flyff_bot.features.policy.models import PolicyRuntimeMode

    far, near = _same_class_pair()
    state = _state(1.0, mobs=(far, near))
    orchestrator = FarmingOrchestrator(
        cast(PerceptionPipeline, _Pipeline([state])),
        _InputAdapter(),
        WINDOW_HANDLE,
        config=FarmingConfig(policy_mode=PolicyRuntimeMode.HEURISTIC),
    )
    orchestrator.configure_policy_model_directory(str(write_minimal_value_model(tmp_path / "m")))
    assert orchestrator.learned_policy_available

    orchestrator.configure_policy_model_directory(None)
    orchestrator.configure_policy_mode(PolicyRuntimeMode.ML_ACTIVE)
    orchestrator.start()
    orchestrator._state = state

    assert orchestrator._evaluate_policy_target() is None
    assert orchestrator.policy_fault is not None
    assert orchestrator.mode is FarmingMode.PAUSED


def test_the_halt_diagnostic_is_available_in_both_supported_languages() -> None:
    reason = f"{PolicyFaultCode.MODEL_UNAVAILABLE.value}:metadata_invalid"

    texts = {
        language: Translator(language).text(Message.POLICY_MODEL_UNAVAILABLE, reason=reason)
        for language in Language
    }

    assert set(texts) == set(Language)
    assert all(reason in text for text in texts.values())
    assert len(set(texts.values())) == len(Language)


def test_a_deterministic_learned_policy_still_reaches_the_execution_boundary(
    tmp_path: Path,
) -> None:
    """A loaded artifact plus decision-time features yields a legal, validated action."""

    from test_orchestrator import _state

    directory = write_minimal_value_model(tmp_path / "model")
    far, near = _same_class_pair()
    candidates = (
        PolicyCandidate(far, True, True, True, True, True, 0),
        PolicyCandidate(near, True, True, True, True, True, 1),
    )
    matrix = np.zeros((2, len(FEATURE_NAMES)), dtype=np.float64)
    matrix[0, FEATURE_NAMES.index("relative_distance")] = 90.0
    matrix[1, FEATURE_NAMES.index("relative_distance")] = 5.0
    context = PolicyContext(candidates, frozenset(), (False, False), matrix)
    runner = PolicyRunner(LearnedPolicy(directory))

    action = runner.evaluate(_state(1.0, mobs=(far, near)), context)

    assert runner.last_fault is None
    assert isinstance(action, TargetAction)
    assert action.candidate_index == 1
    assert action.target_pos == Position(near.x, near.y)
