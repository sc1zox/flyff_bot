"""Unit tests for the reactive combat state machine and guarded input boundary."""

from __future__ import annotations

import pytest

from flyff_bot.features.automation.combat_execution import CombatInputDispatcher
from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_1,
    VIRTUAL_KEY_C,
    VIRTUAL_KEY_F1,
    CombatConfig,
    CombatController,
    CombatInputKind,
    CombatMode,
    EngagementBreakReason,
    KeyBinding,
)
from flyff_bot.features.automation.models import (
    Position,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)

WINDOW_HANDLE = 42
VALID_TARGET = SelectedTarget(TargetState.VALID, "Mushpang", 100)
NO_TARGET = SelectedTarget(TargetState.NONE, None, 0)
DEFAULT_VIEWPORT = Viewport(200, 100)


def _mob(
    *,
    class_name: str = "Mushpang",
    x: int = 10,
    y: int = 20,
    confidence: float = 0.9,
) -> VisibleMob:
    return VisibleMob(1, class_name, confidence, x, y, 20, 10)


def _state(
    *,
    time: float = 0.0,
    target: SelectedTarget = NO_TARGET,
    mobs: tuple[VisibleMob, ...] = (),
    viewport: Viewport = DEFAULT_VIEWPORT,
    monster_kill_count: int = 0,
) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=len(mobs),
        inventory=(),
        progress_marker=0,
        selected_target=target,
        visible_mobs=mobs,
        viewport=viewport,
        monster_kill_count=monster_kill_count,
    )


def test_selects_nearest_whitelisted_mob_and_clicks_its_center() -> None:
    controller = CombatController(CombatConfig(allowed_class_names=frozenset({"Mushpang"})))
    nearest = _mob(x=80, y=40)
    ignored = _mob(class_name="Aibatt", x=95, y=45)

    decision = controller.step(_state(mobs=(ignored, nearest)))

    assert decision.mode is CombatMode.TARGETING
    assert decision.input_kind is CombatInputKind.CLICK
    assert decision.position == Position(90, 45)


def test_progresses_from_targeting_through_fighting_until_target_dies() -> None:
    controller = CombatController()

    assert controller.step(_state(mobs=(_mob(),))).mode is CombatMode.TARGETING
    attack = controller.step(_state(time=1.0, target=VALID_TARGET))
    assert attack.mode is CombatMode.FIGHTING
    assert attack.input_kind is CombatInputKind.KEY
    damaged = controller.step(
        _state(time=1.5, target=SelectedTarget(TargetState.VALID, "Mushpang", 50))
    )
    assert damaged.progress_observed
    assert controller.step(
        _state(time=2.0, target=SelectedTarget(TargetState.NONE, None, 0))
    ).mode is (CombatMode.TARGET_DEAD)
    assert controller.step(_state(time=3.0)).mode is CombatMode.IDLE


def test_rotation_honors_cooldowns_and_reports_hp_progress() -> None:
    controller = CombatController(
        CombatConfig(rotation=(KeyBinding(VIRTUAL_KEY_1, 2.0), KeyBinding(VIRTUAL_KEY_C, 0.0)))
    )
    controller.step(_state(mobs=(_mob(),)))

    first = controller.step(_state(time=1.0, target=VALID_TARGET))
    waiting = controller.step(
        _state(time=2.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 90))
    )
    second = controller.step(
        _state(time=3.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 90))
    )

    assert first.virtual_key == VIRTUAL_KEY_1
    assert waiting.input_kind is None
    assert waiting.progress_observed
    assert second.virtual_key == VIRTUAL_KEY_C


def test_rejects_unverified_target_and_empty_candidates() -> None:
    controller = CombatController(CombatConfig(allowed_class_names=frozenset({"Mushpang"})))

    assert controller.step(_state(mobs=(_mob(class_name="Aibatt"),))).mode is CombatMode.IDLE
    controller.step(_state(mobs=(_mob(),)))
    assert (
        controller.step(_state(target=SelectedTarget(TargetState.WRONG, None, 100))).mode
        is CombatMode.TARGETING
    )
    assert (
        controller.step(_state(time=1.0, target=SelectedTarget(TargetState.WRONG, None, 100))).mode
        is CombatMode.IDLE
    )


