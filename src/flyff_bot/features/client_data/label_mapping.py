"""The exact, versioned join from a YOLO class label to a client mover (US-083).

The client does not ship the ``MI_*``-to-numeric-mover-id table; those constants are compiled
into ``neuz.exe``, so the join cannot be derived from the packed tables alone. It is therefore
a *curated, versioned artifact*: a label is bound to one numeric mover id and one client
symbol, and the binding carries the client digest it was established against.

Everything here fails closed. A label with no entry, a label bound to two different movers, a
display name shared by two mover ids, or an entry naming a symbol the mover table never
declared all resolve to a typed :class:`LabelJoinRejection`. A detected monster is never
joined to a nearby or similarly named mover, because a policy that then learns that mover's
combat properties would be learning from a value the client never stated about the thing on
screen.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Protocol

from flyff_bot.features.client_data.models import (
    ClientCatalog,
    DropRecord,
    MoverCombatProperties,
    MoverRecord,
)

# Bumped whenever a label binding changes. A mapping stamped with any other version is
# rejected rather than adapted (ADR-003).
MOVER_LABEL_MAPPING_VERSION = "us083-v1"


@unique
class LabelJoinRejectionReason(StrEnum):
    """Why one detected class cannot be joined to an authoritative mover."""

    # The mapping declares no entry for this detector label.
    LABEL_UNMAPPED = "label_unmapped"
    # Two entries bind this label to different movers, so neither can be chosen.
    LABEL_AMBIGUOUS = "label_ambiguous"
    # Two movers share the display name this label resolves to.
    DISPLAY_NAME_AMBIGUOUS = "display_name_ambiguous"
    # The entry names a client symbol the mover table does not declare.
    MOVER_SYMBOL_UNKNOWN = "mover_symbol_unknown"
    # The mapping was produced against a different client build than the one in use.
    CLIENT_DIGEST_MISMATCH = "client_digest_mismatch"
    # The mapping artifact was written under a different mapping version.
    MAPPING_VERSION_MISMATCH = "mapping_version_mismatch"


@dataclass(frozen=True, slots=True)
class MoverLabelBinding:
    """One curated binding of a detector label to exactly one client mover."""

    detector_label: str
    mover_id: int
    mover_symbol: str

    def __post_init__(self) -> None:
        if not self.detector_label:
            raise ValueError("A label binding names the detector label it binds.")
        if not self.mover_symbol:
            raise ValueError("A label binding names the client mover symbol it binds.")
        if self.mover_id < 0:
            raise ValueError("A mover id is non-negative.")


@dataclass(frozen=True, slots=True)
class MoverLabelMapping:
    """Every curated label binding, stamped with the client build it was proven against."""

    bindings: tuple[MoverLabelBinding, ...] = ()
    client_digest: str = ""
    mapping_version: str = MOVER_LABEL_MAPPING_VERSION

    def labels(self) -> tuple[str, ...]:
        """Return every bound detector label in declaration order."""

        return tuple(binding.detector_label for binding in self.bindings)


class SpawnZoneDeclaration(Protocol):
    """The three spawn columns this join reads from an extracted world zone.

    Declared structurally so the static catalog keeps depending only on client tables: the
    world artifact is produced by the navigation feature and is not imported here.
    """

    @property
    def monster_id(self) -> int: ...

    @property
    def capacity(self) -> int: ...

    @property
    def respawn_seconds(self) -> int: ...


@dataclass(frozen=True, slots=True)
class SpawnEvidence:
    """What the extracted world declares about one mover's presence, as declared.

    These are the client's own spawn numbers, not an observation: they say how many of a
    mover the world may hold and how quickly it replaces one, which is what a follow-up or
    camp decision needs. A mover with no zone in the loaded world has no evidence at all
    rather than a zeroed record.
    """

    zone_count: int
    total_capacity: int
    minimum_respawn_seconds: int | None = None


def spawn_evidence_by_mover(
    zones: Iterable[SpawnZoneDeclaration],
) -> dict[int, SpawnEvidence]:
    """Aggregate every zone of one world into per-mover spawn evidence."""

    aggregated: dict[int, SpawnEvidence] = {}
    for zone in zones:
        previous = aggregated.get(zone.monster_id)
        respawn_seconds = zone.respawn_seconds
        if previous is None:
            aggregated[zone.monster_id] = SpawnEvidence(1, zone.capacity, respawn_seconds)
            continue
        aggregated[zone.monster_id] = SpawnEvidence(
            previous.zone_count + 1,
            previous.total_capacity + zone.capacity,
            respawn_seconds
            if previous.minimum_respawn_seconds is None
            else min(previous.minimum_respawn_seconds, respawn_seconds),
        )
    return aggregated


@dataclass(frozen=True, slots=True)
class LabelJoinRejection:
    """Why one detection stays unenriched, stated instead of being resolved by guess."""

    detector_label: str
    reason: LabelJoinRejectionReason


@dataclass(frozen=True, slots=True)
class JoinedMoverCandidate:
    """One detection joined to its authoritative mover, with the provenance of the join."""

    #: The stable per-instance identity of the detection this describes (US-079).
    candidate_index: int
    detector_label: str
    mover_id: int
    mover_symbol: str
    display_name: str | None
    combat: MoverCombatProperties
    drops: tuple[DropRecord, ...]
    mapping_version: str
    client_digest: str
    #: Declared spawn capacity and respawn cadence, absent when the loaded world has no zone.
    spawn: SpawnEvidence | None = None

    @property
    def has_verified_combat_properties(self) -> bool:
        """Return whether the client actually stated this mover's combat columns."""

        return self.combat != MoverCombatProperties()


