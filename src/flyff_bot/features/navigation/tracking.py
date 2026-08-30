"""Stall detection from authoritative live world-position displacement."""

from __future__ import annotations

from dataclasses import dataclass

from flyff_bot.features.navigation.live_position import WorldPosition

DEFAULT_LIVE_MOTION_THRESHOLD_UNITS_PER_SECOND = 0.5
DEFAULT_LIVE_STALL_TIMEOUT_SECONDS = 2.0
DEFAULT_MOVEMENT_GRACE_SECONDS = 2.0
MAXIMUM_STALL_SAMPLE_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class StallConfig:
    """Thresholds for authoritative position-based stall detection."""

    live_motion_threshold_units_per_second: float = DEFAULT_LIVE_MOTION_THRESHOLD_UNITS_PER_SECOND
    live_stall_timeout_seconds: float = DEFAULT_LIVE_STALL_TIMEOUT_SECONDS
    movement_grace_seconds: float = DEFAULT_MOVEMENT_GRACE_SECONDS

    def __post_init__(self) -> None:
        if self.live_motion_threshold_units_per_second <= 0.0:
            raise ValueError("Live stall motion threshold must be positive.")
        if self.live_stall_timeout_seconds <= 0.0:
            raise ValueError("Live stall timeout must be positive.")
        if self.movement_grace_seconds < 0.0:
            raise ValueError("Stall movement grace must not be negative.")


class StallDetector:
    """Report a stall only from commanded movement and measured world displacement."""

    def __init__(self, config: StallConfig | None = None) -> None:
        self._config = config or StallConfig()
        self._stalled_seconds = 0.0
        self._commanded_at_seconds: float | None = None
        self._live_position: WorldPosition | None = None
        self._live_at_seconds: float | None = None

    @property
    def is_stalled(self) -> bool:
        return self._stalled_seconds >= self._config.live_stall_timeout_seconds

    @property
    def stalled_seconds(self) -> float:
        return self._stalled_seconds

    def reset(self) -> None:
        self._stalled_seconds = 0.0
        self._commanded_at_seconds = None
        self._live_position = None
        self._live_at_seconds = None

    def observe(
        self,
        *,
        movement_commanded: bool = True,
        at_seconds: float,
        live_position: WorldPosition | None,
        live_sampled_at_seconds: float | None = None,
    ) -> bool:
        """Return the current verdict; missing live evidence never creates a stall."""

        if live_position is None:
            self._live_position = None
            self._live_at_seconds = None
            self._stalled_seconds = 0.0
            return False
        sampled_at = at_seconds if live_sampled_at_seconds is None else live_sampled_at_seconds
        previous = self._live_position
        previous_at = self._live_at_seconds
        self._live_position = live_position
        self._live_at_seconds = sampled_at
        gated = self._gate(movement_commanded, sampled_at)
        if gated is not None:
            return gated
        if previous is None or previous_at is None:
            self._stalled_seconds = 0.0
            return False
        elapsed = min(max(0.0, sampled_at - previous_at), MAXIMUM_STALL_SAMPLE_SECONDS)
        if elapsed <= 0.0:
            return self.is_stalled
        speed = live_position.distance_to(previous) / elapsed
        if speed < self._config.live_motion_threshold_units_per_second:
            self._stalled_seconds += elapsed
        else:
            self._stalled_seconds = 0.0
        return self.is_stalled

    def _gate(self, movement_commanded: bool, at_seconds: float) -> bool | None:
        if movement_commanded:
            self._commanded_at_seconds = at_seconds
            return None
        if self._commanded_at_seconds is not None and (
            at_seconds - self._commanded_at_seconds <= self._config.movement_grace_seconds
        ):
            return self.is_stalled
        self._stalled_seconds = 0.0
        return False
