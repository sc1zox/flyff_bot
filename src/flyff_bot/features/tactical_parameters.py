"""Versioned, bounded tactical parameters shared by offline and live control.

Only operational heuristics belong here.  System invariants such as virtual-key codes,
process fingerprints, memory offsets, focus guards, emergency-stop handling and schema
digests deliberately have no representation in this module (US-084).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum, unique
from pathlib import Path
from types import MappingProxyType

TACTICAL_PARAMETER_SCHEMA_VERSION = "us084-v1"
TACTICAL_PROFILE_FILENAME = "tactical-profile.json"
DEFAULT_TACTICAL_PROFILE_NAME = "default"


@unique
class TacticalParameterName(StrEnum):
    NAVMESH_WAYPOINT_ARRIVAL_UNITS = "navmesh_waypoint_arrival_units"
    HEADING_TOLERANCE_DEGREES = "heading_tolerance_degrees"
    HEADING_PIVOT_THRESHOLD_DEGREES = "heading_pivot_threshold_degrees"
    REPLAN_INTERVAL_SECONDS = "replan_interval_seconds"
    STALL_TIMEOUT_SECONDS = "stall_timeout_seconds"
    ENGAGEMENT_DISTANCE_UNITS = "engagement_distance_units"
    ATTACK_KEY_DELAY_SECONDS = "attack_key_delay_seconds"
    TARGET_LOCKOUT_SECONDS = "target_lockout_seconds"
    CLICK_DEBOUNCE_SECONDS = "click_debounce_seconds"
    CAMERA_PITCH_DEGREES = "camera_pitch_degrees"
    CAMERA_ZOOM_LEVEL = "camera_zoom_level"
    SEARCH_TURN_DURATION_SECONDS = "search_turn_duration_seconds"
    TARGET_VERIFICATION_THRESHOLD = "target_verification_threshold"
    HP_POTION_THRESHOLD_PERCENT = "hp_potion_threshold_percent"
    MP_THRESHOLD_PERCENT = "mp_threshold_percent"
    RECOVERY_DEBOUNCE_SECONDS = "recovery_debounce_seconds"


@dataclass(frozen=True, slots=True)
class TacticalParameterDefinition:
    """Immutable safe range and fallback for one tunable scalar."""

    name: TacticalParameterName
    minimum: float
    maximum: float
    default: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.minimum, self.maximum, self.default)):
            raise ValueError("Tactical parameter definitions must be finite.")
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError("Tactical parameter defaults must lie inside their bounds.")

    def normalize(self, value: float) -> tuple[float, TacticalParameterDiagnosticCode | None]:
        """Return a finite, clamped value and the diagnostic it required, if any."""

        if not math.isfinite(value):
            return self.default, TacticalParameterDiagnosticCode.NON_FINITE_FALLBACK
        clamped = min(max(value, self.minimum), self.maximum)
        return clamped, (
            None if clamped == value else TacticalParameterDiagnosticCode.OUT_OF_RANGE_CLAMPED
        )


_DEFINITIONS = (
    TacticalParameterDefinition(
        TacticalParameterName.NAVMESH_WAYPOINT_ARRIVAL_UNITS, 0.1, 20.0, 1.5
    ),
    TacticalParameterDefinition(TacticalParameterName.HEADING_TOLERANCE_DEGREES, 1.0, 45.0, 25.0),
    TacticalParameterDefinition(
        TacticalParameterName.HEADING_PIVOT_THRESHOLD_DEGREES, 10.0, 179.0, 45.0
    ),
    TacticalParameterDefinition(TacticalParameterName.REPLAN_INTERVAL_SECONDS, 0.1, 60.0, 20.0),
    TacticalParameterDefinition(TacticalParameterName.STALL_TIMEOUT_SECONDS, 0.5, 30.0, 2.0),
    TacticalParameterDefinition(TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS, 0.1, 100.0, 3.0),
    TacticalParameterDefinition(TacticalParameterName.ATTACK_KEY_DELAY_SECONDS, 0.01, 1.0, 0.05),
    TacticalParameterDefinition(TacticalParameterName.TARGET_LOCKOUT_SECONDS, 0.0, 30.0, 1.0),
    TacticalParameterDefinition(TacticalParameterName.CLICK_DEBOUNCE_SECONDS, 0.0, 5.0, 0.2),
    TacticalParameterDefinition(TacticalParameterName.CAMERA_PITCH_DEGREES, 10.0, 80.0, 45.0),
    TacticalParameterDefinition(TacticalParameterName.CAMERA_ZOOM_LEVEL, 1.0, 20.0, 20.0),
    TacticalParameterDefinition(TacticalParameterName.SEARCH_TURN_DURATION_SECONDS, 0.05, 2.0, 0.2),
    TacticalParameterDefinition(
        TacticalParameterName.TARGET_VERIFICATION_THRESHOLD, 0.3, 1.0, 0.75
    ),
    TacticalParameterDefinition(TacticalParameterName.HP_POTION_THRESHOLD_PERCENT, 1.0, 99.0, 70.0),
    TacticalParameterDefinition(TacticalParameterName.MP_THRESHOLD_PERCENT, 1.0, 99.0, 30.0),
    TacticalParameterDefinition(TacticalParameterName.RECOVERY_DEBOUNCE_SECONDS, 0.1, 30.0, 0.8),
)
TACTICAL_PARAMETER_DEFINITIONS: Mapping[TacticalParameterName, TacticalParameterDefinition] = (
    MappingProxyType({definition.name: definition for definition in _DEFINITIONS})
)


@unique
class TacticalParameterDiagnosticCode(StrEnum):
    NON_FINITE_FALLBACK = "non_finite_fallback"
    OUT_OF_RANGE_CLAMPED = "out_of_range_clamped"


@dataclass(frozen=True, slots=True)
class TacticalParameterDiagnostic:
    """One validation event retained for telemetry and localized presentation."""

    code: TacticalParameterDiagnosticCode
    parameter: TacticalParameterName
    received: float
    applied: float


@dataclass(frozen=True, slots=True)
class MonsterEngagementDistance:
    """One exact monster-class override inside a tactical profile."""

    monster_class_name: str
    distance_units: float

    def __post_init__(self) -> None:
        if not self.monster_class_name.strip():
            raise ValueError("A monster engagement override needs a class name.")


@dataclass(frozen=True, slots=True)
class TacticalParameterSpace:
    """The complete ML-modifiable operational parameter vector.

    Construction is itself the validation boundary: finite outliers are clamped and non-finite
    values fall back to the immutable safe default.  The resulting diagnostics remain attached
    to the value object so config, simulator and policy callers cannot accidentally discard them.
    """

    navmesh_waypoint_arrival_units: float = 1.5
    heading_tolerance_degrees: float = 25.0
    heading_pivot_threshold_degrees: float = 45.0
    replan_interval_seconds: float = 20.0
    stall_timeout_seconds: float = 2.0
    engagement_distance_units: float = 3.0
    attack_key_delay_seconds: float = 0.05
    target_lockout_seconds: float = 1.0
    click_debounce_seconds: float = 0.2
    camera_pitch_degrees: float = 45.0
    camera_zoom_level: float = 20.0
    search_turn_duration_seconds: float = 0.2
    target_verification_threshold: float = 0.75
    hp_potion_threshold_percent: float = 70.0
    mp_threshold_percent: float = 30.0
    recovery_debounce_seconds: float = 0.8
    engagement_distance_profiles: tuple[MonsterEngagementDistance, ...] = ()
    diagnostics: tuple[TacticalParameterDiagnostic, ...] = field(
        default=(), compare=False, repr=False
    )

    def __post_init__(self) -> None:
        diagnostics = list(self.diagnostics)
        for definition in _DEFINITIONS:
            raw = float(getattr(self, definition.name.value))
            value, code = definition.normalize(raw)
            object.__setattr__(self, definition.name.value, value)
            if code is not None:
                diagnostics.append(TacticalParameterDiagnostic(code, definition.name, raw, value))

        normalized_profiles: list[MonsterEngagementDistance] = []
        seen: set[str] = set()
        engagement = TACTICAL_PARAMETER_DEFINITIONS[TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS]
        for profile in self.engagement_distance_profiles:
            normalized_name = profile.monster_class_name.strip().casefold()
            if normalized_name in seen:
                raise ValueError("Monster engagement profile names must be unique.")
            seen.add(normalized_name)
            value, code = engagement.normalize(float(profile.distance_units))
            normalized_profiles.append(
                MonsterEngagementDistance(profile.monster_class_name.strip(), value)
            )
            if code is not None:
                diagnostics.append(
                    TacticalParameterDiagnostic(
                        code,
                        TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS,
                        float(profile.distance_units),
                        value,
                    )
                )
        object.__setattr__(self, "engagement_distance_profiles", tuple(normalized_profiles))
        object.__setattr__(self, "diagnostics", tuple(diagnostics))

        if self.heading_pivot_threshold_degrees < self.heading_tolerance_degrees:
            received_pivot = self.heading_pivot_threshold_degrees
            pivot = self.heading_tolerance_degrees
            object.__setattr__(self, "heading_pivot_threshold_degrees", pivot)
            diagnostics.append(
                TacticalParameterDiagnostic(
                    TacticalParameterDiagnosticCode.OUT_OF_RANGE_CLAMPED,
                    TacticalParameterName.HEADING_PIVOT_THRESHOLD_DEGREES,
                    received_pivot,
                    pivot,
                )
            )
            object.__setattr__(self, "diagnostics", tuple(diagnostics))

    def engagement_distance_for(self, monster_class_name: str | None) -> float:
        """Return the exact class override or the profile's bounded default."""

        if monster_class_name is None:
            return self.engagement_distance_units
        wanted = monster_class_name.casefold()
        return next(
            (
                item.distance_units
                for item in self.engagement_distance_profiles
                if item.monster_class_name.casefold() == wanted
            ),
            self.engagement_distance_units,
        )

    def with_value(self, name: TacticalParameterName, value: float) -> TacticalParameterSpace:
        """Return a new validated parameter vector with one scalar replaced."""

        values = self.as_values_document()
        values[name.value] = value
        return _parameters_from_document(values)

    def as_values_document(self) -> dict[str, object]:
        """Return only the ML-modifiable values, never system invariants."""

        values = {
            definition.name.value: getattr(self, definition.name.value)
            for definition in _DEFINITIONS
        }
        values["engagement_distance_profiles"] = {
            item.monster_class_name: item.distance_units
            for item in self.engagement_distance_profiles
        }
        return values

    @property
    def content_digest(self) -> str:
        """Identify the exact bounded vector independently of a UI profile name."""

        return _profile_digest(
            {
                "schema_version": TACTICAL_PARAMETER_SCHEMA_VERSION,
                "parameters": self.as_values_document(),
            }
        )


