"""Foreground-safe, no-OCR dispatch and closed-loop confirmation for the teleporter."""

from __future__ import annotations

import math
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from flyff_bot.features.navigation.live_position import (
    PositionReading,
    PositionSource,
    WorldPosition,
)
from flyff_bot.features.navigation.live_world_id import LiveWorldIdReader
from flyff_bot.features.navigation.teleporter_models import TeleporterDestination

DEFAULT_TELEPORTER_HOTKEY_VIRTUAL_KEY = ord("V")
DEFAULT_TELEPORTER_CONFIRMATION_TIMEOUT_SECONDS = 5.0
DEFAULT_ARRIVAL_TOLERANCE_UNITS = 10.0
DEFAULT_COMBAT_STABLE_SECONDS = 1.0
MINIMUM_VIRTUAL_KEY = 1
MAXIMUM_VIRTUAL_KEY = 0xFE


class TeleporterDispatchStatus(StrEnum):
    """The externally observable phase of one teleporter attempt."""

    DEFERRED = "deferred"
    DISPATCHED = "dispatched"
    CONFIRMED = "confirmed"
    FAILED_STANDBY = "failed_standby"


@dataclass(frozen=True, slots=True)
class CombatObservation:
    """The minimal combat evidence needed to defer a zone transition safely."""

    engaged: bool
    health: float
    observed_at_seconds: float


@dataclass(frozen=True, slots=True)
class ArrivalObservation:
    """One authoritative live-client observation used for teleport confirmation."""

    position: WorldPosition | None
    world_id: int | None
    sampled_at_seconds: float


@dataclass(frozen=True, slots=True)
class TeleporterDispatchResult:
    """Whether an attempt progressed, was deferred, confirmed, or failed safely."""

    status: TeleporterDispatchStatus
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ClientPoint:
    """One measured point in the target window's client coordinates."""

    x: int
    y: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError("Teleporter client coordinates cannot be negative.")


@dataclass(frozen=True, slots=True)
class TeleporterDialogGeometry:
    """Clickable client points derived from one detected teleporter dialog."""

    search_field: ClientPoint
    first_result: ClientPoint
    teleport_button: ClientPoint


class TeleporterInputAdapter(Protocol):
    """Guarded UI operations; every implementation must enforce its own safety checks."""

    def is_aborted(self) -> bool: ...

    def is_foreground(self, window_handle: int) -> bool: ...

    def pulse_teleporter_hotkey(self, virtual_key: int, duration_seconds: float) -> None: ...

    def locate_dialog(self, window_handle: int) -> TeleporterDialogGeometry | None: ...

    def type_search_text(self, window_handle: int, text: str) -> None: ...

    def click_client_point(self, window_handle: int, point: ClientPoint) -> None: ...

    def close_teleporter_window(self, window_handle: int) -> None: ...


class ArrivalPositionReader(Protocol):
    """Explicit read-only position sampling contract for arrival confirmation."""

    def poll(self, at_seconds: float) -> PositionReading: ...


class ArrivalObserver(Protocol):
    """Read-only source of authoritative world identity and coordinates."""

    def observe(self) -> ArrivalObservation: ...


class LiveArrivalObserver:
    """Production observer backed by read-only process memory."""

    def __init__(
        self,
        position_reader: ArrivalPositionReader,
        world_id_reader: LiveWorldIdReader | None = None,
    ) -> None:
        self._position_reader = position_reader
        self._world_id_reader = world_id_reader

    def observe(self) -> ArrivalObservation:
        position: WorldPosition | None = None
        world_id: int | None = None
        sampled_at: float | None = None

        reading = self._position_reader.poll(time.monotonic())
        if reading.source is PositionSource.LIVE and reading.position is not None:
            position = reading.position
            sampled_at = reading.sampled_at_seconds

        if self._world_id_reader is not None:
            timestamp = time.monotonic() if sampled_at is None else sampled_at
            wid_reading = self._world_id_reader.poll(timestamp)
            if wid_reading.is_available:
                world_id = wid_reading.world_id
                if sampled_at is None:
                    sampled_at = wid_reading.sampled_at_seconds

        return ArrivalObservation(
            position=position,
            world_id=world_id,
            sampled_at_seconds=sampled_at or 0.0,
        )


@dataclass(frozen=True, slots=True)
class TeleporterDispatchConfig:
    """Explicit timings for one deterministic, detected-dialog UI sequence."""

    hotkey_virtual_key: int = DEFAULT_TELEPORTER_HOTKEY_VIRTUAL_KEY
    hotkey_duration_seconds: float = 0.08
    confirmation_timeout_seconds: float = DEFAULT_TELEPORTER_CONFIRMATION_TIMEOUT_SECONDS
    arrival_tolerance_units: float = DEFAULT_ARRIVAL_TOLERANCE_UNITS
    combat_stable_seconds: float = DEFAULT_COMBAT_STABLE_SECONDS

    def __post_init__(self) -> None:
        if self.hotkey_duration_seconds <= 0.0:
            raise ValueError("Teleporter hotkey duration must be positive.")
        if self.confirmation_timeout_seconds <= 0.0:
            raise ValueError("Teleporter confirmation timeout must be positive.")
        if self.arrival_tolerance_units <= 0.0 or self.combat_stable_seconds <= 0.0:
            raise ValueError("Teleporter safety thresholds must be positive.")
        if not MINIMUM_VIRTUAL_KEY <= self.hotkey_virtual_key <= MAXIMUM_VIRTUAL_KEY:
            raise ValueError("Teleporter hotkey must be a valid virtual-key code.")


