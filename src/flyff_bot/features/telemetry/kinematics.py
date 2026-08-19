"""Numerically stable world-space kinematics for telemetry snapshots."""

from __future__ import annotations

from flyff_bot.features.telemetry.models import TelemetryPosition, TelemetryVelocity


class KinematicsDeriver:
    """Derive velocity only from consecutive monotonic live-coordinate samples."""

    def __init__(self) -> None:
        self._previous: tuple[int, TelemetryPosition] | None = None

    def observe(
        self, timestamp_ns: int, position: TelemetryPosition | None
    ) -> TelemetryVelocity | None:
        """Return a velocity or ``None`` for absent, first, or non-monotonic observations."""

        if position is None:
            self._previous = None
            return None
        previous = self._previous
        self._previous = (timestamp_ns, position)
        if previous is None or timestamp_ns <= previous[0]:
            return None
        elapsed_seconds = (timestamp_ns - previous[0]) / 1_000_000_000
        return TelemetryVelocity(
            (position.x - previous[1].x) / elapsed_seconds,
            (position.y - previous[1].y) / elapsed_seconds,
            (position.z - previous[1].z) / elapsed_seconds,
        )
