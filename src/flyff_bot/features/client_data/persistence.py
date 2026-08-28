"""Versioned persistence for the client catalog and its source manifest (US-083).

A document written under a different schema version is rejected rather than adapted, so a
stale artifact cannot silently feed a policy fields that have since changed meaning
(ADR-003).
"""

from __future__ import annotations

import json
from pathlib import Path

from flyff_bot.features.client_data.label_mapping import (
    MOVER_LABEL_MAPPING_VERSION,
    MoverLabelBinding,
    MoverLabelMapping,
)
from flyff_bot.features.client_data.manifest import (
    SOURCE_MANIFEST_SCHEMA_VERSION,
    FieldProvenance,
    SourceCompleteness,
    SourceEntry,
    SourceKind,
    SourceManifest,
)
from flyff_bot.features.client_data.models import (
    CLIENT_CATALOG_SCHEMA_VERSION,
    CatalogRejection,
    CatalogRejectionReason,
    CatalogTable,
    ClientCatalog,
    DropRecord,
    ItemRecord,
    MoverCombatProperties,
    MoverRecord,
    NpcRecord,
    SkillRecord,
)

# Named so the handlers below stay single-name `except` clauses. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
DOCUMENT_READ_ERRORS = (OSError, json.JSONDecodeError)


class CatalogSchemaError(ValueError):
    """One persisted document was written under a schema this build does not serve."""

    def __init__(self, *, expected: str, found: str) -> None:
        self.expected = expected
        self.found = found
        super().__init__(f"schema_mismatch:expected={expected},found={found}")


def _combat_document(combat: MoverCombatProperties) -> dict[str, object]:
    return {
        "level": combat.level,
        "attack_minimum": combat.attack_minimum,
        "attack_maximum": combat.attack_maximum,
        "hit_points": combat.hit_points,
        "attack_speed": combat.attack_speed,
        "movement_speed": combat.movement_speed,
        "sight_range": combat.sight_range,
        "belligerence": combat.belligerence,
        "experience_value": combat.experience_value,
    }


def catalog_document(catalog: ClientCatalog) -> dict[str, object]:
    """Return the catalog in the form written to disk."""

    return {
        "schema_version": catalog.schema_version,
        "movers": [
            {
                "symbol": mover.symbol,
                "display_name": mover.display_name,
                "combat": _combat_document(mover.combat),
            }
            for mover in catalog.movers
        ],
        "drops": [
            {
                "mover_symbol": drop.mover_symbol,
                "item_symbol": drop.item_symbol,
                "probability_weight": drop.probability_weight,
                "minimum_quantity": drop.minimum_quantity,
                "maximum_quantity": drop.maximum_quantity,
            }
            for drop in catalog.drops
        ],
        "items": [
            {"symbol": item.symbol, "display_name": item.display_name} for item in catalog.items
        ],
        "skills": [
            {"symbol": skill.symbol, "display_name": skill.display_name} for skill in catalog.skills
        ],
        "npcs": [{"symbol": npc.symbol, "display_name": npc.display_name} for npc in catalog.npcs],
        "rejections": [
            {
                "table": rejection.table.value,
                "reason": rejection.reason.value,
                "locator": rejection.locator,
            }
            for rejection in catalog.rejections
        ],
    }


def save_client_catalog(catalog: ClientCatalog, path: Path) -> None:
    """Write the catalog artifact, creating its directory when needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(catalog_document(catalog), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _text_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def _required_int(value: object, field_name: str) -> int:
    """Return one required integer column, refusing a document that omits it."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise CatalogSchemaError(expected=field_name, found=type(value).__name__)
    return value


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _combat_from_document(payload: object) -> MoverCombatProperties:
    if not isinstance(payload, dict):
        return MoverCombatProperties()
    return MoverCombatProperties(
        level=_int_or_none(payload.get("level")),
        attack_minimum=_int_or_none(payload.get("attack_minimum")),
        attack_maximum=_int_or_none(payload.get("attack_maximum")),
        hit_points=_int_or_none(payload.get("hit_points")),
        attack_speed=_int_or_none(payload.get("attack_speed")),
        movement_speed=_float_or_none(payload.get("movement_speed")),
        sight_range=_int_or_none(payload.get("sight_range")),
        belligerence=_int_or_none(payload.get("belligerence")),
        experience_value=_int_or_none(payload.get("experience_value")),
    )


