"""What one recorded decision has to carry for US-081 to learn from it (US-083 AC10)."""

from __future__ import annotations

from flyff_bot.features.telemetry.models import (
    CandidateFeatures,
    DecisionProvenance,
    TargetDecision,
    WorldSnapshot,
    primitive,
)

TIMESTAMP_NS = 1_000
MODEL_ARTIFACT_VERSION = "us083-v2"
MOVER_ID = 1101
MAPPING_VERSION = "3"


def _record(value: object) -> dict[str, object]:
    """Return one serialized telemetry record, narrowed for indexing."""

    recorded = primitive(value)
    assert isinstance(recorded, dict)
    return recorded


def _candidate(
    *,
    mover_id: int | None = None,
    mover_symbol: str | None = None,
    mapping_version: str | None = None,
) -> CandidateFeatures:
    return CandidateFeatures(
        candidate_index=0,
        class_id=1,
        class_name="Aibatt",
        confidence=0.9,
        x=0,
        y=0,
        width=10,
        height=10,
        center_x=5.0,
        center_y=5.0,
        screen_distance_to_center=1.0,
        bbox_area=100,
        world_position=None,
        relative_distance=None,
        relative_elevation=None,
        target_navmesh_polygon_id=None,
        path_distance=None,
        is_locked_out=False,
        mover_id=mover_id,
        mover_symbol=mover_symbol,
        catalog_mapping_version=mapping_version,
    )


def test_a_candidate_carries_the_mover_it_joined_and_the_artifact_that_bound_it() -> None:
    joined = _candidate(
        mover_id=MOVER_ID, mover_symbol="MI_AIBATT", mapping_version=MAPPING_VERSION
    )

    recorded = _record(joined)

    assert recorded["mover_id"] == MOVER_ID
    assert recorded["mover_symbol"] == "MI_AIBATT"
    assert recorded["catalog_mapping_version"] == MAPPING_VERSION


def test_an_unjoined_candidate_records_no_mapping_rather_than_a_placeholder() -> None:
    # All three absent together is what lets a replay tell an unmapped candidate apart from
    # one mapped by an artifact that has since been replaced.
    recorded = _record(_candidate())

    assert recorded["mover_id"] is None
    assert recorded["mover_symbol"] is None
    assert recorded["catalog_mapping_version"] is None


def test_a_decision_names_the_artifact_that_produced_it_and_the_mask_it_had() -> None:
    decision = TargetDecision(
        timestamp_ns=TIMESTAMP_NS,
        player_position=None,
        selected_candidate_index=0,
        decision_reason="policy_ml_active",
        decision_latency_ms=12.0,
        candidates=(_candidate(mover_id=MOVER_ID),),
        model_artifact_version=MODEL_ARTIFACT_VERSION,
        action_mask=(True, False, False, True),
    )

    recorded = _record(decision)

    assert recorded["model_artifact_version"] == MODEL_ARTIFACT_VERSION
    # The same action is a good decision among three options and a forced one among one, so
    # the mask has to travel with the choice.
    assert recorded["action_mask"] == [True, False, False, True]


def test_a_deterministic_decision_names_no_model() -> None:
    # The heuristic path is not a model; giving it a version would let a promotion report
    # compare it against one.
    decision = TargetDecision(
        timestamp_ns=TIMESTAMP_NS,
        player_position=None,
        selected_candidate_index=0,
        decision_reason="shortest_navmesh_path",
        decision_latency_ms=3.0,
        candidates=(_candidate(),),
    )

    assert _record(decision)["model_artifact_version"] == ""


def test_the_decision_time_snapshot_carries_freshness_and_fusion_without_outcomes() -> None:
    # Everything here is knowable at the moment of the decision. Nothing that is only known
    # afterwards belongs on this record, which is what "no post-decision leakage" means.
    snapshot = WorldSnapshot(
        timestamp_ns=TIMESTAMP_NS,
        player_position=None,
        player_velocity=None,
        player_speed=None,
        position_source="live",
        player_navmesh_polygon_id=None,
        player_terrain_slope=None,
        hp_percentage=80.0,
        mp_percentage=50.0,
        fp_percentage=40.0,
        buff_cooldowns={},
        farming_mode="searching",
        visible_mob_count=2,
        readiness_state="ready",
        readiness_primary_reason=None,
        failed_source_codes=(),
        sample_ages_seconds=(("camera", 0.02),),
        action_blocked=False,
        provenance=DecisionProvenance(is_authoritative=True, observation_interval_rejection=None),
    )

    recorded = _record(snapshot)

    assert recorded["sample_ages_seconds"] == [["camera", 0.02]]
    provenance = recorded["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["is_authoritative"] is True
    # No outcome fields exist on the decision-time record at all.
    assert "verified_kill" not in recorded
    assert "reward" not in recorded
