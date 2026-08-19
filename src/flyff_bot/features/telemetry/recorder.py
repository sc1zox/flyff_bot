"""Orchestrator-facing non-blocking telemetry recorder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from math import dist, hypot
from time import monotonic_ns

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.navigation.live_camera import CameraState
from flyff_bot.features.navigation.live_position import PositionSource, WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh
from flyff_bot.features.telemetry.geometry import (
    ProjectedCandidate,
    navmesh_slope,
    project_candidate,
)
from flyff_bot.features.telemetry.kinematics import KinematicsDeriver
from flyff_bot.features.telemetry.models import (
    AttackAction,
    CandidateFeatures,
    CombatEpisode,
    CombatVerificationSource,
    KillCycle,
    NavigationEpisode,
    TelemetryEventKind,
    TelemetryPosition,
    TelemetrySessionMetadata,
    WorldSnapshot,
    primitive,
)
from flyff_bot.features.telemetry.storage import JsonlTelemetryWorker


@dataclass(slots=True)
class _ActiveNavigation:
    """Mutable in-memory evidence for one live GPS terrain-route episode."""

    started_at_ns: int
    start_position: TelemetryPosition
    target_position: TelemetryPosition
    planned_route: tuple[TelemetryPosition, ...]
    trajectory: list[tuple[int, TelemetryPosition, float | None]] = field(default_factory=list)
    replans_count: int = 0
    stall_events: int = 0
    stall_started_at_ns: int | None = None
    stall_duration_seconds: float = 0.0
    collision_evasions: int = 0


class TelemetryRecorder:
    """Serialize actual observations only; all calls are safe on the farming tick thread."""

    def __init__(
        self,
        metadata: TelemetrySessionMetadata,
        worker_factory: Callable[[str, str], JsonlTelemetryWorker],
        *,
        clock_ns: Callable[[], int] = monotonic_ns,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        navmesh: BakedNavMesh | None = None,
    ) -> None:
        self._metadata = metadata.with_generated_identity(session_start_utc=utc_now().isoformat())
        self._worker = worker_factory(self._metadata.session_id, self._metadata.area_id)
        self._clock_ns = clock_ns
        self._kinematics = KinematicsDeriver()
        self._started = False
        self._selection_started_at_ns = 0
        self._active_decision_timestamp_ns: int | None = None
        self._combat_started_at: tuple[int, str | None, float, float | None] | None = None
        self._attack_actions: list[AttackAction] = []
        self._last_verified_kill_at_ns: int | None = None
        self._cycle_started_at_ns: int | None = None
        self._decision_seconds = 0.0
        self._navigation_seconds = 0.0
        self._stall_seconds = 0.0
        self._navigation: _ActiveNavigation | None = None
        self._navmesh = navmesh

    @property
    def session_id(self) -> str:
        """Return this recorder's generated or caller-supplied UUID4 session identity."""

        return self._metadata.session_id

    def start(self, *, active_spawn_zone: dict[str, object] | None = None) -> None:
        """Queue the immutable schema-v1 header before any session observations."""

        if self._started:
            return
        if active_spawn_zone is not None:
            self._metadata = replace(self._metadata, active_spawn_zone=active_spawn_zone)
        self._started = True
        self._submit(TelemetryEventKind.SESSION_HEADER, primitive(self._metadata))
        self._selection_started_at_ns = self._clock_ns()
        self._cycle_started_at_ns = self._selection_started_at_ns

    def record_snapshot(
        self,
        state: WorldState,
        mode: str,
        *,
        live_position: WorldPosition | None,
        position_source: PositionSource = PositionSource.MINIMAP_FALLBACK,
        buff_cooldowns: dict[str, float] | None = None,
        player_terrain_slope: float | None = None,
    ) -> None:
        """Queue one compact numerical snapshot; absent GPS remains explicit ``null``."""

        if not self._started:
            return
        timestamp_ns = self._clock_ns()
        position = _position(live_position)
        velocity = self._kinematics.observe(timestamp_ns, position)
        snapshot = WorldSnapshot(
            timestamp_ns=timestamp_ns,
            player_position=position,
            player_velocity=velocity,
            player_speed=None if velocity is None else velocity.speed,
            position_source=position_source.value,
            player_navmesh_polygon_id=_navmesh_polygon_id(
                self._navmesh, live_position, position_source
            ),
            player_terrain_slope=(
                player_terrain_slope
                if player_terrain_slope is not None
                else navmesh_slope(
                    self._navmesh,
                    live_position if position_source is PositionSource.LIVE else None,
                )
            ),
            hp_percentage=state.player_vitals.hp_percentage,
            mp_percentage=state.player_vitals.mp_percentage,
            fp_percentage=state.player_vitals.fp_percentage,
            buff_cooldowns=buff_cooldowns or {},
            farming_mode=mode,
            visible_mob_count=len(state.visible_mobs),
        )
        self._submit(TelemetryEventKind.WORLD_SNAPSHOT, primitive(snapshot), timestamp_ns)
        navigation = self._navigation
        if (
            navigation is not None
            and position is not None
            and position_source is PositionSource.LIVE
        ):
            navigation.trajectory.append(
                (timestamp_ns, position, None if velocity is None else velocity.speed)
            )

    def record_target_selection(
        self,
        state: WorldState,
        selected_x: int,
        selected_y: int,
        *,
        reason: str,
        player_position: WorldPosition | None = None,
        camera_state: CameraState | None = None,
        is_locked_out: Callable[[int, int], bool] | None = None,
    ) -> None:
        """Persist all visible alternatives in perception order at the actual click boundary."""

        if not self._started:
            return
        timestamp_ns = self._clock_ns()
        viewport = state.viewport
        candidates: list[CandidateFeatures] = []
        selected_index = -1
        for index, mob in enumerate(state.visible_mobs):
            center_x = mob.x + mob.width / 2.0
            center_y = mob.y + mob.height / 2.0
            distance = (
                hypot(center_x - viewport.width / 2.0, center_y - viewport.height / 2.0)
                if viewport.has_size
                else None
            )
            if int(center_x) == selected_x and int(center_y) == selected_y:
                selected_index = index
            geometry = (
                None
                if mob.world_x is None or mob.world_y is None or mob.world_z is None
                else TelemetryPosition(mob.world_x, mob.world_y, mob.world_z)
            )
            projected = (
                None
                if geometry is not None
                else project_candidate(
                    camera=camera_state,
                    navmesh=self._navmesh,
                    player_position=player_position,
                    viewport_width=viewport.width,
                    viewport_height=viewport.height,
                    screen_x=center_x,
                    screen_bottom_y=mob.y + mob.height,
                )
            )
            candidates.append(
                CandidateFeatures(
                    index,
                    mob.class_id,
                    mob.class_name,
                    mob.confidence,
                    mob.x,
                    mob.y,
                    mob.width,
                    mob.height,
                    center_x,
                    center_y,
                    distance,
                    mob.width * mob.height,
                    geometry if geometry is not None else _projected_position(projected),
                    _relative_distance(geometry, player_position, projected),
                    _relative_elevation(geometry, player_position, projected),
                    (
                        str(mob.navmesh_polygon_id)
                        if mob.navmesh_polygon_id is not None
                        else None
                        if projected is None
                        else str(projected.polygon_id)
                    ),
                    (
                        mob.navmesh_path_distance
                        if geometry is not None
                        else None
                        if projected is None
                        else projected.path_distance
                    ),
                    False if is_locked_out is None else is_locked_out(int(center_x), int(center_y)),
                )
            )
        if selected_index < 0:
            return
        payload = {
            "timestamp_ns": timestamp_ns,
            "player_position": primitive(_position(player_position)),
            "selected_candidate_index": selected_index,
            "decision_reason": reason,
            "decision_latency_ms": (timestamp_ns - self._selection_started_at_ns) / 1_000_000,
            "candidates": primitive(tuple(candidates)),
        }
        self._submit(TelemetryEventKind.TARGET_SELECTED, payload, timestamp_ns)
        self._decision_seconds += (timestamp_ns - self._selection_started_at_ns) / 1_000_000_000
        self._selection_started_at_ns = timestamp_ns
        self._active_decision_timestamp_ns = timestamp_ns

    def begin_navigation(
        self,
        start_position: WorldPosition,
        planned_route: tuple[WorldPosition, ...],
    ) -> None:
        """Begin or replan a route based solely on US-052 live terrain waypoints."""

        if not self._started or not planned_route:
            return
        timestamp_ns = self._clock_ns()
        route = tuple(_position(point) for point in planned_route)
        assert all(point is not None for point in route)
        resolved_route = tuple(point for point in route if point is not None)
        navigation = self._navigation
        if navigation is not None:
            if navigation.planned_route != resolved_route:
                navigation.planned_route = resolved_route
                navigation.target_position = resolved_route[-1]
                navigation.replans_count += 1
            return
        start = _position(start_position)
        assert start is not None
        self._navigation = _ActiveNavigation(
            timestamp_ns, start, resolved_route[-1], resolved_route
        )

    def record_navigation_stall(self, *, stalled: bool) -> None:
        """Accumulate a live terrain-route stall and emit a durable edge event."""

        navigation = self._navigation
        if navigation is None:
            return
        timestamp_ns = self._clock_ns()
        if stalled and navigation.stall_started_at_ns is None:
            navigation.stall_started_at_ns = timestamp_ns
            navigation.stall_events += 1
            self._submit(
                TelemetryEventKind.STALL_EVENT,
                {"navigation_started_at_ns": navigation.started_at_ns},
                timestamp_ns,
            )
        elif not stalled and navigation.stall_started_at_ns is not None:
            duration = (timestamp_ns - navigation.stall_started_at_ns) / 1_000_000_000
            navigation.stall_duration_seconds += duration
            self._stall_seconds += duration
            navigation.stall_started_at_ns = None

    def record_navigation_evasion(self) -> None:
        """Count a confirmed bounded Q/S recovery action in the active route."""

        if self._navigation is not None:
            self._navigation.collision_evasions += 1

    def finish_navigation(self, outcome: str) -> None:
        """Persist the active live-GPS episode without ever deriving minimap trajectories."""

        navigation = self._navigation
        if navigation is None:
            return
        ended_at_ns = self._clock_ns()
        if navigation.stall_started_at_ns is not None:
            duration = (ended_at_ns - navigation.stall_started_at_ns) / 1_000_000_000
            navigation.stall_duration_seconds += duration
            self._stall_seconds += duration
        actual_distance = sum(
            dist(
                (previous.x, previous.y, previous.z),
                (current.x, current.y, current.z),
            )
            for (
                _previous_time,
                previous,
                _previous_speed,
            ), (
                _current_time,
                current,
                _current_speed,
            ) in zip(navigation.trajectory, navigation.trajectory[1:], strict=False)
        )
        planned_length = sum(
            dist(
                (previous.x, previous.y, previous.z),
                (current.x, current.y, current.z),
            )
            for previous, current in zip(
                navigation.planned_route, navigation.planned_route[1:], strict=False
            )
        )
        episode = NavigationEpisode(
            navigation.started_at_ns,
            ended_at_ns,
            navigation.start_position,
            navigation.target_position,
            navigation.planned_route,
            planned_length,
            actual_distance,
            tuple(navigation.trajectory),
            navigation.replans_count,
            navigation.stall_events,
            navigation.stall_duration_seconds,
            navigation.collision_evasions,
            outcome,
        )
        self.record_navigation_episode(episode)
        self._navigation_seconds += (ended_at_ns - navigation.started_at_ns) / 1_000_000_000
        self._navigation = None

    def close(self) -> None:
        """Close the worker idempotently; telemetry failure never affects client control."""

        self.finish_navigation("session_closed")
        self._worker.close()

    def record_navigation_episode(self, episode: NavigationEpisode) -> None:
        """Queue a completed navigation episode collected by the session controller."""

        if self._started:
            self._submit(
                TelemetryEventKind.NAVIGATION_EPISODE, primitive(episode), episode.ended_at_ns
            )

    def begin_combat(self, state: WorldState) -> None:
        """Capture the measured combat baseline exactly once for the current engagement."""

        if not self._started or self._combat_started_at is not None:
            return
        self._combat_started_at = (
            self._clock_ns(),
            state.selected_target.name,
            state.player_vitals.hp_percentage,
            state.selected_target.hp_percentage
            if state.selected_target.state.value == "valid"
            else None,
        )
        self._attack_actions = []

    def record_attack(self, virtual_key: int, duration_seconds: float) -> None:
        """Record only a key that the guarded dispatcher confirmed it sent."""

        if self._started and self._combat_started_at is not None:
            self._attack_actions.append(
                AttackAction(self._clock_ns(), virtual_key, duration_seconds)
            )

    def finish_combat(
        self,
        state: WorldState,
        *,
        outcome: str,
        verification_source: CombatVerificationSource | None = None,
    ) -> None:
        """Persist one combat episode and a kill cycle only after a verified defeat."""

        started = self._combat_started_at
        if not self._started or started is None:
            return
        ended_at_ns = self._clock_ns()
        episode = CombatEpisode(
            started_at_ns=started[0],
            ended_at_ns=ended_at_ns,
            target_name=started[1],
            player_hp_start=started[2],
            player_hp_end=state.player_vitals.hp_percentage,
            target_hp_start_pct=started[3],
            target_hp_end_pct=state.selected_target.hp_percentage,
            attack_actions=tuple(self._attack_actions),
            outcome=outcome,
            verification_source=verification_source,
        )
        self.record_combat_episode(episode)
        if verification_source is not None:
            prior = self._cycle_started_at_ns or self._last_verified_kill_at_ns or started[0]
            total_seconds = (ended_at_ns - prior) / 1_000_000_000
            combat_seconds = (ended_at_ns - started[0]) / 1_000_000_000
            self.record_kill_cycle(
                KillCycle(
                    timestamp_ns=ended_at_ns,
                    decision_seconds=self._decision_seconds,
                    navigation_seconds=self._navigation_seconds,
                    combat_seconds=combat_seconds,
                    idle_seconds=max(
                        0.0,
                        total_seconds
                        - self._decision_seconds
                        - self._navigation_seconds
                        - combat_seconds,
                    ),
                    damage_taken=max(0.0, started[2] - state.player_vitals.hp_percentage),
                    stall_seconds=self._stall_seconds,
                    verified_kill=True,
                    reward=-total_seconds + 1.0,
                    target_decision_timestamp_ns=self._active_decision_timestamp_ns,
                )
            )
            self._last_verified_kill_at_ns = ended_at_ns
            self._cycle_started_at_ns = ended_at_ns
            self._decision_seconds = 0.0
            self._navigation_seconds = 0.0
            self._stall_seconds = 0.0
        self._combat_started_at = None
        self._attack_actions = []
        self._active_decision_timestamp_ns = None

    def record_combat_episode(self, episode: CombatEpisode) -> None:
        """Queue a completed combat episode without retaining frames or input adapters."""

        if self._started:
            self._submit(TelemetryEventKind.COMBAT_EPISODE, primitive(episode), episode.ended_at_ns)

    def record_kill_cycle(self, cycle: KillCycle) -> None:
        """Queue a fully decomposed verified kill cycle for offline policy training."""

        if self._started:
            self._submit(TelemetryEventKind.KILL_CYCLE, primitive(cycle), cycle.timestamp_ns)

    def _submit(
        self, kind: TelemetryEventKind, payload: object, timestamp_ns: int | None = None
    ) -> None:
        self._worker.submit(
            {
                "schema_version": 1,
                "event_kind": kind.value,
                "session_id": self._metadata.session_id,
                "timestamp_ns": self._clock_ns() if timestamp_ns is None else timestamp_ns,
                "payload": payload,
            }
        )


