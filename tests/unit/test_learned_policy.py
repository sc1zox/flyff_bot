"""Learned-policy metadata, scoring, and invalid-output coverage."""

import json
from pathlib import Path

import numpy as np
import pytest

from flyff_bot.features.automation.models import Position, Viewport, VisibleMob, WorldState
from flyff_bot.features.ml.features import FEATURE_NAMES
from flyff_bot.features.policy.learned import LearnedPolicy, LearnedPolicyError
from flyff_bot.features.policy.models import PolicyCandidate, PolicyContext, TargetAction


def _metadata(path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "feature_schema": {
            "raw_features": list(FEATURE_NAMES),
            "input_name": "features",
        },
        "models": {
            kind: {"file": f"{kind}.onnx", "trained": True}
            for kind in (
                "travel_time",
                "stuck_risk",
                "recovery_time",
                "kill_time",
                "followup_value",
            )
        },
    }
    path.mkdir(parents=True)
    path.joinpath("metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    return path


class _FakeNetwork:
    def __init__(self) -> None:
        self.blob: np.ndarray | None = None

    def setInput(self, blob: np.ndarray) -> None:
        self.blob = blob

    def forward(self) -> np.ndarray:
        assert self.blob is not None
        count = self.blob.shape[0]
        return np.arange(count, dtype=np.float32).reshape(count, 1)


def _state(mob: VisibleMob) -> WorldState:
    return WorldState(
        observed_at_seconds=1.0,
        position=Position(0, 0),
        nearby_mob_count=1,
        inventory=(),
        progress_marker=0,
        visible_mobs=(mob,),
        viewport=Viewport(100, 100),
    )


def _policy_mob() -> VisibleMob:
    return VisibleMob(
        class_id=7,
        class_name="Mob",
        confidence=0.9,
        x=10,
        y=20,
        width=10,
        height=10,
    )


def _context() -> PolicyContext:
    mob = VisibleMob(
        class_id=7,
        class_name="Mob",
        confidence=0.9,
        x=10,
        y=20,
        width=10,
        height=10,
        world_x=1.0,
        world_y=2.0,
        world_z=3.0,
    )
    candidate = PolicyCandidate(
        mob=mob,
        is_alive_and_recognized=True,
        is_unlocked=True,
        is_within_leash=True,
        is_navmesh_reachable=True,
        has_valid_world_position=True,
    )
    matrix = np.zeros((1, len(FEATURE_NAMES)), dtype=np.float64)
    return PolicyContext((candidate,), frozenset(), (False,), matrix)


def test_metadata_schema_must_match_feature_contract(tmp_path: Path) -> None:
    directory = _metadata(tmp_path / "model")
    policy = LearnedPolicy(directory, network_loader=lambda _path: _FakeNetwork())

    action = policy.evaluate(_state(_policy_mob()), _context())

    assert isinstance(action, TargetAction)
    assert action.target_id == 7
    assert action.expected_cost == pytest.approx(0.0)


def test_missing_or_invalid_heads_fall_back_to_typed_error(tmp_path: Path) -> None:
    directory = _metadata(tmp_path / "model")
    payload = json.loads(directory.joinpath("metadata.json").read_text(encoding="utf-8"))
    payload["models"]["kill_time"]["trained"] = False
    directory.joinpath("metadata.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LearnedPolicyError):
        LearnedPolicy(directory, network_loader=lambda _path: _FakeNetwork())
