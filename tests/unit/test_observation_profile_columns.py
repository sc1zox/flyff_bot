"""Proven player-stat fields reach the encoded decision with provenance (US-083 AC5)."""

from __future__ import annotations

import numpy as np

from flyff_bot.features.rl.models import (
    OBSERVATION_DIMENSION,
    NavMeshContext,
    ObjectiveState,
    ObservationSpace,
    OperationalState,
    PlayerKinematics,
    PlayerProfileObservation,
    PlayerVitals,
    RlObservation,
)

# The profile block is encoded last but one, immediately before the goal columns, so the
# tests locate it by decoding two observations that differ only in the profile.
LEVEL = 60.0
LEVEL_SCALE = 200.0


def _observation(profile: PlayerProfileObservation) -> RlObservation:
    return RlObservation(
        PlayerKinematics(0.0, 0.0, 0.0, 0.0),
        PlayerVitals(50.0, 50.0, 50.0),
        NavMeshContext(None, None, None),
        (),
        OperationalState(None, 0.0, 0, "farming"),
        ObjectiveState(),
        profile=profile,
    )


def test_an_absent_profile_encodes_as_missing_rather_than_zero() -> None:
    absent = ObservationSpace.encode(_observation(PlayerProfileObservation()))
    present = ObservationSpace.encode(
        _observation(PlayerProfileObservation(is_authoritative=True, level=0.0))
    )

    # A character at level zero and an install that cannot read the level must not encode
    # to the same vector; the paired missing indicator is what separates them.
    assert not np.array_equal(absent, present)
    assert absent.shape == (OBSERVATION_DIMENSION,)


def test_the_provenance_column_states_whether_the_read_was_authoritative() -> None:
    unproven = ObservationSpace.encode(_observation(PlayerProfileObservation()))
    proven = ObservationSpace.encode(_observation(PlayerProfileObservation(is_authoritative=True)))

    differing = np.flatnonzero(unproven != proven)
    assert differing.size == 1
    assert proven[differing[0]] == 1.0


def test_a_measured_level_is_scaled_into_range_and_marked_present() -> None:
    encoded = ObservationSpace.encode(
        _observation(PlayerProfileObservation(is_authoritative=True, level=LEVEL))
    )

    assert np.all(encoded >= -1.0) and np.all(encoded <= 1.0)
    assert float(LEVEL / LEVEL_SCALE) in set(encoded.tolist())


def test_a_disagreeing_target_identity_is_visible_in_the_vector() -> None:
    agreed = ObservationSpace.encode(
        _observation(PlayerProfileObservation(is_authoritative=True, target_identity_agreed=True))
    )
    disagreed = ObservationSpace.encode(
        _observation(PlayerProfileObservation(is_authoritative=True, target_identity_agreed=False))
    )
    unproven = ObservationSpace.encode(
        _observation(PlayerProfileObservation(is_authoritative=True))
    )

    # Three distinct states: agreed, disagreed, and never proven either way.
    assert not np.array_equal(agreed, disagreed)
    assert not np.array_equal(agreed, unproven)
    assert not np.array_equal(disagreed, unproven)


def test_an_out_of_range_statistic_saturates_instead_of_escaping_the_vector() -> None:
    encoded = ObservationSpace.encode(
        _observation(
            PlayerProfileObservation(is_authoritative=True, level=LEVEL_SCALE * 10.0, strength=1e9)
        )
    )

    assert np.all(encoded >= -1.0) and np.all(encoded <= 1.0)
