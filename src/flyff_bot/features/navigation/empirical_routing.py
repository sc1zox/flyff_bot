"""Digest-bound empirical traversal costs for baked NavMesh routing."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

EMPIRICAL_NAVMESH_SCHEMA_VERSION = 1
DEFAULT_NOMINAL_SPEED_UNITS_PER_SECOND = 4.0
DEFAULT_EXPERIENCE_WEIGHT = 0.5
DEFAULT_MINIMUM_EDGE_SAMPLES = 5
DEFAULT_SPARSE_SAMPLE_WEIGHT_FRACTION = 0.25


@dataclass(frozen=True, slots=True)
class ExperienceRoutingConfig:
    """Weights that turn observed traversal evidence into A* edge costs."""

    nominal_speed_units_per_second: float = DEFAULT_NOMINAL_SPEED_UNITS_PER_SECOND
    experience_weight: float = DEFAULT_EXPERIENCE_WEIGHT
    minimum_edge_samples: int = DEFAULT_MINIMUM_EDGE_SAMPLES
    sparse_sample_weight_fraction: float = DEFAULT_SPARSE_SAMPLE_WEIGHT_FRACTION

    def __post_init__(self) -> None:
        speed = self.nominal_speed_units_per_second
        if not math.isfinite(speed) or speed <= 0.0:
            raise ValueError("Nominal NavMesh speed must be finite and positive.")
        if not 0.0 <= self.experience_weight <= 1.0:
            raise ValueError("Experience weight must be between zero and one.")
        if self.minimum_edge_samples <= 0:
            raise ValueError("Minimum empirical edge samples must be positive.")
        fraction = self.sparse_sample_weight_fraction
        if not 0.0 < fraction <= 1.0:
            raise ValueError("Sparse sample weight fraction must be between zero and one.")


@dataclass(frozen=True, slots=True)
class PolygonTraversalStats:
    """Observed GPS dwell and stall evidence on one stable NavMesh polygon."""

    polygon_id: int
    traversal_count: int
    stall_count: int
    mean_traversal_seconds: float
    mean_recovery_seconds: float


@dataclass(frozen=True, slots=True)
class EdgeTraversalStats:
    """Directed empirical traversal statistics for one NavMesh polygon transition."""

    from_polygon_id: int
    to_polygon_id: int
    traversal_count: int
    stall_count: int
    distance_units: float
    mean_travel_seconds: float
    mean_recovery_seconds: float

    @property
    def stuck_probability(self) -> float:
        """Return the observed fraction of traversals that stalled."""

        return self.stall_count / self.traversal_count

    @property
    def expected_cost_seconds(self) -> float:
        """Return observed movement time plus expected stall-recovery time."""

        return self.mean_travel_seconds + self.stuck_probability * self.mean_recovery_seconds


def _validated_stats(*, traversal_count: int, stall_count: int, mean_seconds: float) -> None:
    if traversal_count < 0 or stall_count < 0 or stall_count > traversal_count:
        raise ValueError("Empirical traversal and stall counts are inconsistent.")
    if not math.isfinite(mean_seconds) or mean_seconds < 0.0:
        raise ValueError("Empirical duration statistics must be finite and non-negative.")


def _validated_polygon(stats: PolygonTraversalStats) -> PolygonTraversalStats:
    for mean_seconds in (stats.mean_traversal_seconds, stats.mean_recovery_seconds):
        _validated_stats(
            traversal_count=stats.traversal_count,
            stall_count=stats.stall_count,
            mean_seconds=mean_seconds,
        )
    return stats


def _validated_edge(stats: EdgeTraversalStats) -> EdgeTraversalStats:
    if stats.from_polygon_id <= 0 or stats.to_polygon_id <= 0:
        raise ValueError("Empirical edge polygon IDs must be positive.")
    if not math.isfinite(stats.distance_units) or stats.distance_units <= 0.0:
        raise ValueError("Empirical edge distance must be finite and positive.")
    for mean_seconds in (stats.mean_travel_seconds, stats.mean_recovery_seconds):
        _validated_stats(
            traversal_count=stats.traversal_count,
            stall_count=stats.stall_count,
            mean_seconds=mean_seconds,
        )
    return stats


@dataclass(frozen=True, slots=True)
class EmpiricalCostIndex:
    """An immutable, compact lookup indexed by the mesh's exact content digest."""

    mesh_digest: str
    polygons: Mapping[int, PolygonTraversalStats]
    edges: Mapping[tuple[int, int], EdgeTraversalStats]
    config: ExperienceRoutingConfig = ExperienceRoutingConfig()

    @property
    def lookup_count(self) -> int:
        """Return the number of pre-resolved polygon and edge cost records."""

        return len(self.polygons) + len(self.edges)

    def edge_stats(self, from_polygon_id: int, to_polygon_id: int) -> EdgeTraversalStats | None:
        """Return directed evidence, falling back to the reverse transition."""

        return self.edges.get((from_polygon_id, to_polygon_id)) or self.edges.get(
            (to_polygon_id, from_polygon_id)
        )

    def weighted_edge_cost(
        self,
        distance_units: float,
        from_polygon_id: int,
        to_polygon_id: int,
        config: ExperienceRoutingConfig | None = None,
    ) -> float:
        """Blend geometric and empirical costs with a smooth sparse-sample fallback."""

        settings = config or self.config
        geometric_cost = distance_units / settings.nominal_speed_units_per_second
        stats = self.edge_stats(from_polygon_id, to_polygon_id)
        if stats is None:
            return geometric_cost
        confidence = min(
            1.0,
            (
                settings.sparse_sample_weight_fraction
                if stats.traversal_count < settings.minimum_edge_samples
                else 1.0
            )
            * stats.traversal_count
            / settings.minimum_edge_samples,
        )
        empirical_weight = settings.experience_weight * confidence
        return (1.0 - empirical_weight) * geometric_cost + (
            empirical_weight * stats.expected_cost_seconds
        )


