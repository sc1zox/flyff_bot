from __future__ import annotations

import pytest
from test_rl_state_space import observation

from flyff_bot.features.policy.action_payloads import TacticalAction
from flyff_bot.features.rl.actions import ParameterizedAction, TacticalActionMask
from flyff_bot.features.rl.environment import TacticalRlEnvironment
from flyff_bot.features.rl.models import Transition


@pytest.fixture
def minimal_transition() -> Transition:
    state = observation()
    mask = TacticalActionMask((False, False, False, False, False, False, True))
    action = ParameterizedAction(TacticalAction.WAIT, wait_seconds=0.1, wait_reason="idle")
    return Transition(state, action, 1.25, state, mask, False, mask)


def test_environment_rejects_masked_action(minimal_transition: Transition) -> None:
    environment = TacticalRlEnvironment([minimal_transition])
    with pytest.raises(ValueError, match=r"Masked tactical action selected\."):
        environment.step(0)


def test_environment_returns_standard_step_tuple(minimal_transition: Transition) -> None:
    environment = TacticalRlEnvironment([minimal_transition])
    observation, reward, terminated, truncated, info = environment.step(6)
    assert reward == minimal_transition.reward
    assert observation is minimal_transition.next_observation
    assert (terminated, truncated) == (False, True)
    assert info["action_mask"] == minimal_transition.action_mask.actions
