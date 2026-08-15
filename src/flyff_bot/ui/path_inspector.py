"""2D visual navigation path and spawn heatmap inspector widget."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import NavigationSnapshot

BG_COLOR = QColor(22, 25, 34)
GRID_LINE_COLOR = QColor(45, 55, 72, 100)
AXIS_COLOR = QColor(74, 85, 104, 180)
LEASH_COLOR = QColor(100, 116, 139, 150)
EDGE_NORMAL_COLOR = QColor(64, 150, 255, 180)
EDGE_STALL_COLOR = QColor(245, 34, 45, 200)
NODE_COLOR = QColor(105, 192, 255)
ROUTE_COLOR = QColor(179, 127, 235, 220)
SAFE_NODE_COLOR = QColor(82, 196, 26)
PLAYER_COLOR = QColor(82, 196, 26)
PLAYER_ACCENT_COLOR = QColor(255, 255, 255)
STALL_MARKER_COLOR = QColor(245, 34, 45, 220)
TEXT_COLOR = QColor(226, 232, 240)
MUTED_TEXT_COLOR = QColor(148, 163, 184)

PADDING_FRACTION = 0.2
MINIMUM_VIEW_EXTENT = 60.0
WIDGET_MIN_WIDTH = 360
WIDGET_MIN_HEIGHT = 280


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
            and self._snapshot.player_x == 0.0
            and self._snapshot.player_y == 0.0
        ):
            self._draw_standby_message(painter, width, height)
            painter.end()
            return

        scale, offset_x, offset_y = self._calculate_viewport_transform(width, height)

        def to_screen(wx: float, wy: float) -> QPointF:
            return QPointF(offset_x + wx * scale, offset_y - wy * scale)

        self._draw_grid_and_axes(painter, width, height, to_screen)
        self._draw_leash_boundary(painter, to_screen)
        self._draw_heatmap_cells(painter, to_screen, scale)
        self._draw_graph_edges(painter, to_screen)
        self._draw_active_route(painter, to_screen)
        self._draw_safe_waypoint(painter, to_screen)
        self._draw_player_marker(painter, to_screen)
        self._draw_overlay_hud(painter, width, height)
        painter.end()

    def _calculate_viewport_transform(self, width: int, height: int) -> tuple[float, float, float]:
        snapshot = self._snapshot
        assert snapshot is not None

        xs: list[float] = [0.0, snapshot.player_x]
        ys: list[float] = [0.0, snapshot.player_y]
        leash = max(MINIMUM_VIEW_EXTENT, snapshot.leash_radius_units)
        xs.extend([-leash, leash])
        ys.extend([-leash, leash])

        for cell in snapshot.cells:
            xs.extend(
                [cell.center_x - snapshot.cell_size_units, cell.center_x + snapshot.cell_size_units]
            )
            ys.extend(
                [cell.center_y - snapshot.cell_size_units, cell.center_y + snapshot.cell_size_units]
            )

        for wx, wy in snapshot.waypoints:
            xs.append(wx)
            ys.append(wy)

        if snapshot.safe_waypoint is not None:
            xs.append(snapshot.safe_waypoint[0])
            ys.append(snapshot.safe_waypoint[1])

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        span_x = max(MINIMUM_VIEW_EXTENT * 2.0, (max_x - min_x) * (1.0 + PADDING_FRACTION))
        span_y = max(MINIMUM_VIEW_EXTENT * 2.0, (max_y - min_y) * (1.0 + PADDING_FRACTION))

        center_world_x = (min_x + max_x) / 2.0
        center_world_y = (min_y + max_y) / 2.0

        avail_w = max(10, width - 40)
        avail_h = max(10, height - 70)
        scale = min(avail_w / span_x, avail_h / span_y)

        screen_center_x = width / 2.0 - center_world_x * scale
        screen_center_y = (height - 30) / 2.0 + center_world_y * scale

        return scale, screen_center_x, screen_center_y

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
    ) -> None:
        origin = to_screen(0.0, 0.0)
        painter.setPen(QPen(AXIS_COLOR, 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(0, origin.y()), QPointF(width, origin.y()))
        painter.drawLine(QPointF(origin.x(), 0), QPointF(origin.x(), height))

    def _draw_leash_boundary(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None
        if snapshot.leash_radius_units <= 0.0:
            return

        origin = to_screen(0.0, 0.0)
        radius_px = abs(to_screen(snapshot.leash_radius_units, 0.0).x() - origin.x())
        painter.setPen(QPen(LEASH_COLOR, 1, Qt.PenStyle.DotLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(origin, radius_px, radius_px)

    def _draw_heatmap_cells(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF], scale: float
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None

        max_weight = max((c.spawn_weight for c in snapshot.cells), default=1.0)
        max_weight = max(1.0, max_weight)
        cell_size_px = snapshot.cell_size_units * scale

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
                heat_color = self._spawn_heat_color(intensity)
                painter.fillRect(rect, heat_color)

            if cell.stalls > 0:
                painter.setPen(QPen(STALL_MARKER_COLOR, 1.5, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(QColor(245, 34, 45, 40)))
                painter.drawRect(rect)
            elif cell.spawn_weight <= 0.0:
                painter.setPen(QPen(GRID_LINE_COLOR, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)

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

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(NODE_COLOR))
        for cell in snapshot.cells:
            pt = to_screen(cell.center_x, cell.center_y)
            painter.drawEllipse(pt, 3.0, 3.0)

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

    def _draw_safe_waypoint(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None
        if snapshot.safe_waypoint is None:
            return

        pt = to_screen(snapshot.safe_waypoint[0], snapshot.safe_waypoint[1])
        painter.setPen(QPen(SAFE_NODE_COLOR, 2))
        painter.setBrush(QBrush(QColor(82, 196, 26, 120)))
        painter.drawRect(QRectF(pt.x() - 4, pt.y() - 4, 8, 8))

    def _draw_player_marker(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None

        pt = to_screen(snapshot.player_x, snapshot.player_y)
        heading_rad = math.radians(snapshot.heading_degrees)
        dx = math.sin(heading_rad)
        dy = math.cos(heading_rad)

        size = 8.0
        front = QPointF(pt.x() + dx * size * 1.5, pt.y() - dy * size * 1.5)
        left = QPointF(pt.x() - dy * size - dx * size * 0.6, pt.y() - dx * size + dy * size * 0.6)
        right = QPointF(pt.x() + dy * size - dx * size * 0.6, pt.y() + dx * size + dy * size * 0.6)

        painter.setPen(QPen(PLAYER_ACCENT_COLOR, 1.5))
        painter.setBrush(QBrush(PLAYER_COLOR))
        painter.drawPolygon(QPolygonF([front, left, pt, right]))
        painter.drawEllipse(pt, 3.5, 3.5)

    def _draw_overlay_hud(self, painter: QPainter, width: int, height: int) -> None:
        snapshot = self._snapshot
        assert snapshot is not None

        painter.setFont(QFont("", 9))
        painter.setPen(QPen(TEXT_COLOR))
        status_line = (
            f"Pos: ({snapshot.player_x:.1f}, {snapshot.player_y:.1f})  "
            f"Facing: {snapshot.heading_degrees:.0f}°  "
            f"Cells: {len(snapshot.cells)}  "
            f"Route: {len(snapshot.waypoints)}"
        )
        painter.drawText(QRectF(10, 8, width - 20, 20), Qt.AlignmentFlag.AlignLeft, status_line)

        legend_y = height - 22
        legend_items = [
            (PLAYER_COLOR, Message.UI_NAV_LEGEND_PLAYER),
            (QColor(250, 173, 20), Message.UI_NAV_LEGEND_SPAWN),
            (EDGE_NORMAL_COLOR, Message.UI_NAV_LEGEND_PATH),
            (STALL_MARKER_COLOR, Message.UI_NAV_LEGEND_OBSTACLE),
            (ROUTE_COLOR, Message.UI_NAV_LEGEND_ROUTE),
        ]
        cur_x = 10.0
        for color, msg in legend_items:
            painter.fillRect(QRectF(cur_x, legend_y + 3, 10, 10), color)
            cur_x += 14
            label = self._translator.text(msg)
            painter.setPen(QPen(MUTED_TEXT_COLOR))
            painter.drawText(QPointF(cur_x, legend_y + 12), label)
            cur_x += painter.fontMetrics().horizontalAdvance(label) + 12

    @staticmethod
    def _spawn_heat_color(intensity: float) -> QColor:
        clamped = max(0.0, min(1.0, intensity))
        if clamped < 0.5:
            fraction = clamped / 0.5
            red = int(82 + (250 - 82) * fraction)
            green = int(196 + (173 - 196) * fraction)
            blue = int(26 + (20 - 26) * fraction)
        else:
            fraction = (clamped - 0.5) / 0.5
            red = int(250 + (245 - 250) * fraction)
            green = int(173 + (34 - 173) * fraction)
            blue = int(20 + (45 - 20) * fraction)
        return QColor(red, green, blue, int(60 + clamped * 120))