class TeleporterDispatcher:
    """Run one guarded teleporter attempt and confirm it only with authoritative evidence."""

    def __init__(
        self,
        adapter: TeleporterInputAdapter,
        window_handle: int,
        observer: ArrivalObserver,
        *,
        config: TeleporterDispatchConfig | None = None,
    ) -> None:
        self._adapter = adapter
        self._window_handle = window_handle
        self._observer = observer
        self._config = config or TeleporterDispatchConfig()
        self._destination: TeleporterDestination | None = None
        self._started_at_seconds: float | None = None
        self._last_health: float | None = None
        self._safe_since_seconds: float | None = None

    @property
    def observer(self) -> ArrivalObserver:
        """Return the read-only source of authoritative world identity and coordinates."""

        return self._observer

    @property
    def destination(self) -> TeleporterDestination | None:
        """Return the pending or last requested destination."""

        return self._destination

    def request(self, destination: TeleporterDestination, at_seconds: float) -> None:
        """Arm a zone transition without touching the client until the next tick."""

        if at_seconds < 0.0:
            raise ValueError("A teleporter request timestamp cannot be negative.")
        self._destination = destination
        self._started_at_seconds = None
        self._last_health = None
        self._safe_since_seconds = None

    def cancel(self) -> None:
        """Drop a pending request before any client interaction."""

        self._destination = None
        self._started_at_seconds = None
        self._safe_since_seconds = None

    def update_hotkey(self, virtual_key: int) -> None:
        """Adopt a persisted operator binding for future dispatches."""

        self._config = TeleporterDispatchConfig(
            hotkey_virtual_key=virtual_key,
            hotkey_duration_seconds=self._config.hotkey_duration_seconds,
            confirmation_timeout_seconds=self._config.confirmation_timeout_seconds,
            arrival_tolerance_units=self._config.arrival_tolerance_units,
            combat_stable_seconds=self._config.combat_stable_seconds,
        )

    def tick(
        self,
        combat: CombatObservation | None,
        *,
        at_seconds: float,
    ) -> TeleporterDispatchResult:
        """Advance one attempt using combat, focus, emergency-stop, and arrival guards."""

        if self._destination is None:
            return TeleporterDispatchResult(TeleporterDispatchStatus.DEFERRED, "no_request")
        if combat is not None:
            damaged = self._last_health is not None and combat.health < self._last_health
            self._last_health = combat.health
            if combat.engaged or damaged:
                self._started_at_seconds = None
                self._safe_since_seconds = None
                return TeleporterDispatchResult(TeleporterDispatchStatus.DEFERRED, "combat")
            if self._safe_since_seconds is None:
                self._safe_since_seconds = at_seconds
            if at_seconds - self._safe_since_seconds < self._config.combat_stable_seconds:
                return TeleporterDispatchResult(TeleporterDispatchStatus.DEFERRED, "combat_stable")
        elif self._safe_since_seconds is None:
            self._safe_since_seconds = at_seconds
            return TeleporterDispatchResult(TeleporterDispatchStatus.DEFERRED, "combat_unknown")

        if self._adapter.is_aborted():
            return self._fail("emergency_stop")
        if not self._adapter.is_foreground(self._window_handle):
            self._started_at_seconds = None
            return TeleporterDispatchResult(TeleporterDispatchStatus.DEFERRED, "not_foreground")

        if self._started_at_seconds is None:
            try:
                sequence_error = self._dispatch_sequence()
            except OSError as error:
                return self._fail(f"input_failed:{error}")
            if sequence_error is not None:
                return self._fail(sequence_error)
            self._started_at_seconds = at_seconds
            return TeleporterDispatchResult(TeleporterDispatchStatus.DISPATCHED, "ui_sequence")

        observation = self._observer.observe()
        if self._is_arrived(observation):
            self.cancel()
            return TeleporterDispatchResult(TeleporterDispatchStatus.CONFIRMED)
        if at_seconds - self._started_at_seconds >= self._config.confirmation_timeout_seconds:
            return self._fail("confirmation_timeout")
        return TeleporterDispatchResult(TeleporterDispatchStatus.DISPATCHED, "awaiting_arrival")

    def _dispatch_sequence(self) -> str | None:
        destination = self._destination
        if destination is None:
            return "no_request"
        self._adapter.pulse_teleporter_hotkey(
            self._config.hotkey_virtual_key,
            self._config.hotkey_duration_seconds,
        )
        if not self._input_is_safe():
            return "guard_changed"
        geometry = self._adapter.locate_dialog(self._window_handle)
        if geometry is None:
            return "dialog_not_found"
        if not self._input_is_safe():
            return "guard_changed"
        self._adapter.click_client_point(self._window_handle, geometry.search_field)
        if not self._input_is_safe():
            return "guard_changed"
        self._adapter.type_search_text(self._window_handle, destination.search_text)
        if not self._input_is_safe():
            return "guard_changed"
        self._adapter.click_client_point(self._window_handle, geometry.first_result)
        if not self._input_is_safe():
            return "guard_changed"
        self._adapter.click_client_point(self._window_handle, geometry.teleport_button)
        return None

    def _input_is_safe(self) -> bool:
        return not self._adapter.is_aborted() and self._adapter.is_foreground(self._window_handle)

    def _is_arrived(self, observation: ArrivalObservation) -> bool:
        destination = self._destination
        if destination is None or observation.world_id != destination.world_id:
            return False
        position = observation.position
        if position is None:
            return False
        return (
            math.hypot(
                position.x - destination.anchor_x,
                position.z - destination.anchor_z,
            )
            <= self._config.arrival_tolerance_units
        )

    def _fail(self, reason: str) -> TeleporterDispatchResult:
        with suppress(OSError):
            self._adapter.close_teleporter_window(self._window_handle)
        self.cancel()
        return TeleporterDispatchResult(TeleporterDispatchStatus.FAILED_STANDBY, reason)
