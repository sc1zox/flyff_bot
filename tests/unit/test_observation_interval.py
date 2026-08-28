"""Coherence rules for one tick's camera, GPS, world map and NavMesh samples (US-083 AC4)."""

from __future__ import annotations

from flyff_bot.features.automation.observation_interval import (
    DEFAULT_INTERVAL_MAX_SPAN_SECONDS,
    DEFAULT_LIVE_SAMPLE_MAX_AGE_SECONDS,
    IntervalRejection,
    ObservationSample,
    ObservationSource,
    evaluate_observation_interval,
)

NOW = 1_000.0


def _live(source: ObservationSource, age: float, world_id: int | None = None) -> ObservationSample:
    return ObservationSample(source, sampled_at_seconds=NOW - age, world_id=world_id)


def _static(source: ObservationSource, world_id: int | None = None) -> ObservationSample:
    return ObservationSample(source, world_id=world_id, is_live=False)


def test_fresh_aligned_samples_form_one_coherent_interval() -> None:
    samples = (
        _live(ObservationSource.CAMERA, 0.01),
        _live(ObservationSource.GPS, 0.02),
        _static(ObservationSource.NAVMESH),
        _static(ObservationSource.WORLD_MAP),
    )

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    assert interval.is_coherent
    assert interval.rejection is None
    assert interval.span_seconds is not None
    assert interval.span_seconds < DEFAULT_INTERVAL_MAX_SPAN_SECONDS


def test_a_stale_live_sample_is_rejected_rather_than_combined() -> None:
    samples = (
        _live(ObservationSource.CAMERA, DEFAULT_LIVE_SAMPLE_MAX_AGE_SECONDS + 0.1),
        _live(ObservationSource.GPS, 0.01),
    )

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    assert not interval.is_coherent
    assert interval.rejection is IntervalRejection.SOURCE_STALE
    assert interval.rejected_sources == (ObservationSource.CAMERA,)


def test_two_fresh_samples_far_apart_are_not_one_observation() -> None:
    # Each read is inside the per-source age limit; the pair still spans two instants.
    span = DEFAULT_INTERVAL_MAX_SPAN_SECONDS + 0.05
    samples = (
        _live(ObservationSource.CAMERA, 0.01),
        _live(ObservationSource.GPS, 0.01 + span),
    )

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    assert interval.rejection is IntervalRejection.INTERVAL_INCOHERENT
    assert interval.span_seconds == span


def test_a_cross_world_sample_set_is_refused() -> None:
    samples = (
        _live(ObservationSource.CAMERA, 0.01, world_id=1),
        _live(ObservationSource.GPS, 0.01, world_id=1),
        _static(ObservationSource.NAVMESH, world_id=7),
    )

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    assert interval.rejection is IntervalRejection.CROSS_WORLD
    # No single world can be claimed for a set that disagrees about which one it is.
    assert interval.world_id is None


def test_a_source_that_does_not_know_its_world_is_not_a_conflict() -> None:
    samples = (
        _live(ObservationSource.CAMERA, 0.01, world_id=1),
        _static(ObservationSource.NAVMESH),
    )

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    assert interval.is_coherent
    assert interval.world_id == 1


def test_a_missing_source_outranks_every_other_fault() -> None:
    samples = (
        ObservationSample(ObservationSource.CAMERA, sampled_at_seconds=None, is_available=False),
        _live(ObservationSource.GPS, DEFAULT_LIVE_SAMPLE_MAX_AGE_SECONDS + 5.0),
    )

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    assert interval.rejection is IntervalRejection.SOURCE_MISSING
    assert interval.rejected_sources == (ObservationSource.CAMERA,)


def test_a_sample_from_the_future_reports_a_clock_discontinuity() -> None:
    samples = (
        ObservationSample(ObservationSource.CAMERA, sampled_at_seconds=NOW + 1.0),
        _live(ObservationSource.GPS, 0.01),
    )

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    assert interval.rejection is IntervalRejection.CLOCK_DISCONTINUITY


def test_a_static_source_is_never_judged_stale() -> None:
    # A baked mesh has no age to decay; ageing it would reject every long session.
    samples = (
        _live(ObservationSource.CAMERA, 0.01),
        ObservationSample(
            ObservationSource.NAVMESH,
            sampled_at_seconds=NOW - 9_999.0,
            is_live=False,
        ),
    )

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    assert interval.is_coherent


def test_measured_ages_are_reported_per_source() -> None:
    samples = (_live(ObservationSource.CAMERA, 0.05), _live(ObservationSource.GPS, 0.01))

    interval = evaluate_observation_interval(samples, at_seconds=NOW)

    camera_age = interval.age_of(ObservationSource.CAMERA)
    assert camera_age is not None
    assert abs(camera_age - 0.05) < 1e-9
    assert interval.age_of(ObservationSource.WORLD_MAP) is None
