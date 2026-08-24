"""Asynchronous farming telemetry, operational storage, and offline dataset export.

``geometry`` is deliberately absent from this aggregate. It is shared with the navigation
layer, which telemetry itself depends on, so re-exporting it here would make importing the
telemetry package first -- as the offline value-model trainer does -- a circular import.
Import :mod:`flyff_bot.features.telemetry.geometry` directly instead.
"""

from flyff_bot.features.telemetry.exporter import TelemetryDatasetExporter
from flyff_bot.features.telemetry.kinematics import KinematicsDeriver
from flyff_bot.features.telemetry.models import (
    TELEMETRY_SCHEMA_VERSION,
    TRAJECTORY_SCHEMA_VERSION,
    AttackAction,
    CandidateFeatures,
    CombatEpisode,
    CombatVerificationSource,
    KillCycle,
    NavigationEpisode,
    TelemetryEventKind,
    TelemetryPosition,
    TelemetrySessionMetadata,
    TelemetryVelocity,
    WorldSnapshot,
)
from flyff_bot.features.telemetry.recorder import TelemetryRecorder
from flyff_bot.features.telemetry.storage import JsonlTelemetryWorker, SqliteTelemetryStore

__all__ = [
    "TELEMETRY_SCHEMA_VERSION",
    "TRAJECTORY_SCHEMA_VERSION",
    "AttackAction",
    "CandidateFeatures",
    "CombatEpisode",
    "CombatVerificationSource",
    "JsonlTelemetryWorker",
    "KillCycle",
    "KinematicsDeriver",
    "NavigationEpisode",
    "SqliteTelemetryStore",
    "TelemetryDatasetExporter",
    "TelemetryEventKind",
    "TelemetryPosition",
    "TelemetryRecorder",
    "TelemetrySessionMetadata",
    "TelemetryVelocity",
    "WorldSnapshot",
]
