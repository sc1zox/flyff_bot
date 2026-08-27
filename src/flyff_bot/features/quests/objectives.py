"""Ordered quest goals and the single object that states which one is active.

A resolved quest states *what* has to happen. This module states in which order it happens,
what each step's completion condition is, and how far the active step has progressed.
`QuestGoalSequence` is the objective bus: the executor, the tactical policy, the dashboard and
the telemetry sidecar all read the current goal from this one object, so recorded experience
is conditioned on the same goal the session was pursuing.

The module measures nothing and dispatches nothing. Arrival, kills and interactions are
reported into it by the session that observes them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from flyff_bot.features.navigation.live_position import WorldPosition
from flyff_bot.features.navigation.world_extractor import VectorSpawnZone
from flyff_bot.features.quests.goals import QuestNpc, QuestResolution, QuestTarget
from flyff_bot.features.quests.models import QuestObjectiveProgress

# A goal that only has to be reached or clicked is complete once, so one unit of progress is
# its whole requirement. Kill and collect goals override this with their required kill count.
SINGLE_STEP_REQUIRED_PROGRESS = 1.0
# Goals that are not one of a quest's objectives carry no objective ordinal.
NO_OBJECTIVE_ORDINAL = -1

DEFAULT_TRAVEL_GOAL_TIMEOUT_SECONDS = 300.0
DEFAULT_INTERACTION_GOAL_TIMEOUT_SECONDS = 60.0
DEFAULT_OBJECTIVE_GOAL_TIMEOUT_SECONDS = 1800.0


class QuestGoalKind(StrEnum):
    """The ordered step families one quest cycle decomposes into."""

    TRAVEL_TO_ACCEPT = "travel_to_accept"
    ACCEPT = "accept"
    TRAVEL_TO_OBJECTIVE = "travel_to_objective"
    SATISFY_OBJECTIVE = "satisfy_objective"
    TRAVEL_TO_TURN_IN = "travel_to_turn_in"
    TURN_IN = "turn_in"


TRAVEL_GOAL_KINDS = frozenset(
    {
        QuestGoalKind.TRAVEL_TO_ACCEPT,
        QuestGoalKind.TRAVEL_TO_OBJECTIVE,
        QuestGoalKind.TRAVEL_TO_TURN_IN,
    }
)
OBJECTIVE_GOAL_KINDS = frozenset(
    {QuestGoalKind.TRAVEL_TO_OBJECTIVE, QuestGoalKind.SATISFY_OBJECTIVE}
)
INTERACTION_GOAL_KINDS = frozenset({QuestGoalKind.ACCEPT, QuestGoalKind.TURN_IN})


class QuestGoalState(StrEnum):
    """The lifecycle of one goal inside its sequence."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class QuestGoalFailure(StrEnum):
    """Why an active goal stopped being executable."""

    # No walkable route and no mapped teleporter destination reaches this goal.
    UNREACHABLE_DESTINATION = "unreachable_destination"
    # The teleporter was dispatched but arrival was never confirmed from live client state.
    TELEPORT_FAILED = "teleport_failed"
    # Every bounded NPC interaction attempt was exhausted.
    INTERACTION_FAILED = "interaction_failed"
    # The goal made no measurable progress within its configured timeout.
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class QuestGoalTimeouts:
    """How long each goal family may run without measurable progress."""

    travel_seconds: float = DEFAULT_TRAVEL_GOAL_TIMEOUT_SECONDS
    interaction_seconds: float = DEFAULT_INTERACTION_GOAL_TIMEOUT_SECONDS
    objective_seconds: float = DEFAULT_OBJECTIVE_GOAL_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if min(self.travel_seconds, self.interaction_seconds, self.objective_seconds) <= 0.0:
            raise ValueError("Quest goal timeouts must be positive.")

    def for_kind(self, kind: QuestGoalKind) -> float:
        """Return the timeout that governs one goal family."""

        if kind in TRAVEL_GOAL_KINDS:
            return self.travel_seconds
        if kind in INTERACTION_GOAL_KINDS:
            return self.interaction_seconds
        return self.objective_seconds


