from test_rl_state_space import observation

from flyff_bot.features.rl.actions import TacticalAction
from flyff_bot.features.rl.masking import build_action_mask


def _masked(candidate_locked_out: bool) -> tuple[bool, ...]:
    state = observation()
    candidate = state.candidates[0]
    masked_candidate = candidate.__class__(
        candidate.candidate_index,
        candidate.class_id,
        candidate.confidence,
        candidate.position_x,
        candidate.position_y,
        candidate.position_z,
        candidate.path_distance,
        candidate.relative_elevation,
        candidate.is_dead,
        candidate_locked_out,
        candidate.is_unreachable,
    )
    state = state.__class__(
        state.kinematics,
        state.vitals,
        state.navmesh,
        (masked_candidate,),
        state.operational,
        state.objective,
    )
    return build_action_mask(
        state, patrol_center=(state.kinematics.position_x,) * 3, patrol_radius=100.0
    )


def test_mask_disables_locked_targets_and_enables_wait() -> None:
    mask = _masked(True)
    assert mask[TacticalAction.SELECT_TARGET] is False
    assert mask[TacticalAction.WAIT] is True


def test_mask_allows_valid_target() -> None:
    mask = _masked(False)
    assert mask[TacticalAction.SELECT_TARGET] is True
