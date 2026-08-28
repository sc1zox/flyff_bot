"""Tests for staged, guarded no-mob search navigation."""

from __future__ import annotations

import pytest

from flyff_bot.features.automation.controllers import (
    SearchConfig,
    SearchController,
    SearchMode,
)
from flyff_bot.features.automation.search_execution import SearchInputDispatcher
from flyff_bot.features.input_control.keymap import (
    VIRTUAL_KEY_D,
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_W,
)


class _Adapter:
    def __init__(self, *, aborted: bool = False, foreground: bool = True) -> None:
        self.aborted = aborted
        self.foreground = foreground
        self.keys: list[tuple[int, int, float]] = []
        self.clicks: list[tuple[int, int, int]] = []

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, _window_handle: int) -> bool:
        return self.foreground

    def send_key_while_guarded(self, handle: int, key: int, duration: float) -> None:
        self.keys.append((handle, key, duration))

    def click_client(self, handle: int, x_coordinate: int, y_coordinate: int) -> None:
        self.clicks.append((handle, x_coordinate, y_coordinate))


def test_search_progresses_from_idle_rotation_to_roaming_and_cycles() -> None:
    search = SearchController(
        SearchConfig(
            idle_timeout_seconds=1.0,
            rotation_steps=2,
            rotation_step_duration_seconds=0.2,
            rotation_settle_pause_seconds=0.3,
            roam_steps=2,
            movement_step_duration_seconds=1.0,
        )
    )

    # Idle period
    assert search.step(0.0).input_kind is None
    assert search.step(0.9).input_kind is None

    # Step 1: ROTATE pulse 1 (0.2s duration + 0.3s settle pause = next action at 1.5s)
    step1 = search.step(1.0)
    assert step1.mode is SearchMode.ROTATE
    assert step1.virtual_key == VIRTUAL_KEY_RIGHT
    assert step1.key_press_duration_seconds == 0.2

    # Settle pause during ROTATE
    settle1 = search.step(1.2)
    assert settle1.mode is SearchMode.ROTATE
    assert settle1.input_kind is None

    # Step 2: ROTATE pulse 2 (next action at 1.5 + 0.2 + 0.3 = 2.0s)
    step2 = search.step(1.5)
    assert step2.mode is SearchMode.ROTATE
    assert step2.virtual_key == VIRTUAL_KEY_RIGHT

    # Settle pause during ROTATE
    assert search.step(1.8).input_kind is None

    # Step 3: ROAM_STEP 1 (next action at 2.0 + 1.0 = 3.0s)
    step3 = search.step(2.0)
    assert step3.mode is SearchMode.ROAM_STEP
    assert step3.virtual_key == VIRTUAL_KEY_W
    assert step3.key_press_duration_seconds == 1.0

    # Step 4: ROAM_STEP 2 (next action at 3.0 + 1.0 = 4.0s)
    step4 = search.step(3.0)
    assert step4.mode is SearchMode.ROAM_STEP
    assert step4.virtual_key == VIRTUAL_KEY_D

    # Step 5: Completed roaming cycle resets back to ROTATE for continuous sweeping
    step5 = search.step(4.0)
    assert step5.mode is SearchMode.ROTATE
    assert step5.virtual_key == VIRTUAL_KEY_RIGHT
    assert step5.key_press_duration_seconds == 0.2


def test_search_uses_configured_rotation_virtual_key() -> None:
    search = SearchController(
        SearchConfig(
            idle_timeout_seconds=0.0,
            rotation_steps=1,
            rotation_virtual_key=VIRTUAL_KEY_LEFT,
        )
    )
    decision = search.step(0.0)
    assert decision.mode is SearchMode.ROTATE
    assert decision.virtual_key == VIRTUAL_KEY_LEFT


def test_search_config_validation() -> None:
    with pytest.raises(ValueError, match="idle timeout"):
        SearchConfig(idle_timeout_seconds=-1.0)
    with pytest.raises(ValueError, match="rotation step duration"):
        SearchConfig(rotation_step_duration_seconds=0.0)
    with pytest.raises(ValueError, match="settle pause"):
        SearchConfig(rotation_settle_pause_seconds=-0.1)
    with pytest.raises(ValueError, match="stage step counts"):
        SearchConfig(rotation_steps=0)
    with pytest.raises(ValueError, match="stage step counts"):
        SearchConfig(roam_steps=0)
    with pytest.raises(ValueError, match="rotation key"):
        SearchConfig(rotation_virtual_key=0x41)


def test_search_dispatch_is_aborted_or_paused_before_any_navigation_input() -> None:
    decision = SearchController(SearchConfig(idle_timeout_seconds=0.0)).step(0.0)
    for adapter in (_Adapter(aborted=True), _Adapter(foreground=False)):
        assert not SearchInputDispatcher(adapter, 42).dispatch(decision)
        assert adapter.keys == []
        assert adapter.clicks == []
