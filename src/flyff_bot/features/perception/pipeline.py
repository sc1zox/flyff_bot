"""Perception application service for building coherent world-state snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol

import cv2

from flyff_bot.features.automation.models import (
    PlayerVitals,
    SelectedTarget,
    TargetState,
    Viewport,
    VisibleMob,
    WorldState,
)
from flyff_bot.features.automation.observation_interval import ObservationInterval
from flyff_bot.features.client_data.label_mapping import SpawnZoneDeclaration
from flyff_bot.features.perception.catalog_join import MobCatalogJoin
from flyff_bot.features.perception.mob_world_position import (
    MobWorldGeometryFeed,
    MobWorldPositionEstimator,
    with_estimated_world_positions,
)
from flyff_bot.features.player_stats.models import (
    ClientPlayerStatsSnapshot,
    PlayerStatsSource,
)
from flyff_bot.features.vision.capture import FrameSource
from flyff_bot.features.vision.detection import Detection, DetectionError, Detector
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.features.vision.target_verification import (
    TargetStatus,
    TargetVerificationResult,
)
from flyff_bot.features.vision.vitals import PlayerVitalsFeed, PlayerVitalsReader

# Named so the handlers below stay single-name `except` clauses. The pinned formatter
# rewrites an inline `except (A, B):` into invalid Python, and a named tuple also says
# what the group of failures means.
DETECTION_ERRORS = (DetectionError, cv2.error)
FRAME_READ_ERRORS = (ValueError, cv2.error)


class PerceptionFailure(StrEnum):
    """A non-fatal feed failure observed while processing a frame."""

    DETECTION = "detection"
    TARGET_VERIFICATION = "target_verification"
    VITALS_READING = "vitals_reading"


class PlayerStatsProvider(Protocol):
    """A provider of exact-profile client-memory statistics."""

    def poll(self, at_seconds: float) -> ClientPlayerStatsSnapshot: ...

    def close(self) -> None: ...


class TargetVerificationFeed(Protocol):
    """A component that classifies the selected target from a captured frame."""

    def verify(self, frame: CapturedFrame) -> TargetVerificationResult:
        """Return the current target classification."""


class PerceptionEventKind(StrEnum):
    """State transitions emitted by one perception tick."""

    TARGET_CHANGED = "target_changed"
    MOB_APPEARED = "mob_appeared"
    VITALS_CHANGED = "vitals_changed"


@dataclass(frozen=True, slots=True)
class PerceptionEvent:
    """A material change between two world-state snapshots."""

    kind: PerceptionEventKind
    target: SelectedTarget | None = None
    mob: VisibleMob | None = None
    vitals: PlayerVitals | None = None


@dataclass(frozen=True, slots=True)
class PerceptionTick:
    """The state and feed outcomes produced from one captured frame."""

    state: WorldState
    events: tuple[PerceptionEvent, ...]
    failures: frozenset[PerceptionFailure]
    frame: CapturedFrame | None = None


class PerceptionPipeline:
    """Capture once and independently aggregate all perception feeds."""

    def __init__(
        self,
        frame_source: FrameSource,
        detector: Detector,
        target_verifier: TargetVerificationFeed,
        clock: Callable[[], float] = monotonic,
        vitals_reader: PlayerVitalsFeed | None = None,
        player_stats_reader: PlayerStatsProvider | None = None,
    ) -> None:
        self._frame_source = frame_source
        self._detector = detector
        self._target_verifier = target_verifier
        self._clock = clock
        # The HUD reader is always built, even when an exact client-memory provider is
        # configured: a client whose build is not fingerprinted has to keep reporting vitals
        # from what is on screen instead of blocking the session (US-085).
        self._vitals_reader = vitals_reader or PlayerVitalsReader()
        self._player_stats_reader = player_stats_reader
        self._mob_world_estimator: MobWorldPositionEstimator | None = None
        self._catalog_join: MobCatalogJoin | None = None
        self._adopted_world_id: int | None = None

    def attach_world_geometry(self, geometry: MobWorldGeometryFeed | None) -> None:
        """Bind, or release, the live camera and NavMesh detections are unprojected against.

        Without a feed the pipeline keeps reporting purely client-space detections, which is
        exactly what a session without a baked mesh or a readable camera has to work from.
        """

        self._mob_world_estimator = (
            None if geometry is None else MobWorldPositionEstimator(geometry)
        )

    def attach_client_catalog(self, catalog_join: MobCatalogJoin | None) -> None:
        """Bind, or release, the authoritative catalog detections are enriched from.

        Without a join the pipeline reports the same unenriched detections it always has,
        which is what an install with no extracted client data has to work from.
        """

        self._catalog_join = catalog_join

    def attach_spawn_zones(self, zones: Iterable[SpawnZoneDeclaration]) -> None:
        """Read spawn capacity and respawn cadence from the world now being farmed.

        Does nothing until a catalog is attached: spawn numbers describe a mover, and
        without the join there is no mover to attribute them to.
        """

        if self._catalog_join is not None:
            self._catalog_join = self._catalog_join.with_spawn_zones(zones)

    def adopt_world_id(self, world_id: int | None) -> None:
        """Record which world the session's offline geometry was adopted for.

        The mesh and the map are offline artifacts that cannot notice a teleport. Pinning the
        world they were adopted in is what lets a later tick see that the client has moved to
        a different one and refuse to unproject into geometry that no longer applies.
        """

        self._adopted_world_id = world_id

    @property
    def has_player_stats_provider(self) -> bool:
        """Return whether exact client-memory player statistics are configured."""

        return self._player_stats_reader is not None

    def demote_player_stats_provider(self) -> bool:
        """Release the exact client-memory reader and fall back to the visual HUD.

        A profile the running client build was never fingerprinted for can never start
        working, so the session drops it once instead of reporting the same block forever.
        Returns whether this call was the one that performed the demotion.
        """

        if self._player_stats_reader is None:
            return False
        self.close()
        self._player_stats_reader = None
        return True

    def restore_player_stats_provider(self, reader: PlayerStatsProvider) -> None:
        """Re-adopt a reloaded exact-profile reader after an unsupported-build demotion."""

        if self._player_stats_reader is not None and self._player_stats_reader is not reader:
            self._player_stats_reader.close()
        self._player_stats_reader = reader

    def tick(
        self,
        window_handle: int,
        previous_state: WorldState,
        *,
        poll_live_providers: bool = True,
    ) -> PerceptionTick:
        """Build a new snapshot, retaining a feed's prior data if that feed fails."""

        frame = self._frame_source.capture(window_handle)
        # Read once, at the top, and judge every source against this one instant. Two clock
        # reads in a tick would be the very incoherence the interval check exists to catch.
        observed_at_seconds = self._clock()
        viewport = Viewport(frame.client_size.width, frame.client_size.height)
        failures: set[PerceptionFailure] = set()
        visible_mobs = previous_state.visible_mobs
        selected_target = previous_state.selected_target
        player_vitals = previous_state.player_vitals
        monster_kill_count = previous_state.monster_kill_count
        catalog_joins = previous_state.mob_catalog_joins
        catalog_rejections = previous_state.mob_catalog_rejections
        observation_interval = ObservationInterval()

        try:
            visible_mobs = tuple(
                _visible_mob(index, detection)
                for index, detection in enumerate(self._detector.detect(frame))
            )
        except DETECTION_ERRORS:
            failures.add(PerceptionFailure.DETECTION)
        else:
            if self._mob_world_estimator is not None:
                observation = self._mob_world_estimator.observe(
                    visible_mobs,
                    viewport,
                    observed_at_seconds,
                    adopted_world_id=self._adopted_world_id,
                )
                observation_interval = observation.interval
                visible_mobs = with_estimated_world_positions(visible_mobs, observation.estimates)
            # Joined against this frame's own detections, so the enrichment can never
            # outlive the boxes it describes: a failed detection keeps the previous join
            # alongside the previous mobs instead of re-keying a stale one.
            catalog_joins, catalog_rejections = (
                ((), ()) if self._catalog_join is None else self._catalog_join.join(visible_mobs)
            )
        try:
            selected_target = _selected_target(self._target_verifier.verify(frame))
        except FRAME_READ_ERRORS:
            failures.add(PerceptionFailure.TARGET_VERIFICATION)
        player_stats_snapshot = previous_state.player_stats_snapshot
        try:
            if self._player_stats_reader is not None and poll_live_providers:
                snapshot = self._player_stats_reader.poll(observed_at_seconds)
                player_stats_snapshot = snapshot
                if snapshot.source is PlayerStatsSource.CLIENT_MEMORY:
                    values = {field.name: field.value for field in snapshot.fields}
                    if all(name in values for name in ("hp", "mp", "fp")):
                        player_vitals = PlayerVitals(
                            values["hp"],
                            values["mp"],
                            values["fp"],
                        )
                    if "monster_kills" in values:
                        monster_kill_count = int(values["monster_kills"])
            elif self._player_stats_reader is None:
                player_vitals = self._vitals_reader.read(frame)
        except FRAME_READ_ERRORS:
            failures.add(PerceptionFailure.VITALS_READING)

        state = WorldState(
            observed_at_seconds=observed_at_seconds,
            position=previous_state.position,
            nearby_mob_count=len(visible_mobs),
            inventory=previous_state.inventory,
            progress_marker=previous_state.progress_marker,
            is_stuck=previous_state.is_stuck,
            selected_target=selected_target,
            visible_mobs=visible_mobs,
            viewport=viewport,
            player_vitals=player_vitals,
            player_stats_snapshot=player_stats_snapshot,
            monster_kill_count=monster_kill_count,
            mob_catalog_joins=catalog_joins,
            mob_catalog_rejections=catalog_rejections,
            observation_interval=observation_interval,
        )
        return PerceptionTick(state, _events(previous_state, state), frozenset(failures), frame)

    def close(self) -> None:
        """Release any read-only live provider owned by this pipeline."""

        close = getattr(self._player_stats_reader, "close", None)
        if callable(close):
            close()


