"""A dependent decision refuses rather than inventing a value (US-083 AC12)."""

from __future__ import annotations

import pytest

from flyff_bot.features.automation.models import (
    InventoryEntry,
    Position,
    WorldState,
)
from flyff_bot.features.automation.observation_interval import (
    IntervalRejection,
    ObservationInterval,
    ObservationSample,
    ObservationSource,
    evaluate_observation_interval,
)
from flyff_bot.features.policy.hierarchical import HierarchicalObjective
from flyff_bot.features.policy.hierarchical_onnx import (
    INCOHERENT_OBSERVATION_INTERVAL,
    LIVE_OBSERVATION_UNAVAILABLE,
    live_observation,
)
from flyff_bot.features.policy.models import LiveObservationState, PolicyContext
from flyff_bot.features.rl.models import NavMeshContext, PlayerKinematics

NOW = 100.0


def _live_state() -> LiveObservationState:
    return LiveObservationState(
        PlayerKinematics(0.0, 0.0, 0.0, 0.0),
        NavMeshContext(None, None, None),
    )


def _state(interval: ObservationInterval) -> WorldState:
    return WorldState(
        observed_at_seconds=NOW,
        position=Position(0, 0),
        nearby_mob_count=0,
        inventory=(InventoryEntry("penya", 0),),
        progress_marker=0,
        observation_interval=interval,
    )


def _coherent() -> ObservationInterval:
    return evaluate_observation_interval(
        (
            ObservationSample(ObservationSource.CAMERA, sampled_at_seconds=NOW),
            ObservationSample(ObservationSource.GPS, sampled_at_seconds=NOW),
        ),
        at_seconds=NOW,
    )


def _stale() -> ObservationInterval:
    return evaluate_observation_interval(
        (
            ObservationSample(ObservationSource.CAMERA, sampled_at_seconds=NOW - 10.0),
            ObservationSample(ObservationSource.GPS, sampled_at_seconds=NOW),
        ),
        at_seconds=NOW,
    )


def test_a_coherent_interval_still_builds_a_decision() -> None:
    context = PolicyContext((), frozenset(), (), live_state=_live_state())

    observation = live_observation(_state(_coherent()), context, HierarchicalObjective())

    assert observation.kinematics.position_x == 0.0


def test_an_incoherent_interval_refuses_and_names_the_reason() -> None:
    # The alternative is serving the model measured-looking numbers that no single moment
    # produced, which is indistinguishable from a real observation once encoded.
    context = PolicyContext((), frozenset(), (), live_state=_live_state())
    interval = _stale()
    assert interval.rejection is IntervalRejection.SOURCE_STALE

    with pytest.raises(ValueError) as error:
        live_observation(_state(interval), context, HierarchicalObjective())

    message = str(error.value)
    assert message.startswith(INCOHERENT_OBSERVATION_INTERVAL)
    # The diagnostic is stable and names which fault refused the decision.
    assert IntervalRejection.SOURCE_STALE.value in message


def test_absent_live_state_still_refuses_with_its_own_diagnostic() -> None:
    # Two different faults must stay distinguishable: no live state at all is not the same
    # finding as live state that could not be fused.
    context = PolicyContext((), frozenset(), (), live_state=None)

    with pytest.raises(ValueError, match=LIVE_OBSERVATION_UNAVAILABLE):
        live_observation(_state(_coherent()), context, HierarchicalObjective())


def test_recovery_requires_a_fresh_coherent_sample_set_not_merely_a_later_tick() -> None:
    context = PolicyContext((), frozenset(), (), live_state=_live_state())

    with pytest.raises(ValueError):
        live_observation(_state(_stale()), context, HierarchicalObjective())

    # A later tick that is still stale keeps refusing; only coherent samples resume.
    with pytest.raises(ValueError):
        live_observation(_state(_stale()), context, HierarchicalObjective())

    recovered = live_observation(_state(_coherent()), context, HierarchicalObjective())
    assert recovered is not None


def test_a_refusal_fabricates_no_partial_observation() -> None:
    # Nothing is returned on refusal, so there is no half-built vector for a caller to use.
    context = PolicyContext((), frozenset(), (), live_state=_live_state())

    with pytest.raises(ValueError):
        live_observation(_state(_stale()), context, HierarchicalObjective())