def test_undamaged_target_loss_is_not_reported_as_a_kill() -> None:
    controller = CombatController()
    controller.step(_state(mobs=(_mob(),)))
    assert controller.step(_state(time=1.0, target=VALID_TARGET)).mode is CombatMode.FIGHTING

    lost = controller.step(_state(time=1.5, target=NO_TARGET))

    assert lost.mode is CombatMode.TARGET_LOST
    assert not lost.damage_dealt


def test_kill_count_increment_confirms_death_without_hp_evidence() -> None:
    controller = CombatController(CombatConfig(kill_verification_enabled=True))

    controller.step(_state(mobs=(_mob(),), monster_kill_count=5))
    attack = controller.step(_state(time=1.0, target=VALID_TARGET, monster_kill_count=5))
    assert attack.mode is CombatMode.FIGHTING

    confirmed = controller.step(_state(time=1.5, target=VALID_TARGET, monster_kill_count=6))

    assert confirmed.mode is CombatMode.TARGET_DEAD
    assert confirmed.damage_dealt


def test_kill_count_increment_confirms_death() -> None:
    """An incrementing kill count during fight confirms death."""

    controller = CombatController(CombatConfig(kill_verification_enabled=True))

    controller.step(_state(mobs=(_mob(),), monster_kill_count=47))
    attack = controller.step(_state(time=1.0, target=VALID_TARGET, monster_kill_count=47))
    assert attack.mode is CombatMode.FIGHTING

    confirmed = controller.step(_state(time=2.0, target=VALID_TARGET, monster_kill_count=48))
    assert confirmed.mode is CombatMode.TARGET_DEAD


def test_kill_count_rise_beyond_one_still_confirms_death() -> None:
    """Two kills landing between ticks still confirm death."""

    controller = CombatController(CombatConfig(kill_verification_enabled=True))

    controller.step(_state(mobs=(_mob(),), monster_kill_count=5))
    attack = controller.step(_state(time=1.0, target=VALID_TARGET, monster_kill_count=5))
    assert attack.mode is CombatMode.FIGHTING

    confirmed = controller.step(_state(time=1.5, target=VALID_TARGET, monster_kill_count=7))

    assert confirmed.mode is CombatMode.TARGET_DEAD
    assert confirmed.damage_dealt


def test_repeated_identical_reading_across_ticks_does_not_confirm_death() -> None:
    """When kill count is unchanged across ticks, fighting continues."""

    controller = CombatController(CombatConfig(kill_verification_enabled=True))

    controller.step(_state(mobs=(_mob(),), monster_kill_count=5))
    for elapsed in (1.0, 1.1, 1.2, 1.3):
        decision = controller.step(_state(time=elapsed, target=VALID_TARGET, monster_kill_count=5))
        assert decision.mode is CombatMode.FIGHTING

    confirmed = controller.step(_state(time=1.4, target=VALID_TARGET, monster_kill_count=6))

    assert confirmed.mode is CombatMode.TARGET_DEAD


def test_new_engagement_attacks_immediately_despite_previous_cooldown() -> None:
    controller = CombatController(CombatConfig(rotation=(KeyBinding(VIRTUAL_KEY_1, 100.0),)))

    controller.step(_state(mobs=(_mob(),)))
    first_attack = controller.step(_state(time=1.0, target=VALID_TARGET))
    assert first_attack.virtual_key == VIRTUAL_KEY_1

    damaged = controller.step(
        _state(time=1.1, target=SelectedTarget(TargetState.VALID, "Mushpang", 50))
    )
    assert damaged.progress_observed
    dead = controller.step(_state(time=1.2, target=SelectedTarget(TargetState.NONE, None, 0)))
    assert dead.mode is CombatMode.TARGET_DEAD
    assert controller.step(_state(time=1.3)).mode is CombatMode.IDLE

    # A different mob, far enough away that the BUG-010 corpse lockout does not cover it.
    controller.step(_state(time=1.4, mobs=(_mob(x=120, y=60),)))
    new_attack = controller.step(_state(time=1.5, target=VALID_TARGET))

    assert new_attack.mode is CombatMode.FIGHTING
    assert new_attack.input_kind is CombatInputKind.KEY
    assert new_attack.virtual_key == VIRTUAL_KEY_1


