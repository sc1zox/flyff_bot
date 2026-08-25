"""Interactive world-map transforms, input semantics, culling, and selection (US-074)."""

from __future__ import annotations

import os
from time import perf_counter

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from flyff_bot.features.navigation.live_position import PositionSource, WorldPosition
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshBaker
from flyff_bot.features.navigation.world_extractor import (
    LAND_BLOCK_SAMPLE_COUNT,
    LandBlock,
    VectorSpawnZone,
    WorldCoordinate,
    WorldDimensions,
    WorldVectorMap,
)
from flyff_bot.features.navigation.world_geometry import WorldTriangle, WorldVertex
from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.dashboard import NavigationSnapshot
from flyff_bot.ui.path_inspector import PathInspectorWidget
from flyff_bot.ui.world_map_view import (
    ScreenPoint,
    ViewportLimits,
    ViewportTransform,
    WorldBounds,
    WorldMapScene,
)


@pytest.fixture(scope="module", autouse=True)
def _application() -> None:
    if QApplication.instance() is None:
        QApplication([])


def _zone(
    monster_id: int = 1453,
    *,
    name: str = "Flame",
    center_x: float = 64.0,
    center_z: float = 64.0,
) -> VectorSpawnZone:
    return VectorSpawnZone(
        monster_id=monster_id,
        monster_name=name,
        center_x=center_x,
        center_y=12.5,
        center_z=center_z,
        minimum_x=center_x - 20.0,
        minimum_z=center_z - 15.0,
        maximum_x=center_x + 20.0,
        maximum_z=center_z + 15.0,
        capacity=26,
        respawn_seconds=30,
    )


def _world_map(*, block_count: int = 4) -> WorldVectorMap:
    blocks = tuple(
        LandBlock(index, 0, (float(index * 10),) * LAND_BLOCK_SAMPLE_COUNT)
        for index in range(block_count)
    )
    return WorldVectorMap(
        "WdTest",
        WorldDimensions(block_count, 1, 1.0),
        zones=(
            _zone(),
            _zone(1458, name="Rapra", center_x=block_count * 128.0 - 50.0, center_z=70.0),
        ),
        terrain_blocks=blocks,
    )


def _navmesh() -> BakedNavMesh:
    return NavMeshBaker().bake(
        (
            WorldTriangle(
                WorldVertex(20.0, 0.0, 20.0),
                WorldVertex(20.0, 0.0, 100.0),
                WorldVertex(100.0, 0.0, 20.0),
                "ground-a",
            ),
            WorldTriangle(
                WorldVertex(100.0, 0.0, 20.0),
                WorldVertex(20.0, 0.0, 100.0),
                WorldVertex(100.0, 0.0, 100.0),
                "ground-b",
            ),
        )
    )


