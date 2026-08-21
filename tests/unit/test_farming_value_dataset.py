"""Unit tests for Parquet ingestion, trajectory correlation, and label extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from farming_value_fixtures import DEFAULT_CYCLES_PER_SESSION, write_dataset

from flyff_bot.features.ml.dataset import (
    DatasetError,
    DatasetErrorCode,
    FollowupValueDefinition,
    SplitStrategy,
    build_samples,
    load_kill_cycles,
    load_navigation_episodes,
    load_target_decisions,
    split_samples,
)
from flyff_bot.features.ml.features import FEATURE_NAMES
from flyff_bot.features.telemetry.exporter import (
    KILL_CYCLES_FILE,
    NAVIGATION_TRAJECTORIES_FILE,
    TARGET_DECISIONS_FILE,
)


def test_every_exported_table_is_read_back_into_typed_records(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    decisions = load_target_decisions(dataset / TARGET_DECISIONS_FILE)
    episodes = load_navigation_episodes(dataset / NAVIGATION_TRAJECTORIES_FILE)
    cycles = load_kill_cycles(dataset / KILL_CYCLES_FILE)

    assert len(decisions) == 2 * DEFAULT_CYCLES_PER_SESSION
    assert len(episodes) == 2 * DEFAULT_CYCLES_PER_SESSION
    assert len(cycles) == 2 * DEFAULT_CYCLES_PER_SESSION
    assert all(decision.selected_candidate is not None for decision in decisions)
    assert all(len(episode.planned_route) == 3 for episode in episodes)
    assert all(cycle.target_decision_timestamp_ns is not None for cycle in cycles)


def test_each_sample_links_one_executed_decision_to_its_observed_kill_cycle(
    tmp_path: Path,
) -> None:
    dataset = write_dataset(tmp_path)

    samples = build_samples(dataset)

    cycles = load_kill_cycles(dataset / KILL_CYCLES_FILE)
    assert len(samples) == len(cycles)
    assert len({(sample.session_id, sample.decision_timestamp_ns) for sample in samples}) == len(
        samples
    )


def test_unselected_candidates_stay_counterfactually_unknown(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    samples = build_samples(dataset)

    decisions = load_target_decisions(dataset / TARGET_DECISIONS_FILE)
    evaluated_candidates = sum(len(decision.candidates) for decision in decisions)
    assert evaluated_candidates > len(samples)
    assert all(sample.unselected_candidate_count == 2 for sample in samples)


def test_features_follow_the_exported_schema_and_derive_corridor_geometry(
    tmp_path: Path,
) -> None:
    dataset = write_dataset(tmp_path)

    samples = build_samples(dataset)

    sample = samples[0]
    assert tuple(sample.features) == FEATURE_NAMES
    assert sample.features["corridor_waypoint_count"] == 3.0
    assert sample.features["corridor_length"] is not None
    assert sample.features["corridor_detour_ratio"] is not None
    assert sample.features["visible_mob_count"] == 3.0
    # Three candidates were evaluated; the third is locked out and the nearest two are
    # inside the local cluster radius, so only those two count as targetable neighbours.
    assert sample.features["nearby_targetable_mob_count"] == 2.0
    assert samples[5].features["nearby_targetable_mob_count"] == 0.0


def test_unobserved_history_is_null_instead_of_a_fabricated_zero(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    samples = build_samples(dataset)

    first = samples[0]
    assert first.features["recent_stuck_rate"] is None
    assert samples[3].features["recent_stuck_rate"] is not None


def test_labels_come_from_the_observed_cycle_decomposition(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    samples = build_samples(dataset)

    cycles = {
        (cycle.session_id, cycle.target_decision_timestamp_ns): cycle
        for cycle in load_kill_cycles(dataset / KILL_CYCLES_FILE)
    }
    for sample in samples:
        cycle = cycles[(sample.session_id, sample.decision_timestamp_ns)]
        assert sample.labels.actual_travel_time == cycle.navigation_seconds
        assert sample.labels.actual_kill_time == cycle.combat_seconds
        assert sample.labels.actual_stuck_time == cycle.stall_seconds
        assert sample.labels.kill_to_kill_time == pytest.approx(cycle.total_seconds)


def test_recovery_time_is_unknown_when_no_stall_was_ever_observed(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    samples = build_samples(dataset)

    without_stall = [sample for sample in samples if not sample.labels.stuck_occurred]
    with_stall = [sample for sample in samples if sample.labels.stuck_occurred]
    assert without_stall and with_stall
    assert all(sample.labels.actual_recovery_time is None for sample in without_stall)
    assert all(sample.labels.actual_recovery_time is not None for sample in with_stall)


def test_followup_windows_are_censored_at_the_end_of_a_session(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    samples = build_samples(dataset)

    per_session = [sample for sample in samples if sample.session_id == "session-a"]
    assert per_session[-1].labels.kills_next_10s is None
    assert per_session[-1].labels.targetable_mobs_after_kill is None
    observed = [
        sample.labels.kills_next_10s
        for sample in per_session
        if sample.labels.kills_next_10s is not None
    ]
    assert set(observed) == {0.0, 1.0}


def test_followup_definition_selects_the_configured_observable(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path)

    labels = build_samples(dataset)[0].labels

    assert labels.followup_value(FollowupValueDefinition.KILLS_NEXT_5S) == labels.kills_next_5s
    assert labels.followup_value(FollowupValueDefinition.KILLS_NEXT_10S) == labels.kills_next_10s
    assert (
        labels.followup_value(FollowupValueDefinition.TARGETABLE_MOBS_AFTER_KILL)
        == labels.targetable_mobs_after_kill
    )


def test_splitting_multiple_sessions_never_leaks_a_session_across_the_boundary(
    tmp_path: Path,
) -> None:
    dataset = write_dataset(tmp_path)

    split = split_samples(build_samples(dataset))

    train_sessions = {sample.session_id for sample in split.train}
    holdout_sessions = {sample.session_id for sample in split.holdout}
    assert split.strategy is SplitStrategy.SESSION
    assert train_sessions and holdout_sessions
    assert not train_sessions & holdout_sessions
    assert split.session_ids == ("session-a", "session-b")


def test_a_single_session_is_split_into_contiguous_temporal_blocks(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path, session_ids=("session-only",))

    split = split_samples(build_samples(dataset), holdout_fraction=0.25)

    assert split.strategy is SplitStrategy.TEMPORAL
    assert split.train and split.holdout
    assert max(sample.decision_timestamp_ns for sample in split.train) < min(
        sample.decision_timestamp_ns for sample in split.holdout
    )


def test_an_out_of_range_holdout_fraction_is_rejected(tmp_path: Path) -> None:
    samples = build_samples(write_dataset(tmp_path))

    with pytest.raises(ValueError, match="holdout_fraction"):
        split_samples(samples, holdout_fraction=1.0)


def test_a_missing_table_reports_which_file_is_absent(tmp_path: Path) -> None:
    with pytest.raises(DatasetError) as error:
        build_samples(tmp_path / "absent")

    assert error.value.code is DatasetErrorCode.TABLE_MISSING
    assert TARGET_DECISIONS_FILE in error.value.detail


def test_a_dataset_without_recorded_sessions_reports_no_samples(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path, session_ids=())

    with pytest.raises(DatasetError) as error:
        build_samples(dataset)

    assert error.value.code is DatasetErrorCode.NO_SAMPLES
