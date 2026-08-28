"""Decide whether a tick's live samples describe one instant, or refuse to fuse them (US-083).

A fused candidate is only meaningful if every source that contributed to it was read from the
same moment in the same world. The camera, the GPS coordinate, the adopted world map, and the
baked NavMesh are polled independently, so nothing in the types alone stops a stale camera pose
from being unprojected against a fresh player position: the arithmetic succeeds and produces a
world coordinate that no entity ever occupied. That is the failure this module exists to make
impossible.

The rule is refusal, not repair. An incoherent set yields no enrichment and a typed reason with
the per-source ages that produced it, because a decision taken on a coordinate the client never
reported is worse than a decision deferred until the next coherent tick.

Two kinds of source are checked differently and deliberately so. A *live* source carries a
sample age: the camera and the GPS coordinate describe a pose that decays within a frame or
two. A *static* source -- the baked mesh, the adopted world map -- has no age to decay; it is
an offline artifact, and the only way it can be wrong is by describing a different world than
the one the character is standing in. Ageing a baked mesh would reject every long session; not
checking its world would silently unproject into another map's geometry.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

# A live pose read older than this no longer describes where the camera or the character is.
# The client renders faster than this, so a sample this old means a poll was missed rather
# than merely delayed, and the miss is the signal worth acting on.
DEFAULT_LIVE_SAMPLE_MAX_AGE_SECONDS = 0.35
# Two live reads further apart than this are not one observation, however fresh each is on its
# own: the character can travel a meaningful distance between them, so the pair describes two
# different instants and unprojecting one against the other misplaces the result.
DEFAULT_INTERVAL_MAX_SPAN_SECONDS = 0.2


class ObservationSource(StrEnum):
    """The independently polled sources one fused candidate is built from."""

    CAMERA = "camera"
    GPS = "gps"
    WORLD_MAP = "world_map"
    NAVMESH = "navmesh"


class IntervalRejection(StrEnum):
    """Why a tick's samples could not be treated as one coherent observation."""

    SOURCE_MISSING = "source_missing"
    SOURCE_STALE = "source_stale"
    INTERVAL_INCOHERENT = "interval_incoherent"
    CROSS_WORLD = "cross_world"
    CLOCK_DISCONTINUITY = "clock_discontinuity"


@dataclass(frozen=True, slots=True)
class ObservationSample:
    """One source's contribution to a tick, with everything needed to judge it.

    ``sampled_at_seconds`` is ``None`` for a static source, which has no age, and for a live
    source that produced no reading at all -- ``is_available`` separates those two cases.
    """

    source: ObservationSource
    sampled_at_seconds: float | None = None
    world_id: int | None = None
    is_live: bool = True
    is_available: bool = True


@dataclass(frozen=True, slots=True)
class ObservationInterval:
    """The verdict on one tick's sample set, and the evidence behind it."""

    ages_seconds: tuple[tuple[ObservationSource, float | None], ...] = ()
    span_seconds: float | None = None
    world_id: int | None = None
    rejection: IntervalRejection | None = None
    rejected_sources: tuple[ObservationSource, ...] = ()

    @property
    def is_coherent(self) -> bool:
        """Return whether every sample described the same instant in the same world."""

        return self.rejection is None

    def age_of(self, source: ObservationSource) -> float | None:
        """Return one source's measured age, or ``None`` when it has none."""

        for candidate, age in self.ages_seconds:
            if candidate is source:
                return age
        return None


def evaluate_observation_interval(
    samples: tuple[ObservationSample, ...],
    at_seconds: float,
    max_age_seconds: float = DEFAULT_LIVE_SAMPLE_MAX_AGE_SECONDS,
    max_span_seconds: float = DEFAULT_INTERVAL_MAX_SPAN_SECONDS,
) -> ObservationInterval:
    """Classify a tick's samples as one coherent observation, or state why they are not.

    Rejections are reported in a fixed precedence so a session reads one stable diagnostic
    while several faults overlap: a source that is absent cannot also be judged stale, and a
    clock that ran backwards makes every age meaningless rather than merely large.
    """

    ages = tuple((sample.source, _age_of(sample, at_seconds)) for sample in samples)
    world_id = _single_world_id(samples)

    if any(not sample.is_available for sample in samples):
        return ObservationInterval(
            ages,
            None,
            world_id,
            IntervalRejection.SOURCE_MISSING,
            _sources(sample for sample in samples if not sample.is_available),
        )

    future = tuple(
        sample
        for sample in samples
        if sample.sampled_at_seconds is not None and sample.sampled_at_seconds > at_seconds
    )
    if future:
        return ObservationInterval(
            ages, None, world_id, IntervalRejection.CLOCK_DISCONTINUITY, _sources(future)
        )

    conflicting = _conflicting_worlds(samples)
    if conflicting:
        return ObservationInterval(ages, None, None, IntervalRejection.CROSS_WORLD, conflicting)

    stale = tuple(
        source
        for source, age in ages
        if age is not None and _is_live(samples, source) and age > max_age_seconds
    )
    if stale:
        return ObservationInterval(ages, None, world_id, IntervalRejection.SOURCE_STALE, stale)

    span = _live_span(samples)
    if span is not None and span > max_span_seconds:
        return ObservationInterval(
            ages,
            span,
            world_id,
            IntervalRejection.INTERVAL_INCOHERENT,
            _sources(sample for sample in samples if sample.is_live),
        )
    return ObservationInterval(ages, span, world_id)


def _age_of(sample: ObservationSample, at_seconds: float) -> float | None:
    timestamp = sample.sampled_at_seconds
    if timestamp is None or not math.isfinite(timestamp):
        return None
    return at_seconds - timestamp


def _is_live(samples: tuple[ObservationSample, ...], source: ObservationSource) -> bool:
    return any(sample.source is source and sample.is_live for sample in samples)


def _live_span(samples: tuple[ObservationSample, ...]) -> float | None:
    timestamps = [
        sample.sampled_at_seconds
        for sample in samples
        if sample.is_live
        and sample.sampled_at_seconds is not None
        and math.isfinite(sample.sampled_at_seconds)
    ]
    if len(timestamps) < 2:
        return None
    return max(timestamps) - min(timestamps)


def _single_world_id(samples: tuple[ObservationSample, ...]) -> int | None:
    declared = {sample.world_id for sample in samples if sample.world_id is not None}
    return declared.pop() if len(declared) == 1 else None


def _conflicting_worlds(samples: tuple[ObservationSample, ...]) -> tuple[ObservationSource, ...]:
    """Return the sources disagreeing about the world, or nothing when they agree.

    A source that does not know its world is not in conflict with one that does. Only two
    stated and different worlds are a conflict, because that is the case where fusing them
    would combine geometry from two maps.
    """

    declared = {sample.world_id for sample in samples if sample.world_id is not None}
    if len(declared) < 2:
        return ()
    return _sources(sample for sample in samples if sample.world_id is not None)


def _sources(samples: Iterable[ObservationSample]) -> tuple[ObservationSource, ...]:
    return tuple(sorted({sample.source for sample in samples}, key=lambda source: source.value))
