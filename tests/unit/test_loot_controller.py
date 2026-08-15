"""Tests for reactive pickup sequencing and its guarded input boundary."""

from __future__ import annotations

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_F,
    CombatDecision,
    CombatMode,
    LootConfig,
    LootController,
    LootMode,
)
from flyff_bot.features.automation.loot_execution import LootInputDispatcher
from flyff_bot.features.automation.models import ActionKind, Position, RecentLoot, WorldState

WINDOW_HANDLE = 42


def _state(*, time: float, loot: tuple[RecentLoot, ...] = ()) -> WorldState:
    return WorldState(
        observed_at_seconds=time,
        position=Position(0, 0),
        nearby_mob_count=0,
        inventory=(),
        progress_marker=0,
        recent_loot=loot,
    )


def test_loot_controller_picks_up_after_death_and_accepts_confirmed_loot() -> None:
    controller = LootController()
    dead = CombatDecision(CombatMode.TARGET_DEAD)
    fighting = CombatDecision(CombatMode.FIGHTING)

    pickup = controller.step(_state(time=1.0), dead)
    waiting = controller.step(_state(time=1.1), fighting)
    confirmed = controller.step(
        _state(time=1.2, loot=(RecentLoot("Sword", 1, "You received Sword."),)), fighting
    )

    assert pickup.mode is LootMode.PICKING_UP
    assert pickup.action_kind is ActionKind.LOOT
    assert pickup.virtual_key == VIRTUAL_KEY_F
    assert waiting.mode is LootMode.WAITING
    assert confirmed.mode is LootMode.IDLE


def test_loot_controller_times_out_and_requests_patrol_once() -> None:
    controller = LootController(LootConfig(pickup_wait_seconds=1.0))
    dead = CombatDecision(CombatMode.TARGET_DEAD)
    fighting = CombatDecision(CombatMode.FIGHTING)

    controller.step(_state(time=1.0), dead)
    controller.step(_state(time=1.1), fighting)
    timeout = controller.step(_state(time=2.0), fighting)
    idle = controller.step(_state(time=2.1), fighting)

    assert timeout.mode is LootMode.TIMED_OUT
    assert timeout.action_kind is ActionKind.MOVE
    assert idle.mode is LootMode.IDLE


class _InputAdapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.keys: list[tuple[int, float]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def send_key(self, virtual_key: int, duration_seconds: float) -> None:
        self.keys.append((virtual_key, duration_seconds))


def test_loot_dispatcher_requires_foreground_and_clear_emergency_stop() -> None:
    pickup = LootController().step(_state(time=1.0), CombatDecision(CombatMode.TARGET_DEAD))
    stopped = _InputAdapter(aborted=True)
    unfocused = _InputAdapter(foreground=False)
    active = _InputAdapter()

    assert not LootInputDispatcher(stopped, WINDOW_HANDLE).dispatch(pickup)
    assert not LootInputDispatcher(unfocused, WINDOW_HANDLE).dispatch(pickup)
    assert LootInputDispatcher(active, WINDOW_HANDLE).dispatch(pickup)
    assert active.keys == [(VIRTUAL_KEY_F, pickup.key_press_duration_seconds)]
