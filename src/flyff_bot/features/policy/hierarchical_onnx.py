"""Cached ONNX inference for the exported hierarchical policy heads."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.automation.target_reconciliation import TargetAgreement
from flyff_bot.features.player_stats.models import (
    PROFILE_DEXTERITY_FIELD,
    PROFILE_EXPERIENCE_FIELD,
    PROFILE_INTELLIGENCE_FIELD,
    PROFILE_LEVEL_FIELD,
    PROFILE_STAMINA_FIELD,
    PROFILE_STRENGTH_FIELD,
    ClientTargetState,
    PlayerStatsSource,
)
from flyff_bot.features.policy.action_payloads import (
    STRATEGIC_GOAL_COUNT,
    STRATEGIC_GOAL_ORDER,
    AttackPointAction,
    CorridorAction,
    StrategicGoalKind,
    TacticalActionKind,
    strategic_goal_at,
    strategic_goal_index,
)
from flyff_bot.features.policy.goal_preconditions import (
    can_engage_targets,
    can_interact,
    can_navigate,
)
from flyff_bot.features.policy.hierarchical import (
    HierarchicalObjective,
    MidLevelTacticalPolicy,
)
from flyff_bot.features.policy.hierarchical_training import (
    APPROACH_DISTANCE_INPUT_NAME,
    HIERARCHICAL_METADATA_FILENAME,
    HIGH_LEVEL_ACTION_ORDER,
    MID_LEVEL_ACTION_ORDER,
    read_hierarchical_metadata,
)
from flyff_bot.features.policy.models import (
    LiveObservationState,
    PolicyCandidate,
    PolicyContext,
    StrategicDecision,
    TacticalActionPayload,
)
from flyff_bot.features.rl.models import (
    OBSERVATION_DIMENSION,
    CandidateObservation,
    ObjectiveState,
    ObservationSpace,
    OperationalState,
    PlayerProfileObservation,
    PlayerVitals,
    RlObservation,
)


class InferenceNetwork(Protocol):
    def setInput(self, blob: np.ndarray, name: str = "") -> None: ...

    def forward(self) -> np.ndarray: ...


class HierarchicalOnnxPolicy:
    """Rank only currently masked options through three cached ONNX sessions."""

    def __init__(
        self,
        model_directory: Path,
        *,
        objective: HierarchicalObjective | None = None,
        network_loader: object | None = None,
    ) -> None:
        metadata = read_hierarchical_metadata(model_directory / HIERARCHICAL_METADATA_FILENAME)
        models = metadata["models"]
        if not isinstance(models, dict):
            raise ValueError("model_heads_missing")
        loader = network_loader if callable(network_loader) else _load_network
        high = _model_document(models, "high_level")
        mid = _model_document(models, "mid_level")
        approach = _model_document(models, "approach_distance")
        self._high_network = loader(model_directory / str(high["file"]))
        self._mid_network = loader(model_directory / str(mid["file"]))
        self._approach_network = loader(model_directory / str(approach["file"]))
        self._high_input_name = str(high["input_name"])
        self._mid_input_name = str(mid["input_name"])
        self._approach_input_name = str(approach.get("input_name", APPROACH_DISTANCE_INPUT_NAME))
        self._high_trained = _trained_kinds(high, HIGH_LEVEL_ACTION_ORDER)
        self._mid_trained = _trained_kinds(mid, MID_LEVEL_ACTION_ORDER)
        self._high_wait = strategic_goal_index(StrategicGoalKind.WAIT)
        self._mid_wait = MID_LEVEL_ACTION_ORDER.index(TacticalActionKind.WAIT)
        self.objective = objective or HierarchicalObjective()
        self._mid_level = MidLevelTacticalPolicy()
        self.last_values: tuple[float, float] | None = None

    def warm_up(self) -> None:
        """Run one throwaway inference per head so graph setup never delays a decision."""

        features = np.zeros(OBSERVATION_DIMENSION, dtype=np.float64)
        _predict(self._high_network, features, self._high_input_name, STRATEGIC_GOAL_COUNT)
        _predict(self._mid_network, features, self._mid_input_name, len(MID_LEVEL_ACTION_ORDER))
        _predict(self._approach_network, features, self._approach_input_name, 1)

    def configure_objective(self, objective: HierarchicalObjective) -> None:
        """Bind the objective the session is actually pursuing before the next evaluation."""

        self.objective = objective

    def evaluate(
        self, world_state: WorldState, context: PolicyContext
    ) -> TacticalActionPayload | None:
        features = ObservationSpace.encode(live_observation(world_state, context, self.objective))
        high_logits = _predict(
            self._high_network,
            features,
            self._high_input_name,
            STRATEGIC_GOAL_COUNT,
        )
        high_mask = _restrict(self._high_mask(context), self._high_trained, self._high_wait)
        high_index = _masked_argmax(high_logits, high_mask)
        goal = strategic_goal_at(high_index)
        decision = self._decision(goal, world_state, context)

        mid_logits = _predict(
            self._mid_network,
            features,
            self._mid_input_name,
            len(MID_LEVEL_ACTION_ORDER),
        )
        mid_mask = _restrict(
            self._mid_mask(goal, decision, context), self._mid_trained, self._mid_wait
        )
        mid_index = _masked_argmax(mid_logits, mid_mask)
        mid_kind = TacticalActionKind(MID_LEVEL_ACTION_ORDER[mid_index])
        self.last_values = (float(high_logits[high_index]), float(mid_logits[mid_index]))
        selected = _decision_candidate(decision, context)
        if mid_kind is TacticalActionKind.ATTACK_POINT:
            options = tuple(
                item
                for item in context.valid_attack_points
                if selected is not None and _names(item.candidate_index, item.target_id, selected)
            )
            approach_value = float(
                _predict(
                    self._approach_network,
                    features,
                    self._approach_input_name,
                    1,
                )[0]
            )
            return _select_attack_point(options, approach_value)
        if mid_kind is TacticalActionKind.CORRIDOR:
            corridor = next(iter(sorted(context.valid_corridor_ids)), None)
            return (
                None
                if selected is None or corridor is None
                else CorridorAction(selected.mob.class_id, corridor, selected.original_position)
            )
        return self._mid_level.evaluate_for_goal(world_state, context, decision)

    def _high_mask(self, context: PolicyContext) -> tuple[bool, ...]:
        objective = self.objective
        progress_complete = objective.progress >= objective.required_progress
        grounding = context.grounding
        # The grounding facts narrow the option set first; the objective and the prevalidated
        # option lists then narrow it further. A capability blocked for an unrelated reason
        # removes only its own goal (US-083).
        target_allowed = (
            any(candidate.is_eligible for candidate in context.candidates)
            and can_engage_targets(grounding)
            and not (objective.kind.value == "navigation" or progress_complete)
        )
        navigate_allowed = (
            objective.destination in context.valid_destinations
            and can_navigate(grounding)
            and not objective.destination_reached
        )
        interact_allowed = (
            (
                objective.interaction_target_id,
                objective.interaction_type,
            )
            in context.valid_interactions
            and can_interact(grounding)
            and progress_complete
        )
        allowed = {
            StrategicGoalKind.TARGET: target_allowed,
            StrategicGoalKind.NAVIGATE: navigate_allowed,
            StrategicGoalKind.INTERACT: interact_allowed,
            StrategicGoalKind.WAIT: True,
        }
        return tuple(allowed[goal] for goal in STRATEGIC_GOAL_ORDER)

    def _decision(
        self,
        goal: StrategicGoalKind,
        world_state: WorldState,
        context: PolicyContext,
    ) -> StrategicDecision:
        objective = self.objective
        target_index = None
        if goal is StrategicGoalKind.TARGET:
            selected = min(
                (candidate for candidate in context.candidates if candidate.is_eligible),
                key=lambda item: _candidate_key(item, world_state),
            )
            target_index = selected.original_position
        return StrategicDecision(
            goal,
            "onnx_policy",
            objective.quest_id,
            objective.objective_index,
            objective.progress,
            objective.destination,
            target_index,
            objective.interaction_target_id,
            objective.interaction_type,
        )

    @staticmethod
    def _mid_mask(
        goal: StrategicGoalKind,
        decision: StrategicDecision,
        context: PolicyContext,
    ) -> tuple[bool, ...]:
        selected = _decision_candidate(decision, context)
        allowed = {
            TacticalActionKind.TARGET: goal is StrategicGoalKind.TARGET,
            TacticalActionKind.NAVIGATE: goal is StrategicGoalKind.NAVIGATE,
            TacticalActionKind.ATTACK_POINT: (
                goal is StrategicGoalKind.TARGET
                and selected is not None
                and any(
                    _names(item.candidate_index, item.target_id, selected)
                    for item in context.valid_attack_points
                )
            ),
            TacticalActionKind.CORRIDOR: (
                goal is StrategicGoalKind.TARGET
                and selected is not None
                and bool(context.valid_corridor_ids)
            ),
            TacticalActionKind.INTERACT: goal is StrategicGoalKind.INTERACT,
            TacticalActionKind.WAIT: goal is StrategicGoalKind.WAIT,
        }
        return tuple(allowed[kind] for kind in TacticalActionKind)


def _load_network(path: Path) -> InferenceNetwork:
    try:
        return cv2.dnn.readNetFromONNX(str(path))
    except cv2.error as error:
        raise ValueError(f"model_load_failed:{path}") from error


def _select_attack_point(
    options: tuple[AttackPointAction, ...], model_value: float
) -> AttackPointAction | None:
    """Map one finite learned output onto the ordered prevalidated contextual choices."""

    if not options:
        return None
    ordered = tuple(
        sorted(
            options,
            key=lambda item: (
                float("inf")
                if item.approach_distance_units is None
                else item.approach_distance_units,
                item.attack_point,
            ),
        )
    )
    normalized = float(np.clip(model_value, 0.0, 1.0))
    index = min(int(normalized * len(ordered)), len(ordered) - 1)
    return ordered[index]


def _model_document(models: dict[object, object], name: str) -> dict[object, object]:
    document = models.get(name)
    if not isinstance(document, dict):
        raise ValueError("model_heads_missing")
    return document


def _predict(
    network: InferenceNetwork,
    features: np.ndarray,
    input_name: str,
    output_width: int,
) -> np.ndarray:
    network.setInput(features.reshape(1, -1).astype(np.float32), input_name)
    output = np.asarray(network.forward(), dtype=np.float64).reshape(-1)
    if output.shape != (output_width,) or not np.isfinite(output).all():
        raise ValueError("invalid_hierarchical_prediction")
    return output


def _trained_kinds(model: dict[object, object], action_order: tuple[str, ...]) -> tuple[bool, ...]:
    """Return, per action slot, whether the exported head was fitted on that class.

    A class the training run never produced a positive example for carries an unfitted
    constant logit, so enabling it live would let noise win the argmax.
    """

    trained = model.get("trained_actions")
    if not isinstance(trained, list):
        raise ValueError("trained_actions_invalid")
    names = {str(item) for item in trained}
    enabled = tuple(name in names for name in action_order)
    if not any(enabled):
        raise ValueError("trained_actions_invalid")
    return enabled


def _restrict(
    mask: tuple[bool, ...], trained: tuple[bool, ...], wait_index: int
) -> tuple[bool, ...]:
    """Return the mask with every untrained action class removed, never fully closed."""

    restricted = tuple(
        allowed and is_trained for allowed, is_trained in zip(mask, trained, strict=True)
    )
    if any(restricted):
        return restricted
    return tuple(index == wait_index for index in range(len(mask)))


def _masked_argmax(logits: np.ndarray, mask: tuple[bool, ...]) -> int:
    if logits.shape != (len(mask),) or not any(mask):
        raise ValueError("invalid_hierarchical_mask")
    masked = np.where(np.asarray(mask, dtype=bool), logits, -np.inf)
    return int(np.argmax(masked))


def _candidate_key(candidate: PolicyCandidate, state: WorldState) -> tuple[bool, float, int]:
    return (
        candidate.mob.navmesh_path_distance is None,
        candidate.mob.navmesh_path_distance
        if candidate.mob.navmesh_path_distance is not None
        else float("inf"),
        (candidate.mob.x - state.position.x) ** 2 + (candidate.mob.y - state.position.y) ** 2,
    )


def _decision_candidate(
    decision: StrategicDecision, context: PolicyContext
) -> PolicyCandidate | None:
    """Resolve the exact candidate instance a strategic decision selected."""

    return next(
        (
            candidate
            for candidate in context.candidates
            if candidate.original_position == decision.target_candidate_index
        ),
        None,
    )


def _names(candidate_index: int | None, target_id: int, candidate: PolicyCandidate) -> bool:
    """Match by per-instance identity when the option declares one, by class only otherwise."""

    if candidate_index is not None:
        return candidate_index == candidate.original_position
    return target_id == candidate.mob.class_id


def live_observation(
    state: WorldState,
    context: PolicyContext,
    objective: HierarchicalObjective,
) -> RlObservation:
    """Build the decision-time observation in exactly the training-time layout.

    Position, heading, velocity, NavMesh context, and objective progress come from the live
    session instead of being fabricated as zeros, so the vector served to a model matches the
    one it was trained on. Without those live facts the policy fails closed (BUG-031).
    """

    live = context.live_state
    if live is None:
        raise ValueError("live_observation_unavailable")
    candidates = tuple(
        CandidateObservation(
            candidate.original_position if candidate.original_position is not None else index,
            candidate.mob.class_id,
            candidate.mob.confidence,
            candidate.mob.world_x,
            candidate.mob.world_y,
            candidate.mob.world_z,
            candidate.mob.navmesh_path_distance,
            _relative_elevation(candidate, live),
            is_dead=not candidate.is_alive_and_recognized,
            is_locked_out=not candidate.is_unlocked,
            is_unreachable=not candidate.is_navmesh_reachable,
        )
        for index, candidate in enumerate(context.candidates)
    )
    return RlObservation(
        live.kinematics,
        PlayerVitals(
            state.player_vitals.hp_percentage,
            state.player_vitals.mp_percentage,
            state.player_vitals.fp_percentage,
        ),
        live.navmesh,
        candidates,
        OperationalState(
            live.current_target_index,
            live.recent_kill_rate_per_minute,
            live.recent_stuck_count,
            objective.kind.value,
        ),
        profile=_profile_observation(state),
        objective=ObjectiveState(
            objective.quest_id,
            ((int(objective.required_progress), objective.progress),),
            live.objective_target_distance,
            objective.encoded_identity,
            objective.encoded_kind,
            objective.objective_index,
            objective.objective_count,
            objective.progress,
            objective.required_progress,
        ),
    )


def _profile_observation(state: WorldState) -> PlayerProfileObservation:
    """Carry every proven exact-profile field into the decision, with its missingness.

    A field the client never exposed stays ``None`` and encodes as missing rather than as a
    measured zero, and the reconciliation verdict travels with them so a policy can see that
    the client disagrees about what is selected instead of ranking a candidate blind.
    """

    snapshot = state.player_stats_snapshot
    reconciliation = state.target_reconciliation
    agreement = reconciliation.agreement
    identity_agreed = (
        True
        if agreement is TargetAgreement.AGREED
        else False
        if agreement is TargetAgreement.IDENTITY_MISMATCH
        else None
    )
    if snapshot is None or snapshot.source is not PlayerStatsSource.CLIENT_MEMORY:
        return PlayerProfileObservation(target_identity_agreed=identity_agreed)

    values = {field.name: field.value for field in snapshot.fields if not field.is_unknown}
    target = snapshot.target
    hp_fraction = (
        None
        if reconciliation.client_hp_percentage is None
        else reconciliation.client_hp_percentage / 100.0
    )
    return PlayerProfileObservation(
        is_authoritative=True,
        level=values.get(PROFILE_LEVEL_FIELD),
        experience_fraction=values.get(PROFILE_EXPERIENCE_FIELD),
        strength=values.get(PROFILE_STRENGTH_FIELD),
        stamina=values.get(PROFILE_STAMINA_FIELD),
        dexterity=values.get(PROFILE_DEXTERITY_FIELD),
        intelligence=values.get(PROFILE_INTELLIGENCE_FIELD),
        target_hp_fraction=hp_fraction,
        target_is_alive=(
            None
            if target is None or target.state is None
            else target.state is ClientTargetState.ALIVE
        ),
        target_identity_agreed=identity_agreed,
    )


def _relative_elevation(candidate: PolicyCandidate, live: LiveObservationState) -> float | None:
    """Return the measured height difference to a candidate, or ``None`` without a measurement."""

    if candidate.mob.world_y is None:
        return None
    return candidate.mob.world_y - live.kinematics.position_y
