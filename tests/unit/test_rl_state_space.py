from __future__ import annotations

import numpy as np

from flyff_bot.features.rl.models import (
    CandidateObservation,
    NavMeshContext,
    ObjectiveState,
    OperationalState,
    PlayerKinematics,
    PlayerVitals,
    RlObservation,
)
from flyff_bot.features.rl.state_space import OBSERVATION_DIMENSION, ObservationSpace


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
