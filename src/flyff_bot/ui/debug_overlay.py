"""Client-space debug rendering for captured Flyff frames."""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap

from flyff_bot.features.automation.models import SelectedTarget, TargetState, VisibleMob
from flyff_bot.features.vision.models import CapturedFrame, PixelFormat
from flyff_bot.i18n import Message, Translator

MOB_BOX_COLOR = QColor(0, 255, 0)
TARGET_VALID_COLOR = QColor(0, 200, 0)
TARGET_WRONG_COLOR = QColor(220, 160, 0)
TARGET_NONE_COLOR = QColor(200, 0, 0)
OVERLAY_PEN_WIDTH = 2
OVERLAY_FONT_POINT_SIZE = 10


def render_debug_overlay(
    frame: CapturedFrame,
    mobs: tuple[VisibleMob, ...],
    target: SelectedTarget,
    translator: Translator,
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
