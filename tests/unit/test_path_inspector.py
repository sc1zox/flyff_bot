"""Tests for the 2D visual navigation path and spawn heatmap inspector widget."""

from __future__ import annotations

import math
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from flyff_bot.features.navigation.live_position import PositionSource, WorldPosition
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.dashboard import (
    CellSnapshot,
    EdgeSnapshot,
    NavigationSnapshot,
)
from flyff_bot.ui.path_inspector import (
    BG_COLOR,
    EDGE_NORMAL_COLOR,
    LEGEND_ITEMS,
    NODE_COLOR,
    PLAYER_COLOR,
    ROUTE_COLOR,
    SAFE_NODE_COLOR,
    SPAWN_HEAT_BASE_COLOR,
    SPAWN_HEAT_EDGE_LOW_COLOR,
    VISITED_CELL_BORDER_COLOR,
    WIDGET_MIN_HEIGHT,
    WIDGET_MIN_WIDTH,
    PathInspectorWidget,
)

# Colors reserved for non-heat map elements; no spawn heat stop may reuse any of them.
MARKER_COLORS = (PLAYER_COLOR, SAFE_NODE_COLOR, NODE_COLOR, EDGE_NORMAL_COLOR)
INTENSITY_SWEEP = (0.0, 0.25, 0.5, 0.75, 1.0)
SUBTLE_BORDER_MAX_ALPHA = 128
# Sample the arrow body ahead of the white centroid dot, and the heat gradient clear of the
# blue graph node drawn on top of the cell center.
PLAYER_BODY_SAMPLE_OFFSET_PIXELS = 7
HEAT_SAMPLE_RADIUS_FRACTION = 0.12
# Sample the stall cross a quarter cell out from the centre, between the blue node dot and the
# cell border.
STALL_DIAGONAL_SAMPLE_FRACTION = 0.25
# How much brighter than the canvas background a dotted leash-ring sample must read.
LEASH_RING_BRIGHTNESS_MARGIN = 20


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
        cell_size_pixels=40.0,
        leash_radius_pixels=60.0,
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


def test_widget_renders_live_topography_3d_waypoints_and_elevation_profile() -> None:
    _app = QApplication.instance() or QApplication([])
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    widget.resize(600, 400)
    snapshot = NavigationSnapshot(
        player_x=10.0,
        player_y=10.0,
        heading_degrees=30.0,
        cells=(),
        edges=(),
        waypoints=((20.0, 20.0), (30.0, 25.0)),
        position_source=PositionSource.LIVE,
        world_position=WorldPosition(10.0, 100.0, 10.0),
        world_waypoints=(
            WorldPosition(20.0, 104.0, 20.0),
            WorldPosition(30.0, 98.0, 25.0),
        ),
        terrain_samples=(
            (0.0, 90.0, 0.0),
            (20.0, 100.0, 20.0),
            (40.0, 110.0, 40.0),
        ),
    )
    widget.set_navigation(snapshot)

    image = QImage(600, 400, QImage.Format.Format_RGB32)
    widget.render(image)

    assert widget.snapshot == snapshot
    assert not image.isNull()

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
        cell_size_pixels=40.0,
        leash_radius_pixels=0.0,
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


def test_spawn_heat_palette_stays_warm_and_never_reuses_a_marker_color() -> None:
    """BUG-004: heat cells must read as gold-to-red and never as the green player badge."""

    marker_rgbs = {(color.red(), color.green(), color.blue()) for color in MARKER_COLORS}

    for intensity in INTENSITY_SWEEP:
        center = PathInspectorWidget._spawn_heat_center_color(intensity)
        edge = PathInspectorWidget._spawn_heat_edge_color(intensity)
        for heat in (center, edge):
            assert heat.red() > heat.green() > heat.blue()
            assert (heat.red(), heat.green(), heat.blue()) not in marker_rgbs

    dense = PathInspectorWidget._spawn_heat_center_color(1.0)
    sparse = PathInspectorWidget._spawn_heat_center_color(0.0)
    assert dense.green() < sparse.green()


