"""Orchestrator-facing non-blocking telemetry recorder."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from math import hypot
from time import monotonic_ns

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.navigation.live_position import PositionSource, WorldPosition
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


class TelemetryRecorder:
    """Serialize actual observations only; all calls are safe on the farming tick thread."""

    def __init__(
        self,
        metadata: TelemetrySessionMetadata,
        worker_factory: Callable[[str, str], JsonlTelemetryWorker],
        *,
        clock_ns: Callable[[], int] = monotonic_ns,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._metadata = metadata.with_generated_identity(session_start_utc=utc_now().isoformat())
        self._worker = worker_factory(self._metadata.session_id, self._metadata.area_id)
        self._clock_ns = clock_ns
        self._kinematics = KinematicsDeriver()
        self._started = False
        self._selection_started_at_ns = 0
        self._combat_started_at: tuple[int, str | None, float, float | None] | None = None
        self._attack_actions: list[AttackAction] = []
        self._last_verified_kill_at_ns: int | None = None

    @property
    def session_id(self) -> str:
        """Return this recorder's generated or caller-supplied UUID4 session identity."""

        return self._metadata.session_id

    def start(self) -> None:
        """Queue the immutable schema-v1 header before any session observations."""

        if self._started:
            return
        self._started = True
        self._submit(TelemetryEventKind.SESSION_HEADER, primitive(self._metadata))
        self._selection_started_at_ns = self._clock_ns()

    def record_snapshot(
        self,
        state: WorldState,
        mode: str,
        *,
        live_position: WorldPosition | None,
        position_source: PositionSource = PositionSource.MINIMAP_FALLBACK,
        buff_cooldowns: dict[str, float] | None = None,
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
            player_navmesh_polygon_id=None,
            player_terrain_slope=None,
            hp_percentage=state.player_vitals.hp_percentage,
            mp_percentage=state.player_vitals.mp_percentage,
            fp_percentage=state.player_vitals.fp_percentage,
            buff_cooldowns=buff_cooldowns or {},
            farming_mode=mode,
            visible_mob_count=len(state.visible_mobs),
        )
        self._submit(TelemetryEventKind.WORLD_SNAPSHOT, primitive(snapshot), timestamp_ns)

    def record_target_selection(
        self, state: WorldState, selected_x: int, selected_y: int, *, reason: str
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
                    None,
                    None,
                    None,
                    None,
                    None,
                    False,
                )
            )
        if selected_index < 0:
            return
        payload = {
            "timestamp_ns": timestamp_ns,
            "player_position": None,
            "selected_candidate_index": selected_index,
            "decision_reason": reason,
            "decision_latency_ms": (timestamp_ns - self._selection_started_at_ns) / 1_000_000,
            "candidates": primitive(tuple(candidates)),
        }
        self._submit(TelemetryEventKind.TARGET_SELECTED, payload, timestamp_ns)
        self._selection_started_at_ns = timestamp_ns

    def close(self) -> None:
        """Close the worker idempotently; telemetry failure never affects client control."""

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
            prior = self._last_verified_kill_at_ns or started[0]
            total_seconds = (ended_at_ns - prior) / 1_000_000_000
            combat_seconds = (ended_at_ns - started[0]) / 1_000_000_000
            self.record_kill_cycle(
                KillCycle(
                    timestamp_ns=ended_at_ns,
                    decision_seconds=0.0,
                    navigation_seconds=0.0,
                    combat_seconds=combat_seconds,
                    idle_seconds=max(0.0, total_seconds - combat_seconds),
                    damage_taken=max(0.0, started[2] - state.player_vitals.hp_percentage),
                    stall_seconds=0.0,
                    verified_kill=True,
                    reward=-total_seconds + 1.0,
                )
            )
            self._last_verified_kill_at_ns = ended_at_ns
        self._combat_started_at = None
        self._attack_actions = []

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
