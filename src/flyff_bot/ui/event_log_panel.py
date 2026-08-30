"""Reverse-chronological diagnostic session event log panel (US-049)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from flyff_bot.features.diagnostics import SessionEvent, SessionEventKind
from flyff_bot.i18n import Message, Translator

# Only the most recent rows are worth scanning in the panel; the full history stays on
# disk and in `SessionEventLogger`'s own ring buffer.
MAXIMUM_DISPLAYED_EVENTS = 100

_NEUTRAL_BADGE_COLOR = QColor("#94a3b8")
_WARNING_BADGE_COLOR = QColor("#f59e0b")
_DANGER_BADGE_COLOR = QColor("#ef4444")
_SUCCESS_BADGE_COLOR = QColor("#10b981")

_KIND_MESSAGES: dict[SessionEventKind, Message] = {
    SessionEventKind.MODE_TRANSITION: Message.UI_EVENT_KIND_MODE_TRANSITION,
    SessionEventKind.FOCUS_LOST: Message.UI_EVENT_KIND_FOCUS_LOST,
    SessionEventKind.EMERGENCY_STOPPED: Message.UI_EVENT_KIND_EMERGENCY_STOPPED,
    SessionEventKind.OBSTACLE_STALL: Message.UI_EVENT_KIND_OBSTACLE_STALL,
    SessionEventKind.SUPERVISOR_FAILURE: Message.UI_EVENT_KIND_SUPERVISOR_FAILURE,
    SessionEventKind.FRAME_CAPTURE_ERROR: Message.UI_EVENT_KIND_FRAME_CAPTURE_ERROR,
    SessionEventKind.GOAL_COMPLETED: Message.UI_EVENT_KIND_GOAL_COMPLETED,
    SessionEventKind.CAPABILITY_DEGRADED: Message.UI_EVENT_KIND_CAPABILITY_DEGRADED,
    SessionEventKind.TICK_FAULT: Message.UI_EVENT_KIND_TICK_FAULT,
    SessionEventKind.AUTOPILOT_ARMED: Message.UI_EVENT_KIND_AUTOPILOT_ARMED,
    SessionEventKind.AUTOPILOT_DISARMED: Message.UI_EVENT_KIND_AUTOPILOT_DISARMED,
    SessionEventKind.AUTOPILOT_GOAL: Message.UI_EVENT_KIND_AUTOPILOT_GOAL,
    SessionEventKind.PLAYER_DEATH: Message.UI_EVENT_KIND_PLAYER_DEATH,
    SessionEventKind.RECOVERY_RESUMED: Message.UI_EVENT_KIND_RECOVERY_RESUMED,
    SessionEventKind.BUDGET_EXHAUSTED: Message.UI_EVENT_KIND_BUDGET_EXHAUSTED,
    SessionEventKind.NAVIGATION_TEST_ARRIVED: Message.UI_EVENT_KIND_NAVIGATION_TEST_ARRIVED,
    SessionEventKind.ZONE_ROUTE_UNAVAILABLE: Message.UI_EVENT_KIND_ZONE_ROUTE_UNAVAILABLE,
}

_KIND_BADGE_COLORS: dict[SessionEventKind, QColor] = {
    SessionEventKind.MODE_TRANSITION: _NEUTRAL_BADGE_COLOR,
    SessionEventKind.FOCUS_LOST: _WARNING_BADGE_COLOR,
    SessionEventKind.EMERGENCY_STOPPED: _DANGER_BADGE_COLOR,
    SessionEventKind.OBSTACLE_STALL: _WARNING_BADGE_COLOR,
    SessionEventKind.SUPERVISOR_FAILURE: _WARNING_BADGE_COLOR,
    SessionEventKind.FRAME_CAPTURE_ERROR: _WARNING_BADGE_COLOR,
    SessionEventKind.GOAL_COMPLETED: _SUCCESS_BADGE_COLOR,
    SessionEventKind.CAPABILITY_DEGRADED: _WARNING_BADGE_COLOR,
    SessionEventKind.TICK_FAULT: _DANGER_BADGE_COLOR,
    SessionEventKind.AUTOPILOT_ARMED: _SUCCESS_BADGE_COLOR,
    SessionEventKind.AUTOPILOT_DISARMED: _NEUTRAL_BADGE_COLOR,
    SessionEventKind.AUTOPILOT_GOAL: _NEUTRAL_BADGE_COLOR,
    SessionEventKind.PLAYER_DEATH: _WARNING_BADGE_COLOR,
    SessionEventKind.RECOVERY_RESUMED: _SUCCESS_BADGE_COLOR,
    SessionEventKind.BUDGET_EXHAUSTED: _WARNING_BADGE_COLOR,
    SessionEventKind.NAVIGATION_TEST_ARRIVED: _SUCCESS_BADGE_COLOR,
    SessionEventKind.ZONE_ROUTE_UNAVAILABLE: _WARNING_BADGE_COLOR,
}

_MODE_MESSAGES: dict[str, Message] = {
    "paused": Message.UI_EVENT_MODE_PAUSED,
    "aligning": Message.UI_EVENT_MODE_ALIGNING,
    "searching": Message.UI_EVENT_MODE_SEARCHING,
    "repositioning": Message.UI_EVENT_MODE_REPOSITIONING,
    "test_navigating": Message.UI_STATUS_TEST_NAVIGATING,
    "approaching": Message.UI_EVENT_MODE_APPROACHING,
    "targeting": Message.UI_EVENT_MODE_TARGETING,
    "combat": Message.UI_EVENT_MODE_COMBAT,
    "reconciling": Message.UI_EVENT_MODE_RECONCILING,
    "completed": Message.UI_EVENT_MODE_COMPLETED,
    "emergency_stopped": Message.UI_EVENT_MODE_EMERGENCY_STOPPED,
}


def _local_time_text(timestamp: str) -> str:
    """Render a stored UTC ISO-8601 timestamp as the operator's local wall-clock time."""

    try:
        moment = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    return moment.astimezone().strftime("%H:%M:%S")