def test_legend_pairs_distinct_glyphs_with_the_colors_actually_drawn() -> None:
    glyphs = [glyph for glyph, _color, _message in LEGEND_ITEMS]
    colors = {message: color for _glyph, color, message in LEGEND_ITEMS}
    messages = [message for _glyph, _color, message in LEGEND_ITEMS]

    assert len(messages) == len(set(messages))
    assert "▲" in glyphs
    assert len(set(glyphs)) > 1

    player_color = colors[Message.UI_NAV_LEGEND_PLAYER]
    spawn_color = colors[Message.UI_NAV_LEGEND_SPAWN]
    assert player_color.rgb() == PLAYER_COLOR.rgb()
    assert spawn_color.rgb() == SPAWN_HEAT_BASE_COLOR.rgb()
    assert spawn_color.rgb() != player_color.rgb()
    # The legend swatch and the sparse end of the heat gradient share one base color, so the
    # legend cannot drift away from what the canvas paints.
    assert spawn_color.rgb() == SPAWN_HEAT_EDGE_LOW_COLOR.rgb()


def test_visited_cells_use_a_subtle_border_instead_of_a_player_colored_fill() -> None:
    assert VISITED_CELL_BORDER_COLOR.alpha() < SUBTLE_BORDER_MAX_ALPHA
    assert VISITED_CELL_BORDER_COLOR.rgb() != PLAYER_COLOR.rgb()
    assert VISITED_CELL_BORDER_COLOR.rgb() != SAFE_NODE_COLOR.rgb()
    assert VISITED_CELL_BORDER_COLOR.rgb() != ROUTE_COLOR.rgb()


def test_rendered_stall_cell_route_and_safe_waypoint_are_readable() -> None:
    """BUG-009: obstacle cells, the planned route, and the retreat anchor must be readable."""

    _app = QApplication.instance() or QApplication([])
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    width, height = 640, 480
    widget.resize(width, height)

    # The stalled cell carries no spawn weight, so a red-dominant pixel can only come from the
    # stall marker itself and not from the warm spawn heat gradient. Nothing else is placed on the
    # leash radius or on the straight route leg the assertions sample.
    snapshot = NavigationSnapshot(
        player_x=-60.0,
        player_y=-60.0,
        heading_degrees=0.0,
        cells=(
            CellSnapshot(
                x=1, y=1, center_x=60.0, center_y=60.0, visits=2, stalls=3, spawn_weight=0.0
            ),
        ),
        edges=(),
        waypoints=((-60.0, 20.0),),
        safe_waypoint=(0.0, 60.0),
        cell_size_pixels=40.0,
        leash_radius_pixels=45.0,
    )
    widget.set_navigation(snapshot)

    image = QImage(width, height, QImage.Format.Format_RGB32)
    widget.render(image)

    scale, offset_x, offset_y = widget._calculate_viewport_transform(width, height)[:3]

    def to_screen(world_x: float, world_y: float) -> tuple[int, int]:
        return round(offset_x + world_x * scale), round(offset_y - world_y * scale)

    cell = snapshot.cells[0]
    cell_x, cell_y = to_screen(cell.center_x, cell.center_y)
    # Sample along the marker's diagonal cross, clear of the blue graph node at the cell centre.
    diagonal_offset = round(snapshot.cell_size_pixels * scale * STALL_DIAGONAL_SAMPLE_FRACTION)
    stall_pixel = image.pixelColor(cell_x + diagonal_offset, cell_y + diagonal_offset)

    assert stall_pixel.red() > stall_pixel.green()
    assert stall_pixel.red() > stall_pixel.blue()

    assert snapshot.safe_waypoint is not None
    safe_pixel = image.pixelColor(*to_screen(*snapshot.safe_waypoint))

    assert safe_pixel.green() > safe_pixel.red()
    assert safe_pixel.green() > safe_pixel.blue()

    # The route leg runs straight up from the player to its single waypoint, so its midpoint
    # carries the purple polyline and nothing else.
    route_x, route_y = to_screen(
        snapshot.player_x, (snapshot.player_y + snapshot.waypoints[0][1]) / 2.0
    )
    route_pixel = image.pixelColor(route_x, route_y)

    assert route_pixel.blue() > route_pixel.red() > route_pixel.green()

    # The leash ring is dotted, so at least one sample around it must be brighter than the
    # background it is drawn on.
    ring_samples = [
        image.pixelColor(
            *to_screen(
                snapshot.leash_radius_pixels * math.cos(math.radians(degrees)),
                snapshot.leash_radius_pixels * math.sin(math.radians(degrees)),
            )
        )
        for degrees in range(0, 360, 5)
    ]

    assert any(
        pixel.blue() > BG_COLOR.blue() + LEASH_RING_BRIGHTNESS_MARGIN for pixel in ring_samples
    )