def _visible_mob(candidate_index: int, detection: Detection) -> VisibleMob:
    """Give one decoded box its per-instance identity for the rest of the tick (US-079)."""

    box = detection.bounding_box
    return VisibleMob(
        detection.class_id,
        detection.class_name,
        detection.confidence,
        box.x,
        box.y,
        box.width,
        box.height,
        candidate_index=candidate_index,
    )


def _selected_target(result: TargetVerificationResult) -> SelectedTarget:
    state_by_status = {
        TargetStatus.VALID_TARGET: TargetState.VALID,
        TargetStatus.WRONG_TARGET: TargetState.WRONG,
        TargetStatus.NO_TARGET: TargetState.NONE,
    }
    return SelectedTarget(
        state_by_status[result.status],
        result.target_name,
        result.hp_pixel_count,
        result.hp_percentage,
        result.metrics,
    )


def _events(previous_state: WorldState, state: WorldState) -> tuple[PerceptionEvent, ...]:
    events: list[PerceptionEvent] = []
    if state.selected_target != previous_state.selected_target:
        events.append(
            PerceptionEvent(PerceptionEventKind.TARGET_CHANGED, target=state.selected_target)
        )
    if state.player_vitals != previous_state.player_vitals:
        events.append(
            PerceptionEvent(PerceptionEventKind.VITALS_CHANGED, vitals=state.player_vitals)
        )
    previous_mobs = set(previous_state.visible_mobs)
    events.extend(
        PerceptionEvent(PerceptionEventKind.MOB_APPEARED, mob=mob)
        for mob in state.visible_mobs
        if mob not in previous_mobs
    )
    return tuple(events)
