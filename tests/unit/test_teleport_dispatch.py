"""Tests for guarded teleporter UI dispatch and closed-loop confirmation (US-065)."""

from __future__ import annotations

from typing import cast

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.teleporter_dispatch import (
    ArrivalObservation,
    ArrivalObserver,
    ClientPoint,
    CombatObservation,
    TeleporterDialogGeometry,
    TeleporterDispatchConfig,
    TeleporterDispatcher,
    TeleporterDispatchStatus,
    TeleporterInputAdapter,
)
from flyff_bot.features.navigation.teleporter_models import TeleporterDestination

DESTINATION = TeleporterDestination(
    destination_id=1,
    name="Flarine",
    search_text="Flarine City",
    world_id=0,
    anchor_x=100.0,
    anchor_z=200.0,
)
DIALOG = TeleporterDialogGeometry(ClientPoint(10, 20), ClientPoint(30, 40), ClientPoint(50, 60))


class Adapter:
    def __init__(
        self,
        *,
        foreground: bool = True,
        aborted: bool = False,
        dialog: TeleporterDialogGeometry | None = DIALOG,
    ) -> None:
        self.actions: list[tuple[str, object]] = []
        self.foreground = foreground
        self.aborted = aborted
        self.dialog = dialog

    def is_aborted(self) -> bool:
        return self.aborted

    def is_foreground(self, window_handle: int) -> bool:
        return self.foreground

    def pulse_teleporter_hotkey(self, virtual_key: int, duration_seconds: float) -> None:
        self.actions.append(("hotkey", (virtual_key, duration_seconds)))

    def type_search_text(self, window_handle: int, text: str) -> None:
        self.actions.append(("type", text))

    def locate_dialog(self, _window_handle: int) -> TeleporterDialogGeometry | None:
        return self.dialog

    def click_client_point(self, window_handle: int, point: ClientPoint) -> None:
        name = {
            DIALOG.search_field: "search_click",
            DIALOG.first_result: "select_click",
            DIALOG.teleport_button: "teleport_click",
        }[point]
        self.actions.append((name, window_handle))

    def close_teleporter_window(self, window_handle: int) -> None:
        self.actions.append(("close", window_handle))


class Observer:
    def __init__(self, observation: ArrivalObservation | None = None) -> None:
        self.observation = observation

    def observe(self) -> ArrivalObservation:
        if self.observation is None:
            raise AssertionError("observer called before dispatch")
        return self.observation


def dispatcher(adapter: Adapter, observer: Observer) -> TeleporterDispatcher:
    result = TeleporterDispatcher(
        cast(TeleporterInputAdapter, adapter),
        1234,
        cast(ArrivalObserver, observer),
        config=TeleporterDispatchConfig(
            combat_stable_seconds=1.0,
            confirmation_timeout_seconds=1.0,
        ),
    )
    return result


def test_dispatches_the_exact_no_ocr_ui_sequence_when_safe() -> None:
    adapter = Adapter()
    controller = dispatcher(adapter, Observer())
    controller.request(DESTINATION, 0.0)

    assert controller.tick(None, at_seconds=0.0).reason == "combat_unknown"
    assert controller.tick(CombatObservation(False, 100.0, 0.5), at_seconds=0.5).status is (
        TeleporterDispatchStatus.DEFERRED
    )
    result = controller.tick(CombatObservation(False, 100.0, 2.0), at_seconds=2.0)

    assert result.status is TeleporterDispatchStatus.DISPATCHED
    assert [action[0] for action in adapter.actions] == [
        "hotkey",
        "search_click",
        "type",
        "select_click",
        "teleport_click",
    ]


def test_defers_engagement_and_damage_until_combat_is_stable() -> None:
    adapter = Adapter()
    controller = dispatcher(adapter, Observer())
    controller.request(DESTINATION, 0.0)

    engaged = controller.tick(CombatObservation(True, 100.0, 0.0), at_seconds=0.0)
    damaged = controller.tick(CombatObservation(False, 90.0, 0.1), at_seconds=0.1)
    stable = controller.tick(CombatObservation(False, 90.0, 0.2), at_seconds=0.2)

    assert engaged.reason == "combat"
    assert damaged.reason == "combat"
    assert stable.reason == "combat_stable"
    assert adapter.actions == []


def test_refuses_input_while_backgrounded_or_aborted() -> None:
    background = Adapter(foreground=False)
    aborted = Adapter(aborted=True)
    for adapter in (background, aborted):
        controller = dispatcher(adapter, Observer())
        controller.request(DESTINATION, 0.0)
        result = controller.tick(CombatObservation(False, 100.0, 2.0), at_seconds=2.0)
        assert result.status in {
            TeleporterDispatchStatus.DEFERRED,
            TeleporterDispatchStatus.FAILED_STANDBY,
        }

    assert background.actions == []
    assert aborted.actions == []


def test_missing_dialog_geometry_fails_closed_after_the_guarded_hotkey() -> None:
    adapter = Adapter(dialog=None)
    controller = dispatcher(adapter, Observer())
    controller.request(DESTINATION, 0.0)

    controller.tick(CombatObservation(False, 100.0, 0.5), at_seconds=0.5)
    result = controller.tick(CombatObservation(False, 100.0, 2.0), at_seconds=2.0)

    assert result.status is TeleporterDispatchStatus.FAILED_STANDBY
    assert result.reason == "dialog_not_found"
    assert [name for name, _value in adapter.actions] == ["hotkey", "close"]


def test_confirms_only_matching_world_identity_and_position() -> None:
    adapter = Adapter()
    controller = dispatcher(adapter, Observer())
    controller.request(DESTINATION, 0.0)
    controller.tick(CombatObservation(False, 100.0, 2.0), at_seconds=2.0)

    wrong_world = ArrivalObservation(WorldPosition(101.0, 10.0, 201.0), 1, 2.5)
    wrong_place = ArrivalObservation(WorldPosition(500.0, 10.0, 500.0), 0, 2.5)
    arrival = ArrivalObservation(WorldPosition(101.0, 10.0, 201.0), 0, 2.5)
    controller._observer = Observer(wrong_world)
    assert controller.tick(None, at_seconds=2.5).status is TeleporterDispatchStatus.DISPATCHED
    controller._observer = Observer(wrong_place)
    assert controller.tick(None, at_seconds=2.6).status is TeleporterDispatchStatus.DISPATCHED
    controller._observer = Observer(arrival)
    assert controller.tick(None, at_seconds=2.7).status is TeleporterDispatchStatus.CONFIRMED
    assert controller.destination is None


def test_timeout_closes_the_window_and_enters_standby_without_retry() -> None:
    adapter = Adapter()
    controller = dispatcher(adapter, Observer(ArrivalObservation(None, None, 0.0)))
    controller.request(DESTINATION, 0.0)
    controller.tick(None, at_seconds=0.0)
    controller.tick(CombatObservation(False, 100.0, 2.0), at_seconds=2.0)

    failed = controller.tick(None, at_seconds=8.0)
    again = controller.tick(None, at_seconds=9.0)

    assert failed.status is TeleporterDispatchStatus.FAILED_STANDBY
    assert failed.reason == "confirmation_timeout"
    assert ("close", 1234) in adapter.actions
    assert again.status is TeleporterDispatchStatus.DEFERRED
    assert again.reason == "no_request"
