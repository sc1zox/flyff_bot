"""The versioned source/consumer manifest and its coverage guarantees (US-083)."""

from __future__ import annotations

from pathlib import Path

import pytest

from flyff_bot.features.client_data.manifest import (
    SOURCE_MANIFEST_SCHEMA_VERSION,
    STATIC_UNTIL_REEXTRACTION,
    ConsumerCoverageError,
    FieldProvenance,
    SourceCompleteness,
    SourceEntry,
    SourceKind,
    build_manifest,
    content_digest,
    unconsumed_fields,
    verify_consumer_coverage,
)
from flyff_bot.features.client_data.models import (
    CatalogTable,
    ClientCatalog,
    DropRecord,
    ItemRecord,
    MoverCombatProperties,
    MoverRecord,
    NpcRecord,
    SkillRecord,
)
from flyff_bot.features.client_data.persistence import (
    CatalogSchemaError,
    load_source_manifest,
    save_source_manifest,
)
from flyff_bot.features.client_data.sources import (
    MOVER_SOURCE_ID,
    SKILL_SOURCE_ID,
    build_source_manifest,
    undeclared_tables,
)

CLIENT_DIGEST = "8079c88f4c4e35a0b5acd117995125bee528c175d5b621e0533d85a4458dada5"


def _catalog() -> ClientCatalog:
    return ClientCatalog(
        movers=(MoverRecord("MI_FLAME", "Flame", MoverCombatProperties(level=15)),),
        drops=(DropRecord("MI_FLAME", "II_STONE", 700, 1, 3),),
        items=(ItemRecord("II_STONE", "Stone"),),
        skills=(SkillRecord("SI_BLAZE", "Blaze"),),
        npcs=(NpcRecord("MI_TRADER", "Trader"),),
    )


def test_every_parsed_table_appears_with_its_digest_schema_and_freshness_rule() -> None:
    manifest = build_source_manifest(_catalog(), client_digest=CLIENT_DIGEST)

    entry = manifest.entry(MOVER_SOURCE_ID)
    assert entry is not None
    assert entry.kind is SourceKind.STATIC_TABLE
    assert entry.record_count == 1
    assert entry.client_digest == CLIENT_DIGEST
    assert entry.content_digest
    assert entry.schema_version
    assert entry.freshness_rule == STATIC_UNTIL_REEXTRACTION
    assert entry.completeness is SourceCompleteness.COMPLETE


def test_the_shipped_registry_leaves_no_parsed_field_without_a_consumer() -> None:
    """A field nobody reads is a field an operator wrongly believes the bot acts on."""

    verify_consumer_coverage(build_source_manifest(_catalog(), client_digest=CLIENT_DIGEST))


def test_a_field_declared_without_a_consumer_is_refused() -> None:
    manifest = build_manifest(
        (
            SourceEntry(
                source_id="client.example",
                kind=SourceKind.STATIC_TABLE,
                schema_version="us083-v1",
                completeness=SourceCompleteness.COMPLETE,
                freshness_rule=STATIC_UNTIL_REEXTRACTION,
                fields=(FieldProvenance("orphan", True, ()),),
                record_count=1,
            ),
        ),
        client_digest=CLIENT_DIGEST,
    )

    assert unconsumed_fields(manifest) == (unconsumed_fields(manifest)[0],)
    with pytest.raises(ConsumerCoverageError):
        verify_consumer_coverage(manifest)


def test_a_table_holding_records_cannot_be_hidden_by_omitting_its_fields() -> None:
    """Field-level coverage alone could be satisfied by simply declaring nothing."""

    catalog = _catalog()
    manifest = build_manifest((), client_digest=CLIENT_DIGEST)

    assert set(undeclared_tables(catalog, manifest)) == {
        CatalogTable.MOVERS,
        CatalogTable.DROPS,
        CatalogTable.ITEMS,
        CatalogTable.SKILLS,
        CatalogTable.NPCS,
    }
    assert undeclared_tables(catalog, build_source_manifest(catalog, client_digest="")) == ()


def test_a_parsed_table_with_no_promoted_field_is_visible_rather_than_omitted() -> None:
    """Skill rows are extracted but no decision reads them yet; the manifest says so."""

    manifest = build_source_manifest(_catalog(), client_digest=CLIENT_DIGEST)

    skills = manifest.entry(SKILL_SOURCE_ID)
    assert skills is not None
    assert skills.record_count == 1
    assert skills.fields == ()
    assert skills.completeness is SourceCompleteness.PARTIAL


def test_a_rejected_row_downgrades_completeness_and_is_carried_as_a_diagnostic() -> None:
    from flyff_bot.features.client_data.models import CatalogRejection, CatalogRejectionReason

    catalog = ClientCatalog(
        movers=(MoverRecord("MI_FLAME", "Flame"),),
        rejections=(
            CatalogRejection(
                CatalogTable.MOVERS, CatalogRejectionReason.SYMBOL_DUPLICATED, "MI_GHOST"
            ),
        ),
    )

    entry = build_source_manifest(catalog, client_digest=CLIENT_DIGEST).entry(MOVER_SOURCE_ID)

    assert entry is not None
    assert entry.completeness is SourceCompleteness.PARTIAL
    assert entry.diagnostics == ("symbol_duplicated:MI_GHOST",)


def test_a_live_provider_must_state_a_sample_age_not_a_static_rule() -> None:
    with pytest.raises(ValueError):
        SourceEntry(
            source_id="live.player_stats",
            kind=SourceKind.LIVE_PROVIDER,
            schema_version="us076-v1",
            completeness=SourceCompleteness.COMPLETE,
            freshness_rule=STATIC_UNTIL_REEXTRACTION,
        )


def test_content_digest_ignores_key_ordering() -> None:
    assert content_digest({"a": 1, "b": 2}) == content_digest({"b": 2, "a": 1})


def test_a_manifest_round_trips_through_its_persisted_document(tmp_path: Path) -> None:
    manifest = build_source_manifest(
        _catalog(), client_digest=CLIENT_DIGEST, generated_at="2026-08-28T00:00:00+00:00"
    )
    path = tmp_path / "source_manifest.json"

    save_source_manifest(manifest, path)

    assert load_source_manifest(path) == manifest


def test_a_manifest_of_another_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "source_manifest.json"
    path.write_text('{"schema_version": "us000-v0"}', encoding="utf-8")

    with pytest.raises(CatalogSchemaError) as error:
        load_source_manifest(path)

    assert error.value.expected == SOURCE_MANIFEST_SCHEMA_VERSION