@dataclass(frozen=True, slots=True)
class QuestGoal:
    """One ordered step of a quest, with its completion condition stated explicitly."""

    kind: QuestGoalKind
    index: int
    quest_id: str
    quest_title: str
    timeout_seconds: float
    required_progress: float = SINGLE_STEP_REQUIRED_PROGRESS
    objective_ordinal: int = NO_OBJECTIVE_ORDINAL
    destination: WorldPosition | None = None
    npc: QuestNpc | None = None
    target: QuestTarget | None = None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("A quest goal index cannot be negative.")
        if self.timeout_seconds <= 0.0:
            raise ValueError("A quest goal timeout must be positive.")
        if self.required_progress <= 0.0:
            raise ValueError("A quest goal must require positive progress.")
        if self.kind in OBJECTIVE_GOAL_KINDS and self.target is None:
            raise ValueError("An objective goal must name the quest target it works on.")

    @property
    def is_travel(self) -> bool:
        """Return whether this goal is satisfied by arriving somewhere."""

        return self.kind in TRAVEL_GOAL_KINDS

    @property
    def monster_name(self) -> str | None:
        """Return the monster class this goal farms, when it farms one."""

        return None if self.target is None else self.target.monster_name

    @property
    def spawn_zone(self) -> VectorSpawnZone | None:
        """Return the resolved spawn zone this goal is bound to, when it has one."""

        return None if self.target is None else self.target.zone


@dataclass(frozen=True, slots=True)
class QuestGoalIdentity:
    """The active goal as every consumer outside the sequence reads it."""

    quest_id: str
    quest_title: str
    kind: QuestGoalKind
    index: int
    goal_count: int
    progress: float
    required_progress: float
    state: QuestGoalState
    monster_name: str | None = None
    spawn_zone_monster_id: int | None = None
    world_id: int | None = None
    failure: QuestGoalFailure | None = None

    @property
    def progress_ratio(self) -> float:
        """Return the bounded fraction of this goal's requirement already met."""

        return min(1.0, self.progress / self.required_progress)


def build_goal_sequence(
    resolution: QuestResolution,
    *,
    timeouts: QuestGoalTimeouts | None = None,
) -> tuple[QuestGoal, ...]:
    """Return the ordered, executable goals one resolved quest decomposes into.

    Only steps the resolution can actually execute are emitted: a quest whose accept or
    turn-in NPC has no world position contributes no travel or interaction goal for it,
    so the sequence never states a step the session has no way to reach.
    """

    if not resolution.targets:
        return ()
    timeouts = timeouts or QuestGoalTimeouts()
    quest_id = resolution.quest.quest_id
    title = resolution.quest.display_title
    goals: list[QuestGoal] = []

    def append(
        kind: QuestGoalKind,
        *,
        required_progress: float = SINGLE_STEP_REQUIRED_PROGRESS,
        objective_ordinal: int = NO_OBJECTIVE_ORDINAL,
        destination: WorldPosition | None = None,
        npc: QuestNpc | None = None,
        target: QuestTarget | None = None,
    ) -> None:
        goals.append(
            QuestGoal(
                kind,
                len(goals),
                quest_id,
                title,
                timeouts.for_kind(kind),
                required_progress,
                objective_ordinal,
                destination,
                npc,
                target,
            )
        )

    if resolution.accept_npc.is_resolved:
        append(
            QuestGoalKind.TRAVEL_TO_ACCEPT,
            destination=resolution.accept_npc.position,
            npc=resolution.accept_npc,
        )
        append(QuestGoalKind.ACCEPT, npc=resolution.accept_npc)
    for ordinal, target in enumerate(resolution.targets):
        append(
            QuestGoalKind.TRAVEL_TO_OBJECTIVE,
            objective_ordinal=ordinal,
            destination=_zone_destination(target.zone),
            target=target,
        )
        append(
            QuestGoalKind.SATISFY_OBJECTIVE,
            required_progress=float(target.required_kills),
            objective_ordinal=ordinal,
            destination=_zone_destination(target.zone),
            target=target,
        )
    if resolution.turn_in_npc.is_resolved:
        append(
            QuestGoalKind.TRAVEL_TO_TURN_IN,
            destination=resolution.turn_in_npc.position,
            npc=resolution.turn_in_npc,
        )
        append(QuestGoalKind.TURN_IN, npc=resolution.turn_in_npc)
    return tuple(goals)


