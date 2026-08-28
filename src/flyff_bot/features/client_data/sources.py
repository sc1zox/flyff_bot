"""The concrete source registry this build declares and verifies (US-083).

This module is the single place that answers "what data does the bot read, and which code
acts on it?". :func:`build_source_manifest` turns an extracted catalog into that manifest, and
the coverage checks in :mod:`flyff_bot.features.client_data.manifest` make an undeclared or
unconsumed field a test failure.

Two tables are deliberately declared with no promoted field. The client's skill rows and NPC
rows are parsed and persisted, but no decision path reads a column from them yet; declaring a
field with an invented consumer would defeat the check this registry exists to enforce. They
are listed with their record counts and :attr:`SourceCompleteness.PARTIAL`, so the gap is
visible in the manifest instead of being hidden by omission.
"""

from __future__ import annotations

from flyff_bot.features.client_data.manifest import (
    STATIC_UNTIL_REEXTRACTION,
    FieldProvenance,
    SourceCompleteness,
    SourceEntry,
    SourceKind,
    SourceManifest,
    build_manifest,
    content_digest,
)
from flyff_bot.features.client_data.models import (
    CLIENT_CATALOG_SCHEMA_VERSION,
    CatalogTable,
    ClientCatalog,
)

# Production consumers, named by their import path so a reader can go straight to the code.
CANDIDATE_JOIN_CONSUMER = "features.client_data.label_mapping.join_detected_candidates"
QUEST_OBJECTIVE_CONSUMER = "features.quests.extraction.extract_quest_database"
SPAWN_ZONE_CONSUMER = "features.navigation.world_extractor.extract_world"

# Source identifiers used by the manifest and by every test that asserts coverage.
MOVER_SOURCE_ID = "client.movers"
DROP_SOURCE_ID = "client.drops"
ITEM_SOURCE_ID = "client.items"
SKILL_SOURCE_ID = "client.skills"
NPC_SOURCE_ID = "client.npcs"


def _completeness(record_count: int, rejection_count: int) -> SourceCompleteness:
    if record_count == 0:
        return SourceCompleteness.UNAVAILABLE
    return SourceCompleteness.PARTIAL if rejection_count else SourceCompleteness.COMPLETE


def _diagnostics(catalog: ClientCatalog, table: CatalogTable) -> tuple[str, ...]:
    return tuple(
        f"{rejection.reason.value}:{rejection.locator}"
        for rejection in catalog.rejections_for(table)
    )


def _entry(
    source_id: str,
    table: CatalogTable,
    catalog: ClientCatalog,
    fields: tuple[FieldProvenance, ...],
    *,
    client_digest: str,
    payload: object,
    completeness: SourceCompleteness | None = None,
) -> SourceEntry:
    record_count = catalog.record_count(table)
    diagnostics = _diagnostics(catalog, table)
    return SourceEntry(
        source_id=source_id,
        kind=SourceKind.STATIC_TABLE,
        schema_version=CLIENT_CATALOG_SCHEMA_VERSION,
        completeness=completeness or _completeness(record_count, len(diagnostics)),
        freshness_rule=STATIC_UNTIL_REEXTRACTION,
        fields=fields,
        record_count=record_count,
        client_digest=client_digest,
        content_digest=content_digest(payload),
        diagnostics=diagnostics,
    )


def build_source_manifest(
    catalog: ClientCatalog,
    *,
    client_digest: str,
    generated_at: str | None = None,
) -> SourceManifest:
    """Return the manifest describing one extracted catalog and who consumes it."""

    mover_fields = (
        FieldProvenance("symbol", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("display_name", True, (CANDIDATE_JOIN_CONSUMER, QUEST_OBJECTIVE_CONSUMER)),
        FieldProvenance("combat.level", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("combat.attack_minimum", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("combat.attack_maximum", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("combat.hit_points", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("combat.attack_speed", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("combat.movement_speed", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("combat.sight_range", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("combat.belligerence", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("combat.experience_value", True, (CANDIDATE_JOIN_CONSUMER,)),
    )
    drop_fields = (
        FieldProvenance("mover_symbol", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("item_symbol", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("probability_weight", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("minimum_quantity", True, (CANDIDATE_JOIN_CONSUMER,)),
        FieldProvenance("maximum_quantity", True, (CANDIDATE_JOIN_CONSUMER,)),
    )
    item_fields = (
        FieldProvenance("symbol", True, (QUEST_OBJECTIVE_CONSUMER,)),
        FieldProvenance("display_name", True, (QUEST_OBJECTIVE_CONSUMER,)),
    )
    document = {
        "movers": len(catalog.movers),
        "drops": len(catalog.drops),
        "items": len(catalog.items),
        "skills": len(catalog.skills),
        "npcs": len(catalog.npcs),
    }
    return build_manifest(
        (
            _entry(
                MOVER_SOURCE_ID,
                CatalogTable.MOVERS,
                catalog,
                mover_fields,
                client_digest=client_digest,
                payload=[
                    (mover.symbol, mover.display_name, mover.combat.level)
                    for mover in catalog.movers
                ],
            ),
            _entry(
                DROP_SOURCE_ID,
                CatalogTable.DROPS,
                catalog,
                drop_fields,
                client_digest=client_digest,
                payload=[
                    (drop.mover_symbol, drop.item_symbol, drop.probability_weight)
                    for drop in catalog.drops
                ],
            ),
            _entry(
                ITEM_SOURCE_ID,
                CatalogTable.ITEMS,
                catalog,
                item_fields,
                client_digest=client_digest,
                payload=[(item.symbol, item.display_name) for item in catalog.items],
            ),
            # Parsed and persisted, but no decision path reads a column yet (US-083 AC6).
            _entry(
                SKILL_SOURCE_ID,
                CatalogTable.SKILLS,
                catalog,
                (),
                client_digest=client_digest,
                payload=[(skill.symbol, skill.display_name) for skill in catalog.skills],
                completeness=SourceCompleteness.PARTIAL if catalog.skills else None,
            ),
            _entry(
                NPC_SOURCE_ID,
                CatalogTable.NPCS,
                catalog,
                (),
                client_digest=client_digest,
                payload=[(npc.symbol, npc.display_name) for npc in catalog.npcs],
                completeness=SourceCompleteness.PARTIAL if catalog.npcs else None,
            ),
        ),
        client_digest=client_digest or content_digest(document),
        generated_at=generated_at,
    )


def undeclared_tables(catalog: ClientCatalog, manifest: SourceManifest) -> tuple[CatalogTable, ...]:
    """Return every table holding records that the manifest does not describe.

    Field-level coverage alone could be satisfied by simply not declaring a field, so a table
    that produced records must also appear as its own entry.
    """

    source_by_table = {
        CatalogTable.MOVERS: MOVER_SOURCE_ID,
        CatalogTable.DROPS: DROP_SOURCE_ID,
        CatalogTable.ITEMS: ITEM_SOURCE_ID,
        CatalogTable.SKILLS: SKILL_SOURCE_ID,
        CatalogTable.NPCS: NPC_SOURCE_ID,
    }
    return tuple(
        table
        for table, source_id in source_by_table.items()
        if catalog.record_count(table) and manifest.entry(source_id) is None
    )
