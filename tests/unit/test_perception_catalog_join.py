"""Authoritative client enrichment of a perception tick's own detections (US-083)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flyff_bot.features.automation.models import (
    InventoryEntry,
    PlayerVitals,
    Position,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.client_data.label_mapping import (
    LabelJoinRejection,
    LabelJoinRejectionReason,
    MoverLabelBinding,
    MoverLabelMapping,
    SpawnEvidence,
    join_detected_candidates,
    spawn_evidence_by_mover,
)
from flyff_bot.features.client_data.models import (
    ClientCatalog,
    DropRecord,
    MoverCombatProperties,
    MoverRecord,
)
from flyff_bot.features.client_data.persistence import (
    CatalogSchemaError,
    load_mover_label_mapping,
    save_client_catalog,
    save_mover_label_mapping,
    save_source_manifest,
)
from flyff_bot.features.client_data.sources import build_source_manifest
from flyff_bot.features.perception.catalog_join import MobCatalogJoin, load_mob_catalog_join
from flyff_bot.features.perception.pipeline import PerceptionPipeline
from flyff_bot.features.vision import (
    BoundingBox,
    CapturedFrame,
    ClientSize,
    Detection,
    DetectionError,
    DetectionErrorCode,
    TargetStatus,
    TargetVerificationResult,
)

CLIENT_DIGEST = "8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5"
FOREIGN_DIGEST = "1111111111111111111111111111111111111111111111111111111111111111"
WINDOW_HANDLE = 42
OBSERVED_AT_SECONDS = 12.5
FRAME = CapturedFrame(np.zeros((4, 4, 3), dtype=np.uint8), ClientSize(4, 4))
FLAME_MOVER_ID = 1453
MINIMUSH_MOVER_ID = 1455


class _FrameSource:
    def capture(self, window_handle: int) -> CapturedFrame:
        return FRAME


class _Detector:
    def __init__(self, result: list[Detection] | Exception) -> None:
        self.result = result

    def detect(self, frame: CapturedFrame) -> list[Detection]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _TargetVerifier:
    def verify(self, frame: CapturedFrame) -> TargetVerificationResult:
        return TargetVerificationResult(TargetStatus.NO_TARGET, None, 0)


class _SpawnZone:
    """The three spawn columns the join reads from an extracted world zone."""

    def __init__(self, monster_id: int, capacity: int, respawn_seconds: int) -> None:
        self.monster_id = monster_id
        self.capacity = capacity
        self.respawn_seconds = respawn_seconds


def _catalog() -> ClientCatalog:
    return ClientCatalog(
        movers=(
            MoverRecord("MI_FLAME", "Flame", MoverCombatProperties(level=15, hit_points=560)),
            MoverRecord("MI_MINIMUSH", "MiniMush", MoverCombatProperties(level=3)),
        ),
        drops=(DropRecord("MI_FLAME", "II_STONE", 700, 1, 3),),
    )


def _mapping(digest: str = CLIENT_DIGEST) -> MoverLabelMapping:
    return MoverLabelMapping(
        bindings=(
            MoverLabelBinding("Flame", FLAME_MOVER_ID, "MI_FLAME"),
            MoverLabelBinding("MiniMush", MINIMUSH_MOVER_ID, "MI_MINIMUSH"),
        ),
        client_digest=digest,
    )


def _join() -> MobCatalogJoin:
    return MobCatalogJoin(_mapping(), _catalog())


def _mob(candidate_index: int = 0, class_name: str = "Flame") -> VisibleMob:
    return VisibleMob(0, class_name, 0.9, 1, 2, 3, 4, candidate_index=candidate_index)


def _previous_state(
    visible_mobs: tuple[VisibleMob, ...] = (),
    mob_catalog_joins: tuple[object, ...] = (),
) -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(3, 4),
        nearby_mob_count=0,
        inventory=(InventoryEntry("potion", 2),),
        progress_marker=9,
        player_vitals=PlayerVitals(0.0, 0.0, 0.0),
        visible_mobs=visible_mobs,
        mob_catalog_joins=mob_catalog_joins,  # type: ignore[arg-type]
    )


def _pipeline(detector: _Detector) -> PerceptionPipeline:
    return PerceptionPipeline(
        _FrameSource(), detector, _TargetVerifier(), clock=lambda: OBSERVED_AT_SECONDS
    )


def _detection(class_id: int, class_name: str) -> Detection:
    return Detection(BoundingBox(1, 2, 3, 4), 0.9, class_id, class_name)


def _artifacts(
    directory: Path, *, mapping: MoverLabelMapping, digest: str
) -> tuple[Path, Path, Path]:
    catalog_path = directory / "catalog.json"
    mapping_path = directory / "mover_label_mapping.json"
    manifest_path = directory / "source_manifest.json"
    save_client_catalog(_catalog(), catalog_path)
    save_mover_label_mapping(mapping, mapping_path)
    save_source_manifest(build_source_manifest(_catalog(), client_digest=digest), manifest_path)
    return catalog_path, mapping_path, manifest_path


def test_spawn_evidence_aggregates_every_zone_of_one_mover() -> None:
    evidence = spawn_evidence_by_mover(
        (
            _SpawnZone(FLAME_MOVER_ID, 8, 60),
            _SpawnZone(FLAME_MOVER_ID, 4, 45),
            _SpawnZone(MINIMUSH_MOVER_ID, 6, 30),
        )
    )

    assert evidence[FLAME_MOVER_ID] == SpawnEvidence(2, 12, 45)
    assert evidence[MINIMUSH_MOVER_ID] == SpawnEvidence(1, 6, 30)


def test_a_mover_the_loaded_world_never_declares_has_no_spawn_evidence() -> None:
    joined, _rejections = join_detected_candidates(
        {0: "Flame"},
        _mapping(),
        _catalog(),
        spawn_evidence_by_mover((_SpawnZone(MINIMUSH_MOVER_ID, 6, 30),)),
    )

    assert joined[0].spawn is None


def test_a_tick_gives_every_detection_its_own_candidate_identity() -> None:
    detector = _Detector([_detection(0, "Flame"), _detection(0, "Flame")])

    tick = _pipeline(detector).tick(WINDOW_HANDLE, _previous_state())

    assert [mob.candidate_index for mob in tick.state.visible_mobs] == [0, 1]


def test_a_tick_enriches_each_detection_with_its_authoritative_mover() -> None:
    pipeline = _pipeline(_Detector([_detection(2, "MiniMush"), _detection(0, "Flame")]))
    pipeline.attach_client_catalog(_join())
    pipeline.attach_spawn_zones((_SpawnZone(FLAME_MOVER_ID, 8, 60),))

    state = pipeline.tick(WINDOW_HANDLE, _previous_state()).state

    minimush = state.catalog_join(0)
    flame = state.catalog_join(1)
    assert minimush is not None
    assert flame is not None
    assert minimush.mover_id == MINIMUSH_MOVER_ID
    assert flame.mover_symbol == "MI_FLAME"
    assert flame.display_name == "Flame"
    assert flame.combat == MoverCombatProperties(level=15, hit_points=560)
    assert flame.drops == (DropRecord("MI_FLAME", "II_STONE", 700, 1, 3),)
    assert flame.spawn == SpawnEvidence(1, 8, 60)
    assert minimush.spawn is None
    assert state.mob_catalog_rejections == ()


def test_two_mobs_of_one_class_are_enriched_as_separate_instances() -> None:
    pipeline = _pipeline(_Detector([_detection(0, "Flame"), _detection(0, "Flame")]))
    pipeline.attach_client_catalog(_join())

    state = pipeline.tick(WINDOW_HANDLE, _previous_state()).state

    assert [join.candidate_index for join in state.mob_catalog_joins] == [0, 1]
    assert {join.mover_id for join in state.mob_catalog_joins} == {FLAME_MOVER_ID}


def test_an_unmapped_class_is_rejected_once_rather_than_joined_to_a_similar_mover() -> None:
    pipeline = _pipeline(_Detector([_detection(5, "Rapra"), _detection(5, "Rapra")]))
    pipeline.attach_client_catalog(_join())

    state = pipeline.tick(WINDOW_HANDLE, _previous_state()).state

    assert state.mob_catalog_joins == ()
    assert state.mob_catalog_rejections == (
        LabelJoinRejection("Rapra", LabelJoinRejectionReason.LABEL_UNMAPPED),
    )


def test_an_install_without_a_catalog_reports_neither_a_join_nor_a_rejection() -> None:
    tick = _pipeline(_Detector([_detection(0, "Flame")])).tick(WINDOW_HANDLE, _previous_state())

    assert tick.state.mob_catalog_joins == ()
    assert tick.state.mob_catalog_rejections == ()


def test_a_refused_mapping_keeps_saying_so_on_every_tick() -> None:
    pipeline = _pipeline(_Detector([_detection(0, "Flame")]))
    pipeline.attach_client_catalog(
        MobCatalogJoin.refused(LabelJoinRejectionReason.CLIENT_DIGEST_MISMATCH)
    )

    state = pipeline.tick(WINDOW_HANDLE, _previous_state()).state

    assert state.mob_catalog_joins == ()
    assert state.mob_catalog_rejections == (
        LabelJoinRejection("Flame", LabelJoinRejectionReason.CLIENT_DIGEST_MISMATCH),
    )


def test_a_failed_detection_keeps_the_enrichment_of_the_mobs_it_still_reports() -> None:
    joined, _rejections = _join().join((_mob(),))
    previous = _previous_state(visible_mobs=(_mob(),), mob_catalog_joins=joined)
    pipeline = _pipeline(_Detector(DetectionError(DetectionErrorCode.INFERENCE_FAILED)))
    pipeline.attach_client_catalog(_join())

    state = pipeline.tick(WINDOW_HANDLE, previous).state

    assert state.visible_mobs == previous.visible_mobs
    assert state.mob_catalog_joins == previous.mob_catalog_joins


def test_spawn_zones_alone_do_not_enrich_a_pipeline_without_a_catalog() -> None:
    pipeline = _pipeline(_Detector([_detection(0, "Flame")]))
    pipeline.attach_spawn_zones((_SpawnZone(FLAME_MOVER_ID, 8, 60),))

    assert pipeline.tick(WINDOW_HANDLE, _previous_state()).state.mob_catalog_joins == ()


def test_a_label_mapping_survives_a_write_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "mover_label_mapping.json"
    save_mover_label_mapping(_mapping(), path)

    assert load_mover_label_mapping(path) == _mapping()


def test_a_label_mapping_of_another_version_is_refused_rather_than_partly_applied(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mover_label_mapping.json"
    save_mover_label_mapping(_mapping(), path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mapping_version"] = "us083-v0"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CatalogSchemaError):
        load_mover_label_mapping(path)


def test_an_install_without_artifacts_loads_no_join(tmp_path: Path) -> None:
    assert (
        load_mob_catalog_join(
            tmp_path / "catalog.json",
            tmp_path / "mover_label_mapping.json",
            tmp_path / "source_manifest.json",
        )
        is None
    )


def test_persisted_artifacts_load_into_a_working_join(tmp_path: Path) -> None:
    paths = _artifacts(tmp_path, mapping=_mapping(), digest=CLIENT_DIGEST)

    join = load_mob_catalog_join(*paths, (_SpawnZone(FLAME_MOVER_ID, 8, 60),))

    assert join is not None
    joined, rejections = join.join((_mob(),))
    assert rejections == ()
    assert joined[0].mover_id == FLAME_MOVER_ID
    assert joined[0].spawn == SpawnEvidence(1, 8, 60)


def test_a_mapping_from_another_client_build_loads_as_a_refusal(tmp_path: Path) -> None:
    paths = _artifacts(tmp_path, mapping=_mapping(FOREIGN_DIGEST), digest=CLIENT_DIGEST)

    join = load_mob_catalog_join(*paths)

    assert join is not None
    assert join.refusal is LabelJoinRejectionReason.CLIENT_DIGEST_MISMATCH


def test_a_mapping_of_another_version_loads_as_a_refusal(tmp_path: Path) -> None:
    catalog_path, mapping_path, manifest_path = _artifacts(
        tmp_path, mapping=_mapping(), digest=CLIENT_DIGEST
    )
    document = json.loads(mapping_path.read_text(encoding="utf-8"))
    document["mapping_version"] = "us083-v0"
    mapping_path.write_text(json.dumps(document), encoding="utf-8")

    join = load_mob_catalog_join(catalog_path, mapping_path, manifest_path)

    assert join is not None
    assert join.refusal is LabelJoinRejectionReason.MAPPING_VERSION_MISMATCH
