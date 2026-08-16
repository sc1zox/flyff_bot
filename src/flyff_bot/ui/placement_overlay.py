"""Transparent desktop guide overlay aligned with the live game client area."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from PySide6.QtCore import QRect, Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from flyff_bot.features.input_control import ScreenRect
from flyff_bot.features.vision.models import ClientSize
from flyff_bot.features.vision.monster_stats import MonsterStatsConfig, compute_monster_stats_roi
from flyff_bot.features.vision.target_verification import compute_target_header_bounds
from flyff_bot.features.vision.vitals import compute_vitals_layout
from flyff_bot.i18n import Message, Translator

GUIDE_PEN_WIDTH = 2
GUIDE_FONT_POINT_SIZE = 10
GEOMETRY_POLL_INTERVAL_MS = 250
MONSTER_STATS_GUIDE_COLOR = QColor(0, 200, 200)
PLACEMENTS_VITALS_COLOR = QColor(255, 215, 0)
PLACEMENTS_HP_COLOR = QColor(255, 80, 80)
PLACEMENTS_MP_COLOR = QColor(80, 140, 255)
PLACEMENTS_FP_COLOR = QColor(80, 255, 120)
PLACEMENTS_TARGET_COLOR = QColor(180, 120, 255)


class GuideStyle(StrEnum):
    """Outline style distinguishing calibration frames from measured sub-regions."""

    DASHED = "dashed"
    SOLID = "solid"


@dataclass(frozen=True, slots=True)
class PlacementGuide:
    """One labeled client-space region an operator aligns in-game HUD elements with."""

    left: int
    top: int
    right: int
    bottom: int
    color: QColor
    style: GuideStyle
    label: str | None = None


class ClientGeometryProvider(Protocol):
    """The desktop geometry lookup required to track the game client on screen."""

    def client_screen_bounds(self, window_handle: int) -> ScreenRect | None: ...


def compute_placement_guides(
    client_size: ClientSize,
    translator: Translator,
    monster_stats_config: MonsterStatsConfig | None = None,
) -> tuple[PlacementGuide, ...]:
    """Return every placement guide for a client area in client-space pixels."""

    guides: list[PlacementGuide] = []
    if monster_stats_config is not None:
        left, top, right, bottom = compute_monster_stats_roi(
            client_size.width, client_size.height, monster_stats_config
        )
        guides.append(
            PlacementGuide(
                left,
                top,
                right,
                bottom,
                MONSTER_STATS_GUIDE_COLOR,
                GuideStyle.DASHED,
                translator.text(Message.UI_MONSTER_STATS_GUIDE),
            )
        )

    layout = compute_vitals_layout()
    hud_left, hud_top, hud_right, hud_bottom = layout.hud
    guides.append(
        PlacementGuide(
            hud_left,
            hud_top,
            hud_right,
            hud_bottom,
            PLACEMENTS_VITALS_COLOR,
            GuideStyle.DASHED,
            translator.text(Message.UI_PLACEMENTS_VITALS_LABEL),
        )
    )
    for gauge, color in (
        (layout.hp, PLACEMENTS_HP_COLOR),
        (layout.mp, PLACEMENTS_MP_COLOR),
        (layout.fp, PLACEMENTS_FP_COLOR),
    ):
        gauge_left, gauge_top, gauge_right, gauge_bottom = gauge
        guides.append(
            PlacementGuide(
                gauge_left, gauge_top, gauge_right, gauge_bottom, color, GuideStyle.SOLID
            )
        )

    try:
        target_bounds = compute_target_header_bounds(client_size.width, client_size.height)
    except ValueError:
        return tuple(guides)
    target_left, target_top, target_right, target_bottom = target_bounds
    guides.append(
        PlacementGuide(
            target_left,
            target_top,
            target_right,
            target_bottom,
            PLACEMENTS_TARGET_COLOR,
            GuideStyle.DASHED,
            translator.text(Message.UI_PLACEMENTS_TARGET_LABEL),
        )
    )
    return tuple(guides)


def draw_placement_guides(
    painter: QPainter, guides: tuple[PlacementGuide, ...], scale: float = 1.0
) -> None:
    """Draw client-space guides onto a painter whose surface is scaled by ``scale``."""

    painter.setFont(QFont("", GUIDE_FONT_POINT_SIZE))
    for guide in guides:
        left = round(guide.left * scale)
        top = round(guide.top * scale)
        right = round(guide.right * scale)
        bottom = round(guide.bottom * scale)
        pen = QPen(guide.color, GUIDE_PEN_WIDTH)
        if guide.style is GuideStyle.DASHED:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(QRect(left, top, right - left, bottom - top))
        if guide.label is None:
            continue
        painter.setPen(QPen(guide.color, GUIDE_PEN_WIDTH))
        painter.drawText(left, max(GUIDE_FONT_POINT_SIZE, top - GUIDE_PEN_WIDTH), guide.label)


def logical_geometry(bounds: ScreenRect, device_pixel_ratio: float) -> tuple[int, int, int, int]:
    """Convert physical desktop pixels into the logical units Qt window geometry uses."""

    ratio = device_pixel_ratio if device_pixel_ratio > 0 else 1.0
    return (
        round(bounds.left / ratio),
        round(bounds.top / ratio),
        round(bounds.width / ratio),
        round(bounds.height / ratio),
    )


class PlacementOverlayWindow(QWidget):
    """Click-through always-on-top window drawing HUD guides over the game client.

    The window never activates: taking foreground would pause the guarded session and
    make the client register as occluded for frame capture.
    """

    def __init__(
        self,
        translator: Translator,
        *,
        monster_stats_config: MonsterStatsConfig | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._translator = translator
        self._monster_stats_config = monster_stats_config or MonsterStatsConfig()
        self._provider: ClientGeometryProvider | None = None
        self._window_handle: int | None = None
        self._client_size: ClientSize | None = None
        self._enabled = False
        self._timer = QTimer(self)
        self._timer.setInterval(GEOMETRY_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh_geometry)

    @property
    def client_size(self) -> ClientSize | None:
        """Return the client size the currently drawn guides were computed for."""

        return self._client_size

    def attach_target(self, provider: ClientGeometryProvider, window_handle: int) -> None:
        """Bind the overlay to a discovered game window handle."""

        self._provider = provider
        self._window_handle = window_handle
        self.refresh_geometry()

    def set_translator(self, translator: Translator) -> None:
        """Adopt a new language for the guide labels."""

        self._translator = translator
        self.update()

    def set_guides_visible(self, visible: bool) -> None:
        """Show or hide the desktop guide overlay and its geometry tracking."""

        self._enabled = visible
        if visible:
            self._timer.start()
            self.refresh_geometry()
            return
        self._timer.stop()
        self.hide()

    @Slot()
    def refresh_geometry(self) -> None:
        """Track the client area on screen, hiding whenever it is unavailable."""

        if not self._enabled or self._provider is None or self._window_handle is None:
            self.hide()
            return
        bounds = self._provider.client_screen_bounds(self._window_handle)
        if bounds is None or bounds.width <= 0 or bounds.height <= 0:
            self.hide()
            return
        self._client_size = ClientSize(width=bounds.width, height=bounds.height)
        left, top, width, height = logical_geometry(bounds, self.devicePixelRatioF())
        self.setGeometry(left, top, width, height)
        if not self.isVisible():
            self.show()
        self.update()

    def stop(self) -> None:
        """Halt geometry tracking and close the overlay before the dashboard exits."""

        self._enabled = False
        self._timer.stop()
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop polling whenever the overlay window is closed."""

        self._timer.stop()
        super().closeEvent(event)

    def paintEvent(self, _event: object) -> None:
        """Draw the guides scaled from client pixels onto the tracked window area."""

        if self._client_size is None:
            return
        painter = QPainter(self)
        scale = self.width() / self._client_size.width
        draw_placement_guides(
            painter,
            compute_placement_guides(
                self._client_size, self._translator, self._monster_stats_config
            ),
            scale,
        )
        painter.end()
