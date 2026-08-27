"""Bounded multi-target lookahead over US-066 learned farming value heads."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from flyff_bot.features.automation.models import WorldState
from flyff_bot.features.ml.cost import (
    DEFAULT_COST_WEIGHTS,
    ExpectedCostWeights,
    FarmingValuePrediction,
    expected_cost,
)
from flyff_bot.features.policy.learned import MODEL_INPUT_WIDTH, LearnedPolicy, NetworkLoader
from flyff_bot.features.policy.models import (
    PolicyCandidate,
    PolicyContext,
    TacticalActionPayload,
)

DEFAULT_MAX_HORIZON = 3
MAX_SUPPORTED_HORIZON = 4
DEFAULT_BEAM_WIDTH = 3
MAX_SUPPORTED_BEAM_WIDTH = 5
MIN_HORIZON = 2
MIN_BEAM_WIDTH = 1


class RollingHorizonPlanner(LearnedPolicy):
    """Evaluate bounded acyclic sequences and commit only the first target."""

    def __init__(
        self,
        model_directory: Path,
        *,
        max_horizon: int = DEFAULT_MAX_HORIZON,
        beam_width: int = DEFAULT_BEAM_WIDTH,
        cost_weights: ExpectedCostWeights = DEFAULT_COST_WEIGHTS,
        network_loader: NetworkLoader | None = None,
    ) -> None:
        super().__init__(model_directory, cost_weights=cost_weights, network_loader=network_loader)
        if not MIN_HORIZON <= max_horizon <= MAX_SUPPORTED_HORIZON:
            raise ValueError("Lookahead horizon must be between two and four.")
        if not MIN_BEAM_WIDTH <= beam_width <= MAX_SUPPORTED_BEAM_WIDTH:
            raise ValueError("Lookahead beam width must be between one and five.")
        self.max_horizon = max_horizon
        self.beam_width = beam_width
        self.provisional_sequence: tuple[int, ...] = ()
        self.last_sequence_cost: float | None = None

    def evaluate(
        self, world_state: WorldState, context: PolicyContext
    ) -> TacticalActionPayload | None:
        eligible = tuple(candidate for candidate in context.candidates if candidate.is_eligible)
        matrix = context.feature_matrix
        expected_shape = (len(context.candidates), MODEL_INPUT_WIDTH)
        if not eligible or matrix is None or matrix.shape != expected_shape:
            self._clear_plan()
            return None

        if any(candidate.original_position is None for candidate in eligible):
            self._clear_plan()
            return None

        rows = np.asarray(matrix, dtype=np.float32)
        predictions_by_index = {
            candidate_index: self.predictions(rows[candidate_index : candidate_index + 1])
            for candidate_index, candidate in enumerate(context.candidates)
            if candidate.is_eligible
        }
        best_sequence = self._best_sequence(tuple(eligible), predictions_by_index)
        if best_sequence is None:
            self._clear_plan()
            return None

        sequence_indices, total_cost = best_sequence
        self.provisional_sequence = tuple(
            context.candidates[index].mob.class_id for index in sequence_indices
        )
        self.last_sequence_cost = round(total_cost, 6)
        return LearnedPolicy._action(context.candidates[sequence_indices[0]], total_cost)

    def _best_sequence(
        self,
        eligible: tuple[PolicyCandidate, ...],
        predictions_by_index: dict[int, FarmingValuePrediction],
    ) -> tuple[tuple[int, ...], float] | None:
        if not eligible:
            return None
        beams: list[tuple[float, tuple[int, ...]]] = [(0.0, ())]
        best_sequence: tuple[int, ...] | None = None

        for _ in range(self.max_horizon):
            expansions: list[tuple[float, tuple[int, ...]]] = []
            for accumulated_cost, sequence in beams:
                used = frozenset(sequence)
                for candidate_index, candidate in enumerate(eligible):
                    if candidate_index in used:
                        continue
                    original_position = candidate.original_position
                    if original_position is None:
                        return None
                    prediction = predictions_by_index[original_position]
                    transition_cost = expected_cost(prediction, weights=self._cost_weights)
                    expanded = (*sequence, candidate_index)
                    expansions.append((accumulated_cost + transition_cost, expanded))
            if not expansions:
                break
            expansions.sort(key=lambda item: item[0])
            beams = expansions[: self.beam_width]
            best_cost, best_sequence = beams[0]

        if best_sequence is None or best_cost is None:
            return None
        return (best_sequence, best_cost)

    def _clear_plan(self) -> None:
        self.provisional_sequence = ()
        self.last_sequence_cost = None
