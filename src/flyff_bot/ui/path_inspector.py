"""3D authoritative visual navigation path, NavMesh, and terrain inspector widget."""

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
)
from PySide6.QtWidgets import QWidget

from flyff_bot.features.navigation.live_position import PositionReadErrorCode, PositionSource
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import NavigationSnapshot, VectorZoneSnapshot


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
ROUTE_COLOR = QColor(179, 127, 235, 240)
NAVMESH_REACHABLE_COLOR = QColor(82, 196, 26)
NAVMESH_UNREACHABLE_COLOR = QColor(255, 77, 79)
NAVMESH_LOCKED_COLOR = QColor(148, 163, 184)
NAVIGATION_TRAJECTORY_COLOR = QColor(250, 204, 21, 220)
ZONE_COLOR = QColor(250, 140, 22, 220)
ZONE_FILL_COLOR = _with_alpha(ZONE_COLOR, 35)
PLAYER_COLOR = QColor(0, 240, 255)
PLAYER_CONE_FILL_ALPHA = 30
PLAYER_CONE_EDGE_ALPHA = 60
PLAYER_CONE_COLOR = _with_alpha(PLAYER_COLOR, PLAYER_CONE_FILL_ALPHA)
PLAYER_CONE_EDGE_COLOR = _with_alpha(PLAYER_COLOR, PLAYER_CONE_EDGE_ALPHA)
PLAYER_ACCENT_COLOR = QColor(255, 255, 255)
MARKER_OUTLINE_COLOR = QColor(15, 23, 42)
TEXT_COLOR = QColor(241, 245, 249)
MUTED_TEXT_COLOR = QColor(148, 163, 184)
HUD_BG_COLOR = QColor(15, 23, 42, 200)
HUD_BORDER_COLOR = QColor(51, 65, 85, 160)
HUD_ROW_HEIGHT_PIXELS = 24.0
HUD_MAXIMUM_WIDTH_PIXELS = 520.0
LEASH_NOTICE_COLOR = QColor(250, 173, 20)
TERRAIN_LOW_COLOR = QColor(23, 55, 45, 150)
TERRAIN_HIGH_COLOR = QColor(118, 104, 53, 190)
ELEVATION_PROFILE_COLOR = QColor(134, 239, 172)
ELEVATION_STRIP_HEIGHT_PIXELS = 42.0

LEGEND_ITEMS: tuple[tuple[str, QColor, Message], ...] = (
    ("▲", PLAYER_COLOR, Message.UI_NAV_LEGEND_PLAYER),
    ("━", ROUTE_COLOR, Message.UI_NAV_LEGEND_ROUTE),
    ("●", NAVMESH_REACHABLE_COLOR, Message.UI_NAV_LEGEND_NAVMESH_TARGET),
    ("●", NAVMESH_UNREACHABLE_COLOR, Message.UI_NAV_LEGEND_NAVMESH_UNREACHABLE),
    ("┄", NAVIGATION_TRAJECTORY_COLOR, Message.UI_NAV_LEGEND_GPS_TRAJECTORY),
    ("□", ZONE_COLOR, Message.UI_NAV_LEGEND_ZONE),
)

PADDING_FRACTION = 0.2
MINIMUM_VIEW_EXTENT = 50.0
WIDGET_MIN_WIDTH = 360
WIDGET_MIN_HEIGHT = 280
GRID_STEP_UNITS = 20.0
FOV_DEGREES = 60.0
FOV_DISTANCE_UNITS = 25.0