@dataclass(frozen=True, slots=True)
class EmpiricalCostArtifact:
    """A saved empirical index and the digest of its canonical encoded payload."""

    index: EmpiricalCostIndex
    path: Path
    content_digest: str


def world_empirical_path(directory: Path, world_name: str) -> Path:
    """Return the empirical artifact stored beside one world's NavMesh cache."""

    return directory / f"{world_name.lower()}.empirical.json"


def save_empirical_cost_index(index: EmpiricalCostIndex, path: Path) -> EmpiricalCostArtifact:
    """Write a versioned, self-verifying empirical lookup without changing client assets."""

    payload = _document(index)
    document = {
        "schema_version": EMPIRICAL_NAVMESH_SCHEMA_VERSION,
        "mesh_digest": index.mesh_digest,
        "payload_digest": _digest(_encode(payload)),
        "payload": payload,
    }
    encoded = _encode(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return EmpiricalCostArtifact(index, path, _digest(encoded))


def load_empirical_cost_index(path: Path, mesh_digest: str) -> EmpiricalCostIndex:
    """Load an empirical lookup only when its payload matches the supplied mesh digest."""

    try:
        value: object = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise EmpiricalCostError(f"Cannot read empirical NavMesh artifact {path}.") from error
    if not isinstance(value, dict):
        raise EmpiricalCostError("Empirical NavMesh document must be an object.")
    if value.get("schema_version") != EMPIRICAL_NAVMESH_SCHEMA_VERSION:
        raise EmpiricalCostError("Unsupported empirical NavMesh schema version.")
    if value.get("mesh_digest") != mesh_digest:
        raise EmpiricalCostError("Empirical NavMesh digest does not match the loaded mesh.")
    payload = value.get("payload")
    if not isinstance(payload, dict) or value.get("payload_digest") != _digest(_encode(payload)):
        raise EmpiricalCostError("Empirical NavMesh payload failed integrity validation.")
    return _index(value["mesh_digest"], payload)


class EmpiricalCostError(ValueError):
    """Raised when an empirical cost artifact is malformed or mismatched."""


def _document(index: EmpiricalCostIndex) -> dict[str, object]:
    return {
        "config": {
            "nominal_speed_units_per_second": index.config.nominal_speed_units_per_second,
            "experience_weight": index.config.experience_weight,
            "minimum_edge_samples": index.config.minimum_edge_samples,
            "sparse_sample_weight_fraction": index.config.sparse_sample_weight_fraction,
        },
        "polygons": [
            {
                "polygon_id": stats.polygon_id,
                "traversal_count": stats.traversal_count,
                "stall_count": stats.stall_count,
                "mean_traversal_seconds": stats.mean_traversal_seconds,
                "mean_recovery_seconds": stats.mean_recovery_seconds,
            }
            for _, stats in sorted(index.polygons.items())
        ],
        "edges": [
            {
                "from_polygon_id": stats.from_polygon_id,
                "to_polygon_id": stats.to_polygon_id,
                "traversal_count": stats.traversal_count,
                "stall_count": stats.stall_count,
                "distance_units": stats.distance_units,
                "mean_travel_seconds": stats.mean_travel_seconds,
                "mean_recovery_seconds": stats.mean_recovery_seconds,
            }
            for _, stats in sorted(index.edges.items())
        ],
    }


def _index(mesh_digest: object, payload: object) -> EmpiricalCostIndex:
    if not isinstance(mesh_digest, str) or not isinstance(payload, dict):
        raise EmpiricalCostError("Empirical NavMesh identity or payload is invalid.")
    raw_config = payload.get("config")
    raw_polygons = payload.get("polygons")
    raw_edges = payload.get("edges")
    if not isinstance(raw_config, dict) or not isinstance(raw_polygons, list):
        raise EmpiricalCostError("Empirical NavMesh configuration or polygons are invalid.")
    if not isinstance(raw_edges, list):
        raise EmpiricalCostError("Empirical NavMesh edges are invalid.")
    config = ExperienceRoutingConfig(
        nominal_speed_units_per_second=_number(raw_config.get("nominal_speed_units_per_second")),
        experience_weight=_number(raw_config.get("experience_weight")),
        minimum_edge_samples=_integer(raw_config.get("minimum_edge_samples")),
        sparse_sample_weight_fraction=_number(raw_config.get("sparse_sample_weight_fraction")),
    )
    polygons = {
        stats.polygon_id: stats
        for stats in (
            _validated_polygon(
                PolygonTraversalStats(
                    _positive_integer(item.get("polygon_id"), "polygon ID"),
                    _non_negative_integer(item.get("traversal_count"), "traversal count"),
                    _non_negative_integer(item.get("stall_count"), "stall count"),
                    _number(item.get("mean_traversal_seconds")),
                    _number(item.get("mean_recovery_seconds")),
                )
            )
            for item in raw_polygons
            if isinstance(item, dict)
        )
    }
    if len(polygons) != len(raw_polygons):
        raise EmpiricalCostError("Empirical NavMesh polygon IDs must be unique.")
    edges = {
        (stats.from_polygon_id, stats.to_polygon_id): stats
        for stats in (
            _validated_edge(
                EdgeTraversalStats(
                    _positive_integer(item.get("from_polygon_id"), "source polygon ID"),
                    _positive_integer(item.get("to_polygon_id"), "target polygon ID"),
                    _non_negative_integer(item.get("traversal_count"), "traversal count"),
                    _non_negative_integer(item.get("stall_count"), "stall count"),
                    _number(item.get("distance_units")),
                    _number(item.get("mean_travel_seconds")),
                    _number(item.get("mean_recovery_seconds")),
                )
            )
            for item in raw_edges
            if isinstance(item, dict)
        )
    }
    if len(edges) != len(raw_edges):
        raise EmpiricalCostError("Empirical NavMesh edge IDs must be unique.")
    return EmpiricalCostIndex(str(mesh_digest), polygons, edges, config)


def _encode(document: dict[str, object] | Mapping[str, object]) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _digest(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EmpiricalCostError("Empirical NavMesh number is invalid.")
    return float(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EmpiricalCostError("Empirical NavMesh integer is invalid.")
    return value


def _non_negative_integer(value: object, label: str) -> int:
    integer = _integer(value)
    if integer < 0:
        raise EmpiricalCostError(f"Empirical NavMesh {label} must not be negative.")
    return integer


def _positive_integer(value: object, label: str) -> int:
    integer = _non_negative_integer(value, label)
    if integer == 0:
        raise EmpiricalCostError(f"Empirical NavMesh {label} must be positive.")
    return integer
