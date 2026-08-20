"""Tests for the 3D terrain and vector navigation path inspector widget (US-045, US-059)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from flyff_bot.features.navigation.live_camera import CameraState
from flyff_bot.features.navigation.live_position import PositionSource, WorldPosition
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import NavigationSnapshot, VectorZoneSnapshot
from flyff_bot.ui.path_inspector import (
    LEGEND_ITEMS,
    WIDGET_MIN_HEIGHT,
    WIDGET_MIN_WIDTH,
    PathInspectorWidget,
)


def _vector_snapshot() -> NavigationSnapshot:
    zones = (
        VectorZoneSnapshot(
            monster_name="Aibatt",
            center_x=100.0,
            center_y=200.0,
            half_width_pixels=20.0,
            half_depth_pixels=20.0,
            capacity=10,
        ),
    )
    return NavigationSnapshot(
        player_x=100.0,
        player_y=200.0,
        heading_degrees=90.0,
        position_source=PositionSource.LIVE,
        world_position=WorldPosition(100.0, 10.0, 200.0),
        world_waypoints=(
            WorldPosition(110.0, 12.0, 210.0),
            WorldPosition(120.0, 14.0, 220.0),
        ),
        camera_state=CameraState(pitch_radians=0.5, yaw_radians=1.5, vertical_fov_radians=1.0),
        vector_zones=zones,
        terrain_samples=(
            (80.0, 10.0, 180.0),
            (100.0, 12.0, 200.0),
            (120.0, 14.0, 220.0),
        ),
    )


def test_widget_initialization_and_properties() -> None:
    _app = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    widget = PathInspectorWidget(translator)

    assert widget.snapshot is None
    assert widget.minimumSize() == QSize(WIDGET_MIN_WIDTH, WIDGET_MIN_HEIGHT)
    assert widget.sizeHint() == QSize(540, 360)


def test_widget_renders_standby_on_none_snapshot() -> None:
    _app = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    widget = PathInspectorWidget(translator)
    widget.resize(600, 400)

    image = QImage(600, 400, QImage.Format.Format_RGB32)
    widget.render(image)
    assert not image.isNull()


def test_widget_renders_vector_navigation_snapshot() -> None:
    _app = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    widget = PathInspectorWidget(translator)
    widget.resize(640, 480)

    snapshot = _vector_snapshot()
    widget.set_navigation(snapshot)

    image = QImage(640, 480, QImage.Format.Format_RGB32)
    widget.render(image)
    assert not image.isNull()
    assert widget.snapshot == snapshot


def test_widget_retranslates_legend_and_hud() -> None:
    _app = QApplication.instance() or QApplication([])
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    widget.resize(600, 400)
    widget.set_navigation(_vector_snapshot())

    widget.set_translator(Translator(Language.GERMAN))
    image = QImage(600, 400, QImage.Format.Format_RGB32)
    widget.render(image)
    assert not image.isNull()


def test_legend_items_have_unique_messages() -> None:
    messages = [message for _glyph, _color, message in LEGEND_ITEMS]
    assert len(messages) == len(set(messages))
    assert Message.UI_NAV_LEGEND_PLAYER in messages
    assert Message.UI_NAV_LEGEND_ZONE in messages


def test_calculate_grid_step_adapts_to_zoom() -> None:
    from flyff_bot.ui.path_inspector import _calculate_grid_step

    assert _calculate_grid_step(10.0) == 5.0
    assert _calculate_grid_step(2.0) == 20.0
    assert _calculate_grid_step(0.5) == 100.0
    assert _calculate_grid_step(0.05) == 1000.0


def test_widget_renders_multiple_zones_without_clutter() -> None:
    _app = QApplication.instance() or QApplication([])
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    widget.resize(640, 480)

    zones = (
        VectorZoneSnapshot(
            monster_name="MiniMush",
            center_x=1380.0,
            center_y=1045.0,
            half_width_pixels=25.0,
            half_depth_pixels=25.0,
            capacity=15,
        ),
        VectorZoneSnapshot(
            monster_name="MiniMush",
            center_x=1400.0,
            center_y=1060.0,
            half_width_pixels=10.0,
            half_depth_pixels=10.0,
            capacity=5,
        ),
    )
    snapshot = NavigationSnapshot(
        player_x=1380.0,
        player_y=1045.0,
        heading_degrees=0.0,
        position_source=PositionSource.LIVE,
        world_position=WorldPosition(1380.0, 10.0, 1045.0),
        vector_zone=zones[0],
        vector_zones=zones,
        terrain_samples=(
            (1300.0, 10.0, 1000.0),
            (1400.0, 12.0, 1100.0),
        ),
    )
    widget.set_navigation(snapshot)

    image = QImage(640, 480, QImage.Format.Format_RGB32)
    widget.render(image)
    assert not image.isNull()

