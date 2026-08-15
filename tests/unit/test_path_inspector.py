"""Tests for the 2D visual navigation path and spawn heatmap inspector widget."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from flyff_bot.i18n import Language, Translator
from flyff_bot.ui.dashboard import (
    CellSnapshot,
    EdgeSnapshot,
    NavigationSnapshot,
)
from flyff_bot.ui.path_inspector import (
    WIDGET_MIN_HEIGHT,
    WIDGET_MIN_WIDTH,
    PathInspectorWidget,
)


def _populated_snapshot() -> NavigationSnapshot:
    cells = (
        CellSnapshot(x=0, y=0, center_x=0.0, center_y=0.0, visits=10, stalls=0, spawn_weight=0.0),
        CellSnapshot(x=1, y=0, center_x=40.0, center_y=0.0, visits=3, stalls=1, spawn_weight=2.0),
        CellSnapshot(x=1, y=1, center_x=40.0, center_y=40.0, visits=8, stalls=0, spawn_weight=8.0),
        CellSnapshot(x=0, y=1, center_x=0.0, center_y=40.0, visits=1, stalls=0, spawn_weight=0.5),
    )
    edges = (
        EdgeSnapshot(origin_x=0.0, origin_y=0.0, destination_x=40.0, destination_y=0.0, stalls=1),
        EdgeSnapshot(origin_x=40.0, origin_y=0.0, destination_x=40.0, destination_y=40.0, stalls=0),
        EdgeSnapshot(origin_x=40.0, origin_y=40.0, destination_x=0.0, destination_y=40.0, stalls=0),
    )
    return NavigationSnapshot(
        player_x=20.0,
        player_y=10.0,
        heading_degrees=135.0,
        cells=cells,
        edges=edges,
        waypoints=((40.0, 40.0), (0.0, 40.0)),
        safe_waypoint=(0.0, 0.0),
        cell_size_units=40.0,
        leash_radius_units=60.0,
    )


def test_widget_initialization_and_properties() -> None:
    _app = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    widget = PathInspectorWidget(translator)

    assert widget.snapshot is None
    assert widget.minimumSize() == QSize(WIDGET_MIN_WIDTH, WIDGET_MIN_HEIGHT)
    assert widget.sizeHint() == QSize(540, 360)


def test_widget_renders_standby_on_none_or_empty_snapshot() -> None:
    _app = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    widget = PathInspectorWidget(translator)
    widget.resize(600, 400)

    image = QImage(600, 400, QImage.Format.Format_RGB32)
    widget.render(image)

    # Empty snapshot at origin
    empty_snapshot = NavigationSnapshot(
        player_x=0.0,
        player_y=0.0,
        heading_degrees=0.0,
        cells=(),
        edges=(),
        waypoints=(),
        safe_waypoint=None,
    )
    widget.set_navigation(empty_snapshot)
    assert widget.snapshot == empty_snapshot

    image2 = QImage(600, 400, QImage.Format.Format_RGB32)
    widget.render(image2)


def test_widget_renders_populated_navigation_map() -> None:
    _app = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    widget = PathInspectorWidget(translator)
    widget.resize(640, 480)

    snapshot = _populated_snapshot()
    widget.set_navigation(snapshot)

    image = QImage(640, 480, QImage.Format.Format_RGB32)
    widget.render(image)

    # Switch to German
    widget.set_translator(Translator(Language.GERMAN))
    image_de = QImage(640, 480, QImage.Format.Format_RGB32)
    widget.render(image_de)


def test_viewport_transform_handles_zero_leash_and_wide_aspect() -> None:
    _app = QApplication.instance() or QApplication([])
    translator = Translator(Language.ENGLISH)
    widget = PathInspectorWidget(translator)
    widget.resize(800, 300)

    snapshot = NavigationSnapshot(
        player_x=100.0,
        player_y=-50.0,
        heading_degrees=270.0,
        cells=(
            CellSnapshot(
                x=2, y=-1, center_x=100.0, center_y=-50.0, visits=1, stalls=0, spawn_weight=1.0
            ),
        ),
        edges=(),
        waypoints=(),
        safe_waypoint=None,
        cell_size_units=40.0,
        leash_radius_units=0.0,
    )
    widget.set_navigation(snapshot)

    image = QImage(800, 300, QImage.Format.Format_RGB32)
    widget.render(image)


def test_spawn_heat_color_interpolation() -> None:
    low = PathInspectorWidget._spawn_heat_center_color(0.0)
    mid = PathInspectorWidget._spawn_heat_center_color(0.5)
    high = PathInspectorWidget._spawn_heat_center_color(1.0)

    assert isinstance(low, QColor)
    assert isinstance(mid, QColor)
    assert isinstance(high, QColor)
    assert low.alpha() > 0
    assert high.alpha() > low.alpha()

    edge_low = PathInspectorWidget._spawn_heat_edge_color(0.0)
    edge_high = PathInspectorWidget._spawn_heat_edge_color(1.0)
    assert isinstance(edge_low, QColor)
    assert isinstance(edge_high, QColor)
    assert edge_high.alpha() > edge_low.alpha()