class PathInspectorWidget(QWidget):
    """Render 3D authoritative terrain, vector spawn zones, NavMesh route, and player position."""

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
        """Draw the 3D coordinate grid, terrain, active vector zones, route, and player marker."""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = self.width()
        height = self.height()

        painter.fillRect(0, 0, width, height, BG_COLOR)

        if self._snapshot is None or (
            not self._snapshot.terrain_samples
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
        self._draw_vector_zones(painter, to_screen, scale)
        self._draw_active_route(painter, to_screen)
        self._draw_navigation_trajectory(painter, to_screen)
        self._draw_navmesh_mobs(painter, to_screen)
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

        xs: list[float] = [snapshot.player_x]
        ys: list[float] = [snapshot.player_y]

        for wx, wy in snapshot.waypoints:
            xs.append(wx)
            ys.append(wy)

        for terrain_x, _h, terrain_z in snapshot.terrain_samples:
            xs.append(terrain_x)
            ys.append(terrain_z)

        for mob in snapshot.navmesh_mobs:
            xs.append(mob.world_x)
            ys.append(mob.world_z)

        for point in snapshot.navigation_trajectory:
            xs.append(point.x)
            ys.append(point.z)

        if snapshot.vector_zone is not None:
            vz = snapshot.vector_zone
            xs.extend([vz.center_x - vz.half_width_pixels, vz.center_x + vz.half_width_pixels])
            ys.extend([vz.center_y - vz.half_depth_pixels, vz.center_y + vz.half_depth_pixels])

        for vz in snapshot.vector_zones:
            xs.extend([vz.center_x - vz.half_width_pixels, vz.center_x + vz.half_width_pixels])
            ys.extend([vz.center_y - vz.half_depth_pixels, vz.center_y + vz.half_depth_pixels])

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

    def _draw_vector_zones(
        self,
        painter: QPainter,
        to_screen: Callable[[float, float], QPointF],
        scale: float,
    ) -> None:
        snapshot = self._snapshot
        assert snapshot is not None
        zones: list[VectorZoneSnapshot] = []
        if snapshot.vector_zone is not None:
            zones.append(snapshot.vector_zone)
        for z in snapshot.vector_zones:
            if z not in zones:
                zones.append(z)
        for zone in zones:
            pt = to_screen(zone.center_x, zone.center_y)
            w_px = zone.half_width_pixels * 2.0 * scale
            h_px = zone.half_depth_pixels * 2.0 * scale
            rect = QRectF(pt.x() - w_px / 2.0, pt.y() - h_px / 2.0, w_px, h_px)
            painter.setPen(QPen(ZONE_COLOR, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(ZONE_FILL_COLOR))
            painter.drawRect(rect)
            painter.setPen(QPen(ZONE_COLOR))
            painter.setFont(QFont("", 8))
            painter.drawText(rect.topLeft() + QPointF(4, 12), zone.monster_name)

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

    def _draw_navigation_trajectory(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        """Draw only measured GPS points collected during the active Funnel approach."""

        snapshot = self._snapshot
        assert snapshot is not None
        if len(snapshot.navigation_trajectory) < 2:
            return
        path = QPainterPath(
            to_screen(snapshot.navigation_trajectory[0].x, snapshot.navigation_trajectory[0].z)
        )
        for point in snapshot.navigation_trajectory[1:]:
            path.lineTo(to_screen(point.x, point.z))
        painter.setPen(QPen(NAVIGATION_TRAJECTORY_COLOR, 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _draw_navmesh_mobs(
        self, painter: QPainter, to_screen: Callable[[float, float], QPointF]
    ) -> None:
        """Render candidate topology without feeding the diagnostic view back into control."""

        snapshot = self._snapshot
        assert snapshot is not None
        for mob in snapshot.navmesh_mobs:
            color = (
                NAVMESH_LOCKED_COLOR
                if mob.locked_out
                else NAVMESH_REACHABLE_COLOR
                if mob.reachable
                else NAVMESH_UNREACHABLE_COLOR
            )
            point = to_screen(mob.world_x, mob.world_z)
            painter.setPen(QPen(color, 2 if mob.selected else 1.25))
            painter.setBrush(QBrush(_with_alpha(color, 90)))
            painter.drawEllipse(point, 5.0 if mob.selected else 3.5, 5.0 if mob.selected else 3.5)

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
        gps_status = (
            self._translator.text(Message.UI_GPS_LIVE)
            if snapshot.position_source is PositionSource.LIVE
            else self._translator.text(Message.UI_GPS_OFFLINE)
        )
        rows: list[tuple[str, QColor]] = [
            (
                f"GPS: ({snapshot.player_x:+.1f}, {snapshot.player_y:+.1f})  "
                f"Facing: {snapshot.heading_degrees:.0f}° ({compass})  "
                f"Waypoints: {len(snapshot.waypoints)}  "
                f"Status: {gps_status}",
                TEXT_COLOR,
            )
        ]
        if snapshot.position_source is not PositionSource.LIVE:
            error = snapshot.position_error_code
            reason = self._translator.text(
                Message.UI_GPS_UNAVAILABLE if error is None else _gps_error_message(error)
            )
            rows.append(
                (self._translator.text(Message.UI_GPS_OFFLINE, reason=reason), LEASH_NOTICE_COLOR)
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


def _gps_error_message(code: PositionReadErrorCode) -> Message:
    return {
        PositionReadErrorCode.UNSUPPORTED_PLATFORM: Message.UI_GPS_ERROR_UNSUPPORTED_PLATFORM,
        PositionReadErrorCode.WINDOW_NOT_FOREGROUND: Message.UI_GPS_ERROR_WINDOW_NOT_FOREGROUND,
        PositionReadErrorCode.PROCESS_UNAVAILABLE: Message.UI_GPS_ERROR_PROCESS_UNAVAILABLE,
        PositionReadErrorCode.WRONG_PROCESS: Message.UI_GPS_ERROR_WRONG_PROCESS,
        PositionReadErrorCode.UNSUPPORTED_BUILD: Message.UI_GPS_ERROR_UNSUPPORTED_BUILD,
        PositionReadErrorCode.HANDLE_LOST: Message.UI_GPS_ERROR_HANDLE_LOST,
        PositionReadErrorCode.MALFORMED_READ: Message.UI_GPS_ERROR_MALFORMED_READ,
        PositionReadErrorCode.INVALID_PROFILE_CONFIGURATION: (
            Message.UI_GPS_ERROR_INVALID_PROFILE_CONFIGURATION
        ),
    }[code]


def _heading_to_compass(heading: float) -> str:
    norm = (heading % 360.0 + 360.0) % 360.0
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = int((norm + 22.5) / 45.0) % 8
    return directions[index]
