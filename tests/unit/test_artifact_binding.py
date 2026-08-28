"""Digest binding of every input an artifact was produced from (US-083 AC11)."""

from __future__ import annotations

import pytest

from flyff_bot.features.policy.artifact_binding import (
    BINDING_MISSING_MARKER,
    ArtifactBinding,
    ArtifactBindingError,
    BoundArtifactKind,
    verify_artifact_binding,
)

MODEL_DIGEST = "a" * 64
OTHER_MODEL_DIGEST = "b" * 64
LABELS_DIGEST = "c" * 64
MESH_DIGEST = "d" * 64


def _binding(**digests: str) -> ArtifactBinding:
    return ArtifactBinding({BoundArtifactKind(kind): value for kind, value in digests.items()})


def test_matching_inputs_are_served() -> None:
    runtime = _binding(yolo_model=MODEL_DIGEST, yolo_labels=LABELS_DIGEST)
    artifact = _binding(yolo_model=MODEL_DIGEST, yolo_labels=LABELS_DIGEST)

    verify_artifact_binding(runtime, artifact)


def test_a_changed_detector_rejects_the_artifact() -> None:
    # A detector whose weights changed turns the same class id into a different monster, and
    # nothing in the vector reveals it.
    runtime = _binding(yolo_model=MODEL_DIGEST)
    artifact = _binding(yolo_model=OTHER_MODEL_DIGEST)

    with pytest.raises(ArtifactBindingError) as error:
        verify_artifact_binding(runtime, artifact)

    assert error.value.kind is BoundArtifactKind.YOLO_MODEL
    assert error.value.expected == MODEL_DIGEST
    assert error.value.found == OTHER_MODEL_DIGEST


def test_an_input_the_runtime_cannot_produce_rejects_the_artifact() -> None:
    # The artifact depends on a mesh that is not installed. Serving it would decide on
    # geometry that is simply absent.
    runtime = _binding(yolo_model=MODEL_DIGEST)
    artifact = _binding(yolo_model=MODEL_DIGEST, navmesh=MESH_DIGEST)

    with pytest.raises(ArtifactBindingError) as error:
        verify_artifact_binding(runtime, artifact)

    assert error.value.kind is BoundArtifactKind.NAVMESH
    assert error.value.expected == BINDING_MISSING_MARKER


def test_an_input_the_artifact_never_bound_is_not_checked() -> None:
    # A model trained without a world map does not become invalid because one is installed.
    runtime = _binding(yolo_model=MODEL_DIGEST, world_map=MESH_DIGEST)
    artifact = _binding(yolo_model=MODEL_DIGEST)

    verify_artifact_binding(runtime, artifact)


def test_there_is_no_partial_compatibility_path() -> None:
    # Every mismatched input refuses; none of them degrades to a warning or a shim.
    runtime = _binding(
        static_dataset=MODEL_DIGEST,
        yolo_model=MODEL_DIGEST,
        yolo_labels=MODEL_DIGEST,
        world_map=MODEL_DIGEST,
        navmesh=MODEL_DIGEST,
        training_sessions=MODEL_DIGEST,
    )

    for kind in BoundArtifactKind:
        with pytest.raises(ArtifactBindingError):
            verify_artifact_binding(runtime, ArtifactBinding({kind: OTHER_MODEL_DIGEST}))


def test_a_binding_round_trips_through_its_document() -> None:
    binding = _binding(yolo_model=MODEL_DIGEST, navmesh=MESH_DIGEST)

    restored = ArtifactBinding.from_document(binding.as_document())

    assert restored == binding


def test_an_unknown_bound_input_is_left_to_the_contract_version() -> None:
    # A newer producer may bind an input this build has no concept of. Rejecting it here
    # would duplicate what the contract version already decides.
    restored = ArtifactBinding.from_document(
        {"yolo_model": MODEL_DIGEST, "some_future_input": OTHER_MODEL_DIGEST}
    )

    assert restored.digest_of(BoundArtifactKind.YOLO_MODEL) == MODEL_DIGEST
    assert restored.digests == {BoundArtifactKind.YOLO_MODEL: MODEL_DIGEST}


def test_an_empty_digest_is_treated_as_no_binding_at_all() -> None:
    restored = ArtifactBinding.from_document({"yolo_model": ""})

    assert restored.digest_of(BoundArtifactKind.YOLO_MODEL) is None