class EventLogPanel(QGroupBox):
    """Render recent session diagnostic events as a reverse-chronological, localized list."""

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardPanel")
        self._translator = translator
        self._events: tuple[SessionEvent, ...] = ()
        self._list = QListWidget()
        self._list.setObjectName("EventLogList")

        layout = QVBoxLayout()
        layout.addWidget(self._list)
        self.setLayout(layout)
        self._retranslate()

    @property
    def list_widget(self) -> QListWidget:
        """Expose the underlying list widget for wiring and verification."""

        return self._list

    def set_translator(self, translator: Translator) -> None:
        """Switch the displayed language and re-render the currently shown rows."""

        self._translator = translator
        self._retranslate()
        self.set_events(self._events)

    def set_events(self, events: Sequence[SessionEvent]) -> None:
        """Replace the displayed rows with the given events, already reverse-chronological."""

        self._events = tuple(events)
        self._list.clear()
        if not self._events:
            empty_item = QListWidgetItem(self._translator.text(Message.UI_EVENT_LOG_EMPTY))
            empty_item.setForeground(_NEUTRAL_BADGE_COLOR)
            self._list.addItem(empty_item)
            return
        for event in self._events[:MAXIMUM_DISPLAYED_EVENTS]:
            item = QListWidgetItem(self._summary(event))
            item.setForeground(_KIND_BADGE_COLORS.get(event.kind, _NEUTRAL_BADGE_COLOR))
            self._list.addItem(item)

    def _summary(self, event: SessionEvent) -> str:
        if event.kind is SessionEventKind.NAVIGATION_TEST_ARRIVED and event.reason:
            x, separator, z = event.reason.partition(",")
            if separator:
                return self._translator.text(Message.UI_NAVIGATION_TEST_ARRIVED, x=x, z=z)
        summary = self._translator.text(
            Message.UI_EVENT_LOG_SUMMARY,
            time=_local_time_text(event.timestamp),
            kind=self._kind_text(event.kind),
            previous=self._mode_text(event.previous_mode),
            new=self._mode_text(event.new_mode),
        )
        if event.reason:
            summary = self._translator.text(
                Message.UI_EVENT_LOG_SUMMARY_WITH_REASON, summary=summary, reason=event.reason
            )
        if event.foreground_window_title:
            summary = self._translator.text(
                Message.UI_EVENT_LOG_SUMMARY_WITH_WINDOW,
                summary=summary,
                title=event.foreground_window_title,
                process=event.foreground_window_process or "",
            )
        return summary

    def _kind_text(self, kind: SessionEventKind) -> str:
        message = _KIND_MESSAGES.get(kind)
        return (
            self._translator.text(message)
            if message is not None
            else str(getattr(kind, "value", kind))
        )

    def _mode_text(self, mode: str) -> str:
        message = _MODE_MESSAGES.get(mode)
        return self._translator.text(message) if message is not None else mode

    def _retranslate(self) -> None:
        self.setTitle(self._translator.text(Message.UI_EVENT_LOG_TITLE))