def _mouse_event(
    event_type: QEvent.Type,
    position: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        position,
        position,
        position,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_world_to_screen_round_trip_and_pan_offsets_are_exact() -> None:
    transform = ViewportTransform(100.0, 200.0, 2.0, 640, 480)
    world = WorldCoordinate(125.5, 175.25)

    screen = transform.world_to_screen(world)
    round_trip = transform.screen_to_world(screen)
    assert (round_trip.x, round_trip.z) == pytest.approx((world.x, world.z))

    transform.pan_by_pixels(40.0, -20.0)
    assert (transform.center_x, transform.center_z) == pytest.approx((80.0, 190.0))


def test_cursor_centered_zoom_preserves_world_point_and_clamps_limits() -> None:
    limits = ViewportLimits(minimum_scale=0.5, maximum_scale=4.0, wheel_zoom_factor=2.0)
    transform = ViewportTransform(0.0, 0.0, 1.0, 400, 300, limits)
    cursor = ScreenPoint(325.0, 75.0)
    before = transform.screen_to_world(cursor)

    transform.zoom_at(2.0, cursor)
    after = transform.screen_to_world(cursor)
    assert (after.x, after.z) == pytest.approx((before.x, before.z))
    assert transform.scale == pytest.approx(2.0)

    transform.zoom_at(100.0, cursor)
    assert transform.scale == pytest.approx(4.0)
    transform.zoom_at(0.0001, cursor)
    assert transform.scale == pytest.approx(0.5)


def test_scene_culls_offscreen_terrain_zones_and_navmesh_polygons() -> None:
    scene = WorldMapScene(_world_map(), _navmesh())
    visible = WorldBounds(0.0, 0.0, 127.9, 127.9)

    assert [(block.block_x, block.block_z) for block in scene.visible_terrain_blocks(visible)] == [
        (0, 0)
    ]
    assert [zone.monster_name for zone in scene.visible_zones(visible)] == ["Flame"]
    assert len(scene.visible_navmesh_polygons(visible)) == 2

    distant = WorldBounds(350.0, 0.0, 511.0, 127.9)
    assert [zone.monster_name for zone in scene.visible_zones(distant)] == ["Rapra"]
    assert scene.visible_navmesh_polygons(distant) == ()


def test_zone_hit_testing_prefers_the_smallest_overlapping_camp() -> None:
    outer = _zone(center_x=64.0, center_z=64.0)
    inner = VectorSpawnZone(
        1458,
        64.0,
        12.0,
        64.0,
        60.0,
        60.0,
        68.0,
        68.0,
        4,
        60,
        "Rapra",
    )
    scene = WorldMapScene(
        WorldVectorMap("WdTest", WorldDimensions(1, 1, 1.0), zones=(outer, inner))
    )

    assert scene.zone_at(WorldCoordinate(64.0, 64.0)) == inner
    assert scene.zone_at(WorldCoordinate(10.0, 10.0)) is None


def test_right_drag_pans_suspends_follow_and_never_selects_a_zone() -> None:
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    widget.resize(640, 480)
    widget.set_world_data(_world_map(), _navmesh())
    widget.set_navigation(
        NavigationSnapshot(
            64.0,
            64.0,
            90.0,
            position_source=PositionSource.LIVE,
            world_position=WorldPosition(64.0, 0.0, 64.0),
        )
    )
    widget.set_follow_player(True)
    selected: list[object] = []
    widget.zone_selected.connect(selected.append)
    start = widget.world_to_screen(WorldCoordinate(64.0, 64.0))
    before = widget.view_center

    widget.mousePressEvent(
        _mouse_event(
            QEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
        )
    )
    widget.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            start + QPointF(30.0, -15.0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.RightButton,
        )
    )
    widget.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.MouseButtonRelease,
            start + QPointF(30.0, -15.0),
            Qt.MouseButton.RightButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert widget.view_center != before
    assert widget.follow_player is False
    assert selected == []


def test_hover_tooltip_and_left_click_expose_complete_zone_metadata() -> None:
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    widget.resize(640, 480)
    world_map = _world_map()
    widget.set_world_data(world_map, _navmesh())
    point = widget.world_to_screen(world_map.zones[0].centroid)

    widget.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            point,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
        )
    )
    tooltip = widget.toolTip()
    assert all(value in tooltip for value in ("Flame", "1453", "26", "30", "12.5"))

    selected: list[object] = []
    widget.zone_selected.connect(selected.append)
    widget.mousePressEvent(
        _mouse_event(
            QEvent.Type.MouseButtonPress,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )

    assert selected == [world_map.zones[0]]
    assert widget.selected_zone == world_map.zones[0]


def test_follow_mode_tracks_successive_live_positions_and_keeps_heading_snapshot() -> None:
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    widget.resize(640, 480)
    widget.set_world_data(_world_map())
    widget.set_follow_player(True)

    for x, z, heading in ((40.0, 50.0, 10.0), (140.0, 80.0, 225.0)):
        snapshot = NavigationSnapshot(
            x,
            z,
            heading,
            position_source=PositionSource.LIVE,
            world_position=WorldPosition(x, 3.0, z),
        )
        widget.set_navigation(snapshot)
        assert widget.view_center == WorldCoordinate(x, z)
        assert widget.snapshot is not None
        assert widget.snapshot.heading_degrees == heading


def test_warm_large_scene_render_sustains_the_synthetic_thirty_fps_budget() -> None:
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    widget.resize(800, 600)
    widget.set_world_data(_world_map(block_count=8), _navmesh())
    image = QImage(800, 600, QImage.Format.Format_RGB32)
    widget.render(image)

    started = perf_counter()
    for _ in range(60):
        widget.render(image)
    elapsed = perf_counter() - started

    assert elapsed < 2.0
    assert widget.last_visible_terrain_block_count == 8
