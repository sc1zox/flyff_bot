"""Comparison of simulated aggregates against fitted telemetry baselines."""

from __future__ import annotations

from dataclasses import dataclass

from flyff_bot.features.simulator.models import (
    CalibrationBaseline,
    CalibrationTolerance,
    SimulationMetrics,
)


class CalibrationError(ValueError):
    """Raised when simulated behavior misses its empirical acceptance bounds."""


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    kills_per_minute_error_fraction: float
    travel_time_error_fraction: float


def validate_calibration(
    metrics: SimulationMetrics,
    baseline: CalibrationBaseline,
    tolerance: CalibrationTolerance | None = None,
) -> CalibrationResult:
    """Reject KPM or mean navigation-time drift beyond the configured fraction."""

    limits = tolerance or CalibrationTolerance()
    kpm_error = (
        abs(metrics.kills_per_minute - baseline.kills_per_minute) / baseline.kills_per_minute
    )
    travel_error = (
        abs(metrics.mean_travel_seconds - baseline.mean_travel_seconds)
        / baseline.mean_travel_seconds
        if baseline.mean_travel_seconds > 0.0
        else 0.0
    )
    result = CalibrationResult(kpm_error, travel_error)
    if kpm_error > limits.kills_per_minute_fraction:
        raise CalibrationError("Simulated kills per minute exceeded the calibration tolerance.")
    if travel_error > limits.travel_time_fraction:
        raise CalibrationError("Simulated travel time exceeded the calibration tolerance.")
    return result
