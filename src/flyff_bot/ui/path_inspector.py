"""3D authoritative visual navigation path, NavMesh, and terrain inspector widget."""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from flyff_bot.features.navigation.live_position import PositionReadErrorCode, PositionSource
from flyff_bot.features.navigation.navmesh import BakedNavMesh, NavMeshPolygon
from flyff_bot.features.navigation.world_extractor import (
    LAND_BLOCK_VERTICES_PER_SIDE,
    LandBlock,
    ObstacleKind,
    VectorSpawnZone,
    WorldCoordinate,
    WorldVectorMap,
)
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import NavigationSnapshot, VectorZoneSnapshot
from flyff_bot.ui.world_map_view import (
    ScreenPoint,
    ViewportLimits,
    ViewportTransform,
    WorldBounds,
    WorldMapScene,
)


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
NAVMESH_FILL_COLOR = QColor(59, 130, 246, 52)
NAVMESH_EDGE_COLOR = QColor(96, 165, 250, 115)
SLOPE_OBSTACLE_COLOR = QColor(239, 68, 68, 95)
OBJECT_OBSTACLE_COLOR = QColor(249, 115, 22, 120)
SELECTED_ZONE_COLOR = QColor(250, 204, 21, 245)
ELEVATION_PROFILE_COLOR = QColor(134, 239, 172)
ELEVATION_STRIP_HEIGHT_PIXELS = 42.0

LEGEND_ITEMS: tuple[tuple[str, QColor, Message], ...] = (
    ("▲", PLAYER_COLOR, Message.UI_NAV_LEGEND_PLAYER),
    ("■", TERRAIN_HIGH_COLOR, Message.UI_NAV_LEGEND_TERRAIN),
    ("△", NAVMESH_EDGE_COLOR, Message.UI_NAV_LEGEND_NAVMESH),
    ("□", ZONE_COLOR, Message.UI_NAV_LEGEND_ZONE),
    ("▧", OBJECT_OBSTACLE_COLOR, Message.UI_NAV_LEGEND_OBSTACLE),
    ("━", ROUTE_COLOR, Message.UI_NAV_LEGEND_ROUTE),
    ("●", NAVMESH_REACHABLE_COLOR, Message.UI_NAV_LEGEND_NAVMESH_TARGET),
    ("●", NAVMESH_UNREACHABLE_COLOR, Message.UI_NAV_LEGEND_NAVMESH_UNREACHABLE),
    ("┄", NAVIGATION_TRAJECTORY_COLOR, Message.UI_NAV_LEGEND_GPS_TRAJECTORY),
)

PADDING_FRACTION = 0.2
MINIMUM_VIEW_EXTENT = 50.0
WIDGET_MIN_WIDTH = 360
WIDGET_MIN_HEIGHT = 280
GRID_STEP_UNITS = 20.0
FOV_DEGREES = 60.0
FOV_DISTANCE_UNITS = 25.0
TERRAIN_DETAIL_MINIMUM_PIXELS = 48.0
TERRAIN_CACHE_LIMIT = 64
MAXIMUM_NAVMESH_POLYGONS_PER_FRAME = 5000


def _calculate_grid_step(scale: float) -> float:
    """Return a comfortable world-unit grid spacing that avoids dense screen clutter."""

    for step in (5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0):
        if step * scale >= 40.0:
            return step
    return 1000.0


