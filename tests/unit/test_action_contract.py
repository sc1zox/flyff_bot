"""US-079: one action vocabulary, defined once, shared by simulator and live policy.

Before this story the name ``TacticalAction`` meant three different things, and the offline
simulator stepped on a private four-member enum whose index order only accidentally matched
the strategic head's exported column order. These tests pin that there is now exactly one
definition of each vocabulary and that an index means the same goal everywhere.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import flyff_bot
import flyff_bot.features.rl as rl_package
import flyff_bot.features.simulator as simulator_package
from flyff_bot.features.policy import action_payloads
from flyff_bot.features.policy.action_payloads import (
    STRATEGIC_GOAL_COUNT,
    STRATEGIC_GOAL_ORDER,
    TACTICAL_ACTION_COUNT,
    StrategicGoalKind,
    TacticalAction,
    TacticalActionKind,
    strategic_goal_at,
    strategic_goal_index,
)
from flyff_bot.features.policy.hierarchical_training import HIGH_LEVEL_ACTION_ORDER
from flyff_bot.features.simulator import FarmingSimulator

CONTRACT_MODULE = Path(action_payloads.__file__).resolve()
VOCABULARY_CLASS_NAMES = frozenset({"StrategicGoalKind", "TacticalAction", "TacticalActionKind"})


def _defining_files(class_name: str) -> list[Path]:
    """Return every source file that declares a class of this name."""

    source_root = Path(flyff_bot.__file__).resolve().parent
    defining: list[Path] = []
    for module_path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ClassDef) and node.name == class_name for node in ast.walk(tree)
        ):
            defining.append(module_path.resolve())
    return defining


def test_each_action_vocabulary_is_defined_exactly_once() -> None:
    for class_name in sorted(VOCABULARY_CLASS_NAMES):
        assert _defining_files(class_name) == [CONTRACT_MODULE]


def test_no_package_re_exports_a_competing_action_vocabulary() -> None:
    assert rl_package.TacticalAction is TacticalAction
    for name in sorted(VOCABULARY_CLASS_NAMES):
        assert not hasattr(simulator_package, name)


def test_the_strategic_wire_order_covers_every_goal_exactly_once() -> None:
    assert sorted(STRATEGIC_GOAL_ORDER) == sorted(StrategicGoalKind)
    assert len(StrategicGoalKind) == STRATEGIC_GOAL_COUNT
    for goal in StrategicGoalKind:
        assert strategic_goal_at(strategic_goal_index(goal)) is goal


def test_the_exported_head_columns_name_the_goals_the_simulator_was_stepped_with() -> None:
    assert tuple(goal.value for goal in STRATEGIC_GOAL_ORDER) == HIGH_LEVEL_ACTION_ORDER
    for index, name in enumerate(HIGH_LEVEL_ACTION_ORDER):
        assert strategic_goal_at(index).value == name


def test_the_simulator_action_space_is_the_shared_strategic_vocabulary(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    simulation = make_simulator()

    assert simulation.action_space_size == STRATEGIC_GOAL_COUNT
    assert len(simulation.action_mask) == STRATEGIC_GOAL_COUNT
    assert simulation.action_mask[strategic_goal_index(StrategicGoalKind.WAIT)] is True


def test_every_tactical_kind_maps_to_one_discrete_action() -> None:
    mapped = {TacticalAction.for_kind(kind) for kind in TacticalActionKind}

    assert len(mapped) == len(TacticalActionKind)
    assert mapped <= set(TacticalAction)
    assert len(TacticalAction) == TACTICAL_ACTION_COUNT