def test_failed_acquisition_locks_out_the_clicked_location_instead_of_reclicking() -> None:
    """BUG-010: an unverified click must not be repeated on the very next tick."""

    controller = CombatController()
    mob = _mob(x=80, y=40)

    assert controller.step(_state(mobs=(mob,))).mode is CombatMode.TARGETING
    timed_out = controller.step(_state(time=1.0, mobs=(mob,)))

    assert timed_out.mode is CombatMode.IDLE
    assert timed_out.break_reason is EngagementBreakReason.ACQUISITION_TIMEOUT
    assert controller.step(_state(time=1.1, mobs=(mob,))).input_kind is None
    assert controller.step(_state(time=1.9, mobs=(mob,))).input_kind is None
    assert controller.step(_state(time=2.1, mobs=(mob,))).input_kind is CombatInputKind.CLICK


def test_lockout_defaults_are_one_second_and_fifteen_pixels() -> None:
    controller = CombatController()
    locked = _mob(x=80, y=40)
    neighbor = _mob(x=105, y=55)  # 25 pixels from the corpse center.

    controller.step(_state(mobs=(locked,)))
    controller.step(_state(time=1.0, target=VALID_TARGET, mobs=(locked,)))
    damaged = controller.step(
        _state(
            time=1.5,
            target=SelectedTarget(TargetState.VALID, "Mushpang", 50),
            mobs=(locked,),
        )
    )
    assert damaged.progress_observed
    confirmed = controller.step(_state(time=2.0, target=NO_TARGET, mobs=(locked,)))
    assert confirmed.mode is CombatMode.TARGET_DEAD

    assert controller.step(_state(time=2.1, mobs=(locked,))).mode is CombatMode.IDLE
    reselected = controller.step(_state(time=3.1, mobs=(locked, neighbor)))

    assert reselected.mode is CombatMode.TARGETING
    assert reselected.position == Position(90, 45)


def test_live_neighbor_outside_lockout_radius_is_immediately_eligible() -> None:
    controller = CombatController()
    locked = _mob(x=80, y=40)
    live_neighbor = _mob(x=120, y=60)

    controller.step(_state(mobs=(locked,)))
    controller.step(_state(time=1.0, target=VALID_TARGET, mobs=(locked,)))
    controller.step(
        _state(
            time=1.5,
            target=SelectedTarget(TargetState.VALID, "Mushpang", 50),
            mobs=(locked,),
        )
    )
    confirmed = controller.step(_state(time=2.0, target=NO_TARGET, mobs=(locked,)))
    assert confirmed.mode is CombatMode.TARGET_DEAD
    assert controller.step(_state(time=2.1, mobs=(live_neighbor,))).mode is CombatMode.IDLE
    candidate = controller.step(_state(time=3.1, mobs=(live_neighbor,)))

    assert candidate.mode is CombatMode.TARGETING
    assert candidate.position == Position(130, 65)


def test_confirmed_kill_locks_out_the_corpse_location() -> None:
    """BUG-010: a corpse stays detected for seconds and must not be clicked again."""

    controller = CombatController()
    mob = _mob(x=80, y=40)
    controller.step(_state(mobs=(mob,)))
    controller.step(_state(time=1.0, target=VALID_TARGET, mobs=(mob,)))
    controller.step(_state(time=1.5, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)))
    dead = controller.step(_state(time=2.0, target=NO_TARGET, mobs=(mob,)))
    assert dead.mode is CombatMode.TARGET_DEAD

    assert controller.step(_state(time=2.1, mobs=(mob,))).mode is CombatMode.IDLE
    assert controller.step(_state(time=2.2, mobs=(mob,))).input_kind is None


def test_stuck_engagement_breaks_after_the_configured_timeout() -> None:
    """BUG-010: a fight without HP progress must abort instead of attacking forever."""

    controller = CombatController()
    mob = _mob(x=80, y=40)
    controller.step(_state(mobs=(mob,)))
    assert controller.step(_state(time=1.0, target=VALID_TARGET)).mode is CombatMode.FIGHTING

    assert controller.step(_state(time=10.9, target=VALID_TARGET)).mode is CombatMode.FIGHTING
    broken = controller.step(_state(time=11.1, target=VALID_TARGET))

    assert broken.mode is CombatMode.IDLE
    assert broken.break_reason is EngagementBreakReason.ENGAGEMENT_TIMEOUT
    assert controller.step(_state(time=11.2, mobs=(mob,))).input_kind is None


def test_observed_damage_extends_the_stuck_engagement_timeout() -> None:
    controller = CombatController()
    controller.step(_state(mobs=(_mob(),)))
    controller.step(_state(time=1.0, target=VALID_TARGET))

    damaged = controller.step(
        _state(time=9.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50))
    )
    assert damaged.progress_observed

    still_fighting = controller.step(
        _state(time=15.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50))
    )

    assert still_fighting.mode is CombatMode.FIGHTING
    assert still_fighting.break_reason is None


