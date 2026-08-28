"""Bind every input an artifact was produced from, by digest (US-083).

A trained model is only meaningful together with the things it was trained against: the static
client tables, the detector and its label order, the world map and baked mesh the coordinates
came from, and the exact set of recorded sessions. Change any of them and the same observation
vector means something different -- a detector whose label order shifted turns class 3 into a
different monster, and a remeshed world turns the same route distance into a different walk.

Nothing in the numbers reveals that. The vector still has the right width, the model still
produces a confident answer, and the answer is quietly about a world that no longer exists.
The only defence is to record what each artifact was built from and refuse to serve it when
those inputs are not the ones present now.

Refusal is the whole design.
[ADR-003](../../../../docs/decisions/ADR-003-clean-schema-over-backward-compatibility.md)
forbids shimming a mismatched artifact, and there is deliberately no partial-compatibility
path: an artifact that names an input the runtime cannot produce is rejected rather than served
on the hope that the difference does not matter, because whether it matters is exactly what
cannot be known from here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum, unique

# The key an artifact document stores its binding under, beside the contract stamp.
ARTIFACT_BINDING_DOCUMENT_KEY = "artifact_binding"
# Reported as the found value when an artifact states nothing for an input.
BINDING_MISSING_MARKER = "none"


@unique
class BoundArtifactKind(StrEnum):
    """Every input whose change would silently alter what an observation means."""

    STATIC_DATASET = "static_dataset"
    YOLO_MODEL = "yolo_model"
    YOLO_LABELS = "yolo_labels"
    WORLD_MAP = "world_map"
    NAVMESH = "navmesh"
    TRAINING_SESSIONS = "training_sessions"


class ArtifactBindingError(ValueError):
    """One artifact was produced from a different input than the one present now."""

    def __init__(self, kind: BoundArtifactKind, *, expected: str, found: str) -> None:
        self.kind = kind
        self.expected = expected
        self.found = found
        super().__init__(f"{kind.value}:expected={expected},found={found}")


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    """The digest of every input one artifact was produced from.

    An input the producer genuinely did not use is simply absent, which is different from one
    it used and could not digest -- the second is a producer defect and shows up as a refusal
    at load time rather than as a silently unbound input.
    """

    digests: Mapping[BoundArtifactKind, str] = field(default_factory=dict)

    def as_document(self) -> dict[str, str]:
        """Return the binding in the form written into an artifact."""

        return {kind.value: digest for kind, digest in sorted(self.digests.items())}

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> ArtifactBinding:
        """Read a binding from an artifact, ignoring inputs this build does not know.

        An unknown key is not an error: a newer producer may bind an input this build has no
        concept of, and the contract version is what rejects that, not this reader.
        """

        digests: dict[BoundArtifactKind, str] = {}
        for kind in BoundArtifactKind:
            value = document.get(kind.value)
            if isinstance(value, str) and value:
                digests[kind] = value
        return cls(digests)

    def digest_of(self, kind: BoundArtifactKind) -> str | None:
        """Return one input's digest, or ``None`` when the artifact bound no such input."""

        return self.digests.get(kind)


def verify_artifact_binding(expected: ArtifactBinding, found: ArtifactBinding) -> None:
    """Raise unless every input the artifact names is the one present now.

    ``expected`` is what the running application can produce; ``found`` is what the artifact
    declares. Three cases, and only the first is allowed:

    * The artifact names an input and it matches -- serve it.
    * The artifact names an input the runtime cannot produce -- refuse. The artifact depends
      on something that is not installed, and serving it would decide on geometry or labels
      that are simply absent.
    * The artifact names an input that differs -- refuse. This is the case the whole module
      exists for, and it is the one that is invisible in the numbers.

    An input the artifact does not name is not checked. A model trained without a world map
    does not become invalid because one is now installed.
    """

    for kind in BoundArtifactKind:
        declared = found.digest_of(kind)
        if declared is None:
            continue
        available = expected.digest_of(kind)
        if available is None:
            raise ArtifactBindingError(kind, expected=BINDING_MISSING_MARKER, found=declared)
        if available != declared:
            raise ArtifactBindingError(kind, expected=available, found=declared)
