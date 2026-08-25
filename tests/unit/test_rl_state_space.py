from __future__ import annotations

import numpy as np

from flyff_bot.features.rl.actions import TacticalAction
from flyff_bot.features.rl.masking import build_action_mask
from flyff_bot.features.rl.models import (
    OBSERVATION_DIMENSION,
    CandidateObservation,
    NavMeshContext,
    ObjectiveState,
    ObservationSpace,
    OperationalState,
    PlayerKinematics,
    PlayerVitals,
    ReadinessObservation,
    RlObservation,
)


def observation() -> RlObservation:
    return RlObservation(
        PlayerKinematics(1.0, 2.0, 3.0, 1.0),
        PlayerVitals(80.0, 70.0, 60.0, (10.0, 20.0)),
        NavMeshContext("7", 15.0, 120.0),
        (
            CandidateObservation(
                0,
                3,
                0.8,
                4.0,
                5.0,
                6.0,
                12.0,
                2.0,
                is_locked_out=False,
            ),
        ),
        OperationalState(None, 30.0, 1, "farming"),
        ObjectiveState("quest", ((5, 2.0),), 40.0),
    )


def test_observation_is_fixed_width_and_bounded() -> None:
    encoded = ObservationSpace.encode(observation())
    assert isinstance(encoded, np.ndarray)
    assert encoded.shape == (OBSERVATION_DIMENSION,)
    assert np.all(np.isfinite(encoded))
    assert np.all(encoded >= -1.0)
    assert np.all(encoded <= 1.0)


def test_action_blocked_readiness_masks_every_action_except_wait() -> None:
    blocked = RlObservation(
        observation().kinematics,
        observation().vitals,
        observation().navmesh,
        observation().candidates,
        observation().operational,
        observation().objective,
        ReadinessObservation(
            state="blocked",
            primary_reason="stale",
            failed_source_codes=("gps",),
            sample_ages_seconds=(("gps", 1.25),),
            action_blocked=True,
        ),
    )

    mask = build_action_mask(blocked, patrol_center=(1.0, 2.0, 3.0), patrol_radius=10.0)

    assert mask == tuple(index == int(TacticalAction.WAIT) for index in range(len(TacticalAction)))
