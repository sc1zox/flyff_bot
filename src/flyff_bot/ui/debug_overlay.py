"""Client-space debug rendering for captured Flyff frames."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from flyff_bot.features.automation.models import (
    PlayerVitals,
    SelectedTarget,
    TargetState,
    VisibleMob,
)
from flyff_bot.features.vision.models import CapturedFrame, PixelFormat
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.placement_overlay import compute_placement_guides, draw_placement_guides

MOB_BOX_COLOR = QColor(0, 255, 0)
TARGET_VALID_COLOR = QColor(0, 200, 0)
TARGET_WRONG_COLOR = QColor(220, 160, 0)
TARGET_NONE_COLOR = QColor(200, 0, 0)
OVERLAY_PEN_WIDTH = 2
OVERLAY_FONT_POINT_SIZE = 10
DEFAULT_PREVIEW_WIDTH = 640
DEFAULT_PREVIEW_HEIGHT = 360
MINIMUM_PREVIEW_WIDTH = 320
MINIMUM_PREVIEW_HEIGHT = 180
OVERLAY_BG_COLOR = QColor(17, 20, 28)


class DebugOverlayWidget(QWidget):
    """Render a scaled viewport debug overlay maintaining aspect ratio."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(MINIMUM_PREVIEW_WIDTH, MINIMUM_PREVIEW_HEIGHT)

    def pixmap(self) -> QPixmap | None:
        """Return the unscaled backing frame pixmap."""

        return self._pixmap

    def setPixmap(self, pixmap: QPixmap | None) -> None:
        """Assign an updated frame pixmap and request repaint."""

        self._pixmap = pixmap
        self.update()

    set_pixmap = setPixmap

    def clear(self) -> None:
        """Clear the current preview frame."""

        self.setPixmap(None)

    def sizeHint(self) -> QSize:
        """Return a sensible default proportional preview dimension."""

        if self._pixmap is not None and not self._pixmap.isNull():
            return self._pixmap.size().scaled(
                DEFAULT_PREVIEW_WIDTH,
                DEFAULT_PREVIEW_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        return QSize(DEFAULT_PREVIEW_WIDTH, DEFAULT_PREVIEW_HEIGHT)

    def paintEvent(self, _event: object) -> None:
        """Draw the current pixmap scaled smoothly to the widget bounds."""

        painter = QPainter(self)
        width = self.width()
        height = self.height()
        painter.fillRect(0, 0, width, height, OVERLAY_BG_COLOR)

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QPen(QColor(148, 163, 184)))
            painter.setFont(QFont("", 10))
            painter.drawText(
                QRect(0, 0, width, height),
                Qt.AlignmentFlag.AlignCenter,
                "Warten auf Spielfenster-Frame…",
            )
            painter.end()
            return

        scaled_size = self._pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target_rect = QRect(
            (width - scaled_size.width()) // 2,
            (height - scaled_size.height()) // 2,
            scaled_size.width(),
            scaled_size.height(),
        )

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(target_rect, self._pixmap)
        painter.end()


def render_debug_overlay(
    frame: CapturedFrame,
    mobs: tuple[VisibleMob, ...],
    target: SelectedTarget,
    translator: Translator,
    vitals: PlayerVitals | None = None,
    show_placements: bool = False,
) -> QPixmap:
    """Return a copied pixmap with client-space mob and target annotations."""

    image_format = (
        QImage.Format.Format_BGR888
        if frame.pixel_format is PixelFormat.BGR
        else QImage.Format.Format_RGB888
    )
    image = QImage(
        frame.pixels.data,
        frame.client_size.width,
        frame.client_size.height,
        frame.pixels.strides[0],
        image_format,
    ).copy()
    painter = QPainter(image)
    painter.setFont(QFont("", OVERLAY_FONT_POINT_SIZE))
    painter.setPen(QPen(MOB_BOX_COLOR, OVERLAY_PEN_WIDTH))
    for mob in mobs:
        painter.drawRect(QRect(mob.x, mob.y, mob.width, mob.height))
        painter.drawText(
            mob.x,
            max(OVERLAY_FONT_POINT_SIZE, mob.y - OVERLAY_PEN_WIDTH),
            translator.text(
                Message.UI_MOB_ANNOTATION,
                class_name=mob.class_name,
                confidence=f"{mob.confidence:.2f}",
            ),
        )
    painter.setPen(QPen(_target_color(target.state), OVERLAY_PEN_WIDTH))
    painter.drawText(
        OVERLAY_PEN_WIDTH,
        OVERLAY_FONT_POINT_SIZE + OVERLAY_PEN_WIDTH,
        translator.text(
            Message.UI_TARGET_ANNOTATION,
            status=translator.text(_target_message(target.state)),
            name=target.name or translator.text(Message.UI_NO_TARGET_NAME),
        ),
    )
    if vitals is not None:
        painter.setPen(QPen(QColor(240, 240, 240), OVERLAY_PEN_WIDTH))
        painter.drawText(
            OVERLAY_PEN_WIDTH,
            (OVERLAY_FONT_POINT_SIZE + OVERLAY_PEN_WIDTH) * 2 + 4,
            translator.text(
                Message.UI_VITALS_ANNOTATION,
                hp=f"{vitals.hp_percentage:.1f}",
                mp=f"{vitals.mp_percentage:.1f}",
                fp=f"{vitals.fp_percentage:.1f}",
            ),
        )
    if show_placements:
        draw_placement_guides(
            painter,
            compute_placement_guides(frame.client_size, translator),
        )
    painter.end()
    return QPixmap.fromImage(image)


def _target_color(state: TargetState) -> QColor:
    return {
        TargetState.VALID: TARGET_VALID_COLOR,
        TargetState.WRONG: TARGET_WRONG_COLOR,
        TargetState.NONE: TARGET_NONE_COLOR,
    }[state]


def _target_message(state: TargetState) -> Message:
    return {
        TargetState.VALID: Message.UI_TARGET_VALID,
        TargetState.WRONG: Message.UI_TARGET_WRONG,
        TargetState.NONE: Message.UI_TARGET_NONE,
    }[state]