def test_kill_count_increment_confirms_death_on_the_timeout_tick() -> None:
    controller = CombatController(CombatConfig(kill_verification_enabled=True))
    controller.step(_state(mobs=(_mob(),), monster_kill_count=5))
    controller.step(_state(time=1.0, target=VALID_TARGET, monster_kill_count=5))

    confirmed = controller.step(_state(time=99.0, target=VALID_TARGET, monster_kill_count=6))

    assert confirmed.mode is CombatMode.TARGET_DEAD


def test_combat_config_rejects_invalid_lockout_and_timeout_values() -> None:
    with pytest.raises(ValueError):
        CombatConfig(target_lockout_seconds=-1.0)
    with pytest.raises(ValueError):
        CombatConfig(target_lockout_radius_pixels=-1)
    with pytest.raises(ValueError):
        CombatConfig(engagement_timeout_seconds=0.0)


@pytest.mark.parametrize("virtual_key", [ord("0"), ord("A"), VIRTUAL_KEY_F1])
def test_key_binding_accepts_all_configured_attack_key_categories(virtual_key: int) -> None:
    assert KeyBinding(virtual_key).virtual_key == virtual_key


def test_key_binding_rejects_unsupported_virtual_key() -> None:
    with pytest.raises(ValueError):
        KeyBinding(0x10)


class _InputAdapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.clicks: list[tuple[int, int, int]] = []
        self.keys: list[tuple[int, float]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def click_client(self, window_handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((window_handle, x_coordinate, y_coordinate))

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))


def test_input_dispatcher_halts_for_emergency_stop_or_focus_loss() -> None:
    controller = CombatController()
    click = controller.step(_state(mobs=(_mob(),)))

    stopped = _InputAdapter(aborted=True)
    unfocused = _InputAdapter(foreground=False)

    assert not CombatInputDispatcher(stopped, WINDOW_HANDLE).dispatch(click)
    assert not CombatInputDispatcher(unfocused, WINDOW_HANDLE).dispatch(click)
    assert stopped.clicks == []
    assert unfocused.clicks == []


def test_input_dispatcher_sends_approved_click_and_key() -> None:
    controller = CombatController()
    adapter = _InputAdapter()
    dispatcher = CombatInputDispatcher(adapter, WINDOW_HANDLE)

    assert dispatcher.dispatch(controller.step(_state(mobs=(_mob(),))))
    assert dispatcher.dispatch(controller.step(_state(time=1.0, target=VALID_TARGET)))
    assert adapter.clicks == [(WINDOW_HANDLE, 20, 25)]
    assert adapter.keys


def test_blocked_approach_breaks_the_engagement_with_an_obstacle_stall() -> None:
    """US-039: the client walks the character, so the session reports the blocked approach."""

    controller = CombatController()
    controller.step(_state(mobs=(_mob(x=80, y=40),)))

    broken = controller.step(_state(time=5.0, target=VALID_TARGET), approach_stalled=True)

    assert broken.mode is CombatMode.IDLE
    assert broken.break_reason is EngagementBreakReason.OBSTACLE_STALL


def test_first_blocked_approach_requests_repositioning_and_keeps_the_short_lockout() -> None:
    """US-039: one obstacle is often cleared by walking around it, so nothing is written off."""

    controller = CombatController()
    mob = _mob(x=80, y=40)
    controller.step(_state(mobs=(mob,)))

    broken = controller.step(_state(time=5.0, target=VALID_TARGET), approach_stalled=True)

    assert broken.reposition_requested
    # The short lockout is still in force, so the very next tick cannot re-click the mob.
    assert controller.step(_state(time=5.1, mobs=(mob,))).input_kind is None
    # It expires with `target_lockout_seconds`, which the re-positioning sweep outlives.
    assert controller.step(_state(time=9.2, mobs=(mob,))).input_kind is CombatInputKind.CLICK


def test_second_consecutive_blocked_approach_locks_the_location_out_for_thirty_seconds() -> None:
    """US-039: a location that blocked twice in a row is unreachable, not merely contested."""

    controller = CombatController()
    mob = _mob(x=80, y=40)
    controller.step(_state(mobs=(mob,)))
    controller.step(_state(time=5.0, target=VALID_TARGET), approach_stalled=True)
    controller.step(_state(time=9.2, mobs=(mob,)))

    broken = controller.step(_state(time=14.0, target=VALID_TARGET), approach_stalled=True)

    assert broken.break_reason is EngagementBreakReason.OBSTACLE_STALL
    assert not broken.reposition_requested
    assert controller.step(_state(time=43.9, mobs=(mob,))).input_kind is None
    assert controller.step(_state(time=44.1, mobs=(mob,))).input_kind is CombatInputKind.CLICK