def _duplicate_labels(mapping: MoverLabelMapping) -> frozenset[str]:
    seen: dict[str, tuple[int, str]] = {}
    duplicated: set[str] = set()
    for binding in mapping.bindings:
        identity = (binding.mover_id, binding.mover_symbol)
        previous = seen.get(binding.detector_label)
        if previous is not None and previous != identity:
            duplicated.add(binding.detector_label)
        seen.setdefault(binding.detector_label, identity)
    return frozenset(duplicated)


def _ambiguous_display_names(movers: Iterable[MoverRecord]) -> frozenset[str]:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for mover in movers:
        if mover.display_name is None:
            continue
        if mover.display_name in seen:
            duplicated.add(mover.display_name)
        seen.add(mover.display_name)
    return frozenset(duplicated)


def verify_mapping(mapping: MoverLabelMapping, *, client_digest: str) -> None:
    """Raise when a mapping cannot serve the client build in use.

    Both checks fail closed: an artifact from another client build or another mapping version
    is refused outright rather than partially applied.
    """

    if mapping.mapping_version != MOVER_LABEL_MAPPING_VERSION:
        raise ValueError(LabelJoinRejectionReason.MAPPING_VERSION_MISMATCH.value)
    if mapping.client_digest and client_digest and mapping.client_digest != client_digest:
        raise ValueError(LabelJoinRejectionReason.CLIENT_DIGEST_MISMATCH.value)


def join_detected_candidates(
    detections: Mapping[int, str],
    mapping: MoverLabelMapping,
    catalog: ClientCatalog,
    spawn_evidence: Mapping[int, SpawnEvidence] | None = None,
) -> tuple[tuple[JoinedMoverCandidate, ...], tuple[LabelJoinRejection, ...]]:
    """Join detections to authoritative movers, keyed by stable candidate identity.

    ``detections`` maps each candidate's per-instance identity to its detector label, so two
    simultaneously visible monsters of the same class each receive their own joined record
    rather than collapsing into one.

    ``spawn_evidence`` is keyed by mover id and supplies the declared capacity and respawn
    cadence of the loaded world. A mover the world never declares stays without evidence.
    """

    duplicated_labels = _duplicate_labels(mapping)
    ambiguous_names = _ambiguous_display_names(catalog.movers)
    bindings = {
        binding.detector_label: binding
        for binding in mapping.bindings
        if binding.detector_label not in duplicated_labels
    }

    joined: list[JoinedMoverCandidate] = []
    rejections: list[LabelJoinRejection] = []
    for candidate_index in sorted(detections):
        label = detections[candidate_index]
        if label in duplicated_labels:
            rejections.append(LabelJoinRejection(label, LabelJoinRejectionReason.LABEL_AMBIGUOUS))
            continue
        binding = bindings.get(label)
        if binding is None:
            rejections.append(LabelJoinRejection(label, LabelJoinRejectionReason.LABEL_UNMAPPED))
            continue
        mover = catalog.mover(binding.mover_symbol)
        if mover is None:
            rejections.append(
                LabelJoinRejection(label, LabelJoinRejectionReason.MOVER_SYMBOL_UNKNOWN)
            )
            continue
        if mover.display_name is not None and mover.display_name in ambiguous_names:
            rejections.append(
                LabelJoinRejection(label, LabelJoinRejectionReason.DISPLAY_NAME_AMBIGUOUS)
            )
            continue
        joined.append(
            JoinedMoverCandidate(
                candidate_index=candidate_index,
                detector_label=label,
                mover_id=binding.mover_id,
                mover_symbol=binding.mover_symbol,
                display_name=mover.display_name,
                combat=mover.combat,
                drops=catalog.drops_for(mover.symbol),
                mapping_version=mapping.mapping_version,
                client_digest=mapping.client_digest,
                spawn=None if spawn_evidence is None else spawn_evidence.get(binding.mover_id),
            )
        )
    return tuple(joined), tuple(rejections)
