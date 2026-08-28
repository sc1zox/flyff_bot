"""One versioned manifest of every data source and the consumers that use it (US-083).

A parsed field that no production consumer reads is not free: it is a field an operator
believes the bot is acting on. :func:`verify_consumer_coverage` therefore refuses a manifest
in which any declared field names no consumer, which makes "extracted but silently unused"
a test failure rather than a discovery made months later.

Each entry states where its data came from (the client build digest), what exactly it holds
(the content digest and record count), how complete it is, and how long one sample stays
valid. A live provider's freshness is an age in seconds; a static table's is
:data:`STATIC_UNTIL_REEXTRACTION`, because it changes only when the client itself does.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, unique

# Bumped whenever an entry or field gains, loses or redefines a column.
SOURCE_MANIFEST_SCHEMA_VERSION = "us083-v1"
# A static table is valid until the client data is extracted again, so it carries no age.
STATIC_UNTIL_REEXTRACTION = "static_until_reextraction"


@unique
class SourceKind(StrEnum):
    """Where one source's values come from."""

    #: An offline client table normalized during setup.
    STATIC_TABLE = "static_table"
    #: A read-only live reader polled during a session.
    LIVE_PROVIDER = "live_provider"
    #: An artifact this application bakes from other sources.
    DERIVED_ARTIFACT = "derived_artifact"


@unique
class SourceCompleteness(StrEnum):
    """How much of one declared source this build actually has."""

    #: Every declared record or field was parsed and is available.
    COMPLETE = "complete"
    #: Some records or fields are available and the rest are typed rejections.
    PARTIAL = "partial"
    #: The source is declared but nothing was obtained from it.
    UNAVAILABLE = "unavailable"
    #: Records were parsed, but this build could not confirm the layout they came from.
    UNVERIFIED_LAYOUT = "unverified_layout"


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """One field a source yields, and the production code paths that consume it."""

    name: str
    #: Whether the client stated this value directly or the application computed it.
    is_measured: bool
    #: Fully qualified production consumers. Empty means nothing reads this field.
    consumers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A field provenance entry names its field.")


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """One parsed table or live provider, with everything needed to trust its values."""

    source_id: str
    kind: SourceKind
    schema_version: str
    completeness: SourceCompleteness
    #: Seconds a sample stays valid, or :data:`STATIC_UNTIL_REEXTRACTION` for a static table.
    freshness_rule: str
    fields: tuple[FieldProvenance, ...] = ()
    record_count: int = 0
    client_digest: str = ""
    content_digest: str = ""
    #: Typed reasons records are missing, carried verbatim from the extraction pass.
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("A manifest entry is identified by its source id.")
        if self.record_count < 0:
            raise ValueError("A manifest entry cannot hold a negative record count.")
        if self.kind is SourceKind.LIVE_PROVIDER and self.freshness_rule == (
            STATIC_UNTIL_REEXTRACTION
        ):
            raise ValueError("A live provider states a sample age, not a static freshness rule.")

    def as_document(self) -> dict[str, object]:
        """Return the entry in the form written into the manifest artifact."""

        return {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "schema_version": self.schema_version,
            "completeness": self.completeness.value,
            "freshness_rule": self.freshness_rule,
            "record_count": self.record_count,
            "client_digest": self.client_digest,
            "content_digest": self.content_digest,
            "diagnostics": list(self.diagnostics),
            "fields": [
                {
                    "name": provenance.name,
                    "is_measured": provenance.is_measured,
                    "consumers": list(provenance.consumers),
                }
                for provenance in self.fields
            ],
        }


@dataclass(frozen=True, slots=True)
class UnconsumedField:
    """One parsed field that no production consumer reads."""

    source_id: str
    field_name: str


class ConsumerCoverageError(ValueError):
    """One or more parsed fields are declared without any production consumer."""

    def __init__(self, unconsumed: tuple[UnconsumedField, ...]) -> None:
        self.unconsumed = unconsumed
        super().__init__(",".join(f"{item.source_id}.{item.field_name}" for item in unconsumed))


@dataclass(frozen=True, slots=True)
class SourceManifest:
    """Every source this build reads, in one versioned, digest-bound document."""

    entries: tuple[SourceEntry, ...] = ()
    client_digest: str = ""
    generated_at: str = ""
    schema_version: str = SOURCE_MANIFEST_SCHEMA_VERSION

    def entry(self, source_id: str) -> SourceEntry | None:
        """Return one entry by its exact source id."""

        for entry in self.entries:
            if entry.source_id == source_id:
                return entry
        return None

    def as_document(self) -> dict[str, object]:
        """Return the manifest in the form written to disk."""

        return {
            "schema_version": self.schema_version,
            "client_digest": self.client_digest,
            "generated_at": self.generated_at,
            "entries": [entry.as_document() for entry in self.entries],
        }


def content_digest(payload: object) -> str:
    """Return a stable digest of one artifact's content.

    The document is serialized with sorted keys so an unrelated ordering change cannot make
    two identical datasets look different.
    """

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def utc_timestamp() -> str:
    """Return the UTC instant a manifest was generated, in ISO-8601 form."""

    return datetime.now(UTC).isoformat()


def unconsumed_fields(manifest: SourceManifest) -> tuple[UnconsumedField, ...]:
    """Return every declared field that names no production consumer."""

    return tuple(
        UnconsumedField(entry.source_id, provenance.name)
        for entry in manifest.entries
        for provenance in entry.fields
        if not provenance.consumers
    )


def verify_consumer_coverage(manifest: SourceManifest) -> None:
    """Raise when any parsed field would remain silently unused."""

    unconsumed = unconsumed_fields(manifest)
    if unconsumed:
        raise ConsumerCoverageError(unconsumed)


def build_manifest(
    entries: Iterable[SourceEntry],
    *,
    client_digest: str,
    generated_at: str | None = None,
) -> SourceManifest:
    """Return one manifest over the supplied entries, stamped with the client build."""

    return SourceManifest(
        entries=tuple(entries),
        client_digest=client_digest,
        generated_at=generated_at or utc_timestamp(),
    )
