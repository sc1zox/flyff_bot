"""US-066 five-head ONNX inference and deterministic expected-cost ranking."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from flyff_bot.features.automation.models import Position, WorldState
from flyff_bot.features.ml.cost import ExpectedCostWeights, expected_costs
from flyff_bot.features.ml.features import FEATURE_NAMES
from flyff_bot.features.policy.models import (
    PolicyCandidate,
    PolicyContext,
    TacticalAction,
    TargetAction,
)

METADATA_SCHEMA_VERSION = 1
REQUIRED_MODEL_KINDS = (
    "travel_time",
    "stuck_risk",
    "recovery_time",
    "kill_time",
    "followup_value",
)
MODEL_INPUT_WIDTH = 20
MODEL_OUTPUT_WIDTH = 1


class _Network(Protocol):
    def setInput(self, blob: np.ndarray) -> None: ...

    def forward(self) -> np.ndarray: ...


NetworkLoader = Callable[[Path], _Network]


class LearnedPolicyError(ValueError):
    """The model set is missing, incompatible, or produced an unusable prediction."""


def _load_network(path: Path) -> _Network:
    try:
        return cv2.dnn.readNetFromONNX(str(path))
    except cv2.error as error:
        raise LearnedPolicyError(f"model_load_failed:{path}") from error


class LearnedPolicy:
    """Rank eligible target candidates with cached, in-memory ONNX sessions."""

    def __init__(
        self,
        model_directory: Path,
        *,
        cost_weights: ExpectedCostWeights | None = None,
        network_loader: NetworkLoader | None = None,
    ) -> None:
        metadata_path = model_directory / "metadata.json"
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            schema_version = int(payload["schema_version"])
            feature_schema = payload["feature_schema"]
            raw_features = tuple(feature_schema["raw_features"])
            input_name = str(feature_schema["input_name"])
            models = {
                kind: str(payload["models"][kind]["file"])
                for kind in REQUIRED_MODEL_KINDS
                if bool(payload["models"][kind]["trained"])
            }
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise LearnedPolicyError("metadata_invalid") from error
        if schema_version != METADATA_SCHEMA_VERSION or raw_features != FEATURE_NAMES:
            raise LearnedPolicyError("schema_incompatible")
        if len(models) != len(REQUIRED_MODEL_KINDS):
            raise LearnedPolicyError("model_heads_missing")
        loader = network_loader or _load_network
        self._networks = {
            kind: loader(model_directory / filename) for kind, filename in models.items()
        }
        self._input_name = input_name
        self._cost_weights = cost_weights or ExpectedCostWeights()

    def evaluate(self, world_state: WorldState, context: PolicyContext) -> TacticalAction | None:
        eligible = [candidate for candidate in context.candidates if candidate.is_eligible]
        matrix = context.feature_matrix
        expected_shape = (len(context.candidates), MODEL_INPUT_WIDTH)
        if not eligible or matrix is None or matrix.shape != expected_shape:
            return None
        rows = np.asarray(matrix, dtype=np.float32)
        (
            travel_time,
            stuck_probability,
            recovery_time,
            kill_time,
            followup_value,
        ) = (
            self._predict(self._networks[kind], self._input_name, rows)
            for kind in REQUIRED_MODEL_KINDS
        )
        costs = expected_costs(
            travel_time,
            stuck_probability,
            recovery_time,
            kill_time,
            followup_value,
            weights=self._cost_weights,
        )
        ranked = sorted((cost, index) for index, cost in enumerate(costs))
        for cost, candidate_index in ranked:
            candidate = context.candidates[candidate_index]
            if candidate.is_eligible:
                return self._action(candidate, float(np.asarray(cost).reshape(())))
        return None

    @staticmethod
    def _predict(network: _Network, input_name: str, rows: np.ndarray) -> np.ndarray:
        network.setInput(rows.reshape((-1, MODEL_INPUT_WIDTH)).astype(np.float32))
        output = np.asarray(network.forward(), dtype=np.float64).reshape(-1)
        if output.shape[0] != rows.shape[0] or not np.isfinite(output).all():
            raise LearnedPolicyError("invalid_prediction")
        return output.reshape(-1, MODEL_OUTPUT_WIDTH)

    @staticmethod
    def _action(candidate: PolicyCandidate, expected_cost: float) -> TacticalAction:
        mob = candidate.mob
        position = (
            Position(mob.x + mob.width // 2, mob.y + mob.height // 2)
            if mob.world_x is not None
            else None
        )
        return TargetAction(mob.class_id, position, round(expected_cost, 6))
