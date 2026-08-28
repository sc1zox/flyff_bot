"""The exact YOLO-label to client-mover join and its refusals (US-083)."""

from __future__ import annotations

import pytest

from flyff_bot.features.client_data.label_mapping import (
    MOVER_LABEL_MAPPING_VERSION,
    LabelJoinRejectionReason,
    MoverLabelBinding,
    MoverLabelMapping,
    join_detected_candidates,
    verify_mapping,
)
from flyff_bot.features.client_data.models import (
    ClientCatalog,
    DropRecord,
    MoverCombatProperties,
    MoverRecord,
)

CLIENT_DIGEST = "8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5"


def _catalog() -> ClientCatalog:
    return ClientCatalog(
        movers=(
            MoverRecord("MI_FLAME", "Flame", MoverCombatProperties(level=15, hit_points=560)),
            MoverRecord("MI_MINIMUSH", "MiniMush", MoverCombatProperties(level=3)),
        ),
        drops=(DropRecord("MI_FLAME", "II_STONE", 700, 1, 3),),
    )


def _mapping(*bindings: MoverLabelBinding) -> MoverLabelMapping:
    return MoverLabelMapping(bindings=bindings, client_digest=CLIENT_DIGEST)


def test_a_detection_is_joined_to_its_authoritative_mover_and_drops() -> None:
    joined, rejections = join_detected_candidates(
        {0: "Flame"},
        _mapping(MoverLabelBinding("Flame", 1453, "MI_FLAME")),
        _catalog(),
    )

    assert rejections == ()
    assert len(joined) == 1
    candidate = joined[0]
    assert candidate.candidate_index == 0
    assert candidate.mover_id == 1453
    assert candidate.mover_symbol == "MI_FLAME"
    assert candidate.display_name == "Flame"
    assert candidate.combat.hit_points == 560
    assert candidate.has_verified_combat_properties is True
    assert [drop.item_symbol for drop in candidate.drops] == ["II_STONE"]
    assert candidate.mapping_version == MOVER_LABEL_MAPPING_VERSION
    assert candidate.client_digest == CLIENT_DIGEST


def test_two_visible_mobs_of_one_class_each_keep_their_own_identity() -> None:
    """US-079 candidate identity must survive the join, not collapse into one record."""

    joined, _rejections = join_detected_candidates(
        {0: "Flame", 1: "Flame"},
        _mapping(MoverLabelBinding("Flame", 1453, "MI_FLAME")),
        _catalog(),
    )

    assert [candidate.candidate_index for candidate in joined] == [0, 1]
    assert {candidate.mover_id for candidate in joined} == {1453}


def test_an_unmapped_label_is_refused_rather_than_matched_to_a_similar_name() -> None:
    joined, rejections = join_detected_candidates(
        {0: "Oldrut"}, _mapping(MoverLabelBinding("Flame", 1453, "MI_FLAME")), _catalog()
    )

    assert joined == ()
    assert rejections[0].reason is LabelJoinRejectionReason.LABEL_UNMAPPED
    assert rejections[0].detector_label == "Oldrut"


def test_a_label_bound_to_two_movers_joins_to_neither() -> None:
    joined, rejections = join_detected_candidates(
        {0: "Flame"},
        _mapping(
            MoverLabelBinding("Flame", 1453, "MI_FLAME"),
            MoverLabelBinding("Flame", 1455, "MI_MINIMUSH"),
        ),
        _catalog(),
    )

    assert joined == ()
    assert rejections[0].reason is LabelJoinRejectionReason.LABEL_AMBIGUOUS


def test_a_display_name_shared_by_two_movers_refuses_the_join() -> None:
    catalog = ClientCatalog(
        movers=(
            MoverRecord("MI_FLAME", "Flame"),
            MoverRecord("MI_FLAME_ELITE", "Flame"),
        )
    )

    joined, rejections = join_detected_candidates(
        {0: "Flame"}, _mapping(MoverLabelBinding("Flame", 1453, "MI_FLAME")), catalog
    )

    assert joined == ()
    assert rejections[0].reason is LabelJoinRejectionReason.DISPLAY_NAME_AMBIGUOUS


def test_a_binding_naming_an_undeclared_symbol_is_refused() -> None:
    joined, rejections = join_detected_candidates(
        {0: "Rapra"}, _mapping(MoverLabelBinding("Rapra", 1458, "MI_RAPRA")), _catalog()
    )

    assert joined == ()
    assert rejections[0].reason is LabelJoinRejectionReason.MOVER_SYMBOL_UNKNOWN


def test_a_mover_without_declared_combat_columns_reports_that_it_has_none() -> None:
    catalog = ClientCatalog(movers=(MoverRecord("MI_FLAME", "Flame"),))

    joined, _rejections = join_detected_candidates(
        {0: "Flame"}, _mapping(MoverLabelBinding("Flame", 1453, "MI_FLAME")), catalog
    )

    assert joined[0].has_verified_combat_properties is False
    assert joined[0].combat.level is None


def test_a_mapping_from_another_client_build_is_refused_outright() -> None:
    mapping = _mapping(MoverLabelBinding("Flame", 1453, "MI_FLAME"))

    with pytest.raises(ValueError) as error:
        verify_mapping(mapping, client_digest="a" * 64)

    assert error.value.args[0] == LabelJoinRejectionReason.CLIENT_DIGEST_MISMATCH.value


def test_a_mapping_of_another_version_is_refused_outright() -> None:
    mapping = MoverLabelMapping(
        bindings=(MoverLabelBinding("Flame", 1453, "MI_FLAME"),),
        client_digest=CLIENT_DIGEST,
        mapping_version="us000-v0",
    )

    with pytest.raises(ValueError) as error:
        verify_mapping(mapping, client_digest=CLIENT_DIGEST)

    assert error.value.args[0] == LabelJoinRejectionReason.MAPPING_VERSION_MISMATCH.value


def test_a_matching_mapping_is_accepted() -> None:
    verify_mapping(
        _mapping(MoverLabelBinding("Flame", 1453, "MI_FLAME")), client_digest=CLIENT_DIGEST
    )