DEFAULT_TACTICAL_PARAMETERS = TacticalParameterSpace()


@dataclass(frozen=True, slots=True)
class TacticalParameterProfile:
    """One model-registry-compatible, versioned tactical profile."""

    profile_name: str
    parameters: TacticalParameterSpace = DEFAULT_TACTICAL_PARAMETERS
    schema_version: str = TACTICAL_PARAMETER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TACTICAL_PARAMETER_SCHEMA_VERSION:
            raise TacticalProfileError(
                f"unsupported_schema:{self.schema_version}:expected={TACTICAL_PARAMETER_SCHEMA_VERSION}"
            )
        if not self.profile_name.strip():
            raise TacticalProfileError("profile_name_missing")

    def as_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "schema_version": self.schema_version,
            "profile_name": self.profile_name,
            "parameters": self.parameters.as_values_document(),
        }
        document["content_digest"] = _profile_digest(document)
        return document

    @property
    def content_digest(self) -> str:
        """Return the stable digest a later model-registry entry can reference."""

        return str(self.as_document()["content_digest"])


class TacticalProfileError(ValueError):
    """A profile is not the current strict tactical-parameter contract."""


def save_tactical_profile(profile: TacticalParameterProfile, path: Path) -> None:
    """Write one deterministic UTF-8 JSON profile for offline promotion or UI export."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile.as_document(), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_tactical_profile(path: Path) -> TacticalParameterProfile:
    """Read the current profile schema strictly, with no legacy compatibility path."""

    try:
        document: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TacticalProfileError(f"profile_unreadable:{path}") from error
    if not isinstance(document, dict):
        raise TacticalProfileError("profile_root_invalid")
    schema_version = document.get("schema_version")
    if schema_version != TACTICAL_PARAMETER_SCHEMA_VERSION:
        raise TacticalProfileError(
            f"unsupported_schema:{schema_version}:expected={TACTICAL_PARAMETER_SCHEMA_VERSION}"
        )
    name = document.get("profile_name")
    values = document.get("parameters")
    if not isinstance(name, str) or not isinstance(values, dict):
        raise TacticalProfileError("profile_fields_invalid")
    parameters = _parameters_from_document(values)
    found_digest = document.get("content_digest")
    digest_document = dict(document)
    digest_document.pop("content_digest", None)
    if not isinstance(found_digest, str) or found_digest != _profile_digest(digest_document):
        raise TacticalProfileError("profile_digest_mismatch")
    return TacticalParameterProfile(name, parameters)


def _parameters_from_document(values: Mapping[str, object]) -> TacticalParameterSpace:
    allowed = {definition.name.value for definition in _DEFINITIONS} | {
        "engagement_distance_profiles"
    }
    unknown = sorted(str(key) for key in values if not isinstance(key, str) or key not in allowed)
    if unknown:
        raise TacticalProfileError(f"unknown_parameter:{','.join(unknown)}")
    kwargs: dict[str, object] = {}
    for definition in _DEFINITIONS:
        raw = values.get(definition.name.value, definition.default)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise TacticalProfileError(f"parameter_not_numeric:{definition.name.value}")
        kwargs[definition.name.value] = float(raw)
    profiles = values.get("engagement_distance_profiles", {})
    if not isinstance(profiles, dict):
        raise TacticalProfileError("engagement_profiles_invalid")
    parsed_profiles: list[MonsterEngagementDistance] = []
    for name, raw in profiles.items():
        if not isinstance(name, str) or isinstance(raw, bool) or not isinstance(raw, int | float):
            raise TacticalProfileError("engagement_profile_invalid")
        parsed_profiles.append(MonsterEngagementDistance(name, float(raw)))
    kwargs["engagement_distance_profiles"] = tuple(parsed_profiles)
    # The dataclass fields are the canonical allow-list; this assertion prevents a future field
    # from silently becoming profile-modifiable without a bounded definition.
    modifiable = {item.name for item in fields(TacticalParameterSpace)} - {
        "diagnostics",
        "engagement_distance_profiles",
    }
    if modifiable != {definition.name.value for definition in _DEFINITIONS}:
        raise RuntimeError("Tactical parameter fields and definitions are out of sync.")
    return TacticalParameterSpace(**kwargs)  # type: ignore[arg-type]


def _profile_digest(document: Mapping[str, object]) -> str:
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
