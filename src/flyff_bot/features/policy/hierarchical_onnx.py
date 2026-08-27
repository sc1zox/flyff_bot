"""Cached ONNX inference for the exported hierarchical policy heads."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.policy.action_payloads import (
    STRATEGIC_GOAL_COUNT,
    STRATEGIC_GOAL_ORDER,
    CorridorAction,
    StrategicGoalKind,
    TacticalActionKind,
    strategic_goal_at,
    strategic_goal_index,
)
from flyff_bot.features.policy.hierarchical import (
    HierarchicalObjective,
    MidLevelTacticalPolicy,
)
from flyff_bot.features.policy.hierarchical_training import (
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
    PlayerVitals,
    RlObservation,
)


class InferenceNetwork(Protocol):
    def setInput(self, blob: np.ndarray, name: str = "") -> None: ...

    def forward(self) -> np.ndarray: ...


class HierarchicalOnnxPolicy:
    """Rank only currently masked options through two cached ONNX sessions."""

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
        self._high_network = loader(model_directory / str(high["file"]))
        self._mid_network = loader(model_directory / str(mid["file"]))
        self._high_input_name = str(high["input_name"])
        self._mid_input_name = str(mid["input_name"])
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
            return next(
                (
                    item
                    for item in context.valid_attack_points
                    if selected is not None
                    and _names(item.candidate_index, item.target_id, selected)
                ),
                None,
            )
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
        target_allowed = any(candidate.is_eligible for candidate in context.candidates) and not (
            objective.kind.value == "navigation" or progress_complete
        )
        navigate_allowed = (
            objective.destination in context.valid_destinations
            and not objective.destination_reached
        )
        interact_allowed = (
            objective.interaction_target_id,
            objective.interaction_type,
        ) in context.valid_interactions and progress_complete
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
        ObjectiveState(
            objective.quest_id,
            ((int(objective.required_progress), objective.progress),),
            live.objective_target_distance,
        ),
    )


def _relative_elevation(candidate: PolicyCandidate, live: LiveObservationState) -> float | None:
    """Return the measured height difference to a candidate, or ``None`` without a measurement."""

    if candidate.mob.world_y is None:
        return None
    return candidate.mob.world_y - live.kinematics.position_y