class QuestGoalSequence:
    """The one object that states which quest goal a session is pursuing right now.

    The sequence does not decide when a goal is done; it is told. What it owns is the
    ordering, the measured progress of each goal, the timeout that bounds a goal that stops
    progressing, and the failure reason when one does.
    """

    def __init__(
        self,
        resolution: QuestResolution,
        *,
        timeouts: QuestGoalTimeouts | None = None,
    ) -> None:
        self._resolution = resolution
        self._goals = build_goal_sequence(resolution, timeouts=timeouts)
        self._progress = [0.0] * len(self._goals)
        self._states = [QuestGoalState.PENDING] * len(self._goals)
        self._active_index = 0
        self._failure: QuestGoalFailure | None = None
        self._world_id: int | None = None
        self._progressed_at_seconds = 0.0
        if self._goals:
            self._states[0] = QuestGoalState.ACTIVE

    @property
    def resolution(self) -> QuestResolution:
        """Return the quest this sequence was built from."""

        return self._resolution

    @property
    def goals(self) -> tuple[QuestGoal, ...]:
        """Return every ordered goal of this quest."""

        return self._goals

    @property
    def has_goals(self) -> bool:
        """Return whether this quest decomposed into anything executable."""

        return bool(self._goals)

    @property
    def active(self) -> QuestGoal | None:
        """Return the goal the session is pursuing, or ``None`` for an empty sequence."""

        if not self._goals:
            return None
        return self._goals[self._active_index]

    @property
    def active_index(self) -> int:
        """Return the position of the active goal within the sequence."""

        return self._active_index

    @property
    def active_state(self) -> QuestGoalState:
        """Return the lifecycle state of the active goal."""

        if not self._goals:
            return QuestGoalState.PENDING
        return self._states[self._active_index]

    @property
    def active_progress(self) -> float:
        """Return the measured progress of the active goal."""

        if not self._goals:
            return 0.0
        return self._progress[self._active_index]

    @property
    def pending_objective_ordinal(self) -> int:
        """Return the ordinal of the first objective still short of its requirement."""

        last = 0
        for goal in self._goals:
            if goal.kind is not QuestGoalKind.SATISFY_OBJECTIVE:
                continue
            last = goal.objective_ordinal
            if self._progress[goal.index] < goal.required_progress:
                return goal.objective_ordinal
        return last

    @property
    def failure(self) -> QuestGoalFailure | None:
        """Return why the active goal failed, when it did."""

        return self._failure

    @property
    def is_failed(self) -> bool:
        """Return whether the active goal is no longer executable."""

        return self.active_state is QuestGoalState.FAILED

    @property
    def world_id(self) -> int | None:
        """Return the world identifier the active goal was resolved to travel into."""

        return self._world_id

    def includes(self, kind: QuestGoalKind) -> bool:
        """Return whether this quest decomposed into a goal of one family at all."""

        return any(goal.kind is kind for goal in self._goals)

    def begin(self, at_seconds: float) -> None:
        """Activate the first goal and restart every progress and timeout measurement."""

        self._progress = [0.0] * len(self._goals)
        self._states = [QuestGoalState.PENDING] * len(self._goals)
        self._active_index = 0
        self._failure = None
        self._world_id = None
        self._progressed_at_seconds = at_seconds
        if self._goals:
            self._states[0] = QuestGoalState.ACTIVE

    def synchronize(
        self,
        kind: QuestGoalKind,
        at_seconds: float,
        *,
        objective_ordinal: int = NO_OBJECTIVE_ORDINAL,
    ) -> bool:
        """Point the sequence at the goal the executor is working on.

        Returns whether the active goal changed, which is the session's signal to re-derive
        the target whitelist, the patrol zone, the leash and the policy objective.
        """

        index = self._index_of(kind, objective_ordinal)
        if index is None or index == self._active_index:
            return False
        # Moving forward retires every step it skipped; moving back - which a bounded
        # interaction retry does - leaves the already recorded states untouched.
        for position in range(self._active_index, index):
            self._states[position] = QuestGoalState.COMPLETED
            self._progress[position] = self._goals[position].required_progress
        self._active_index = index
        self._states[index] = QuestGoalState.ACTIVE
        self._failure = None
        self._world_id = None
        self._progressed_at_seconds = at_seconds
        return True

    def apply_progress(self, entries: Sequence[QuestObjectiveProgress], at_seconds: float) -> None:
        """Adopt the measured kill counts of this quest's objectives, in target order.

        Progress that actually moved restarts the active goal's timeout: the timeout bounds
        a goal that stops progressing, not one that is simply long.
        """

        for goal in self._goals:
            if goal.objective_ordinal == NO_OBJECTIVE_ORDINAL:
                continue
            if goal.objective_ordinal >= len(entries):
                continue
            entry = entries[goal.objective_ordinal]
            measured = min(float(entry.kills), goal.required_progress)
            if measured > self._progress[goal.index]:
                self._progress[goal.index] = measured
                if goal.index == self._active_index:
                    self._progressed_at_seconds = at_seconds

    def bind_world(self, world_id: int | None) -> None:
        """Record which world identifier the active goal was resolved to travel into."""

        self._world_id = world_id

    def fail(self, reason: QuestGoalFailure) -> None:
        """Mark the active goal unexecutable with an explicit reason."""

        if not self._goals:
            return
        self._states[self._active_index] = QuestGoalState.FAILED
        self._failure = reason

    def observe(self, at_seconds: float) -> QuestGoalFailure | None:
        """Apply the active goal's timeout and return the failure it produced, if any."""

        goal = self.active
        if goal is None or self.active_state is not QuestGoalState.ACTIVE:
            return None
        if at_seconds - self._progressed_at_seconds < goal.timeout_seconds:
            return None
        self.fail(QuestGoalFailure.TIMEOUT)
        return QuestGoalFailure.TIMEOUT

    def identity(self) -> QuestGoalIdentity | None:
        """Return the active goal as the dashboard, the policy and telemetry read it."""

        goal = self.active
        if goal is None:
            return None
        zone = goal.spawn_zone
        return QuestGoalIdentity(
            goal.quest_id,
            goal.quest_title,
            goal.kind,
            goal.index,
            len(self._goals),
            self._progress[goal.index],
            goal.required_progress,
            self._states[goal.index],
            goal.monster_name,
            None if zone is None else zone.monster_id,
            self._world_id,
            self._failure,
        )

    def _index_of(self, kind: QuestGoalKind, objective_ordinal: int) -> int | None:
        for goal in self._goals:
            if goal.kind is not kind:
                continue
            if kind in OBJECTIVE_GOAL_KINDS and goal.objective_ordinal != objective_ordinal:
                continue
            return goal.index
        return None


def _zone_destination(zone: VectorSpawnZone | None) -> WorldPosition | None:
    """Return the patrol anchor of a resolved spawn zone as a 3D world position."""

    if zone is None:
        return None
    anchor = zone.anchor
    return WorldPosition(anchor.x, zone.center_y, anchor.z)