def _position(position: WorldPosition | None) -> TelemetryPosition | None:
    if position is None:
        return None
    return TelemetryPosition(position.x, position.y, position.z)


def _projected_position(projected: ProjectedCandidate | None) -> TelemetryPosition | None:
    """Convert the legacy raycast result without asserting it always exists."""

    if projected is None:
        return None
    position = projected.position
    return TelemetryPosition(position.x, position.y, position.z)


def _relative_distance(
    position: TelemetryPosition | None,
    player: WorldPosition | None,
    projected: ProjectedCandidate | None,
) -> float | None:
    if position is not None and player is not None:
        return dist((position.x, position.y, position.z), (player.x, player.y, player.z))
    return None if projected is None else projected.relative_distance


def _relative_elevation(
    position: TelemetryPosition | None,
    player: WorldPosition | None,
    projected: ProjectedCandidate | None,
) -> float | None:
    if position is not None and player is not None:
        return position.y - player.y
    return None if projected is None else projected.relative_elevation


def _navmesh_polygon_id(
    navmesh: BakedNavMesh | None,
    position: WorldPosition | None,
    position_source: PositionSource,
) -> str | None:
    """Return a stable ID only for an explicitly loaded mesh and measured live GPS."""

    if navmesh is None or position is None or position_source is not PositionSource.LIVE:
        return None
    polygon_id = navmesh.polygon_or_region_id(position)
    return None if polygon_id is None else str(polygon_id)
