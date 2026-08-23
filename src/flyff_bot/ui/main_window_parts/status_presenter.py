from __future__ import annotations

from PySide6.QtWidgets import QLabel

from flyff_bot.features.navigation.live_position import PositionSource
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import BotStatus, NavigationSnapshot, WindowStatus
from flyff_bot.ui.main_window_parts.header import (
    camera_error_message,
    gps_error_message,
    status_category,
    status_message,
    window_status_message,
)


class StatusPresenter:
    """Renders persistent client and automation status chips."""

    def __init__(
        self,
        translator: Translator,
        status_label: QLabel,
        window_label: QLabel,
        gps_label: QLabel,
        camera_label: QLabel,
    ) -> None:
        self.translator = translator
        self.status_label = status_label
        self.window_label = window_label
        self.gps_label = gps_label
        self.camera_label = camera_label
        self.window_status = WindowStatus.NOT_FOUND
        self.position_source = PositionSource.UNAVAILABLE

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator

    def render_initial_state(self) -> None:
        self.render_status(BotStatus.PAUSED)
        self.render_window_status()
        self.render_navigation_status(None)

    def render_status(self, status: BotStatus) -> None:
        self.status_label.setText(
            self.translator.text(
                Message.UI_BOT_STATUS,
                status=self.translator.text(status_message(status)),
            )
        )
        self.status_label.setProperty("status", status_category(status))
        self._refresh_property_style(self.status_label)

    def render_window_status(
        self,
        status: WindowStatus | None = None,
    ) -> None:
        if status is not None:
            self.window_status = status
        self.window_label.setText(self.translator.text(window_status_message(self.window_status)))

    def render_navigation_status(
        self,
        navigation: NavigationSnapshot | None,
    ) -> None:
        if navigation is not None:
            self.position_source = navigation.position_source
        self._render_gps(navigation)
        self._render_camera(navigation)

    def _render_gps(
        self,
        navigation: NavigationSnapshot | None,
    ) -> None:
        live = self.position_source is PositionSource.LIVE
        position = navigation.world_position if navigation is not None else None
        error_code = navigation.position_error_code if navigation is not None else None
        reason = self.translator.text(
            Message.UI_GPS_UNAVAILABLE if error_code is None else gps_error_message(error_code)
        )
        self.gps_label.setText(
            self.translator.text(Message.UI_GPS_LIVE)
            if live
            else self.translator.text(Message.UI_GPS_OFFLINE, reason=reason)
        )
        self.gps_label.setProperty("gps", "live" if live else "offline")
        self.gps_label.setToolTip(
            self.translator.text(
                Message.UI_GPS_COORDINATES,
                x=f"{position.x:.2f}",
                y=f"{position.y:.2f}",
                z=f"{position.z:.2f}",
            )
            if position is not None
            else reason
        )
        self._refresh_property_style(self.gps_label)

    def _render_camera(
        self,
        navigation: NavigationSnapshot | None,
    ) -> None:
        state = navigation.camera_state if navigation is not None else None
        error_code = navigation.camera_error_code if navigation is not None else None
        reason = self.translator.text(
            Message.UI_GPS_UNAVAILABLE if error_code is None else camera_error_message(error_code)
        )
        self.camera_label.setText(
            self.translator.text(Message.UI_CAMERA_LIVE)
            if state is not None
            else self.translator.text(Message.UI_CAMERA_OFFLINE, reason=reason)
        )
        self.camera_label.setProperty("camera", "live" if state is not None else "offline")
        self._refresh_property_style(self.camera_label)

    @staticmethod
    def _refresh_property_style(label: QLabel) -> None:
        style = label.style()
        if style is not None:
            style.unpolish(label)
            style.polish(label)
