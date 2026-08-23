"""Integration coverage for guarded teleporter dispatch (BUG-024)."""

from __future__ import annotations

from typing import cast

from flyff_bot.features.navigation.live_position import (
    LivePositionReader,
    PositionReading,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.teleporter_dispatch import (
    ArrivalObservation,
    TeleporterDispatchConfig,
    TeleporterDispatcher,
    TeleporterInputAdapter,
)
from flyff_bot.features.navigation.teleporter_models import TeleporterDestination

WINDOW_HANDLE = 42


class _Pipeline:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def tick(self, window_handle: int, _state: object) -> object:
        self.calls.append(window_handle)
        return None


class _Observer:
    def __init__(self, observation: ArrivalObservation | None = None) -> None:
        self.observation = observation

    def observe(self) -> ArrivalObservation:
        if self.observation is None:
            raise AssertionError("observer called before dispatch")
        return self.observation


class _TeleporterInput:
    def __init__(self) -> None:
        self.actions: list[tuple[str, object]] = []

    def is_aborted(self) -> bool:
        return False

    def is_foreground(self, _window_handle: int) -> bool:
        return True

    def pulse_teleporter_hotkey(self, virtual_key: int, duration_seconds: float) -> None:
        self.actions.append(("hotkey", virtual_key))

    def type_search_text(self, _window_handle: int, text: str) -> None:
        self.actions.append(("type", text))

    def click_search_field(self, window_handle: int) -> None:
        self.actions.append(("search_click", window_handle))

    def select_first_result(self, window_handle: int) -> None:
        self.actions.append(("select_click", window_handle))

    def click_teleport_button(self, window_handle: int) -> None:
        self.actions.append(("teleport_click", window_handle))

    def close_teleporter_window(self, window_handle: int) -> None:
        self.actions.append(("close", window_handle))


def test_teleporter_dispatcher_integrates_with_pathing() -> None:
    destination = TeleporterDestination(
        destination_id=1,
        name="Flarine",
        search_text="Flarine",
        world_id=0,
        anchor_x=101.0,
        anchor_z=201.0,
    )
    adapter = _TeleporterInput()
    observer = _Observer(ArrivalObservation(WorldPosition(101.0, 10.0, 201.0), 0, 2.0))
    dispatcher = TeleporterDispatcher(
        cast(TeleporterInputAdapter, adapter),
        WINDOW_HANDLE,
        observer,
        config=TeleporterDispatchConfig(combat_stable_seconds=0.1),
    )
    pathing = PathingController(
        position_reader=cast(
            LivePositionReader,
            type(
                "_Reader",
                (),
                {
                    "poll": lambda self, at: PositionReading(
                        PositionSource.LIVE,
                        WorldPosition(100.0, 10.0, 200.0),
                        sampled_at_seconds=at,
                    ),
                    "close": lambda self: None,
                },
            )(),
        ),
        teleporter_dispatcher=dispatcher,
    )

    assert pathing.request_teleporter_destination(destination, 0.0)

    pathing.step(0.5)
    result = pathing.step(2.0)

    assert result.mode.value == "teleporting"
    assert [action[0] for action in adapter.actions] == [
        "hotkey",
        "search_click",
        "type",
        "select_click",
        "teleport_click",
    ]
    assert pathing.step(20.0).mode.value in {"blocked", "idle"}
