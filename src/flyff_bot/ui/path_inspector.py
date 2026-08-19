"""2D visual navigation path and spawn heatmap inspector widget."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from flyff_bot.features.navigation.live_position import PositionSource
from flyff_bot.features.navigation.tracking import TrackingQuality
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import NavigationSnapshot


def _with_alpha(color: QColor, alpha: int) -> QColor:
    """Return a copy of a palette color at a different opacity."""

    tinted = QColor(color)
    tinted.setAlpha(alpha)
    return tinted


def _lerp_color(low: QColor, high: QColor, intensity: float) -> QColor:
    """Blend two palette endpoints channel-wise by a clamped 0..1 intensity."""

    clamped = max(0.0, min(1.0, intensity))

    def channel(start: int, end: int) -> int:
        return round(start + (end - start) * clamped)

    return QColor(
        channel(low.red(), high.red()),
        channel(low.green(), high.green()),
        channel(low.blue(), high.blue()),
        channel(low.alpha(), high.alpha()),
    )


BG_COLOR = QColor(17, 20, 28)
GRID_LINE_COLOR = QColor(36, 44, 60, 140)
AXIS_COLOR = QColor(70, 85, 110, 180)
AXIS_TEXT_COLOR = QColor(100, 120, 150, 160)
LEASH_COLOR = QColor(80, 100, 130, 140)
EDGE_NORMAL_COLOR = QColor(24, 144, 255, 200)
EDGE_STALL_COLOR = QColor(255, 77, 79, 220)
NODE_COLOR = QColor(64, 169, 255)
MARKER_OUTLINE_COLOR = QColor(15, 23, 42)
ROUTE_COLOR = QColor(179, 127, 235, 240)
SAFE_NODE_COLOR = QColor(82, 196, 26)
SAFE_NODE_FILL_ALPHA = 160
SAFE_NODE_FILL_COLOR = _with_alpha(SAFE_NODE_COLOR, SAFE_NODE_FILL_ALPHA)
# Magenta, so the one place an emergency teleport lands cannot be confused with the green
# retreat waypoint or any of the learned graph colours (US-040).
SPAWN_POINT_COLOR = QColor(255, 85, 210)
SPAWN_POINT_FILL_ALPHA = 120
SPAWN_POINT_FILL_COLOR = _with_alpha(SPAWN_POINT_COLOR, SPAWN_POINT_FILL_ALPHA)
SPAWN_POINT_RADIUS_PIXELS = 7.0
SPAWN_POINT_PEN_WIDTH = 1.5
PLAYER_COLOR = QColor(0, 240, 255)
PLAYER_CONE_FILL_ALPHA = 30
PLAYER_CONE_EDGE_ALPHA = 60
PLAYER_CONE_COLOR = _with_alpha(PLAYER_COLOR, PLAYER_CONE_FILL_ALPHA)
PLAYER_CONE_EDGE_COLOR = _with_alpha(PLAYER_COLOR, PLAYER_CONE_EDGE_ALPHA)
PLAYER_ACCENT_COLOR = QColor(255, 255, 255)
STALL_MARKER_COLOR = QColor(255, 77, 79, 220)
STALL_FILL_ALPHA = 45
STALL_FILL_COLOR = _with_alpha(STALL_MARKER_COLOR, STALL_FILL_ALPHA)
VISITED_CELL_BORDER_COLOR = QColor(45, 55, 72, 80)
TRANSPARENT_COLOR = QColor(0, 0, 0, 0)
TEXT_COLOR = QColor(241, 245, 249)
MUTED_TEXT_COLOR = QColor(148, 163, 184)
HUD_BG_COLOR = QColor(15, 23, 42, 200)
HUD_BORDER_COLOR = QColor(51, 65, 85, 160)
HUD_ROW_HEIGHT_PIXELS = 24.0
HUD_MAXIMUM_WIDTH_PIXELS = 520.0
# Amber, so a patrol that is quietly shrinking against the leash reads as a warning rather
# than as another status figure.
LEASH_NOTICE_COLOR = QColor(250, 173, 20)
TERRAIN_LOW_COLOR = QColor(23, 55, 45, 150)
TERRAIN_HIGH_COLOR = QColor(118, 104, 53, 190)
ELEVATION_PROFILE_COLOR = QColor(134, 239, 172)
ELEVATION_STRIP_HEIGHT_PIXELS = 42.0

# Spawn density heat palette: translucent gold at sparse density up to dense ember red at
# hotspots. Every stop stays red-dominant so a heat cell can never be mistaken for the cyan
# player marker, the green safe waypoint, or the blue graph nodes and edges.
SPAWN_HEAT_BASE_COLOR = QColor(250, 140, 22)
SPAWN_HEAT_EDGE_LOW_ALPHA = 30
SPAWN_HEAT_CENTER_LOW_COLOR = QColor(255, 197, 61, 90)
SPAWN_HEAT_CENTER_HIGH_COLOR = QColor(255, 77, 21, 220)
SPAWN_HEAT_EDGE_LOW_COLOR = _with_alpha(SPAWN_HEAT_BASE_COLOR, SPAWN_HEAT_EDGE_LOW_ALPHA)
SPAWN_HEAT_EDGE_HIGH_COLOR = QColor(255, 60, 42, 80)
SPAWN_HEAT_RADIUS_FRACTION = 0.7
SPAWN_HEAT_EDGE_STOP = 0.8

# Legend entries pair each map element with the glyph and color it is actually drawn in, so a
# palette change can never leave the legend describing a different marker than the canvas shows.
LEGEND_ITEMS: tuple[tuple[str, QColor, Message], ...] = (
    ("▲", PLAYER_COLOR, Message.UI_NAV_LEGEND_PLAYER),
    ("●", SPAWN_HEAT_BASE_COLOR, Message.UI_NAV_LEGEND_SPAWN),
    ("━", EDGE_NORMAL_COLOR, Message.UI_NAV_LEGEND_PATH),
    ("⛝", STALL_MARKER_COLOR, Message.UI_NAV_LEGEND_OBSTACLE),
    ("━", ROUTE_COLOR, Message.UI_NAV_LEGEND_ROUTE),
    ("◆", SAFE_NODE_COLOR, Message.UI_NAV_LEGEND_SAFE),
    ("✚", SPAWN_POINT_COLOR, Message.UI_NAV_LEGEND_SPAWN_POINT),
)

PADDING_FRACTION = 0.2
MINIMUM_VIEW_EXTENT = 50.0
WIDGET_MIN_WIDTH = 360
WIDGET_MIN_HEIGHT = 280
GRID_STEP_UNITS = 20.0
FOV_DEGREES = 60.0
FOV_DISTANCE_UNITS = 25.0


class PathInspectorWidget(QWidget):
    """Render a 2D top-down navigation mesh, spawn heatmap, and active route."""

    def __init__(
        self,
        translator: Translator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator
        self._snapshot: NavigationSnapshot | None = None
        self.setMinimumSize(WIDGET_MIN_WIDTH, WIDGET_MIN_HEIGHT)

    @property
    def snapshot(self) -> NavigationSnapshot | None:
        """Return the currently rendered navigation snapshot."""

        return self._snapshot

    def set_navigation(self, snapshot: NavigationSnapshot | None) -> None:
        """Update the rendered navigation snapshot and trigger a repaint."""

        self._snapshot = snapshot
        self.update()

    def set_translator(self, translator: Translator) -> None:
        """Update the translator instance and repaint localized labels."""

        self._translator = translator
        self.update()

    def sizeHint(self) -> QSize:
        """Provide a default proportional size hint for dashboard layouts."""

        return QSize(540, 360)

    def paintEvent(self, _event: object) -> None:
        """Draw the 2D coordinate grid, spawn heatmap, edges, route, and player marker."""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = self.width()
        height = self.height()

        painter.fillRect(0, 0, width, height, BG_COLOR)

        if self._snapshot is None or (
            not self._snapshot.cells
            and not self._snapshot.terrain_samples
            and self._snapshot.world_position is None
            and self._snapshot.player_x == 0.0
            and self._snapshot.player_y == 0.0
        ):
            self._draw_standby_message(painter, width, height)
            painter.end()
            return

        scale, offset_x, offset_y, min_x, max_x, min_y, max_y = self._calculate_viewport_transform(
            width, height
        )

        def to_screen(wx: float, wy: float) -> QPointF:
            return QPointF(offset_x + wx * scale, offset_y - wy * scale)

        self._draw_grid_and_axes(
            painter, width, height, to_screen, min_x, max_x, min_y, max_y, scale
        )
        self._draw_terrain(painter, to_screen, scale)
        self._draw_leash_boundary(painter, to_screen)
        self._draw_heatmap_cells(painter, to_screen, scale)
        self._draw_graph_edges(painter, to_screen)
        self._draw_active_route(painter, to_screen)
        self._draw_safe_waypoint(painter, to_screen)
        self._draw_spawn_point(painter, to_screen)
        self._draw_player_marker(painter, to_screen, scale)
        self._draw_elevation_profile(painter, width, height)
        self._draw_overlay_hud(painter, width)
        self._draw_legend(painter, width, height)
        painter.end()

    def _calculate_viewport_transform(
        self, width: int, height: int
    ) -> tuple[float, float, float, float, float, float, float]:
        snapshot = self._snapshot
        assert snapshot is not None

        live_world = snapshot.position_source is PositionSource.LIVE
        xs: list[float] = [snapshot.player_x]
        ys: list[float] = [snapshot.player_y]
        if not live_world:
            xs.append(0.0)
            ys.append(0.0)
            leash = max(MINIMUM_VIEW_EXTENT, snapshot.leash_radius_pixels)
            xs.extend([-leash, leash])
            ys.extend([-leash, leash])

        for cell in snapshot.cells:
            cell_size = snapshot.cell_size_pixels
            xs.extend([cell.center_x - cell_size, cell.center_x + cell_size])
            ys.extend([cell.center_y - cell_size, cell.center_y + cell_size])

        for wx, wy in snapshot.waypoints:
            xs.append(wx)
            ys.append(wy)

        if live_world:
            for terrain_x, _height, terrain_z in snapshot.terrain_samples:
                xs.append(terrain_x)
                ys.append(terrain_z)

        if snapshot.safe_waypoint is not None:
            xs.append(snapshot.safe_waypoint[0])
            ys.append(snapshot.safe_waypoint[1])

        if snapshot.spawn_point is not None:
            xs.append(snapshot.spawn_point[0])
            ys.append(snapshot.spawn_point[1])

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        span_x = max(MINIMUM_VIEW_EXTENT * 2.0, (max_x - min_x) * (1.0 + PADDING_FRACTION))
        span_y = max(MINIMUM_VIEW_EXTENT * 2.0, (max_y - min_y) * (1.0 + PADDING_FRACTION))

        center_world_x = (min_x + max_x) / 2.0
        center_world_y = (min_y + max_y) / 2.0

        avail_w = max(10, width - 40)
        avail_h = max(10, height - 85)
        scale = min(avail_w / span_x, avail_h / span_y)

        screen_center_x = width / 2.0 - center_world_x * scale
        screen_center_y = (height - 35) / 2.0 + center_world_y * scale

        return scale, screen_center_x, screen_center_y, min_x, max_x, min_y, max_y

    def _draw_standby_message(self, painter: QPainter, width: int, height: int) -> None:
        painter.setPen(QPen(MUTED_TEXT_COLOR))
        font = QFont("", 11)
        painter.setFont(font)
        text = self._translator.text(Message.UI_PATH_INSPECTOR_STANDBY)
        painter.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_grid_and_axes(
        self,
        painter: QPainter,
        width: int,
        height: int,
        to_screen: Callable[[float, float], QPointF],
        min_x: float,
        max_x: float,
        min_y: float,
        max_y: float,
        scale: float,
    ) -> None:
        start_x = math.floor(min_x / GRID_STEP_UNITS) * GRID_STEP_UNITS
        end_x = math.ceil(max_x / GRID_STEP_UNITS) * GRID_STEP_UNITS
        start_y = math.floor(min_y / GRID_STEP_UNITS) * GRID_STEP_UNITS
        end_y = math.ceil(max_y / GRID_STEP_UNITS) * GRID_STEP_UNITS

        painter.setFont(QFont("", 7))

        gx = start_x
        while gx <= end_x:
            if abs(gx) > 0.1:
                pt_top = to_screen(gx, max_y + 10.0)
                pt_bottom = to_screen(gx, min_y - 10.0)
                painter.setPen(QPen(GRID_LINE_COLOR, 1, Qt.PenStyle.DashLine))
                painter.drawLine(
                    QPointF(pt_top.x(), 0),
                    QPointF(pt_bottom.x(), float(height)),
                )
                if scale > 1.2:
                    painter.setPen(QPen(AXIS_TEXT_COLOR))
                    painter.drawText(
                        QPointF(pt_top.x() + 2, float(height) - 30),
                        f"{gx:+.0f}m",
                    )
            gx += GRID_STEP_UNITS

        gy = start_y
        while gy <= end_y:
            if abs(gy) > 0.1:
                pt_left = to_screen(min_x - 10.0, gy)
                pt_right = to_screen(max_x + 10.0, gy)
                painter.setPen(QPen(GRID_LINE_COLOR, 1, Qt.PenStyle.DashLine))
                painter.drawLine(
                    QPointF(0, pt_left.y()),
                    QPointF(float(width), pt_right.y()),
                )
                if scale > 1.2:
                    painter.setPen(QPen(AXIS_TEXT_COLOR))
                    painter.drawText(
                        QPointF(10, pt_left.y() - 2),
                        f"{gy:+.0f}m",
                    )
            gy += GRID_STEP_UNITS

        origin = to_screen(0.0, 0.0)
        painter.setPen(QPen(AXIS_COLOR, 1, Qt.PenStyle.SolidLine))
        painter.drawLine(QPointF(0, origin.y()), QPointF(width, origin.y()))
        painter.drawLine(QPointF(origin.x(), 0), QPointF(origin.x(), height))

        painter.setPen(QPen(AXIS_TEXT_COLOR))
        painter.drawText(QPointF(origin.x() + 4, 18), "N (0°)")

    def _draw_leash_boundary(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None
        if snapshot.position_source is PositionSource.LIVE or snapshot.leash_radius_pixels <= 0.0:
            return

        origin = to_screen(0.0, 0.0)
        radius_px = abs(to_screen(snapshot.leash_radius_pixels, 0.0).x() - origin.x())
        painter.setPen(QPen(LEASH_COLOR, 1, Qt.PenStyle.DotLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(origin, radius_px, radius_px)

    def _draw_terrain(
        self,
        painter: QPainter,
        to_screen: Callable[[float, float], QPointF],
        scale: float,
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None
        samples = snapshot.terrain_samples
        if not samples:
            return
        minimum = min(sample[1] for sample in samples)
        maximum = max(sample[1] for sample in samples)
        height_span = max(1.0, maximum - minimum)
        sample_size = max(2.0, GRID_STEP_UNITS * scale * 0.4)
        painter.setPen(Qt.PenStyle.NoPen)
        for world_x, height, world_z in samples:
            point = to_screen(world_x, world_z)
            painter.setBrush(
                QBrush(
                    _lerp_color(
                        TERRAIN_LOW_COLOR, TERRAIN_HIGH_COLOR, (height - minimum) / height_span
                    )
                )
            )
            painter.drawRect(
                QRectF(
                    point.x() - sample_size / 2.0,
                    point.y() - sample_size / 2.0,
                    sample_size,
                    sample_size,
                )
            )

    def _draw_heatmap_cells(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF], scale: float
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None

        max_weight = max((c.spawn_weight for c in snapshot.cells), default=1.0)
        max_weight = max(1.0, max_weight)
        cell_size_px = snapshot.cell_size_pixels * scale

        for cell in snapshot.cells:
            pt = to_screen(cell.center_x, cell.center_y)
            rect = QRectF(
                pt.x() - cell_size_px / 2.0,
                pt.y() - cell_size_px / 2.0,
                cell_size_px,
                cell_size_px,
            )

            if cell.spawn_weight > 0.0:
                intensity = min(1.0, cell.spawn_weight / max_weight)
                heat_radius_px = cell_size_px * SPAWN_HEAT_RADIUS_FRACTION
                gradient = QRadialGradient(pt, heat_radius_px)
                gradient.setColorAt(0.0, self._spawn_heat_center_color(intensity))
                gradient.setColorAt(SPAWN_HEAT_EDGE_STOP, self._spawn_heat_edge_color(intensity))
                gradient.setColorAt(1.0, TRANSPARENT_COLOR)

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(gradient))
                painter.drawEllipse(pt, heat_radius_px, heat_radius_px)
            else:
                painter.setPen(QPen(VISITED_CELL_BORDER_COLOR, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)

            if cell.stalls > 0:
                painter.setPen(QPen(STALL_MARKER_COLOR, 1.5, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(STALL_FILL_COLOR))
                painter.drawRect(rect)
                painter.drawLine(rect.topLeft(), rect.bottomRight())
                painter.drawLine(rect.topRight(), rect.bottomLeft())

    def _draw_graph_edges(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None

        for edge in snapshot.edges:
            p1 = to_screen(edge.origin_x, edge.origin_y)
            p2 = to_screen(edge.destination_x, edge.destination_y)
            if edge.stalls > 0:
                painter.setPen(QPen(EDGE_STALL_COLOR, 2, Qt.PenStyle.DashLine))
            else:
                painter.setPen(QPen(EDGE_NORMAL_COLOR, 1.5))
            painter.drawLine(p1, p2)

        painter.setPen(QPen(MARKER_OUTLINE_COLOR, 1))
        painter.setBrush(QBrush(NODE_COLOR))
        for cell in snapshot.cells:
            pt = to_screen(cell.center_x, cell.center_y)
            painter.drawEllipse(pt, 3.5, 3.5)

    def _draw_active_route(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None
        if not snapshot.waypoints:
            return

        points = [to_screen(snapshot.player_x, snapshot.player_y)]
        for wx, wy in snapshot.waypoints:
            points.append(to_screen(wx, wy))

        path = QPainterPath()
        path.moveTo(points[0])
        for p in points[1:]:
            path.lineTo(p)

        painter.setPen(
            QPen(
                ROUTE_COLOR,
                3,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setBrush(QBrush(ROUTE_COLOR))
        for waypoint in snapshot.world_waypoints:
            painter.drawEllipse(to_screen(waypoint.x, waypoint.z), 4.0, 4.0)

    def _draw_elevation_profile(self, painter: QPainter, width: int, height: int) -> None:
        snapshot = self._snapshot
        assert snapshot is not None
        if not snapshot.world_waypoints:
            return
        positions = (
            (snapshot.world_position,) if snapshot.world_position is not None else ()
        ) + snapshot.world_waypoints
        if len(positions) < 2:
            return
        minimum = min(position.y for position in positions)
        maximum = max(position.y for position in positions)
        span = max(1.0, maximum - minimum)
        left = 12.0
        right = float(width) - 12.0
        bottom = float(height) - 26.0
        top = bottom - ELEVATION_STRIP_HEIGHT_PIXELS
        painter.setPen(QPen(HUD_BORDER_COLOR, 1))
        painter.setBrush(QBrush(HUD_BG_COLOR))
        painter.drawRect(QRectF(left, top, right - left, bottom - top))
        path = QPainterPath()
        for index, position in enumerate(positions):
            x = left + index / (len(positions) - 1) * (right - left)
            y = bottom - (position.y - minimum) / span * (bottom - top)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(ELEVATION_PROFILE_COLOR, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setFont(QFont("", 7))
        painter.drawText(
            QRectF(left + 4.0, top, right - left, 14.0),
            self._translator.text(Message.UI_NAV_ELEVATION_PROFILE),
        )

    def _draw_safe_waypoint(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None
        if snapshot.safe_waypoint is None:
            return

        pt = to_screen(snapshot.safe_waypoint[0], snapshot.safe_waypoint[1])
        painter.setPen(QPen(SAFE_NODE_COLOR, 1.5))
        painter.setBrush(QBrush(SAFE_NODE_FILL_COLOR))
        diamond = QPolygonF(
            [
                QPointF(pt.x(), pt.y() - 6),
                QPointF(pt.x() + 6, pt.y()),
                QPointF(pt.x(), pt.y() + 6),
                QPointF(pt.x() - 6, pt.y()),
            ]
        )
        painter.drawPolygon(diamond)

    def _draw_spawn_point(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        """Mark the anchor an emergency teleport returns the character to (US-040)."""

        snapshot = self._snapshot
        assert snapshot is not None
        if snapshot.spawn_point is None:
            return

        pt = to_screen(snapshot.spawn_point[0], snapshot.spawn_point[1])
        painter.setPen(QPen(SPAWN_POINT_COLOR, SPAWN_POINT_PEN_WIDTH))
        painter.setBrush(QBrush(SPAWN_POINT_FILL_COLOR))
        painter.drawEllipse(pt, SPAWN_POINT_RADIUS_PIXELS, SPAWN_POINT_RADIUS_PIXELS)
        painter.drawLine(
            QPointF(pt.x() - SPAWN_POINT_RADIUS_PIXELS, pt.y()),
            QPointF(pt.x() + SPAWN_POINT_RADIUS_PIXELS, pt.y()),
        )
        painter.drawLine(
            QPointF(pt.x(), pt.y() - SPAWN_POINT_RADIUS_PIXELS),
            QPointF(pt.x(), pt.y() + SPAWN_POINT_RADIUS_PIXELS),
        )

    def _draw_player_marker(
        self,
        painter: QPainter,
        to_screen: Callable[[float, float], QPointF],
        scale: float,
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None

        pt = to_screen(snapshot.player_x, snapshot.player_y)
        heading_rad = math.radians(snapshot.heading_degrees)
        dx = math.sin(heading_rad)
        dy = math.cos(heading_rad)

        fov_dist_px = FOV_DISTANCE_UNITS * scale
        half_fov_rad = math.radians(FOV_DEGREES / 2.0)
        left_angle = heading_rad - half_fov_rad
        right_angle = heading_rad + half_fov_rad

        cone_left = QPointF(
            pt.x() + math.sin(left_angle) * fov_dist_px,
            pt.y() - math.cos(left_angle) * fov_dist_px,
        )
        cone_right = QPointF(
            pt.x() + math.sin(right_angle) * fov_dist_px,
            pt.y() - math.cos(right_angle) * fov_dist_px,
        )

        cone_path = QPainterPath()
        cone_path.moveTo(pt)
        cone_path.lineTo(cone_left)
        cone_path.lineTo(cone_right)
        cone_path.closeSubpath()

        painter.setPen(QPen(PLAYER_CONE_EDGE_COLOR, 1, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(PLAYER_CONE_COLOR))
        painter.drawPath(cone_path)

        size = 9.0
        front = QPointF(pt.x() + dx * size * 1.6, pt.y() - dy * size * 1.6)
        left = QPointF(pt.x() - dy * size - dx * size * 0.5, pt.y() - dx * size + dy * size * 0.5)
        right = QPointF(pt.x() + dy * size - dx * size * 0.5, pt.y() + dx * size + dy * size * 0.5)

        painter.setPen(QPen(PLAYER_ACCENT_COLOR, 1.5))
        painter.setBrush(QBrush(PLAYER_COLOR))
        painter.drawPolygon(QPolygonF([front, left, pt, right]))

        painter.setPen(QPen(MARKER_OUTLINE_COLOR, 1.5))
        painter.setBrush(QBrush(PLAYER_ACCENT_COLOR))
        painter.drawEllipse(pt, 3.5, 3.5)

    def _draw_overlay_hud(self, painter: QPainter, width: int) -> None:
        snapshot = self._snapshot
        assert snapshot is not None

        compass = _heading_to_compass(snapshot.heading_degrees)
        hud_w = min(float(width - 20), HUD_MAXIMUM_WIDTH_PIXELS)
        rows: list[tuple[str, QColor]] = [
            (
                f"Pos: ({snapshot.player_x:+.1f}, {snapshot.player_y:+.1f})  "
                f"Facing: {snapshot.heading_degrees:.0f}° ({compass})  "
                f"Cells: {len(snapshot.cells)}  "
                f"Route: {len(snapshot.waypoints)}  "
                f"{self._translator.text(_tracking_quality_message(snapshot.tracking_quality))}",
                TEXT_COLOR,
            )
        ]
        if snapshot.hotspots_outside_leash > 0:
            # The status row is already close to its width budget, so the leash notice gets a
            # row of its own instead of being appended and silently clipped away.
            rows.append(
                (
                    self._translator.text(
                        Message.UI_NAV_LEASH_SKIPPED, count=snapshot.hotspots_outside_leash
                    ),
                    LEASH_NOTICE_COLOR,
                )
            )

        hud_rect = QRectF(10, 8, hud_w, HUD_ROW_HEIGHT_PIXELS * len(rows))
        painter.setPen(QPen(HUD_BORDER_COLOR, 1))
        painter.setBrush(QBrush(HUD_BG_COLOR))
        painter.drawRoundedRect(hud_rect, 4.0, 4.0)

        painter.setFont(QFont("", 8))
        for index, (line, color) in enumerate(rows):
            painter.setPen(QPen(color))
            painter.drawText(
                QRectF(16, 8 + index * HUD_ROW_HEIGHT_PIXELS, hud_w - 12, HUD_ROW_HEIGHT_PIXELS),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                line,
            )

    def _draw_legend(self, painter: QPainter, width: int, height: int) -> None:
        legend_y = height - 22
        painter.setFont(QFont("", 8))

        cur_x = 10.0
        for symbol, color, msg in LEGEND_ITEMS:
            painter.setPen(QPen(color))
            painter.drawText(QPointF(cur_x, legend_y + 12), symbol)
            cur_x += painter.fontMetrics().horizontalAdvance(symbol) + 4

            label = self._translator.text(msg)
            painter.setPen(QPen(MUTED_TEXT_COLOR))
            painter.drawText(QPointF(cur_x, legend_y + 12), label)
            cur_x += painter.fontMetrics().horizontalAdvance(label) + 10
            if cur_x > width - 30:
                break

    @staticmethod
    def _spawn_heat_center_color(intensity: float) -> QColor:
        """Return the hot core color of a spawn cell at the given relative density."""

        return _lerp_color(SPAWN_HEAT_CENTER_LOW_COLOR, SPAWN_HEAT_CENTER_HIGH_COLOR, intensity)

    @staticmethod
    def _spawn_heat_edge_color(intensity: float) -> QColor:
        """Return the fading rim color of a spawn cell at the given relative density."""

        return _lerp_color(SPAWN_HEAT_EDGE_LOW_COLOR, SPAWN_HEAT_EDGE_HIGH_COLOR, intensity)


def _tracking_quality_message(quality: TrackingQuality) -> Message:
    return {
        TrackingQuality.MEASURED: Message.UI_TRACKING_MEASURED,
        TrackingQuality.PREDICTED: Message.UI_TRACKING_PREDICTED,
        TrackingQuality.DEGRADED: Message.UI_TRACKING_DEGRADED,
    }[quality]


def _heading_to_compass(heading: float) -> str:
    norm = (heading % 360.0 + 360.0) % 360.0
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = int((norm + 22.5) / 45.0) % 8
    return directions[index]
