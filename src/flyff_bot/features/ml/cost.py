"""Expected farming cost composed from the five predicted value-model quantities.

The cost expresses the same objective the live controller optimizes -- maximum kills per
minute -- as a single scalar per candidate:

``cost = travel + kill + stuck_probability * recovery - followup_weight * followup_value``

Each term carries its own weight so an operator can retune the trade-off offline without
retraining, and every input is a prediction rather than a heuristic guess.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

DEFAULT_TRAVEL_WEIGHT = 1.0
DEFAULT_KILL_WEIGHT = 1.0
DEFAULT_STUCK_WEIGHT = 1.0
# Follow-up value is measured in kills, not seconds, so its weight also converts the unit.
DEFAULT_FOLLOWUP_WEIGHT = 1.0


@dataclass(frozen=True, slots=True)
class ExpectedCostWeights:
    """Configurable component weights of the expected farming cost."""

    travel: float = DEFAULT_TRAVEL_WEIGHT
    kill: float = DEFAULT_KILL_WEIGHT
    stuck: float = DEFAULT_STUCK_WEIGHT
    followup: float = DEFAULT_FOLLOWUP_WEIGHT

    def as_dict(self) -> dict[str, float]:
        """Return the weights in a form that can be recorded in model metadata."""

        return {
            "travel": self.travel,
            "kill": self.kill,
            "stuck": self.stuck,
            "followup": self.followup,
        }


DEFAULT_COST_WEIGHTS = ExpectedCostWeights()


@dataclass(frozen=True, slots=True)
class FarmingValuePrediction:
    """The five predicted quantities describing one evaluated target candidate."""

    travel_time: float
    stuck_probability: float
    recovery_time: float
    kill_time: float
    followup_value: float


def expected_cost(
    prediction: FarmingValuePrediction,
    weights: ExpectedCostWeights = DEFAULT_COST_WEIGHTS,
) -> float:
    """Return the weighted expected cost of committing to one predicted candidate."""

    return (
        weights.travel * prediction.travel_time
        + weights.kill * prediction.kill_time
        + weights.stuck * prediction.stuck_probability * prediction.recovery_time
        - weights.followup * prediction.followup_value
    )


def expected_costs(
    travel_time: npt.NDArray[np.float64],
    stuck_probability: npt.NDArray[np.float64],
    recovery_time: npt.NDArray[np.float64],
    kill_time: npt.NDArray[np.float64],
    followup_value: npt.NDArray[np.float64],
    weights: ExpectedCostWeights = DEFAULT_COST_WEIGHTS,
) -> npt.NDArray[np.float64]:
    """Return the expected cost of a whole batch of predicted candidates."""

    return np.asarray(
        weights.travel * travel_time
        + weights.kill * kill_time
        + weights.stuck * stuck_probability * recovery_time
        - weights.followup * followup_value,
        dtype=np.float64,
    )
