"""Shared in-memory fixtures for simulator tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from flyff_bot.features.navigation.world_extractor import (
    LAND_BLOCK_VERTICES_PER_SIDE,
    LandBlock,
    VectorSpawnZone,
    WorldCoordinate,
    WorldDimensions,
    WorldVectorMap,
)
from flyff_bot.features.simulator import (
    FarmingSimulator,
    QuestObjective,
    QuestObjectiveKind,
    SimulatorConfig,
)


@pytest.fixture
def world_map() -> WorldVectorMap:
    heights = tuple(
        float(row)
        for row in range(2 * LAND_BLOCK_VERTICES_PER_SIDE)
        for column in range(2 * LAND_BLOCK_VERTICES_PER_SIDE)
        if row < LAND_BLOCK_VERTICES_PER_SIDE and column < LAND_BLOCK_VERTICES_PER_SIDE
    )
    zone = VectorSpawnZone(
        7,
        50.0,
        25.0,
        50.0,
        40.0,
        40.0,
        60.0,
        60.0,
        capacity=2,
        respawn_seconds=1,
        monster_name="SmallAibatt",
    )
    return WorldVectorMap(
        "WdTest",
        WorldDimensions(1, 1, 1.0),
        zones=(zone,),
        terrain_blocks=(LandBlock(0, 0, heights),),
    )


@pytest.fixture
def make_simulator(
    world_map: WorldVectorMap,
) -> Callable[..., FarmingSimulator]:
    def factory(
        config: SimulatorConfig | None = None,
        *,
        objectives: tuple[QuestObjective, ...] = (),
        seed: int | None = 42,
    ) -> FarmingSimulator:
        default_objective = QuestObjective(
            QuestObjectiveKind.GO_TO, position_x=20.0, position_z=10.0, radius_units=1.0
        )
        return FarmingSimulator(
            world_map,
            start=WorldCoordinate(10.0, 10.0),
            objectives=objectives or (default_objective,),
            config=config or SimulatorConfig(tick_seconds=0.5),
            seed=seed,
        )

    return factory


@pytest.fixture
def simulator(make_simulator: Callable[..., FarmingSimulator]) -> FarmingSimulator:
    return make_simulator(
        objectives=(
            QuestObjective(
                QuestObjectiveKind.GO_TO,
                position_x=10.0,
                position_z=10.0,
                radius_units=1.0,
            ),
        )
    )