class PathInspectorWidget(QWidget):
    """Render 3D authoritative terrain, vector spawn zones, NavMesh route, and player position."""

    zone_selected = Signal(object)
    follow_mode_changed = Signal(bool)

    def __init__(
        self,
        translator: Translator,
        parent: QWidget | None = None,
        *,
        viewport_limits: ViewportLimits | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator
        self._snapshot: NavigationSnapshot | None = None
        self._scene: WorldMapScene | None = None
        self._viewport = ViewportTransform(
            center_x=0.0,
            center_z=0.0,
            scale=1.0,
            width=max(self.width(), 1),
            height=max(self.height(), 1),
            limits=viewport_limits or ViewportLimits(),
        )
        self._view_initialized = False
        self._follow_player = False
        self._right_drag_anchor: QPointF | None = None
        self._selected_zone: VectorSpawnZone | None = None
        self._hovered_zone: VectorSpawnZone | None = None
        self._terrain_images: OrderedDict[tuple[int, int], QImage] = OrderedDict()
        self._terrain_average_colors: dict[tuple[int, int], QColor] = {}
        self._last_visible_terrain_block_count = 0
        self.setMouseTracking(True)
        self.setMinimumSize(WIDGET_MIN_WIDTH, WIDGET_MIN_HEIGHT)

    @property
    def snapshot(self) -> NavigationSnapshot | None:
        """Return the currently rendered navigation snapshot."""

        return self._snapshot

    @property
    def world_map(self) -> WorldVectorMap | None:
        """Return the static extracted map currently backing the scene."""

        return None if self._scene is None else self._scene.world_map

    @property
    def navmesh(self) -> BakedNavMesh | None:
        """Return the optional baked passability mesh currently shown."""

        return None if self._scene is None else self._scene.navmesh

    @property
    def selected_zone(self) -> VectorSpawnZone | None:
        """Return the spawn camp most recently selected in the map."""

        return self._selected_zone

    @property
    def follow_player(self) -> bool:
        """Return whether live GPS updates continuously recenter the map."""

        return self._follow_player

    @property
    def view_center(self) -> WorldCoordinate:
        """Return the persistent viewport centre in client world units."""

        return WorldCoordinate(self._viewport.center_x, self._viewport.center_z)

    @property
    def zoom_scale(self) -> float:
        """Return the current bounded pixels-per-world-unit scale."""

        return self._viewport.scale

    @property
    def visible_world_bounds(self) -> WorldBounds:
        """Return the current inverse-transformed frustum on the X/Z plane."""

        self._sync_viewport_size()
        return self._viewport.visible_world_bounds

    @property
    def last_visible_terrain_block_count(self) -> int:
        """Return how many terrain blocks survived culling during the last paint."""

        return self._last_visible_terrain_block_count

    def set_world_data(
        self, world_map: WorldVectorMap | None, navmesh: BakedNavMesh | None = None
    ) -> None:
        """Adopt a static extracted scene without coupling it to the live update cadence."""

        if world_map is None:
            self._scene = None
            self._selected_zone = None
            self._terrain_images.clear()
            self._terrain_average_colors.clear()
            self._view_initialized = False
            self.update()
            return
        if (
            self._scene is not None
            and self._scene.world_map is world_map
            and self._scene.navmesh is navmesh
        ):
            return
        self._scene = WorldMapScene(world_map, navmesh)
        self._selected_zone = None
        self._terrain_images.clear()
        self._terrain_average_colors.clear()
        self.fit_world()

    def set_selected_zone(self, zone: VectorSpawnZone | None) -> None:
        """Highlight an externally activated camp without emitting a new intent."""

        self._selected_zone = zone
        self.update()

    def set_follow_player(self, enabled: bool) -> None:
        """Enable or disable continuous live-GPS viewport centering."""

        enabled = bool(enabled)
        if enabled == self._follow_player:
            if enabled:
                self._center_on_live_player()
            return
        self._follow_player = enabled
        if enabled:
            self._center_on_live_player()
        self.follow_mode_changed.emit(enabled)
        self.update()

    def fit_world(self) -> None:
        """Fit the full extracted map, or the current dynamic route if no map is loaded."""

        self._sync_viewport_size()
        bounds = self._scene.world_bounds if self._scene is not None else self._dynamic_bounds()
        if bounds is not None:
            self._viewport.fit(bounds)
            self._view_initialized = True
        self.update()

    def world_to_screen(self, point: WorldCoordinate) -> QPointF:
        """Return a Qt point for one world X/Z coordinate."""

        self._sync_viewport_size()
        screen = self._viewport.world_to_screen(point)
        return QPointF(screen.x, screen.y)

    def screen_to_world(self, point: QPointF) -> WorldCoordinate:
        """Return the world X/Z coordinate beneath one widget-local point."""

        self._sync_viewport_size()
        return self._viewport.screen_to_world(ScreenPoint(point.x(), point.y()))

    def pan_by_pixels(self, delta_x: float, delta_y: float) -> None:
        """Pan by a screen-space drag delta and suspend player follow mode."""

        if delta_x == 0.0 and delta_y == 0.0:
            return
        self._viewport.pan_by_pixels(delta_x, delta_y)
        self._view_initialized = True
        if self._follow_player:
            self.set_follow_player(False)
        self.update()

    def zoom_at(self, factor: float, cursor: QPointF) -> None:
        """Apply bounded cursor-anchored zoom for tests and wheel input."""

        self._sync_viewport_size()
        self._viewport.zoom_at(factor, ScreenPoint(cursor.x(), cursor.y()))
        self._view_initialized = True
        self.update()

    def visible_terrain_blocks(self) -> tuple[LandBlock, ...]:
        """Return the heightfield blocks surviving current frustum culling."""

        if self._scene is None:
            return ()
        return self._scene.visible_terrain_blocks(self.visible_world_bounds)

    def zone_at(self, point: QPointF) -> VectorSpawnZone | None:
        """Return the extracted camp beneath a widget-local point."""

        if self._scene is None:
            return None
        return self._scene.zone_at(self.screen_to_world(point))

    def set_navigation(self, snapshot: NavigationSnapshot | None) -> None:
        """Update the rendered navigation snapshot and trigger a repaint."""

        self._snapshot = snapshot
        if not self._view_initialized and snapshot is not None:
            self.fit_world()
        if self._follow_player:
            self._center_on_live_player()
        self.update()

    def set_translator(self, translator: Translator) -> None:
        """Update the translator instance and repaint localized labels."""

        self._translator = translator
        self._update_zone_tooltip(self._hovered_zone)
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

        snapshot_is_empty = self._snapshot is None or (
            not self._snapshot.terrain_samples
            and self._snapshot.world_position is None
            and self._snapshot.player_x == 0.0
            and self._snapshot.player_y == 0.0
        )
        if self._scene is None and snapshot_is_empty:
            self._draw_standby_message(painter, width, height)
            painter.end()
            return

        self._sync_viewport_size()
        if not self._view_initialized:
            self.fit_world()
        scale = self._viewport.scale
        visible = self._viewport.visible_world_bounds

        def to_screen(wx: float, wy: float) -> QPointF:
            point = self._viewport.world_to_screen(WorldCoordinate(wx, wy))
            return QPointF(point.x, point.y)

        self._draw_grid_and_axes(
            painter,
            width,
            height,
            to_screen,
            visible.minimum_x,
            visible.maximum_x,
            visible.minimum_z,
            visible.maximum_z,
            scale,
        )
        scene = self._scene
        snapshot = self._snapshot
        if scene is not None:
            self._draw_world_terrain(painter, scene, to_screen, scale, visible)
            self._draw_navmesh_passability(painter, scene, to_screen, visible)
            self._draw_obstacles(painter, scene, to_screen, visible)
            self._draw_world_zones(painter, scene, to_screen, visible)
        elif snapshot is not None:
            self._draw_terrain(painter, snapshot, to_screen, scale)
            self._draw_vector_zones(painter, snapshot, to_screen, scale)
        if snapshot is not None:
            self._draw_active_route(painter, snapshot, to_screen)
            self._draw_navigation_trajectory(painter, snapshot, to_screen)
            self._draw_navmesh_mobs(painter, snapshot, to_screen)
            self._draw_player_marker(painter, snapshot, to_screen, scale)
            self._draw_elevation_profile(painter, snapshot, width, height)
            self._draw_overlay_hud(painter, snapshot, width)
        self._draw_legend(painter, width, height)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the inverse transform synchronized with the drawable widget size."""

        self._viewport.resize(event.size().width(), event.size().height())
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Reserve RMB for panning and LMB for extracted-zone selection."""

        if event.button() is Qt.MouseButton.RightButton:
            self._right_drag_anchor = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() is Qt.MouseButton.LeftButton:
            zone = self.zone_at(event.position())
            if zone is not None:
                self._selected_zone = zone
                self.zone_selected.emit(zone)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Pan an active RMB drag, otherwise update the localized zone tooltip."""

        if self._right_drag_anchor is not None and event.buttons() & Qt.MouseButton.RightButton:
            delta = event.position() - self._right_drag_anchor
            self._right_drag_anchor = event.position()
            self.pan_by_pixels(delta.x(), delta.y())
            event.accept()
            return
        zone = self.zone_at(event.position())
        if zone is not self._hovered_zone:
            self._hovered_zone = zone
            self._update_zone_tooltip(zone)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a captured RMB pan without running selection hit-testing."""

        if event.button() is Qt.MouseButton.RightButton:
            self._right_drag_anchor = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Apply smooth, bounded, cursor-centred wheel zoom."""

        steps = event.angleDelta().y() / 120.0
        if steps == 0.0:
            event.ignore()
            return
        factor = self._viewport.limits.wheel_zoom_factor**steps
        self.zoom_at(factor, event.position())
        event.accept()

    def _dynamic_bounds(self) -> WorldBounds | None:
        snapshot = self._snapshot
        if snapshot is None:
            return None

        xs: list[float] = [snapshot.player_x]
        zs: list[float] = [snapshot.player_y]

        for wx, wz in snapshot.waypoints:
            xs.append(wx)
            zs.append(wz)

        for mob in snapshot.navmesh_mobs:
            xs.append(mob.world_x)
            zs.append(mob.world_z)

        for point in snapshot.navigation_trajectory:
            xs.append(point.x)
            zs.append(point.z)

        if snapshot.vector_zone is not None:
            vz = snapshot.vector_zone
            xs.extend([vz.center_x - vz.half_width_pixels, vz.center_x + vz.half_width_pixels])
            zs.extend([vz.center_y - vz.half_depth_pixels, vz.center_y + vz.half_depth_pixels])
        elif snapshot.vector_zones:
            for vz in snapshot.vector_zones[:3]:
                xs.extend([vz.center_x - vz.half_width_pixels, vz.center_x + vz.half_width_pixels])
                zs.extend([vz.center_y - vz.half_depth_pixels, vz.center_y + vz.half_depth_pixels])

        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        half_x = max(MINIMUM_VIEW_EXTENT, (max_x - min_x) * (1.0 + PADDING_FRACTION) / 2.0)
        half_z = max(MINIMUM_VIEW_EXTENT, (max_z - min_z) * (1.0 + PADDING_FRACTION) / 2.0)
        center_x = (min_x + max_x) / 2.0
        center_z = (min_z + max_z) / 2.0
        return WorldBounds(
            center_x - half_x,
            center_z - half_z,
            center_x + half_x,
            center_z + half_z,
        )

    def _sync_viewport_size(self) -> None:
        self._viewport.resize(self.width(), self.height())

    def _center_on_live_player(self) -> None:
        snapshot = self._snapshot
        if (
            snapshot is None
            or snapshot.position_source is not PositionSource.LIVE
            or snapshot.world_position is None
        ):
            return
        self._viewport.center_x = snapshot.world_position.x
        self._viewport.center_z = snapshot.world_position.z
        self._view_initialized = True

    def _update_zone_tooltip(self, zone: VectorSpawnZone | None) -> None:
        if zone is None:
            self.setToolTip("")
            return
        self.setToolTip(
            self._translator.text(
                Message.UI_MAP_ZONE_TOOLTIP,
                monster=zone.monster_name or str(zone.monster_id),
                identifier=zone.monster_id,
                capacity=zone.capacity,
                seconds=zone.respawn_seconds,
                x=f"{zone.center_x:.1f}",
                y=f"{zone.center_y:.1f}",
                z=f"{zone.center_z:.1f}",
            )
        )

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
        grid_step = _calculate_grid_step(scale)
        start_x = math.floor(min_x / grid_step) * grid_step
        end_x = math.ceil(max_x / grid_step) * grid_step
        start_y = math.floor(min_y / grid_step) * grid_step
        end_y = math.ceil(max_y / grid_step) * grid_step

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
                painter.setPen(QPen(AXIS_TEXT_COLOR))
                painter.drawText(
                    QPointF(pt_top.x() + 2, float(height) - 30),
                    f"{gx:+.0f}m",
                )
            gx += grid_step

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
                painter.setPen(QPen(AXIS_TEXT_COLOR))
                painter.drawText(
                    QPointF(10, pt_left.y() - 2),
                    f"{gy:+.0f}m",
                )
            gy += grid_step

        origin = to_screen(0.0, 0.0)
        if 0 <= origin.y() <= height:
            painter.setPen(QPen(AXIS_COLOR, 1, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(0, origin.y()), QPointF(width, origin.y()))
        if 0 <= origin.x() <= width:
            painter.setPen(QPen(AXIS_COLOR, 1, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(origin.x(), 0), QPointF(origin.x(), height))

        painter.setPen(QPen(AXIS_TEXT_COLOR))
        painter.setFont(QFont("", 8))
        painter.drawText(
            QRectF(float(width) - 120, 12, 110, 18),
            Qt.AlignmentFlag.AlignRight,
            self._translator.text(Message.UI_MAP_NORTH),
        )

    def _draw_world_terrain(
        self,
        painter: QPainter,
        scene: WorldMapScene,
        to_screen: Callable[[float, float], QPointF],
        scale: float,
        visible: WorldBounds,
    ) -> None:
        blocks = scene.visible_terrain_blocks(visible)
        self._last_visible_terrain_block_count = len(blocks)
        span = scene.world_map.dimensions.block_span_units
        for block in blocks:
            minimum_x = block.block_x * span
            minimum_z = block.block_z * span
            rect = QRectF(
                to_screen(minimum_x, minimum_z + span),
                to_screen(minimum_x + span, minimum_z),
            ).normalized()
            if span * scale < TERRAIN_DETAIL_MINIMUM_PIXELS:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(self._terrain_average_color(block)))
                painter.drawRect(rect)
                continue
            painter.drawImage(rect, self._terrain_image(block))

    def _terrain_average_color(self, block: LandBlock) -> QColor:
        key = block.block_x, block.block_z
        cached = self._terrain_average_colors.get(key)
        if cached is not None:
            return cached
        stride = max(1, len(block.heights) // 128)
        sampled = block.heights[::stride]
        average = sum(sampled) / max(len(sampled), 1)
        intensity = 0.5 + math.atan(average / 200.0) / math.pi
        color = _lerp_color(TERRAIN_LOW_COLOR, TERRAIN_HIGH_COLOR, intensity)
        self._terrain_average_colors[key] = color
        return color

    def _terrain_image(self, block: LandBlock) -> QImage:
        key = block.block_x, block.block_z
        cached = self._terrain_images.pop(key, None)
        if cached is not None:
            self._terrain_images[key] = cached
            return cached

        side = LAND_BLOCK_VERTICES_PER_SIDE
        image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
        minimum = min(block.heights)
        maximum = max(block.heights)
        height_span = max(maximum - minimum, 1.0)
        for row in range(side):
            for column in range(side):
                height = block.height(column, row)
                color = _lerp_color(
                    TERRAIN_LOW_COLOR,
                    TERRAIN_HIGH_COLOR,
                    (height - minimum) / height_span,
                )
                image.setPixelColor(column, side - 1 - row, color)
        self._terrain_images[key] = image
        while len(self._terrain_images) > TERRAIN_CACHE_LIMIT:
            self._terrain_images.popitem(last=False)
        return image

    def _draw_navmesh_passability(
        self,
        painter: QPainter,
        scene: WorldMapScene,
        to_screen: Callable[[float, float], QPointF],
        visible: WorldBounds,
    ) -> None:
        polygons = scene.visible_navmesh_polygons(visible)
        if not polygons:
            return
        stride = max(1, math.ceil(len(polygons) / MAXIMUM_NAVMESH_POLYGONS_PER_FRAME))
        painter.setPen(QPen(NAVMESH_EDGE_COLOR, 0.75))
        painter.setBrush(QBrush(NAVMESH_FILL_COLOR))
        for polygon in polygons[::stride]:
            painter.drawPolygon(self._navmesh_polygon(polygon, to_screen))

    @staticmethod
    def _navmesh_polygon(
        polygon: NavMeshPolygon,
        to_screen: Callable[[float, float], QPointF],
    ) -> QPolygonF:
        triangle = polygon.triangle
        return QPolygonF(
            [
                to_screen(triangle.first.x, triangle.first.z),
                to_screen(triangle.second.x, triangle.second.z),
                to_screen(triangle.third.x, triangle.third.z),
            ]
        )

    def _draw_obstacles(
        self,
        painter: QPainter,
        scene: WorldMapScene,
        to_screen: Callable[[float, float], QPointF],
        visible: WorldBounds,
    ) -> None:
        for obstacle in scene.world_map.obstacles:
            bounds = WorldBounds(
                obstacle.minimum_x,
                obstacle.minimum_z,
                obstacle.maximum_x,
                obstacle.maximum_z,
            )
            if not bounds.intersects(visible):
                continue
            color = (
                OBJECT_OBSTACLE_COLOR
                if obstacle.kind is ObstacleKind.OBJECT
                else SLOPE_OBSTACLE_COLOR
            )
            painter.setPen(QPen(color, 1.0))
            painter.setBrush(QBrush(_with_alpha(color, 45)))
            painter.drawRect(
                QRectF(
                    to_screen(obstacle.minimum_x, obstacle.maximum_z),
                    to_screen(obstacle.maximum_x, obstacle.minimum_z),
                ).normalized()
            )

    def _draw_world_zones(
        self,
        painter: QPainter,
        scene: WorldMapScene,
        to_screen: Callable[[float, float], QPointF],
        visible: WorldBounds,
    ) -> None:
        for zone in scene.visible_zones(visible):
            is_selected = zone == self._selected_zone
            is_active = self._is_active_zone(zone)
            color = SELECTED_ZONE_COLOR if is_selected else ZONE_COLOR
            alpha = 235 if is_selected or is_active else 115
            pen_width = 2.5 if is_selected else 2.0 if is_active else 1.0
            pen_style = Qt.PenStyle.SolidLine if is_selected or is_active else Qt.PenStyle.DashLine
            rect = QRectF(
                to_screen(zone.minimum_x, zone.maximum_z),
                to_screen(zone.maximum_x, zone.minimum_z),
            ).normalized()
            painter.setPen(QPen(_with_alpha(color, alpha), pen_width, pen_style))
            painter.setBrush(QBrush(_with_alpha(color, 45 if is_selected else 25)))
            painter.drawRect(rect)
            if is_selected or is_active or (rect.width() >= 70.0 and rect.height() >= 30.0):
                painter.setPen(QPen(_with_alpha(color, alpha)))
                painter.setFont(
                    QFont(
                        "",
                        8,
                        QFont.Weight.Bold if is_selected or is_active else QFont.Weight.Normal,
                    )
                )
                label = zone.monster_name or str(zone.monster_id)
                if not is_selected and not is_active:
                    label = f"{label} ({zone.capacity})"
                painter.drawText(rect.topLeft() + QPointF(4.0, 13.0), label)

    def _is_active_zone(self, zone: VectorSpawnZone) -> bool:
        snapshot = self._snapshot
        if snapshot is None:
            return False
        candidates = (
            () if snapshot.vector_zone is None else (snapshot.vector_zone,)
        ) + snapshot.vector_zones
        return any(
            candidate.monster_name == (zone.monster_name or str(zone.monster_id))
            and math.isclose(candidate.center_x, zone.center_x)
            and math.isclose(candidate.center_y, zone.center_z)
            for candidate in candidates
        )

    def _draw_terrain(
        self,
        painter: QPainter,
        snapshot: NavigationSnapshot,
        to_screen: Callable[[float, float], QPointF],
        scale: float,
    ) -> None:
        samples = snapshot.terrain_samples
        if not samples:
            return
        minimum = min(sample[1] for sample in samples)
        maximum = max(sample[1] for sample in samples)
        height_span = max(1.0, maximum - minimum)
        sample_size = max(2.0, GRID_STEP_UNITS * scale * 0.4)
        painter.setPen(Qt.PenStyle.NoPen)
        w = float(self.width())
        h = float(self.height())
        for world_x, height, world_z in samples:
            point = to_screen(world_x, world_z)
            if (
                -sample_size <= point.x() <= w + sample_size
                and -sample_size <= point.y() <= h + sample_size
            ):
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
        snapshot: NavigationSnapshot,
        to_screen: Callable[[float, float], QPointF],
        scale: float,
    ) -> None:
        zones: list[VectorZoneSnapshot] = []
        if snapshot.vector_zone is not None:
            zones.append(snapshot.vector_zone)
        for z in snapshot.vector_zones:
            if z not in zones:
                zones.append(z)
        active_zone = snapshot.vector_zone
        for zone in zones:
            is_active = active_zone is not None and zone == active_zone
            pt = to_screen(zone.center_x, zone.center_y)
            w_px = zone.half_width_pixels * 2.0 * scale
            h_px = zone.half_depth_pixels * 2.0 * scale
            rect = QRectF(pt.x() - w_px / 2.0, pt.y() - h_px / 2.0, w_px, h_px)

            pen_color = ZONE_COLOR if is_active else _with_alpha(ZONE_COLOR, 100)
            fill_color = ZONE_FILL_COLOR if is_active else _with_alpha(ZONE_COLOR, 15)
            pen_width = 2.0 if is_active else 1.0
            pen_style = Qt.PenStyle.SolidLine if is_active else Qt.PenStyle.DashLine

            painter.setPen(QPen(pen_color, pen_width, pen_style))
            painter.setBrush(QBrush(fill_color))
            painter.drawRect(rect)

            if is_active or (w_px >= 60.0 and h_px >= 30.0):
                weight = QFont.Weight.Bold if is_active else QFont.Weight.Normal
                painter.setPen(QPen(pen_color))
                painter.setFont(QFont("", 8, weight))
                label = zone.monster_name if is_active else f"{zone.monster_name} ({zone.capacity})"
                painter.drawText(rect.topLeft() + QPointF(4, 12), label)

    def _draw_active_route(
        self,
        painter: QPainter,
        snapshot: NavigationSnapshot,
        to_screen: Callable[[float, float], QPointF],
    ) -> None:
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
        self,
        painter: QPainter,
        snapshot: NavigationSnapshot,
        to_screen: Callable[[float, float], QPointF],
    ) -> None:
        """Draw only measured GPS points collected during the active Funnel approach."""

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
        self,
        painter: QPainter,
        snapshot: NavigationSnapshot,
        to_screen: Callable[[float, float], QPointF],
    ) -> None:
        """Render candidate topology without feeding the diagnostic view back into control."""

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

    def _draw_elevation_profile(
        self,
        painter: QPainter,
        snapshot: NavigationSnapshot,
        width: int,
        height: int,
    ) -> None:
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
        snapshot: NavigationSnapshot,
        to_screen: Callable[[float, float], QPointF],
        scale: float,
    ) -> None:

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

    def _draw_overlay_hud(
        self,
        painter: QPainter,
        snapshot: NavigationSnapshot,
        width: int,
    ) -> None:

        hud_w = min(float(width - 20), HUD_MAXIMUM_WIDTH_PIXELS)
        gps_status = (
            self._translator.text(Message.UI_GPS_LIVE)
            if snapshot.position_source is PositionSource.LIVE
            else self._translator.text(Message.UI_GPS_UNAVAILABLE)
        )
        rows: list[tuple[str, QColor]] = [
            (
                self._translator.text(
                    Message.UI_MAP_HUD,
                    x=f"{snapshot.player_x:+.1f}",
                    z=f"{snapshot.player_y:+.1f}",
                    heading=f"{snapshot.heading_degrees:.0f}",
                    count=len(snapshot.waypoints),
                    status=gps_status,
                ),
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
