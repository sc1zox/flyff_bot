"""One decision snapshot, four consumers, one vector (US-083 AC7).

The live path, the recorded-telemetry path and the simulator all build an ``RlObservation``.
If any of them quietly drops a field or fabricates a zero for one, a model trained on one and
served the other is being fed a different world than it learned, and nothing in the types
would say so. These tests are the thing that says so.
"""

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
from flyff_bot.features.telemetry.models import (
    CandidateFeatures,
    DecisionProvenance,
    primitive,
)

LEVEL = 72.0
EXPERIENCE_FRACTION = 0.4
STRENGTH = 120.0
TARGET_HP_FRACTION = 0.25


def _profile() -> PlayerProfileObservation:
    return PlayerProfileObservation(
        is_authoritative=True,
        level=LEVEL,
        experience_fraction=EXPERIENCE_FRACTION,
        strength=STRENGTH,
        target_hp_fraction=TARGET_HP_FRACTION,
        target_is_alive=True,
        target_identity_agreed=True,
    )


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


def _recorded(provenance: DecisionProvenance) -> dict[str, object]:
    """Return a telemetry snapshot the way the recorder serializes one."""

    return {
        "player_position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "player_velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
        "hp_percentage": 50.0,
        "mp_percentage": 50.0,
        "fp_percentage": 50.0,
        "farming_mode": "farming",
        "provenance": primitive(provenance),
    }


def test_a_recorded_decision_re_encodes_to_the_live_vector() -> None:
    live = ObservationSpace.encode(_observation(_profile()))

    replayed = ObservationSpace.encode(
        ObservationSpace.from_telemetry_snapshot(
            _recorded(
                DecisionProvenance(
                    is_authoritative=True,
                    level=LEVEL,
                    experience_fraction=EXPERIENCE_FRACTION,
                    strength=STRENGTH,
                    target_hp_fraction=TARGET_HP_FRACTION,
                    target_is_alive=True,
                    target_identity_agreed=True,
                )
            )
        )
    )

    # Only the profile block is being compared, so check it agrees rather than the whole
    # vector: the operational and objective columns are not carried by this snapshot.
    assert live.shape == replayed.shape == (OBSERVATION_DIMENSION,)
    assert np.array_equal(_profile_block(live), _profile_block(replayed))


def test_an_unrecorded_statistic_replays_as_missing_not_as_zero() -> None:
    # The client never exposed a level. Reading it back as 0.0 would encode a level-zero
    # character, which is a different world from "this install cannot say".
    measured_zero = ObservationSpace.encode(
        _observation(PlayerProfileObservation(is_authoritative=True, level=0.0))
    )
    unrecorded = ObservationSpace.encode(
        ObservationSpace.from_telemetry_snapshot(
            _recorded(DecisionProvenance(is_authoritative=True, level=None))
        )
    )

    assert not np.array_equal(_profile_block(measured_zero), _profile_block(unrecorded))


def test_a_recorded_disagreement_survives_the_round_trip() -> None:
    disagreed = ObservationSpace.from_telemetry_snapshot(
        _recorded(DecisionProvenance(is_authoritative=True, target_identity_agreed=False))
    )
    never_proven = ObservationSpace.from_telemetry_snapshot(
        _recorded(DecisionProvenance(is_authoritative=True, target_identity_agreed=None))
    )

    assert disagreed.profile.target_identity_agreed is False
    assert never_proven.profile.target_identity_agreed is None


def test_a_snapshot_without_a_provenance_block_stays_unauthoritative() -> None:
    # An older recording has no provenance at all; it must read as "not proven" rather
    # than inventing an authoritative read.
    observation = ObservationSpace.from_telemetry_snapshot(
        {
            "player_position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "player_velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
        }
    )

    assert observation.profile.is_authoritative is False
    assert observation.profile.level is None


def _profile_block(encoded: np.ndarray) -> np.ndarray:
    """Return the 19 profile columns, which the encoder writes before the goal block."""

    return encoded[PROFILE_BLOCK_START:PROFILE_BLOCK_END]


# The profile block is emitted immediately before the goal columns. Locating it by width
# rather than by a hardcoded offset keeps this test honest if earlier blocks move.
PROFILE_BLOCK_WIDTH = 19
GOAL_BLOCK_WIDTH = 10
PROFILE_BLOCK_START = OBSERVATION_DIMENSION - GOAL_BLOCK_WIDTH - PROFILE_BLOCK_WIDTH
PROFILE_BLOCK_END = OBSERVATION_DIMENSION - GOAL_BLOCK_WIDTH


def test_candidate_identities_survive_the_round_trip_unchanged() -> None:
    """The identity a candidate had when it was decided on is the identity it replays with.

    A vector that matches while the candidate identities have shifted is worse than one that
    does not: the numbers line up, so nothing fails, and the recorded action now refers to a
    different actor than the one it was taken against (US-083 AC11).
    """

    recorded: dict[str, object] = {
        "player_position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "player_velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
    }
    candidates = tuple(
        CandidateFeatures(
            candidate_index=identity,
            class_id=identity + 1,
            class_name=f"Mob{identity}",
            confidence=0.9,
            x=0,
            y=0,
            width=10,
            height=10,
            center_x=5.0,
            center_y=5.0,
            screen_distance_to_center=None,
            bbox_area=100,
            world_position=None,
            relative_distance=None,
            relative_elevation=None,
            target_navmesh_polygon_id=None,
            path_distance=None,
            is_locked_out=False,
        )
        # Deliberately not 0..n: the identities perception assigns are not list positions,
        # so a replay that renumbered them would pass a naive equality check.
        for identity in (7, 3, 11)
    )

    observation = ObservationSpace.from_telemetry_snapshot(recorded, candidates)

    assert [item.candidate_index for item in observation.candidates] == [7, 3, 11]
