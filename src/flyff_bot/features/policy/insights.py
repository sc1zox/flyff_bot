"""Read-only ML/RL decision telemetry an operator can inspect while a session runs (US-087).

Nothing here steers a decision. Every value is recorded after the fact and handed to the
presentation layer as an immutable snapshot, so a dashboard that renders it cannot slow, block,
or alter the tick that produced it (ADR-002, ADR-008).

Two rules keep the view honest. A quantity the session did not measure is ``None`` rather than
zero -- an inference that never ran has no latency, and a policy that never disagreed with the
baseline has no agreement rate yet. And a candidate the deterministic mask rejected is shown as
rejected rather than omitted, because the option set a decision was taken from is exactly what
an operator needs in order to judge the decision.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import StrEnum, unique
from pathlib import Path

from flyff_bot.features.ml.export import METADATA_FILENAME
from flyff_bot.features.policy.action_payloads import (
    AttackPointAction,
    CorridorAction,
    InteractAction,
    NavigateAction,
    StrategicGoalKind,
    TacticalActionKind,
    TacticalActionPayload,
    TargetAction,
    WaitAction,
)
from flyff_bot.features.policy.hierarchical_training import HIERARCHICAL_METADATA_FILENAME
from flyff_bot.features.policy.models import (
    DEFAULT_POLICY_RUNTIME_MODE,
    PolicyCandidate,
    PolicyRuntimeMode,
)
from flyff_bot.features.tactical_parameters import TacticalParameterName
from flyff_bot.features.telemetry.models import SessionExperienceTotals

# The documents that identify a learned artifact. Digesting the provenance document rather than
# the weight files is deliberate: it is the document that names the contract, the heads and the
# inputs the artifact was bound to, so it is what changes when the artifact stops being the
# same artifact.
ARTIFACT_DOCUMENT_NAMES = (HIERARCHICAL_METADATA_FILENAME, METADATA_FILENAME)
ARTIFACT_DIGEST_READ_SIZE = 65_536

# The tactical parameters a live learned decision is allowed to modulate (US-084). Everything
# else in the space is operator-configured only, so listing it here would suggest a policy
# influence that does not exist.
POLICY_MODULATED_PARAMETERS: tuple[TacticalParameterName, ...] = (
    TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS,
    TacticalParameterName.REPLAN_INTERVAL_SECONDS,
    TacticalParameterName.STALL_TIMEOUT_SECONDS,
)

_GOAL_BY_ACTION_KIND = {
    TacticalActionKind.TARGET: StrategicGoalKind.TARGET,
    TacticalActionKind.ATTACK_POINT: StrategicGoalKind.TARGET,
    TacticalActionKind.CORRIDOR: StrategicGoalKind.TARGET,
    TacticalActionKind.NAVIGATE: StrategicGoalKind.NAVIGATE,
    TacticalActionKind.INTERACT: StrategicGoalKind.INTERACT,
    TacticalActionKind.WAIT: StrategicGoalKind.WAIT,
}


@unique
class CandidateVerdict(StrEnum):
    """What the deterministic action mask decided about one candidate."""

    ALLOWED = "allowed"
    MASKED = "masked"


@dataclass(frozen=True, slots=True)
class ModelArtifactIdentity:
    """Which learned artifact is loaded, and the digest that pins it."""

    directory: str = ""
    filename: str = ""
    sha256: str = ""

    @property
    def is_loaded(self) -> bool:
        """Return whether a learned artifact was actually identified."""

        return bool(self.filename)


@dataclass(frozen=True, slots=True)
class CandidateInsight:
    """One evaluated option, including the ones the mask rejected."""

    candidate_index: int
    class_name: str
    candidate_identity: int | None = None
    distance_units: float | None = None
    is_reachable: bool = False
    verdict: CandidateVerdict = CandidateVerdict.MASKED
    score: float | None = None
    is_chosen: bool = False


@dataclass(frozen=True, slots=True)
class ChosenActionInsight:
    """The parameterized action one decision actually produced."""

    goal: StrategicGoalKind
    action_kind: TacticalActionKind
    candidate_index: int | None = None
    approach_distance_units: float | None = None
    corridor_id: str | None = None
    wait_seconds: float | None = None

    @classmethod
    def from_action(cls, action: TacticalActionPayload) -> ChosenActionInsight:
        """Describe one payload without inventing fields the payload does not carry."""

        goal = _GOAL_BY_ACTION_KIND[action.kind]
        if isinstance(action, TargetAction):
            attack_point = action.attack_point
            return cls(
                goal,
                action.kind,
                candidate_index=action.candidate_index,
                approach_distance_units=(
                    None if attack_point is None else attack_point.approach_distance_units
                ),
            )
        if isinstance(action, AttackPointAction):
            return cls(
                goal,
                action.kind,
                candidate_index=action.candidate_index,
                approach_distance_units=action.approach_distance_units,
            )
        if isinstance(action, CorridorAction):
            return cls(
                goal,
                action.kind,
                candidate_index=action.candidate_index,
                corridor_id=action.preferred_corridor_id,
            )
        if isinstance(action, WaitAction):
            return cls(goal, action.kind, wait_seconds=action.duration_seconds)
        if isinstance(action, NavigateAction | InteractAction):
            return cls(goal, action.kind)
        raise TypeError("Unknown tactical action payload.")


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    """How often the shadow policy would have chosen what the baseline executed."""

    heuristic_candidate_index: int | None = None
    policy_candidate_index: int | None = None
    agreements: int = 0
    disagreements: int = 0

    @property
    def comparisons(self) -> int:
        """Return how many decisions were compared at all."""

        return self.agreements + self.disagreements

    @property
    def agreement_rate(self) -> float | None:
        """Return the agreed fraction, or ``None`` before the first comparison."""

        if not self.comparisons:
            return None
        return self.agreements / self.comparisons


@dataclass(frozen=True, slots=True)
class ParameterOverrideInsight:
    """One configured baseline value beside the value the decision actually used."""

    parameter: TacticalParameterName
    baseline: float
    active: float

    @property
    def is_overridden(self) -> bool:
        """Return whether a learned decision moved this parameter off its baseline."""

        return self.active != self.baseline


@dataclass(frozen=True, slots=True)
class PolicyInsightSnapshot:
    """Everything the ML and policy view renders for one published tick."""

    mode: PolicyRuntimeMode = DEFAULT_POLICY_RUNTIME_MODE
    artifact: ModelArtifactIdentity = field(default_factory=ModelArtifactIdentity)
    inference_latency_seconds: float | None = None
    candidates: tuple[CandidateInsight, ...] = ()
    chosen: ChosenActionInsight | None = None
    shadow: ShadowComparison | None = None
    experience: SessionExperienceTotals = field(default_factory=SessionExperienceTotals)
    parameter_overrides: tuple[ParameterOverrideInsight, ...] = ()


def baseline_candidate_index(
    candidates: tuple[PolicyCandidate, ...], action: TacticalActionPayload | None
) -> int | None:
    """Return which candidate the deterministic baseline picked, matched by its position.

    The baseline names a screen position rather than a candidate instance, so the comparison
    resolves it back to the option list instead of assuming the two agree on an index.
    """

    if not isinstance(action, TargetAction) or action.target_pos is None:
        return None
    for index, candidate in enumerate(candidates):
        mob = candidate.mob
        if mob.x == action.target_pos.x and mob.y == action.target_pos.y:
            return candidate.original_position if candidate.original_position is not None else index
    return None


def digest_artifact_document(directory: Path) -> ModelArtifactIdentity:
    """Return the loaded artifact's identifying document and its SHA-256 digest.

    A directory without any known provenance document yields an identity that names the
    directory alone, so the view says "no artifact document" instead of claiming a digest it
    could not compute.
    """

    for name in ARTIFACT_DOCUMENT_NAMES:
        document = directory / name
        digest = _file_digest(document)
        if digest is not None:
            return ModelArtifactIdentity(str(directory), name, digest)
    return ModelArtifactIdentity(str(directory))


def _file_digest(path: Path) -> str | None:
    """Return one file's SHA-256, or ``None`` when it cannot be read."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(ARTIFACT_DIGEST_READ_SIZE):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


