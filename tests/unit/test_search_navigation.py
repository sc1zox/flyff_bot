"""Tests for staged, guarded no-mob search navigation."""

from __future__ import annotations

import pytest

from flyff_bot.features.automation.controllers import (
    SearchConfig,
    SearchController,
    SearchInputKind,
    SearchMode,
)
from flyff_bot.features.automation.search_execution import SearchInputDispatcher
from flyff_bot.features.input_control.keymap import (
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
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


def test_a_sweep_alternates_micro_rotations_with_settle_windows_and_cycles() -> None:
    """US-091: every rotation burst is followed by a still frame perception can trust."""

    search = SearchController(
        SearchConfig(
            idle_timeout_seconds=0.0,
            rotation_steps=2,
            rotation_step_duration_seconds=0.2,
            rotation_settle_pause_seconds=0.3,
        )
    )

    # Micro-rotation 1 (0.2s burst + 0.3s settle pause = next action at 0.5s).
    first = search.step(0.0)
    assert first.mode is SearchMode.ROTATE
    assert first.virtual_key == VIRTUAL_KEY_RIGHT
    assert first.key_press_duration_seconds == 0.2

    settle = search.step(0.2)
    assert settle.mode is SearchMode.SETTLE
    assert settle.input_kind is None

    second = search.step(0.5)
    assert second.mode is SearchMode.ROTATE
    assert second.virtual_key == VIRTUAL_KEY_RIGHT
    assert search.completed_cycles == 0

    # The sweep never roams: the step after a full lap is the next micro-rotation.
    third = search.step(1.0)
    assert third.mode is SearchMode.ROTATE
    assert third.virtual_key == VIRTUAL_KEY_RIGHT
    assert search.completed_cycles == 1


def test_a_sweep_begins_without_any_idle_delay() -> None:
    """US-091: the viewport already proved empty, so waiting observes nothing new."""

    search = SearchController()

    decision = search.step(0.0)

    assert decision.mode is SearchMode.ROTATE
    assert decision.input_kind is SearchInputKind.KEY


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
        SearchConfig(rotation_settle_pause_seconds=0.0)
    with pytest.raises(ValueError, match="sweep step count"):
        SearchConfig(rotation_steps=0)
    with pytest.raises(ValueError, match="rotation key"):
        SearchConfig(rotation_virtual_key=0x41)


def test_search_dispatch_is_aborted_or_paused_before_any_navigation_input() -> None:
    decision = SearchController(SearchConfig(idle_timeout_seconds=0.0)).step(0.0)
    for adapter in (_Adapter(aborted=True), _Adapter(foreground=False)):
        assert not SearchInputDispatcher(adapter, 42).dispatch(decision)
        assert adapter.keys == []
        assert adapter.clicks == []
