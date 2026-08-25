"""Cached ONNX inference for the exported hierarchical policy heads."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.policy.action_payloads import (
    CorridorAction,
    TacticalActionKind,
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
    PolicyCandidate,
    PolicyContext,
    StrategicDecision,
    StrategicGoalKind,
    TacticalAction,
)
from flyff_bot.features.rl.models import (
    CandidateObservation,
    NavMeshContext,
    ObjectiveState,
    ObservationSpace,
    OperationalState,
    PlayerKinematics,
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
        self.objective = objective or HierarchicalObjective()
        self._mid_level = MidLevelTacticalPolicy()
        self.last_values: tuple[float, float] | None = None

    def evaluate(self, world_state: WorldState, context: PolicyContext) -> TacticalAction | None:
        features = ObservationSpace.encode(_observation(world_state, context, self.objective))
        high_logits = _predict(
            self._high_network,
            features,
            self._high_input_name,
            len(HIGH_LEVEL_ACTION_ORDER),
        )
        high_mask = self._high_mask(context)
        high_index = _masked_argmax(high_logits, high_mask)
        goal = StrategicGoalKind(HIGH_LEVEL_ACTION_ORDER[high_index])
        decision = self._decision(goal, world_state, context)

        mid_logits = _predict(
            self._mid_network,
            features,
            self._mid_input_name,
            len(MID_LEVEL_ACTION_ORDER),
        )
        mid_mask = self._mid_mask(goal, decision, context)
        mid_index = _masked_argmax(mid_logits, mid_mask)
        mid_kind = TacticalActionKind(MID_LEVEL_ACTION_ORDER[mid_index])
        self.last_values = (float(high_logits[high_index]), float(mid_logits[mid_index]))
        if mid_kind is TacticalActionKind.ATTACK_POINT:
            return next(
                (
                    item
                    for item in context.valid_attack_points
                    if _decision_target_id(decision, context) == item.target_id
                ),
                None,
            )
        if mid_kind is TacticalActionKind.CORRIDOR:
            target_id = _decision_target_id(decision, context)
            corridor = next(iter(sorted(context.valid_corridor_ids)), None)
            return (
                None
                if target_id is None or corridor is None
                else CorridorAction(target_id, corridor)
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
        return target_allowed, navigate_allowed, interact_allowed, True

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
        target_id = _decision_target_id(decision, context)
        allowed = {
            TacticalActionKind.TARGET: goal is StrategicGoalKind.TARGET,
            TacticalActionKind.NAVIGATE: goal is StrategicGoalKind.NAVIGATE,
            TacticalActionKind.ATTACK_POINT: (
                goal is StrategicGoalKind.TARGET
                and any(item.target_id == target_id for item in context.valid_attack_points)
            ),
            TacticalActionKind.CORRIDOR: (
                goal is StrategicGoalKind.TARGET
                and target_id is not None
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


def _decision_target_id(decision: StrategicDecision, context: PolicyContext) -> int | None:
    return next(
        (
            candidate.mob.class_id
            for candidate in context.candidates
            if candidate.original_position == decision.target_candidate_index
        ),
        None,
    )


def _observation(
    state: WorldState,
    context: PolicyContext,
    objective: HierarchicalObjective,
) -> RlObservation:
    candidates = tuple(
        CandidateObservation(
            candidate.original_position if candidate.original_position is not None else index,
            candidate.mob.class_id,
            candidate.mob.confidence,
            candidate.mob.world_x,
            candidate.mob.world_y,
            candidate.mob.world_z,
            candidate.mob.navmesh_path_distance,
            None,
            is_dead=not candidate.is_alive_and_recognized,
            is_locked_out=not candidate.is_unlocked,
            is_unreachable=not candidate.is_navmesh_reachable,
        )
        for index, candidate in enumerate(context.candidates)
    )
    return RlObservation(
        PlayerKinematics(0.0, 0.0, 0.0, 0.0),
        PlayerVitals(
            state.player_vitals.hp_percentage,
            state.player_vitals.mp_percentage,
            state.player_vitals.fp_percentage,
        ),
        NavMeshContext(None, None, None),
        candidates,
        OperationalState(None, 0.0, int(state.is_stuck), objective.kind.value),
        ObjectiveState(
            objective.quest_id,
            ((int(objective.required_progress), objective.progress),),
            None,
        ),
    )
