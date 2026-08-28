"""Shared in-memory fixtures for simulator tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from flyff_bot.features.navigation.world_extractor import (
    LAND_BLOCK_VERTICES_PER_SIDE,
    LandBlock,
    ObstacleRectangle,
    VectorSpawnZone,
    WorldCoordinate,
    WorldDimensions,
    WorldVectorMap,
)
from flyff_bot.features.simulator import (
    FarmingSimulator,
    ObjectiveKind,
    QuestObjective,
    SimulatorConfig,
)
from flyff_bot.features.tactical_parameters import TacticalParameterSpace


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
def multi_zone_world_map(world_map: WorldVectorMap) -> WorldVectorMap:
    """Return the test region with a second, separately timed camp."""

    second = VectorSpawnZone(
        11,
        90.0,
        25.0,
        90.0,
        80.0,
        80.0,
        100.0,
        100.0,
        capacity=3,
        respawn_seconds=2,
        monster_name="Burumung",
    )
    return WorldVectorMap(
        world_map.world_name,
        world_map.dimensions,
        zones=(*world_map.zones, second),
        terrain_blocks=world_map.terrain_blocks,
    )


@pytest.fixture
def blocked_world_map(world_map: WorldVectorMap) -> WorldVectorMap:
    """Return the test region with an impassable wall across the direct route east."""

    return WorldVectorMap(
        world_map.world_name,
        world_map.dimensions,
        zones=world_map.zones,
        obstacles=(ObstacleRectangle(20.0, -40.0, 30.0, 30.0),),
        terrain_blocks=world_map.terrain_blocks,
    )


@pytest.fixture
def make_simulator(
    world_map: WorldVectorMap,
) -> Callable[..., FarmingSimulator]:
    def factory(
        config: SimulatorConfig | None = None,
        *,
        objectives: tuple[QuestObjective, ...] | None = None,
        tactical_parameters: TacticalParameterSpace | None = None,
        seed: int | None = 42,
    ) -> FarmingSimulator:
        default_objective = QuestObjective(
            ObjectiveKind.GO_TO, position_x=20.0, position_z=10.0, radius_units=1.0
        )
        return FarmingSimulator(
            world_map,
            start=WorldCoordinate(10.0, 10.0),
            objectives=(default_objective,) if objectives is None else objectives,
            config=config or SimulatorConfig(tick_seconds=0.5),
            tactical_parameters=tactical_parameters,
            seed=seed,
        )

    return factory


@pytest.fixture
def simulator(make_simulator: Callable[..., FarmingSimulator]) -> FarmingSimulator:
    return make_simulator(
        objectives=(
            QuestObjective(
                ObjectiveKind.GO_TO,
                position_x=10.0,
                position_z=10.0,
                radius_units=1.0,
            ),
        )
    )
