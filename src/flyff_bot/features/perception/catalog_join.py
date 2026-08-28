"""Enrich a perception tick's own detections from the authoritative client data (US-083).

A YOLO box carries a class name and nothing else. Every property a farming decision needs
about the thing on screen -- what the client calls it, how much it hits for, how long it takes
to kill, what it drops, how densely the world spawns it -- lives in the extracted client
catalog and has to be joined to the detection before any policy ranks it.

The join happens here, inside perception, for two reasons. The per-instance candidate identity
that :mod:`flyff_bot.features.client_data.label_mapping` keys on is assigned when a detection
is decoded, so this is the only place where it is unambiguous. And a tick that cannot join a
detection has to say so on that tick: an unmapped or ambiguous label yields a typed rejection,
never a nearby mover, so a policy cannot learn a value the client never stated about that box.

The whole enrichment is optional. An install with no extracted catalog keeps producing exactly
the client-space detections it produced before, with no join and no rejection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from flyff_bot.features.automation.models import VisibleMob
from flyff_bot.features.client_data.label_mapping import (
    JoinedMoverCandidate,
    LabelJoinRejection,
    LabelJoinRejectionReason,
    MoverLabelMapping,
    SpawnEvidence,
    SpawnZoneDeclaration,
    join_detected_candidates,
    spawn_evidence_by_mover,
    verify_mapping,
)
from flyff_bot.features.client_data.models import ClientCatalog
from flyff_bot.features.client_data.persistence import (
    CatalogSchemaError,
    load_client_catalog,
    load_mover_label_mapping,
    load_source_manifest,
)


@dataclass(frozen=True, slots=True)
class MobCatalogJoin:
    """The verified static enrichment one perception tick applies to its detections.

    A refused artifact set is carried here rather than dropped at load time. A session whose
    mapping belongs to another client build must keep saying so on every tick, because "no
    enrichment because the mapping was refused" and "no enrichment because none was installed"
    are different states and only one of them is a defect for the operator to fix.
    """

    mapping: MoverLabelMapping
    catalog: ClientCatalog
    spawn_evidence: Mapping[int, SpawnEvidence] = field(default_factory=dict)
    refusal: LabelJoinRejectionReason | None = None

    @classmethod
    def refused(cls, reason: LabelJoinRejectionReason) -> MobCatalogJoin:
        """Return a join that enriches nothing and states why on every tick."""

        return cls(MoverLabelMapping(), ClientCatalog(), refusal=reason)

    def with_spawn_zones(self, zones: Iterable[SpawnZoneDeclaration]) -> MobCatalogJoin:
        """Return the same join reading the spawn declarations of another world."""

        return replace(self, spawn_evidence=spawn_evidence_by_mover(zones))

    def join(
        self, mobs: tuple[VisibleMob, ...]
    ) -> tuple[tuple[JoinedMoverCandidate, ...], tuple[LabelJoinRejection, ...]]:
        """Join one frame's detections, keyed by the identity each one already carries."""

        detections = {
            mob.candidate_index: mob.class_name for mob in mobs if mob.candidate_index is not None
        }
        if self.refusal is not None:
            return (), _distinct(
                tuple(LabelJoinRejection(label, self.refusal) for label in detections.values())
            )
        joined, rejections = join_detected_candidates(
            detections, self.mapping, self.catalog, self.spawn_evidence
        )
        return joined, _distinct(rejections)


def _distinct(rejections: tuple[LabelJoinRejection, ...]) -> tuple[LabelJoinRejection, ...]:
    """Collapse repeats, preserving order.

    Every rejection reason is a property of the *class*, not of one box, so five unjoinable
    detections of one class state one fact rather than five.
    """

    seen: set[LabelJoinRejection] = set()
    distinct: list[LabelJoinRejection] = []
    for rejection in rejections:
        if rejection in seen:
            continue
        seen.add(rejection)
        distinct.append(rejection)
    return tuple(distinct)


def load_mob_catalog_join(
    catalog_path: Path,
    mapping_path: Path,
    manifest_path: Path,
    zones: Iterable[SpawnZoneDeclaration] = (),
) -> MobCatalogJoin | None:
    """Return the verified join, or ``None`` when this install has no catalog artifacts.

    Both artifacts are required together: a catalog without a curated mapping can join
    nothing, and a mapping without a catalog has nothing to join to. A mapping written for
    another client build or under another mapping version yields a *refused* join rather than
    enriching a detection with a foreign build's mover properties.

    A catalog artifact of another schema version is not a label-join problem and is raised to
    the caller: the fix is to re-run extraction, not to farm on with a partial join.
    """

    if not catalog_path.is_file() or not mapping_path.is_file():
        return None
    client_digest = (
        load_source_manifest(manifest_path).client_digest if manifest_path.is_file() else ""
    )
    try:
        mapping = load_mover_label_mapping(mapping_path)
        verify_mapping(mapping, client_digest=client_digest)
    except CatalogSchemaError:
        return MobCatalogJoin.refused(LabelJoinRejectionReason.MAPPING_VERSION_MISMATCH)
    except ValueError as error:
        # `verify_mapping` fails with the exact reason as its message, so the refusal the
        # operator sees names the real cause instead of a generic "mapping unusable".
        return MobCatalogJoin.refused(LabelJoinRejectionReason(str(error)))
    return MobCatalogJoin(
        mapping, load_client_catalog(catalog_path), spawn_evidence_by_mover(zones)
    )
