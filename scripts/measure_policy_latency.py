"""Measure live tactical-policy inference latency on the target machine.

The policy latency budget in `src/flyff_bot/features/policy/models.py` is a safety threshold:
exceeding it discards the learned decision. A threshold that is guessed either fires constantly
or never fires, so it is derived from this harness and recorded in
`docs/sources/2026-08-28-tactical-policy-inference-latency-measurement.md` (US-086).

Run it from the repository root:

    uv run python scripts/measure_policy_latency.py
"""

from __future__ import annotations

import platform
import statistics
from dataclasses import dataclass
from time import perf_counter

# Importing the navigation package first establishes the package import order the application
# itself uses; importing a leaf policy module first hits a circular import.
import flyff_bot.features.navigation  # noqa: F401
from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.policy.hierarchical import (
    HierarchicalObjective,
    HierarchicalObjectiveKind,
    HierarchicalPolicy,
)
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext

#: Candidate counts spanning an empty camp up to a crowded spawn rectangle.
CANDIDATE_COUNTS = (1, 4, 8, 16)
SAMPLES_PER_COUNT = 2_000
MILLISECONDS_PER_SECOND = 1_000.0
P95 = 0.95
P99 = 0.99
CLIENT_WIDTH = 1_920
CLIENT_HEIGHT = 1_080


@dataclass(frozen=True, slots=True)
class LatencyMeasurement:
    """One measured distribution of policy evaluations, in milliseconds."""

    candidate_count: int
    median_ms: float
    p95_ms: float
    p99_ms: float
    maximum_ms: float


def _candidate(identifier: int, original_position: int) -> PolicyCandidate:
    return PolicyCandidate(
        VisibleMob(
            identifier,
            f"Mob{identifier}",
            0.9,
            identifier * 10,
            20,
            5,
            5,
            float(identifier),
            2.0,
            3.0,
            navmesh_path_distance=float(identifier),
        ),
        True,
        True,
        True,
        True,
        True,
        original_position,
    )


def measure(candidate_count: int, samples: int = SAMPLES_PER_COUNT) -> LatencyMeasurement:
    """Return the measured evaluation latency distribution for one candidate count."""

    state = WorldState(
        1.0,
        Position(50, 50),
        candidate_count,
        (),
        0,
        viewport=Viewport(CLIENT_WIDTH, CLIENT_HEIGHT),
    )
    candidates = tuple(_candidate(index + 1, index) for index in range(candidate_count))
    policy = HierarchicalPolicy(
        objective=HierarchicalObjective(
            HierarchicalObjectiveKind.FARMING,
            frozenset(item.mob.class_name for item in candidates),
        )
    )
    durations: list[float] = []
    for index in range(samples):
        # A fresh macro-event token each iteration forces a full re-decision rather than
        # measuring the high-level policy's retention shortcut.
        context = PolicyContext(
            candidates,
            frozenset(),
            tuple(False for _ in candidates),
            macro_event_token=(index,),
        )
        started_at = perf_counter()
        policy.evaluate(state, context)
        durations.append((perf_counter() - started_at) * MILLISECONDS_PER_SECOND)
    durations.sort()
    return LatencyMeasurement(
        candidate_count,
        statistics.median(durations),
        durations[int(samples * P95)],
        durations[int(samples * P99)],
        durations[-1],
    )


def main() -> None:
    """Print one measurement row per candidate count."""

    print(f"machine: {platform.processor()} | python {platform.python_version()}")
    for count in CANDIDATE_COUNTS:
        result = measure(count)
        print(
            f"candidates={result.candidate_count:2d} "
            f"median={result.median_ms:.4f} ms "
            f"p95={result.p95_ms:.4f} ms "
            f"p99={result.p99_ms:.4f} ms "
            f"max={result.maximum_ms:.4f} ms"
        )


if __name__ == "__main__":
    main()
