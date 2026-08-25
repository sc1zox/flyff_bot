"""Localized dashboard view of the central live-state readiness contract."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flyff_bot.features.automation.readiness import (
    LiveReadinessStatus,
    LiveStateSource,
    ReadinessReason,
    ReadinessState,
    SessionCapability,
    SourceReadiness,
)
from flyff_bot.i18n import Message, Translator

_SOURCE_MESSAGES = {
    LiveStateSource.WINDOW_FOREGROUND: Message.UI_READINESS_SOURCE_FOREGROUND,
    LiveStateSource.PERCEPTION_FRAME: Message.UI_READINESS_SOURCE_FRAME,
    LiveStateSource.GPS: Message.UI_READINESS_SOURCE_GPS,
    LiveStateSource.CAMERA: Message.UI_READINESS_SOURCE_CAMERA,
    LiveStateSource.PLAYER_STATS: Message.UI_READINESS_SOURCE_PLAYER_STATS,
    LiveStateSource.DUNGEON_STATE: Message.UI_READINESS_SOURCE_DUNGEON,
}
_CAPABILITY_MESSAGES = {
    SessionCapability.READ_ONLY_PREVIEW: Message.UI_READINESS_CAPABILITY_PREVIEW,
    SessionCapability.CAMERA_ALIGNMENT: Message.UI_READINESS_CAPABILITY_ALIGNMENT,
    SessionCapability.NAVIGATION: Message.UI_READINESS_CAPABILITY_NAVIGATION,
    SessionCapability.COMBAT: Message.UI_READINESS_CAPABILITY_COMBAT,
    SessionCapability.VITALS: Message.UI_READINESS_CAPABILITY_VITALS,
    SessionCapability.DUNGEON_AUTOMATION: Message.UI_READINESS_CAPABILITY_DUNGEON,
}
_REASON_MESSAGES = {
    ReadinessReason.EMERGENCY_STOP: Message.UI_READINESS_EMERGENCY_STOP,
    ReadinessReason.SHUTDOWN: Message.UI_READINESS_SHUTDOWN,
    ReadinessReason.CLOCK_DISCONTINUITY: Message.UI_READINESS_CLOCK_DISCONTINUITY,
    ReadinessReason.MALFORMED: Message.UI_READINESS_MALFORMED,
    ReadinessReason.UNSUPPORTED: Message.UI_READINESS_UNSUPPORTED,
    ReadinessReason.UNAVAILABLE: Message.UI_READINESS_UNAVAILABLE,
    ReadinessReason.UNREGISTERED: Message.UI_READINESS_UNREGISTERED,
    ReadinessReason.STALE: Message.UI_READINESS_STALE,
}


class ReadinessPanel(QGroupBox):
    """Render every registered provider and its localized action consequence."""

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._status = LiveReadinessStatus()
        self._summary = QLabel()
        self._summary.setObjectName("StatChip")
        self._table = QTableWidget(0, 5, self)
        self._table.setObjectName("ReadinessTable")
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._summary)
        layout.addWidget(self._table)
        self.set_translator(translator)

    @property
    def table(self) -> QTableWidget:
        """Expose the immutable row rendering for focused UI tests."""

        return self._table

    @property
    def summary_label(self) -> QLabel:
        return self._summary

    def set_translator(self, translator: Translator) -> None:
        """Retranslate labels and the current immutable readiness snapshot."""

        self._translator = translator
        self.setTitle(translator.text(Message.UI_READINESS_TITLE))
        for column, message in enumerate(
            (
                Message.UI_READINESS_COLUMN_SOURCE,
                Message.UI_READINESS_COLUMN_HEALTH,
                Message.UI_READINESS_COLUMN_AGE,
                Message.UI_READINESS_COLUMN_CODE,
                Message.UI_READINESS_COLUMN_CONSEQUENCE,
            )
        ):
            self._table.setHorizontalHeaderItem(column, QTableWidgetItem(translator.text(message)))
        self.set_status(self._status)

    def set_status(self, status: LiveReadinessStatus) -> None:
        """Replace the displayed rows from one centrally evaluated status."""

        self._status = status
        self._summary.setText(self._summary_text(status))
        self._table.setRowCount(0)
        for source in status.sources:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = (
                self._translator.text(_SOURCE_MESSAGES[source.source]),
                self._health_text(source),
                self._age_text(source.age_seconds),
                source.diagnostic_code,
                self._consequence_text(source),
            )
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(value))

    def _summary_text(self, status: LiveReadinessStatus) -> str:
        if status.state is ReadinessState.READY:
            return self._translator.text(Message.UI_READINESS_SUMMARY_READY)
        reason = self._reason_text(status.primary_reason)
        if status.state is ReadinessState.CANCELLED:
            return self._translator.text(
                Message.UI_READINESS_SUMMARY_CANCELLED,
                reason=reason,
            )
        source = (
            self._translator.text(_SOURCE_MESSAGES[status.primary_source])
            if status.primary_source is not None
            else self._translator.text(Message.UI_READINESS_NO_SAMPLE)
        )
        return self._translator.text(
            Message.UI_READINESS_SUMMARY_BLOCKED,
            source=source,
            reason=reason,
        )

    def _health_text(self, source: SourceReadiness) -> str:
        if source.reason is not None:
            return self._reason_text(source.reason)
        return self._translator.text(Message.UI_READINESS_HEALTHY)

    def _reason_text(self, reason: ReadinessReason | None) -> str:
        if reason is None:
            return self._translator.text(Message.UI_READINESS_HEALTHY)
        return self._translator.text(_REASON_MESSAGES[reason])

    def _age_text(self, age_seconds: float | None) -> str:
        if age_seconds is None:
            return self._translator.text(Message.UI_READINESS_NO_SAMPLE)
        return self._translator.text(Message.UI_READINESS_AGE, seconds=age_seconds)

    def _consequence_text(self, source: SourceReadiness) -> str:
        if not source.required_by:
            return self._translator.text(Message.UI_READINESS_NO_DEPENDENTS)
        capabilities = ", ".join(
            self._translator.text(_CAPABILITY_MESSAGES[item]) for item in source.required_by
        )
        message = (
            Message.UI_READINESS_AVAILABLE_FOR if source.is_ready else Message.UI_READINESS_BLOCKS
        )
        return self._translator.text(message, capabilities=capabilities)
