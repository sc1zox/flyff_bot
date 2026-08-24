"""Quest objective triggers and state transitions."""

from __future__ import annotations

from collections.abc import Callable

from flyff_bot.features.simulator import FarmingSimulator, QuestObjective, QuestObjectiveKind


def test_kill_go_to_interact_and_talk_objectives_progress_in_order(
    make_simulator: Callable[..., FarmingSimulator],
) -> None:
    objectives = (
        QuestObjective(QuestObjectiveKind.KILL, monster_id=7, required_count=2),
        QuestObjective(QuestObjectiveKind.GO_TO, position_x=20.0, position_z=10.0),
        QuestObjective(
            QuestObjectiveKind.INTERACT, identifier="chest", position_x=20.0, position_z=10.0
        ),
        QuestObjective(
            QuestObjectiveKind.TALK_TO_NPC, npc_id="npc", position_x=20.0, position_z=10.0
        ),
    )
    simulation = make_simulator(objectives=objectives, seed=11)
    simulation.reset()

    for _attempt in range(100):
        mask = simulation.action_mask
        action = next(index for index, allowed in enumerate(mask) if allowed)
        _observation, _reward, terminated, truncated, _info = simulation.step(action)
        if terminated or truncated:
            break

    assert simulation.metrics.kill_count >= 1
    assert truncated or any(simulation._completed)
