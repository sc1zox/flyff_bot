"""Receding-horizon commitment, replanning, and fallback behavior for US-068."""

import json
from pathlib import Path

import numpy as np

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.ml.features import FEATURE_NAMES
from flyff_bot.features.policy.lookahead import RollingHorizonPlanner
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext, TargetAction
from flyff_bot.features.policy.runner import PolicyRunner

REQUIRED_MODEL_KINDS = (
    "travel_time",
    "stuck_risk",
    "recovery_time",
    "kill_time",
    "followup_value",
)


class _FakeNetwork:
    def setInput(self, blob: np.ndarray) -> None:
        self.blob = blob

    def forward(self) -> np.ndarray:
        assert self.blob is not None
        return np.arange(self.blob.shape[0], dtype=np.float32).reshape(-1, 1)


def _metadata(path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "feature_schema": {"raw_features": list(FEATURE_NAMES), "input_name": "features"},
        "models": {
            kind: {"file": f"{kind}.onnx", "trained": True} for kind in REQUIRED_MODEL_KINDS
        },
    }
    path.mkdir(parents=True)
    path.joinpath("metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    return path


def _mob(class_id: int) -> VisibleMob:
    return VisibleMob(
        class_id=class_id,
        class_name=f"Mob{class_id}",
        confidence=0.9,
        x=10,
        y=10,
        width=5,
        height=5,
    )


def _context(class_ids: tuple[int, ...]) -> PolicyContext:
    candidates = tuple(
        PolicyCandidate(_mob(class_id), True, True, True, True, True, index)
        for index, class_id in enumerate(class_ids)
    )
    matrix = np.zeros((len(candidates), len(FEATURE_NAMES)), dtype=np.float64)
    return PolicyContext(candidates, frozenset(), (False,) * len(candidates), matrix)


def _empty_state() -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=0,
        progress_marker=0,
        visible_mobs=(),
        viewport=Viewport(100, 100),
    )


def _planner(path: Path) -> RollingHorizonPlanner:
    return RollingHorizonPlanner(
        _metadata(path),
        max_horizon=3,
        beam_width=2,
        network_loader=lambda _path: _FakeNetwork(),
    )


def test_first_action_only_is_executed_and_plan_is_provisional(tmp_path: Path) -> None:
    planner = _planner(tmp_path / "model")
    runner = PolicyRunner(planner)

    action = runner.evaluate(_empty_state(), _context((7, 8, 9)))

    assert isinstance(action, TargetAction)
    assert not runner.fell_back
    assert planner.provisional_sequence == (7, 8, 9)


def test_each_snapshot_replans_from_current_candidates(tmp_path: Path) -> None:
    planner = _planner(tmp_path / "model")
    runner = PolicyRunner(planner)

    first = runner.evaluate(_empty_state(), _context((7, 8, 9)))
    second = runner.evaluate(_empty_state(), _context((10, 11)))

    assert isinstance(first, TargetAction) and first.target_id == 7
    assert isinstance(second, TargetAction) and second.target_id == 10
    assert planner.provisional_sequence == (10, 11)


def test_empty_or_invalid_sequence_stops_instead_of_acting_heuristically(tmp_path: Path) -> None:
    from flyff_bot.features.automation.models import (
        Position,
        Viewport,
        VisibleMob,
        WorldState,
    )
    from flyff_bot.features.policy.heuristic import HeuristicPolicy
    from flyff_bot.features.policy.runner import PolicyFaultCode

    planner = _planner(tmp_path / "model")
    runner = PolicyRunner(planner, heuristic_factory=HeuristicPolicy)
    mob = VisibleMob(class_id=3, class_name="Mob", confidence=0.9, x=10, y=10, width=5, height=5)
    state = WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=1,
        progress_marker=0,
        visible_mobs=(mob,),
        viewport=Viewport(100, 100),
    )

    candidates = tuple(
        PolicyCandidate(_mob(class_id), True, True, True, True, True, index)
        for index, class_id in enumerate((3, 4))
    )
    invalid_context = PolicyContext(candidates, frozenset(), (False, False))
    action = runner.evaluate(state, invalid_context)

    assert action is None
    assert runner.last_fault is not None
    assert runner.last_fault.code is PolicyFaultCode.NO_VALID_ACTION
    assert planner.provisional_sequence == ()
