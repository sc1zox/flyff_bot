"""Tests for staged, guarded no-mob search navigation."""

from __future__ import annotations

import numpy as np

from flyff_bot.features.automation.controllers import (
    VIRTUAL_KEY_A,
    VIRTUAL_KEY_D,
    VIRTUAL_KEY_W,
    SearchConfig,
    SearchController,
    SearchInputKind,
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


def test_search_progresses_from_idle_rotation_to_roaming_then_radar() -> None:
    search = SearchController(
        SearchConfig(idle_timeout_seconds=1.0, rotation_steps=2, roam_steps=2)
    )

    assert search.step(0.0).input_kind is None
    assert search.step(0.9).input_kind is None
    assert search.step(1.0).virtual_key == VIRTUAL_KEY_A
    assert search.step(1.4).virtual_key == VIRTUAL_KEY_D
    assert search.step(1.8).virtual_key == VIRTUAL_KEY_W
    assert search.step(2.8).virtual_key == VIRTUAL_KEY_D
    assert search.step(3.8).mode is SearchMode.MINIMAP_RADAR
    decision = search.step(3.8, Position(80, 20))
    assert decision.input_kind is SearchInputKind.CLICK
    assert decision.position == Position(80, 20)


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