def test_a_blocked_approach_elsewhere_restarts_the_strike_count() -> None:
    """US-039: only consecutive failures against the same location escalate."""

    controller = CombatController()
    near = _mob(x=80, y=40)
    far = _mob(x=10, y=40)
    controller.step(_state(mobs=(near,)))
    controller.step(_state(time=5.0, target=VALID_TARGET), approach_stalled=True)

    controller.step(_state(time=9.2, mobs=(far,)))
    second = controller.step(_state(time=14.0, target=VALID_TARGET), approach_stalled=True)

    assert second.reposition_requested
    assert controller.step(_state(time=44.0, mobs=(near,))).input_kind is CombatInputKind.CLICK


def test_a_stall_verdict_is_ignored_once_the_target_took_damage() -> None:
    """US-039: in attack range the character stands still, which is not a blocked path."""

    controller = CombatController()
    controller.step(_state(mobs=(_mob(),)))
    controller.step(_state(time=1.0, target=VALID_TARGET))
    damaged = _state(time=2.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50))
    assert controller.step(damaged).progress_observed

    still_fighting = controller.step(
        _state(time=3.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)),
        approach_stalled=True,
    )

    assert still_fighting.mode is CombatMode.FIGHTING
    assert still_fighting.break_reason is None


def test_damage_dealt_is_reported_so_the_session_can_stop_sampling_the_approach() -> None:
    controller = CombatController()
    controller.step(_state(mobs=(_mob(),)))
    controller.step(_state(time=1.0, target=VALID_TARGET))

    assert not controller.damage_dealt

    controller.step(_state(time=2.0, target=SelectedTarget(TargetState.VALID, "Mushpang", 50)))

    assert controller.damage_dealt


def test_engagement_timeout_shares_the_unreachable_strike_count_with_the_obstacle_stall() -> None:
    """US-039: both break reasons mean the same thing - the approach never arrived."""

    controller = CombatController()
    mob = _mob(x=80, y=40)
    controller.step(_state(mobs=(mob,)))
    controller.step(_state(time=1.0, target=VALID_TARGET))
    first = controller.step(_state(time=11.1, target=VALID_TARGET))

    assert first.break_reason is EngagementBreakReason.ENGAGEMENT_TIMEOUT
    assert first.reposition_requested

    controller.step(_state(time=15.2, mobs=(mob,)))
    second = controller.step(_state(time=20.0, target=VALID_TARGET), approach_stalled=True)

    assert not second.reposition_requested
    assert controller.step(_state(time=49.9, mobs=(mob,))).input_kind is None


def test_combat_config_rejects_invalid_unreachable_lockout_values() -> None:
    with pytest.raises(ValueError):
        CombatConfig(unreachable_lockout_seconds=0.5)
    with pytest.raises(ValueError):
        CombatConfig(approach_failure_memory_seconds=-1.0)


def test_a_confirmed_kill_names_the_engaged_monster_class() -> None:
    """US-035: quotas are per monster, so a kill has to carry the class it belongs to."""

    controller = CombatController(CombatConfig(kill_verification_enabled=True))

    selection = controller.step(_state(mobs=(_mob(class_name="Rapra"),), monster_kill_count=5))
    assert selection.engaged_class_name == "Rapra"
    controller.step(_state(time=1.0, target=VALID_TARGET, monster_kill_count=5))

    confirmed = controller.step(_state(time=1.5, target=VALID_TARGET, monster_kill_count=6))

    assert confirmed.mode is CombatMode.TARGET_DEAD
    assert confirmed.engaged_class_name == "Rapra"


def test_an_abandoned_engagement_reports_no_monster_class_to_count() -> None:
    controller = CombatController(
        CombatConfig(target_acquisition_grace_seconds=0.5, kill_verification_enabled=False)
    )

    controller.step(_state(mobs=(_mob(class_name="Rapra"),)))
    broken = controller.step(_state(time=1.0, target=NO_TARGET))

    assert broken.break_reason is EngagementBreakReason.ACQUISITION_TIMEOUT
    assert broken.engaged_class_name is None
