"""Deterministic sequence generation, scoring, and bounded-search coverage for US-068."""

import json
import time
from pathlib import Path

import numpy as np
import pytest

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.ml.features import FEATURE_NAMES
from flyff_bot.features.policy.lookahead import RollingHorizonPlanner
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext, TargetAction

REQUIRED_MODEL_KINDS = (
    "travel_time",
    "stuck_risk",
    "recovery_time",
    "kill_time",
    "followup_value",
)


def _state() -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=0,
        inventory=(),
        progress_marker=0,
        visible_mobs=(),
        viewport=Viewport(100, 100),
    )


def _metadata(path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "feature_schema": {"raw_features": list(FEATURE_NAMES), "input_name": "features"},
        "models": {
            kind: {"file": f"{kind}.onnx", "trained": True} for kind in REQUIRED_MODEL_KINDS
        },
    }
    path.mkdir(parents=True, exist_ok=True)
    path.joinpath("metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    return path


def _loader(path: Path) -> _FakeNetwork:
    return _FakeNetwork(path.stem)


class _FakeNetwork:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def setInput(self, blob: np.ndarray) -> None:
        self.blob = blob

    def forward(self) -> np.ndarray:
        assert self.blob is not None
        count = self.blob.shape[0]
        if self.kind == "travel_time":
            return np.arange(count, dtype=np.float32).reshape(count, 1)
        if self.kind == "stuck_risk":
            return np.full((count, 1), 0.1, dtype=np.float32)
        return np.ones((count, 1), dtype=np.float32)


def _mob(class_id: int, x: int) -> VisibleMob:
    return VisibleMob(
        class_id=class_id,
        class_name=f"Mob{class_id}",
        confidence=0.9,
        x=x,
        y=20,
        width=10,
        height=10,
    )


def _context(count: int = 4) -> PolicyContext:
    candidates = tuple(
        PolicyCandidate(
            mob=_mob(index, 10 + index * 10),
            is_alive_and_recognized=True,
            is_unlocked=True,
            is_within_leash=True,
            is_navmesh_reachable=True,
            has_valid_world_position=True,
            original_position=index,
        )
        for index in range(count)
    )
    matrix = np.arange(count * len(FEATURE_NAMES), dtype=np.float64).reshape(
        count, len(FEATURE_NAMES)
    )
    return PolicyContext(candidates, frozenset(), (False,) * count, matrix)


def test_sequence_is_acyclic_and_commits_first_target(tmp_path: Path) -> None:
    planner = RollingHorizonPlanner(
        _metadata(tmp_path), max_horizon=3, beam_width=2, network_loader=_loader
    )

    action = planner.evaluate(_state(), _context())

    assert isinstance(action, TargetAction)
    assert len(planner.provisional_sequence) == 3
    assert len(set(planner.provisional_sequence)) == 3
    assert action.target_id == planner.provisional_sequence[0]


def test_invalid_horizon_or_beam_width_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="horizon"):
        RollingHorizonPlanner(_metadata(tmp_path), max_horizon=5)
    with pytest.raises(ValueError, match="beam width"):
        RollingHorizonPlanner(_metadata(tmp_path / "same"), beam_width=6, network_loader=_loader)


def test_missing_features_clear_the_plan_for_fallback(tmp_path: Path) -> None:
    planner = RollingHorizonPlanner(_metadata(tmp_path), network_loader=_loader)
    candidates = (PolicyCandidate(_mob(1, 10), True, True, True, True, True, 0),)
    context = PolicyContext(candidates, frozenset(), (False,))

    assert planner.evaluate(_state(), context) is None
    assert planner.provisional_sequence == ()


def test_benchmark_stays_below_five_milliseconds_for_twenty_candidates(tmp_path: Path) -> None:
    planner = RollingHorizonPlanner(
        _metadata(tmp_path), max_horizon=4, beam_width=5, network_loader=_loader
    )

    context = _context(20)
    started = time.perf_counter()
    result = planner.evaluate(_state(), context)
    elapsed = time.perf_counter() - started

    assert isinstance(result, TargetAction)
    assert elapsed < 0.005