def load_client_catalog(path: Path) -> ClientCatalog:
    """Return the persisted catalog, refusing a document of another schema version."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CatalogSchemaError(expected=CLIENT_CATALOG_SCHEMA_VERSION, found="none")
    found = str(payload.get("schema_version", "none"))
    if found != CLIENT_CATALOG_SCHEMA_VERSION:
        raise CatalogSchemaError(expected=CLIENT_CATALOG_SCHEMA_VERSION, found=found)
    return ClientCatalog(
        movers=tuple(
            MoverRecord(
                str(row["symbol"]),
                _text_or_none(row.get("display_name")),
                _combat_from_document(row.get("combat")),
            )
            for row in _rows(payload.get("movers"))
        ),
        drops=tuple(
            DropRecord(
                str(row["mover_symbol"]),
                str(row["item_symbol"]),
                _required_int(row.get("probability_weight"), "probability_weight"),
                _required_int(row.get("minimum_quantity"), "minimum_quantity"),
                _required_int(row.get("maximum_quantity"), "maximum_quantity"),
            )
            for row in _rows(payload.get("drops"))
        ),
        items=tuple(
            ItemRecord(str(row["symbol"]), _text_or_none(row.get("display_name")))
            for row in _rows(payload.get("items"))
        ),
        skills=tuple(
            SkillRecord(str(row["symbol"]), _text_or_none(row.get("display_name")))
            for row in _rows(payload.get("skills"))
        ),
        npcs=tuple(
            NpcRecord(str(row["symbol"]), _text_or_none(row.get("display_name")))
            for row in _rows(payload.get("npcs"))
        ),
        rejections=tuple(
            CatalogRejection(
                CatalogTable(str(row["table"])),
                CatalogRejectionReason(str(row["reason"])),
                str(row["locator"]),
            )
            for row in _rows(payload.get("rejections"))
        ),
    )


def save_source_manifest(manifest: SourceManifest, path: Path) -> None:
    """Write the source manifest artifact, creating its directory when needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.as_document(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_source_manifest(path: Path) -> SourceManifest:
    """Return the persisted manifest, refusing a document of another schema version."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CatalogSchemaError(expected=SOURCE_MANIFEST_SCHEMA_VERSION, found="none")
    found = str(payload.get("schema_version", "none"))
    if found != SOURCE_MANIFEST_SCHEMA_VERSION:
        raise CatalogSchemaError(expected=SOURCE_MANIFEST_SCHEMA_VERSION, found=found)
    return SourceManifest(
        entries=tuple(_entry_from_document(row) for row in _rows(payload.get("entries"))),
        client_digest=str(payload.get("client_digest", "")),
        generated_at=str(payload.get("generated_at", "")),
    )


def _entry_from_document(payload: dict[str, object]) -> SourceEntry:
    return SourceEntry(
        source_id=str(payload["source_id"]),
        kind=SourceKind(str(payload["kind"])),
        schema_version=str(payload.get("schema_version", "")),
        completeness=SourceCompleteness(str(payload["completeness"])),
        freshness_rule=str(payload.get("freshness_rule", "")),
        fields=tuple(
            FieldProvenance(
                str(row["name"]),
                bool(row.get("is_measured", True)),
                tuple(str(consumer) for consumer in _sequence(row.get("consumers"))),
            )
            for row in _rows(payload.get("fields"))
        ),
        record_count=_required_int(payload.get("record_count", 0) or 0, "record_count"),
        client_digest=str(payload.get("client_digest", "")),
        content_digest=str(payload.get("content_digest", "")),
        diagnostics=tuple(str(item) for item in _sequence(payload.get("diagnostics"))),
    )


def _rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def mapping_document(mapping: MoverLabelMapping) -> dict[str, object]:
    """Return the curated label mapping in the form written to disk."""

    return {
        "mapping_version": mapping.mapping_version,
        "client_digest": mapping.client_digest,
        "bindings": [
            {
                "detector_label": binding.detector_label,
                "mover_id": binding.mover_id,
                "mover_symbol": binding.mover_symbol,
            }
            for binding in mapping.bindings
        ],
    }


def save_mover_label_mapping(mapping: MoverLabelMapping, path: Path) -> None:
    """Write the curated label mapping, creating its directory when needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(mapping_document(mapping), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_mover_label_mapping(path: Path) -> MoverLabelMapping:
    """Return the curated label mapping, refusing a document of another mapping version.

    The version is checked here rather than at join time so a stale artifact can never
    contribute even one binding: a label bound to a mover id that has since been reassigned
    would otherwise teach a policy another mover's combat properties.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CatalogSchemaError(expected=MOVER_LABEL_MAPPING_VERSION, found="none")
    found = str(payload.get("mapping_version", "none"))
    if found != MOVER_LABEL_MAPPING_VERSION:
        raise CatalogSchemaError(expected=MOVER_LABEL_MAPPING_VERSION, found=found)
    return MoverLabelMapping(
        bindings=tuple(
            MoverLabelBinding(
                str(row["detector_label"]),
                _required_int(row.get("mover_id"), "mover_id"),
                str(row["mover_symbol"]),
            )
            for row in _rows(payload.get("bindings"))
        ),
        client_digest=str(payload.get("client_digest", "")),
        mapping_version=found,
    )
