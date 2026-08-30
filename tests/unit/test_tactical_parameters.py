"""Bounded tactical parameter profiles, policy overrides, and controller integration."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

import pytest

from flyff_bot.features.automation.controllers import CombatController
from flyff_bot.features.automation.models import Position, VisibleMob, WorldState
from flyff_bot.features.automation.vitals_controller import (
    VitalsTriggerController,
    VitalTriggerType,
)
from flyff_bot.features.navigation.live_camera import CameraState
from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.navmesh import NavMeshBaker
from flyff_bot.features.navigation.pathing import PathingController
from flyff_bot.features.navigation.world_extractor import WorldCoordinate
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex
from flyff_bot.features.policy.action_payloads import AttackPointAction, StrategicGoalKind
from flyff_bot.features.policy.hierarchical_onnx import _select_attack_point
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext
from flyff_bot.features.policy.runner import PolicyFaultCode, PolicyRunner
from flyff_bot.features.rl.actions import TacticalActionCatalog
from flyff_bot.features.simulator import FarmingSimulator
from flyff_bot.features.simulator.engine import _TickAccounting
from flyff_bot.features.tactical_parameters import (
    DEFAULT_TACTICAL_PARAMETERS,
    TACTICAL_PARAMETER_DEFINITIONS,
    TACTICAL_PARAMETER_SCHEMA_VERSION,
    MonsterEngagementDistance,
    TacticalParameterDiagnosticCode,
    TacticalParameterName,
    TacticalParameterProfile,
    TacticalParameterSpace,
    TacticalProfileError,
    load_tactical_profile,
    save_tactical_profile,
)
from flyff_bot.i18n import Language, Message, Translator


def _state(mob: VisibleMob) -> WorldState:
    return WorldState(0.0, Position(0, 0), 1, 0, visible_mobs=(mob,))


def test_every_modifiable_field_has_one_immutable_bounded_definition() -> None:
    scalar_fields = {item.name for item in fields(TacticalParameterSpace)} - {
        "diagnostics",
        "engagement_distance_profiles",
    }

    assert scalar_fields == {name.value for name in TacticalParameterName}
    assert set(TACTICAL_PARAMETER_DEFINITIONS) == set(TacticalParameterName)
    for definition in TACTICAL_PARAMETER_DEFINITIONS.values():
        assert definition.minimum <= definition.default <= definition.maximum
        assert math.isfinite(definition.minimum)
        assert math.isfinite(definition.maximum)


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_non_finite_input_uses_the_safe_default_and_records_a_diagnostic(
    non_finite: float,
) -> None:
    parameters = TacticalParameterSpace(stall_timeout_seconds=non_finite)

    assert parameters.stall_timeout_seconds == (
        TACTICAL_PARAMETER_DEFINITIONS[TacticalParameterName.STALL_TIMEOUT_SECONDS].default
    )
    assert parameters.diagnostics[-1].code is (TacticalParameterDiagnosticCode.NON_FINITE_FALLBACK)
    assert parameters.diagnostics[-1].parameter is TacticalParameterName.STALL_TIMEOUT_SECONDS


def test_finite_outliers_clamp_and_monster_profiles_override_the_default() -> None:
    parameters = TacticalParameterSpace(
        engagement_distance_units=1000.0,
        engagement_distance_profiles=(MonsterEngagementDistance("Aibatt", -10.0),),
    )
    definition = TACTICAL_PARAMETER_DEFINITIONS[TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS]

    assert parameters.engagement_distance_units == definition.maximum
    assert parameters.engagement_distance_for("AIBATT") == definition.minimum
    assert parameters.engagement_distance_for("Mushpang") == definition.maximum
    assert all(
        item.code is TacticalParameterDiagnosticCode.OUT_OF_RANGE_CLAMPED
        for item in parameters.diagnostics
    )


def test_profile_round_trip_is_versioned_digest_checked_and_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "tactical-profile.json"
    profile = TacticalParameterProfile(
        "aibatt-flaris",
        TacticalParameterSpace(
            engagement_distance_profiles=(MonsterEngagementDistance("Aibatt", 4.5),)
        ),
    )

    save_tactical_profile(profile, path)
    first_bytes = path.read_bytes()
    loaded = load_tactical_profile(path)
    save_tactical_profile(loaded, path)

    assert path.read_bytes() == first_bytes
    assert loaded == profile
    document = json.loads(first_bytes)
    assert document["schema_version"] == TACTICAL_PARAMETER_SCHEMA_VERSION
    assert document["content_digest"] == profile.content_digest
    assert profile.parameters.content_digest != DEFAULT_TACTICAL_PARAMETERS.content_digest


def test_non_finite_config_file_value_defaults_after_its_raw_digest_is_verified(
    tmp_path: Path,
) -> None:
    path = tmp_path / "optimized.json"
    document = TacticalParameterProfile("optimizer-output").as_document()
    document.pop("content_digest")
    parameters = document["parameters"]
    assert isinstance(parameters, dict)
    parameters["camera_pitch_degrees"] = math.nan
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=True,
    ).encode("utf-8")
    document["content_digest"] = hashlib.sha256(canonical).hexdigest()
    path.write_text(json.dumps(document, allow_nan=True), encoding="utf-8")

    loaded = load_tactical_profile(path)

    assert (
        loaded.parameters.camera_pitch_degrees == DEFAULT_TACTICAL_PARAMETERS.camera_pitch_degrees
    )
    assert loaded.parameters.diagnostics[-1].code is (
        TacticalParameterDiagnosticCode.NON_FINITE_FALLBACK
    )


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "emergency_stop_key",
        "foreground_required",
        "memory_offset",
        "process_signature",
        "virtual_key",
        "schema_digest",
    ],
)
def test_system_invariants_are_rejected_by_the_positive_profile_allow_list(
    tmp_path: Path, forbidden_key: str
) -> None:
    path = tmp_path / "unsafe.json"
    profile = TacticalParameterProfile("unsafe")
    document = profile.as_document()
    parameters = document["parameters"]
    assert isinstance(parameters, dict)
    parameters[forbidden_key] = 1
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(TacticalProfileError, match="unknown_parameter"):
        load_tactical_profile(path)


def test_action_encoding_preserves_the_contextual_approach_distance() -> None:
    action = AttackPointAction(7, (1.0, 2.0, 3.0), 90.0, 2, 4.5)

    assert TacticalActionCatalog.decode(TacticalActionCatalog.encode(action)) == action


def test_learned_output_selects_one_exact_prevalidated_approach_option() -> None:
    near = AttackPointAction(7, (1.0, 0.0, 0.0), 0.0, 0, 2.0)
    far = AttackPointAction(7, (5.0, 0.0, 0.0), 0.0, 0, 6.0)

    assert _select_attack_point((far, near), 0.0) is near
    assert _select_attack_point((far, near), 1.0) is far


def test_pathing_executes_the_exact_prevalidated_attack_point() -> None:
    triangle = WorldTriangle(
        WorldVertex(-20.0, 0.0, -20.0),
        WorldVertex(20.0, 0.0, -20.0),
        WorldVertex(0.0, 0.0, 20.0),
        "fixture",
    )
    pathing = PathingController(navmesh=NavMeshBaker().bake((triangle,)))
    pathing._live_position = WorldPosition(0.0, 0.0, 0.0)
    pathing._camera_state = CameraState(yaw_radians=0.0)
    mob = VisibleMob(
        7,
        "Aibatt",
        0.9,
        10,
        20,
        20,
        10,
        world_x=8.0,
        world_y=0.0,
        world_z=0.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )

    assert pathing.begin_tactical_attack_point_approach(mob, (4.0, 0.0, 0.0), 1.0)
    assert pathing.navmesh_target == WorldPosition(4.0, 0.0, 0.0)
    assert not pathing.target_in_engagement_range()

    pathing._live_position = WorldPosition(4.0, 0.0, 0.0)
    assert pathing.target_in_engagement_range()


def test_non_finite_live_override_fails_closed_instead_of_using_a_default() -> None:
    mob = VisibleMob(
        7,
        "Aibatt",
        0.9,
        10,
        20,
        20,
        10,
        world_x=1.0,
        world_y=2.0,
        world_z=3.0,
        navmesh_reachable=True,
        navmesh_within_leash=True,
    )
    action = AttackPointAction(7, (1.0, 2.0, 3.0), 90.0, 0, math.nan)
    context = PolicyContext(
        (PolicyCandidate(mob, True, True, True, True, True, 0),),
        frozenset(),
        (False,),
        valid_attack_points=(action,),
    )

    class _NonFinitePolicy:
        def evaluate(
            self, world_state: WorldState, policy_context: PolicyContext
        ) -> AttackPointAction:
            return action

    runner = PolicyRunner(_NonFinitePolicy())

    assert runner.evaluate(_state(mob), context) is None
    assert runner.last_fault is not None
    assert runner.last_fault.code is PolicyFaultCode.INVALID_OR_MASKED_ACTION


def test_controllers_derive_their_operational_values_from_one_parameter_space() -> None:
    parameters = TacticalParameterSpace(
        navmesh_waypoint_arrival_units=4.0,
        heading_tolerance_degrees=12.0,
        heading_pivot_threshold_degrees=30.0,
        replan_interval_seconds=7.0,
        stall_timeout_seconds=3.0,
        attack_key_delay_seconds=0.2,
        target_lockout_seconds=6.0,
        click_debounce_seconds=0.7,
        hp_potion_threshold_percent=55.0,
        mp_threshold_percent=22.0,
        recovery_debounce_seconds=1.3,
    )
    pathing = PathingController(tactical_parameters=parameters)
    combat = CombatController(tactical_parameters=parameters)
    recovery = VitalsTriggerController(tactical_parameters=parameters)

    assert pathing._config.navmesh_waypoint_arrival_units == 4.0
    assert pathing._config.heading_pivot_threshold_degrees == 30.0
    assert pathing._config.stall.live_stall_timeout_seconds == 3.0
    assert combat._config.key_press_duration_seconds == 0.2
    assert combat._config.target_lockout_seconds == 6.0
    assert combat._config.click_debounce_seconds == 0.7
    assert recovery._config.rule_for(VitalTriggerType.HP).threshold_percentage == 55.0  # type: ignore[union-attr]
    assert recovery._config.rule_for(VitalTriggerType.MP).threshold_percentage == 22.0  # type: ignore[union-attr]
    assert recovery._config.rule_for(VitalTriggerType.HP).debounce_seconds == 1.3  # type: ignore[union-attr]


def test_simulator_accepts_profiles_and_reports_stall_rate(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    high_range = make_simulator(
        objectives=(),
        tactical_parameters=TacticalParameterSpace(engagement_distance_units=100.0),
    )
    target_index = list(StrategicGoalKind).index(StrategicGoalKind.TARGET)
    interact_index = list(StrategicGoalKind).index(StrategicGoalKind.INTERACT)

    high_range.step(target_index)
    assert high_range.action_mask[interact_index]
    for _tick in range(10):
        high_range.step(interact_index)
        if high_range.metrics.kill_count:
            break

    assert high_range.metrics.kill_count == 1
    assert high_range.metrics.stalls_per_minute >= 0.0


def test_simulator_does_not_snap_heading_for_free_inside_live_tolerance(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulator = make_simulator(
        objectives=(),
        tactical_parameters=TacticalParameterSpace(heading_tolerance_degrees=20.0),
    )
    simulator._heading = 0.0
    waypoint = WorldCoordinate(
        simulator._x + math.cos(math.radians(10.0)),
        simulator._z + math.sin(math.radians(10.0)),
    )
    tick = _TickAccounting()

    remaining = simulator._turn_toward(waypoint, 1.0, tick)

    assert remaining == 1.0
    assert simulator._heading == 0.0
    assert tick.travel_seconds == 0.0


def test_parameter_validation_diagnostics_are_localized_in_both_languages() -> None:
    diagnostic = TacticalParameterSpace(camera_pitch_degrees=math.inf).diagnostics[-1]
    texts = {
        language: Translator(language).text(
            Message.UI_TACTICAL_NON_FINITE_FALLBACK,
            parameter=Translator(language).text(Message.UI_TACTICAL_CAMERA_PITCH),
            received=diagnostic.received,
            applied=diagnostic.applied,
        )
        for language in Language
    }

    assert set(texts) == set(Language)
    assert len(set(texts.values())) == len(Language)
    assert all(
        str(DEFAULT_TACTICAL_PARAMETERS.camera_pitch_degrees) in text for text in texts.values()
    )
