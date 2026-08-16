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


def test_stale_kill_count_jump_does_not_falsely_confirm_death() -> None:
    """A first successful OCR read mid-fight reports the session total, not a +1 delta."""

    controller = CombatController(CombatConfig(kill_verification_enabled=True))

    controller.step(_state(mobs=(_mob(),), monster_kill_count=0))
    attack = controller.step(_state(time=1.0, target=VALID_TARGET, monster_kill_count=0))
    assert attack.mode is CombatMode.FIGHTING

    stale_jump = controller.step(_state(time=1.5, target=VALID_TARGET, monster_kill_count=47))

    assert stale_jump.mode is CombatMode.FIGHTING


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

    controller.step(_state(time=1.4, mobs=(_mob(),)))
    new_attack = controller.step(_state(time=1.5, target=VALID_TARGET))

    assert new_attack.mode is CombatMode.FIGHTING
    assert new_attack.input_kind is CombatInputKind.KEY
    assert new_attack.virtual_key == VIRTUAL_KEY_1


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
