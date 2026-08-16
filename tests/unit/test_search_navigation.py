"""Tests for staged, guarded no-mob search navigation."""

from __future__ import annotations

import numpy as np
import pytest

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_D,
    VIRTUAL_KEY_DOWN,
    VIRTUAL_KEY_LEFT,
    VIRTUAL_KEY_RIGHT,
    VIRTUAL_KEY_UP,
    VIRTUAL_KEY_W,
    SearchConfig,
    SearchController,
    SearchMode,
)
from flyff_bot.features.automation.models import Position
from flyff_bot.features.automation.search_execution import SearchInputDispatcher
from flyff_bot.features.vision.minimap_radar import MinimapRadar
from flyff_bot.features.vision.models import CapturedFrame, ClientSize


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


def test_search_progresses_from_idle_rotation_to_tilt_then_roaming_and_cycles() -> None:
    search = SearchController(
        SearchConfig(
            idle_timeout_seconds=1.0,
            rotation_steps=2,
            rotation_step_duration_seconds=0.2,
            rotation_settle_pause_seconds=0.3,
            tilt_steps=2,
            tilt_step_duration_seconds=0.2,
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

    # Step 3: TILT pulse 1 (next action at 2.0 + 0.2 + 0.3 = 2.5s)
    step3 = search.step(2.0)
    assert step3.mode is SearchMode.TILT
    assert step3.virtual_key == VIRTUAL_KEY_UP
    assert step3.key_press_duration_seconds == 0.2

    # Settle pause during TILT
    settle3 = search.step(2.2)
    assert settle3.mode is SearchMode.TILT
    assert settle3.input_kind is None

    # Step 4: TILT pulse 2 (next action at 2.5 + 0.2 + 0.3 = 3.0s)
    step4 = search.step(2.5)
    assert step4.mode is SearchMode.TILT
    assert step4.virtual_key == VIRTUAL_KEY_UP

    # Settle pause during TILT
    assert search.step(2.8).input_kind is None

    # Step 5: ROAM_STEP 1 (next action at 3.0 + 1.0 = 4.0s)
    step5 = search.step(3.0)
    assert step5.mode is SearchMode.ROAM_STEP
    assert step5.virtual_key == VIRTUAL_KEY_W
    assert step5.key_press_duration_seconds == 1.0

    # Step 6: ROAM_STEP 2 (next action at 4.0 + 1.0 = 5.0s)
    step6 = search.step(4.0)
    assert step6.mode is SearchMode.ROAM_STEP
    assert step6.virtual_key == VIRTUAL_KEY_D

    # Step 7: Completed roaming cycle resets back to ROTATE for continuous sweeping
    step7 = search.step(5.0)
    assert step7.mode is SearchMode.ROTATE
    assert step7.virtual_key == VIRTUAL_KEY_RIGHT
    assert step7.key_press_duration_seconds == 0.2


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


def test_search_uses_configured_tilt_virtual_key() -> None:
    search = SearchController(
        SearchConfig(
            idle_timeout_seconds=0.0,
            rotation_steps=0,  # Will fail config if <=0, so we use rotation_steps=1 and advance
            tilt_virtual_key=VIRTUAL_KEY_DOWN,
        )
        if False
        else SearchConfig(
            idle_timeout_seconds=0.0,
            rotation_steps=1,
            tilt_steps=1,
            tilt_virtual_key=VIRTUAL_KEY_DOWN,
        )
    )
    # Step 1: rotate
    search.step(0.0)
    # Step 2: tilt (after rotation duration + settle pause)
    decision = search.step(1.0)
    assert decision.mode is SearchMode.TILT
    assert decision.virtual_key == VIRTUAL_KEY_DOWN


def test_search_config_validation() -> None:
    with pytest.raises(ValueError, match="idle timeout"):
        SearchConfig(idle_timeout_seconds=-1.0)
    with pytest.raises(ValueError, match="rotation step duration"):
        SearchConfig(rotation_step_duration_seconds=0.0)
    with pytest.raises(ValueError, match="settle pause"):
        SearchConfig(rotation_settle_pause_seconds=-0.1)
    with pytest.raises(ValueError, match="tilt step duration"):
        SearchConfig(tilt_step_duration_seconds=0.0)
    with pytest.raises(ValueError, match="stage step counts"):
        SearchConfig(rotation_steps=0)
    with pytest.raises(ValueError, match="stage step counts"):
        SearchConfig(tilt_steps=0)
    with pytest.raises(ValueError, match="stage step counts"):
        SearchConfig(roam_steps=0)
    with pytest.raises(ValueError, match="rotation key"):
        SearchConfig(rotation_virtual_key=0x41)
    with pytest.raises(ValueError, match="tilt key"):
        SearchConfig(tilt_virtual_key=0x41)


def test_search_dispatch_is_aborted_or_paused_before_any_navigation_input() -> None:
    decision = SearchController(SearchConfig(idle_timeout_seconds=0.0)).step(0.0)
    for adapter in (_Adapter(aborted=True), _Adapter(foreground=False)):
        assert not SearchInputDispatcher(adapter, 42).dispatch(decision)
        assert adapter.keys == []
        assert adapter.clicks == []


def test_minimap_radar_returns_nearest_red_dot_in_top_right_region() -> None:
    pixels = np.zeros((100, 100, 3), dtype=np.uint8)
    pixels[10:13, 80:83] = (0, 0, 255)
    pixels[20:23, 95:98] = (0, 0, 255)
    frame = CapturedFrame(pixels, ClientSize(100, 100))

    assert MinimapRadar().nearest_dot(frame) == Position(81, 11)


def test_minimap_radar_ignores_non_red_or_outside_pixels() -> None:
    pixels = np.zeros((100, 100, 3), dtype=np.uint8)
    pixels[50:55, 50:55] = (0, 0, 255)
    pixels[10:15, 80:85] = (255, 0, 0)

    assert MinimapRadar().nearest_dot(CapturedFrame(pixels, ClientSize(100, 100))) is None