class PolicyInsightRecorder:
    """Accumulate what each decision revealed, without holding on to any live object.

    The recorder runs on the farming tick thread and only ever produces frozen values, so the
    snapshot it hands to the dashboard cannot be mutated behind the UI's back.
    """

    def __init__(self) -> None:
        self._artifact = ModelArtifactIdentity()
        self._latency_seconds: float | None = None
        self._candidates: tuple[CandidateInsight, ...] = ()
        self._chosen: ChosenActionInsight | None = None
        self._shadow = ShadowComparison()

    @property
    def artifact(self) -> ModelArtifactIdentity:
        """Return the artifact identity the session last loaded."""

        return self._artifact

    def set_artifact(self, directory: Path | None) -> None:
        """Adopt the artifact a newly configured model directory identifies."""

        self._artifact = (
            ModelArtifactIdentity() if directory is None else digest_artifact_document(directory)
        )

    def reset_decision(self) -> None:
        """Forget the last decision without discarding the session's agreement history."""

        self._candidates = ()
        self._chosen = None
        self._latency_seconds = None

    def reset_shadow(self) -> None:
        """Start a fresh comparison series, for instance after the mode changed."""

        self._shadow = ShadowComparison()

    def record_decision(
        self,
        candidates: tuple[PolicyCandidate, ...],
        action: TacticalActionPayload | None,
        *,
        latency_seconds: float | None,
        player_position: tuple[float, float, float] | None = None,
        baseline_candidate_index: int | None = None,
    ) -> None:
        """Record one evaluated option set and the action it produced.

        ``baseline_candidate_index`` is supplied only in shadow mode, where the deterministic
        choice is the one that actually executed and the learned choice is merely observed.
        """

        self._latency_seconds = latency_seconds
        self._chosen = None if action is None else ChosenActionInsight.from_action(action)
        chosen_index = None if self._chosen is None else self._chosen.candidate_index
        expected_cost = action.expected_cost if isinstance(action, TargetAction) else None
        self._candidates = tuple(
            CandidateInsight(
                candidate_index=(
                    candidate.original_position
                    if candidate.original_position is not None
                    else index
                ),
                class_name=candidate.mob.class_name,
                candidate_identity=candidate.candidate_identity,
                distance_units=_candidate_distance(candidate, player_position),
                is_reachable=candidate.is_navmesh_reachable,
                verdict=(
                    CandidateVerdict.ALLOWED if candidate.is_eligible else CandidateVerdict.MASKED
                ),
                score=(
                    expected_cost
                    if chosen_index is not None and candidate.original_position == chosen_index
                    else None
                ),
                is_chosen=(
                    chosen_index is not None and candidate.original_position == chosen_index
                ),
            )
            for index, candidate in enumerate(candidates)
        )
        if baseline_candidate_index is None:
            return
        agreed = chosen_index is not None and chosen_index == baseline_candidate_index
        self._shadow = replace(
            self._shadow,
            heuristic_candidate_index=baseline_candidate_index,
            policy_candidate_index=chosen_index,
            agreements=self._shadow.agreements + int(agreed),
            disagreements=self._shadow.disagreements + int(not agreed),
        )

    def snapshot(
        self,
        mode: PolicyRuntimeMode,
        *,
        experience: SessionExperienceTotals,
        parameter_overrides: tuple[ParameterOverrideInsight, ...],
    ) -> PolicyInsightSnapshot:
        """Return one immutable view of the current decision state."""

        return PolicyInsightSnapshot(
            mode=mode,
            artifact=self._artifact,
            inference_latency_seconds=self._latency_seconds,
            candidates=self._candidates,
            chosen=self._chosen,
            shadow=self._shadow if mode is PolicyRuntimeMode.ML_SHADOW else None,
            experience=experience,
            parameter_overrides=parameter_overrides,
        )


def _candidate_distance(
    candidate: PolicyCandidate, player_position: tuple[float, float, float] | None
) -> float | None:
    """Return the measured 3D distance to one candidate, or ``None`` without live geometry."""

    mob = candidate.mob
    if mob.navmesh_path_distance is not None:
        return mob.navmesh_path_distance
    if player_position is None or mob.world_x is None or mob.world_y is None:
        return None
    if mob.world_z is None:
        return None
    return float(
        (
            (mob.world_x - player_position[0]) ** 2
            + (mob.world_y - player_position[1]) ** 2
            + (mob.world_z - player_position[2]) ** 2
        )
        ** 0.5
    )
