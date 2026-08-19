"""Long-range teleport decisions confirmed only by fresh live coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.navigation.live_position import WorldPosition

DEFAULT_LONG_RANGE_THRESHOLD_UNITS = 150.0
DEFAULT_TELEPORT_KEY_DURATION_SECONDS = 0.1
DEFAULT_TELEPORT_CONFIRMATION_RADIUS_UNITS = 30.0
DEFAULT_TELEPORT_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True, slots=True)
class TeleportAnchor:
    """One configured fast-travel destination and the hotkey that selects it."""

    name: str
    position: WorldPosition
    virtual_key: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A teleport anchor must have a name.")
        if not 0 <= self.virtual_key <= 0xFF:
            raise ValueError("A teleport hotkey must be a Windows virtual-key code.")


@dataclass(frozen=True, slots=True)
class TeleportConfig:
    """Fast-travel availability and confirmation limits."""

    enabled: bool = False
    long_range_threshold_units: float = DEFAULT_LONG_RANGE_THRESHOLD_UNITS
    key_duration_seconds: float = DEFAULT_TELEPORT_KEY_DURATION_SECONDS
    confirmation_radius_units: float = DEFAULT_TELEPORT_CONFIRMATION_RADIUS_UNITS
    timeout_seconds: float = DEFAULT_TELEPORT_TIMEOUT_SECONDS
    anchors: tuple[TeleportAnchor, ...] = ()

    def __post_init__(self) -> None:
        if self.long_range_threshold_units <= 0.0:
            raise ValueError("Long-range threshold must be positive.")
        if self.key_duration_seconds <= 0.0:
            raise ValueError("Teleport hotkey duration must be positive.")
        if self.confirmation_radius_units <= 0.0:
            raise ValueError("Teleport confirmation radius must be positive.")
        if self.timeout_seconds <= 0.0:
            raise ValueError("Teleport timeout must be positive.")


class TeleportStatus(StrEnum):
    """Observable phase of one teleport attempt."""

    IDLE = "idle"
    WAITING_FOR_POSITION = "waiting_for_position"
    CONFIRMED = "confirmed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TeleportDispatch:
    """One guarded hotkey pulse requested by the teleport controller."""

    anchor: TeleportAnchor
    virtual_key: int
    duration_seconds: float


class TeleportController:
    """Select an improving anchor once and await live-coordinate confirmation."""

    def __init__(self, config: TeleportConfig | None = None) -> None:
        self._config = config or TeleportConfig()
        self._status = TeleportStatus.IDLE
        self._pending: TeleportAnchor | None = None
        self._requested_at_seconds: float | None = None
        self._attempted_target: WorldPosition | None = None

    @property
    def status(self) -> TeleportStatus:
        return self._status

    @property
    def pending_anchor(self) -> TeleportAnchor | None:
        return self._pending

    def update(
        self,
        position: WorldPosition,
        target: WorldPosition,
        at_seconds: float,
    ) -> TeleportDispatch | None:
        """Confirm a pending jump or request one strictly beyond the configured threshold."""

        if self._pending is not None:
            if (
                position.distance_to(self._pending.position)
                <= self._config.confirmation_radius_units
            ):
                self._status = TeleportStatus.CONFIRMED
                self._pending = None
                self._requested_at_seconds = None
                return None
            requested_at = self._requested_at_seconds
            if (
                requested_at is not None
                and at_seconds - requested_at >= self._config.timeout_seconds
            ):
                self._status = TeleportStatus.UNAVAILABLE
                self._pending = None
                self._requested_at_seconds = None
            return None

        distance = position.distance_to(target)
        if not self._config.enabled or distance <= self._config.long_range_threshold_units:
            self._status = TeleportStatus.IDLE
            self._attempted_target = None
            return None
        attempted = self._attempted_target
        if (
            attempted is not None
            and attempted.distance_to(target) <= self._config.confirmation_radius_units
        ):
            return None
        anchor = min(
            self._config.anchors,
            key=lambda candidate: candidate.position.distance_to(target),
            default=None,
        )
        if anchor is None or anchor.position.distance_to(target) >= distance:
            self._status = TeleportStatus.UNAVAILABLE
            return None
        self._pending = anchor
        self._requested_at_seconds = at_seconds
        self._attempted_target = target
        self._status = TeleportStatus.WAITING_FOR_POSITION
        return TeleportDispatch(anchor, anchor.virtual_key, self._config.key_duration_seconds)

    def reset(self) -> None:
        """Cancel a pending request without dispatching anything."""

        self._status = TeleportStatus.IDLE
        self._pending = None
        self._requested_at_seconds = None
        self._attempted_target = None

    def reject_pending(self) -> None:
        """Fall back to ground pathing after a guarded dispatcher rejected the hotkey."""

        if self._pending is None:
            return
        self._status = TeleportStatus.UNAVAILABLE
        self._pending = None
        self._requested_at_seconds = None
