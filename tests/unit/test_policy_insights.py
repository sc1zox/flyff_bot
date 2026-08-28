"""Decision, reward and experience telemetry the ML and policy view renders (US-087)."""

from __future__ import annotations

import json
from pathlib import Path

from flyff_bot.features.automation.models import Position, VisibleMob
from flyff_bot.features.policy.insights import (
    POLICY_MODULATED_PARAMETERS,
    CandidateVerdict,
    ChosenActionInsight,
    ParameterOverrideInsight,
    PolicyInsightRecorder,
    baseline_candidate_index,
    digest_artifact_document,
)
from flyff_bot.features.policy.models import (
    AttackPointAction,
    PolicyCandidate,
    PolicyRuntimeMode,
    TargetAction,
    WaitAction,
)
from flyff_bot.features.tactical_parameters import TacticalParameterName
from flyff_bot.features.telemetry.models import SessionExperienceTotals

REACHABLE_DISTANCE_UNITS = 12.5
ARTIFACT_DOCUMENT = "hierarchical-metadata.json"


def _mob(class_id: int, name: str, *, path_distance: float | None = None) -> VisibleMob:
    return VisibleMob(
        class_id=class_id,
        class_name=name,
        confidence=0.9,
        x=10 * class_id,
        y=10 * class_id,
        width=8,
        height=8,
        navmesh_path_distance=path_distance,
    )


def _candidate(mob: VisibleMob, index: int, *, eligible: bool = True) -> PolicyCandidate:
    return PolicyCandidate(
        mob=mob,
        is_alive_and_recognized=True,
        is_unlocked=True,
        is_within_leash=True,
        is_navmesh_reachable=eligible,
        has_valid_world_position=True,
        original_position=index,
        candidate_identity=index + 100,
    )


def test_the_option_set_keeps_rejected_candidates_and_marks_the_chosen_one() -> None:
    first = _mob(1, "Aibatt", path_distance=REACHABLE_DISTANCE_UNITS)
    second = _mob(2, "Burudeng")
    candidates = (_candidate(first, 0), _candidate(second, 1, eligible=False))
    recorder = PolicyInsightRecorder()

    recorder.record_decision(
        candidates,
        TargetAction(first.class_id, Position(first.x, first.y), 3.5, candidate_index=0),
        latency_seconds=0.002,
    )
    snapshot = recorder.snapshot(
        PolicyRuntimeMode.ML_ACTIVE,
        experience=SessionExperienceTotals(),
        parameter_overrides=(),
    )

    assert [item.verdict for item in snapshot.candidates] == [
        CandidateVerdict.ALLOWED,
        CandidateVerdict.MASKED,
    ]
    assert [item.is_chosen for item in snapshot.candidates] == [True, False]
    assert snapshot.candidates[0].distance_units == REACHABLE_DISTANCE_UNITS
    assert snapshot.candidates[0].score == 3.5
    assert snapshot.candidates[1].distance_units is None
    assert snapshot.inference_latency_seconds == 0.002


def test_a_chosen_action_reports_its_goal_candidate_and_dynamic_approach_distance() -> None:
    action = AttackPointAction(1, (1.0, 2.0, 3.0), 0.5, 4, 6.25)

    insight = ChosenActionInsight.from_action(action)

    assert insight.candidate_index == 4
    assert insight.approach_distance_units == 6.25
    assert ChosenActionInsight.from_action(WaitAction(0.1, "idle")).wait_seconds == 0.1


def test_shadow_mode_tracks_agreement_between_the_baseline_and_the_learned_choice() -> None:
    first = _mob(1, "Aibatt")
    second = _mob(2, "Burudeng")
    candidates = (_candidate(first, 0), _candidate(second, 1))
    recorder = PolicyInsightRecorder()

    recorder.record_decision(
        candidates,
        TargetAction(first.class_id, Position(first.x, first.y), candidate_index=0),
        latency_seconds=0.001,
        baseline_candidate_index=0,
    )
    recorder.record_decision(
        candidates,
        TargetAction(second.class_id, Position(second.x, second.y), candidate_index=1),
        latency_seconds=0.001,
        baseline_candidate_index=0,
    )
    shadow = recorder.snapshot(
        PolicyRuntimeMode.ML_SHADOW,
        experience=SessionExperienceTotals(),
        parameter_overrides=(),
    ).shadow

    assert shadow is not None
    assert (shadow.agreements, shadow.disagreements) == (1, 1)
    assert shadow.agreement_rate == 0.5
    assert shadow.heuristic_candidate_index == 0
    assert shadow.policy_candidate_index == 1


def test_a_non_shadow_session_publishes_no_comparison_at_all() -> None:
    recorder = PolicyInsightRecorder()

    snapshot = recorder.snapshot(
        PolicyRuntimeMode.ML_ACTIVE,
        experience=SessionExperienceTotals(),
        parameter_overrides=(),
    )

    assert snapshot.shadow is None


def test_the_deterministic_baseline_choice_resolves_back_to_a_candidate_index() -> None:
    first = _mob(1, "Aibatt")
    second = _mob(2, "Burudeng")
    candidates = (_candidate(first, 0), _candidate(second, 1))

    index = baseline_candidate_index(
        candidates, TargetAction(second.class_id, Position(second.x, second.y))
    )

    assert index == 1
    assert baseline_candidate_index(candidates, None) is None
    assert baseline_candidate_index(candidates, WaitAction(0.1, "idle")) is None


def test_an_artifact_is_identified_by_its_provenance_document_digest(tmp_path: Path) -> None:
    document = tmp_path / ARTIFACT_DOCUMENT
    document.write_text(json.dumps({"schema_version": "test"}), encoding="utf-8")

    identity = digest_artifact_document(tmp_path)

    assert identity.is_loaded
    assert identity.filename == ARTIFACT_DOCUMENT
    assert len(identity.sha256) == 64
    assert digest_artifact_document(tmp_path / "missing").is_loaded is False


def test_an_unmeasured_session_reports_no_rate_rather_than_a_rate_of_zero() -> None:
    totals = SessionExperienceTotals()

    assert totals.kills_per_minute is None
    assert totals.navigation_seconds_per_kill is None
    assert totals.stall_rate is None


def test_measured_totals_report_farming_benchmarks_from_observed_time_only() -> None:
    totals = SessionExperienceTotals(
        verified_kills=4,
        elapsed_seconds=120.0,
        navigation_seconds=40.0,
        stall_seconds=12.0,
    )

    assert totals.kills_per_minute == 2.0
    assert totals.navigation_seconds_per_kill == 10.0
    assert totals.stall_rate == 0.1


def test_an_unmodulated_parameter_still_states_its_baseline_without_an_override() -> None:
    override = ParameterOverrideInsight(TacticalParameterName.REPLAN_INTERVAL_SECONDS, 20.0, 20.0)
    modulated = ParameterOverrideInsight(TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS, 3.0, 4.5)

    assert not override.is_overridden
    assert modulated.is_overridden
    assert TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS in POLICY_MODULATED_PARAMETERS