def test_rendered_player_marker_and_spawn_cell_are_visually_distinguishable() -> None:
    _app = QApplication.instance() or QApplication([])
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    width, height = 640, 480
    widget.resize(width, height)

    snapshot = NavigationSnapshot(
        player_x=-60.0,
        player_y=-60.0,
        heading_degrees=0.0,
        cells=(
            CellSnapshot(
                x=1, y=1, center_x=60.0, center_y=60.0, visits=4, stalls=0, spawn_weight=9.0
            ),
        ),
        edges=(),
        waypoints=(),
        safe_waypoint=None,
        cell_size_pixels=40.0,
        leash_radius_pixels=0.0,
    )
    widget.set_navigation(snapshot)

    image = QImage(width, height, QImage.Format.Format_RGB32)
    widget.render(image)

    scale, offset_x, offset_y = widget._calculate_viewport_transform(width, height)[:3]

    def to_screen(world_x: float, world_y: float) -> tuple[int, int]:
        return round(offset_x + world_x * scale), round(offset_y - world_y * scale)

    player_x, player_y = to_screen(snapshot.player_x, snapshot.player_y)
    player_pixel = image.pixelColor(player_x, player_y - PLAYER_BODY_SAMPLE_OFFSET_PIXELS)

    cell = snapshot.cells[0]
    cell_x, cell_y = to_screen(cell.center_x, cell.center_y)
    heat_offset = round(snapshot.cell_size_pixels * scale * HEAT_SAMPLE_RADIUS_FRACTION)
    heat_pixel = image.pixelColor(cell_x + heat_offset, cell_y - heat_offset)

    # The player body is cyan: blue and green dominate red.
    assert player_pixel.blue() > player_pixel.red()
    assert player_pixel.green() > player_pixel.red()
    # A dense spawn cell is ember red: red dominates both other channels.
    assert heat_pixel.red() > heat_pixel.green()
    assert heat_pixel.red() > heat_pixel.blue()


# The status HUD strip drawn at the top of the canvas, in widget coordinates.
HUD_SAMPLE_TOP_PIXEL = 8
HUD_SAMPLE_BOTTOM_PIXEL = 56


def _hud_ink(image: QImage, width: int) -> int:
    """Count the pixels the status HUD paints over its own background."""

    background = QColor(image.pixel(width - 2, HUD_SAMPLE_TOP_PIXEL + 2)).rgb()
    return sum(
        1
        for y in range(HUD_SAMPLE_TOP_PIXEL, HUD_SAMPLE_BOTTOM_PIXEL)
        for x in range(width)
        if QColor(image.pixel(x, y)).rgb() != background
    )


def test_hotspots_skipped_by_the_leash_are_visible_in_the_status_hud() -> None:
    _app = QApplication.instance() or QApplication([])
    widget = PathInspectorWidget(Translator(Language.ENGLISH))
    widget.resize(640, 480)

    widget.set_navigation(_populated_snapshot())
    without = QImage(640, 480, QImage.Format.Format_RGB32)
    widget.render(without)

    widget.set_navigation(replace(_populated_snapshot(), hotspots_outside_leash=3))
    with_skipped = QImage(640, 480, QImage.Format.Format_RGB32)
    widget.render(with_skipped)

    assert _hud_ink(with_skipped, 640) > _hud_ink(without, 640)
