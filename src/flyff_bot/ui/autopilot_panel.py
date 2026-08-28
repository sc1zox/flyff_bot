"""Localized dashboard view and arming control for one unattended session (US-086)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout, QWidget

from flyff_bot.features.automation.autopilot import (
    AutopilotCompletionReason,
    AutopilotGoalKind,
    AutopilotSnapshot,
    AutopilotSummary,
)
from flyff_bot.i18n import Message, Translator

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60

_GOAL_MESSAGES = {
    AutopilotGoalKind.CONTINUE_QUEST: Message.UI_AUTOPILOT_GOAL_CONTINUE_QUEST,
    AutopilotGoalKind.FARM_QUEST_OBJECTIVE: Message.UI_AUTOPILOT_GOAL_FARM_QUEST_OBJECTIVE,
    AutopilotGoalKind.TURN_IN_QUEST: Message.UI_AUTOPILOT_GOAL_TURN_IN_QUEST,
    AutopilotGoalKind.ACCEPT_QUEST: Message.UI_AUTOPILOT_GOAL_ACCEPT_QUEST,
    AutopilotGoalKind.FALLBACK_FARM: Message.UI_AUTOPILOT_GOAL_FALLBACK_FARM,
}
_COMPLETION_MESSAGES = {
    AutopilotCompletionReason.TIME_BUDGET: Message.UI_AUTOPILOT_REASON_TIME_BUDGET,
    AutopilotCompletionReason.RECOVERY_BUDGET: Message.UI_AUTOPILOT_REASON_RECOVERY_BUDGET,
    AutopilotCompletionReason.TICK_FAULT_BUDGET: Message.UI_AUTOPILOT_REASON_TICK_FAULT_BUDGET,
    AutopilotCompletionReason.CLIENT_ABSENCE: Message.UI_AUTOPILOT_REASON_CLIENT_ABSENCE,
}


def format_duration(seconds: float) -> str:
    """Return a whole-second ``H:MM:SS`` duration, which needs no translation."""

    total = max(0, int(seconds))
    hours, remainder = divmod(total, SECONDS_PER_MINUTE * MINUTES_PER_HOUR)
    minutes, whole_seconds = divmod(remainder, SECONDS_PER_MINUTE)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}"


def goal_text(translator: Translator, snapshot: AutopilotSnapshot) -> str:
    """Return the localized sentence naming the goal the session is pursuing."""

    if snapshot.goal is None:
        return translator.text(Message.UI_AUTOPILOT_GOAL_NONE)
    return translator.text(
        Message.UI_AUTOPILOT_GOAL,
        goal=translator.text(_GOAL_MESSAGES[snapshot.goal.goal]),
    )


def budget_text(translator: Translator, snapshot: AutopilotSnapshot) -> str:
    """Return the localized elapsed and remaining session budget."""

    if snapshot.remaining_seconds is None:
        return translator.text(Message.UI_AUTOPILOT_BUDGET_IDLE)
    return translator.text(
        Message.UI_AUTOPILOT_BUDGET,
        elapsed=format_duration(snapshot.elapsed_seconds),
        remaining=format_duration(snapshot.remaining_seconds),
    )


def fault_text(translator: Translator, snapshot: AutopilotSnapshot) -> str:
    """Return the localized last contained fault and when it happened."""

    if snapshot.last_fault is None or snapshot.last_fault_at_seconds is None:
        return translator.text(Message.UI_AUTOPILOT_NO_FAULT)
    return translator.text(
        Message.UI_AUTOPILOT_LAST_FAULT,
        time=format_duration(snapshot.last_fault_at_seconds),
        fault=snapshot.last_fault,
    )


def summary_text(translator: Translator, summary: AutopilotSummary) -> str:
    """Return the localized completion sentence of one finished session."""

    return translator.text(
        Message.UI_AUTOPILOT_SUMMARY,
        duration=format_duration(summary.duration_seconds),
        kills=summary.kills,
        quests=summary.completed_quests,
        deaths=summary.deaths,
        recoveries=summary.recoveries,
        reason=translator.text(_COMPLETION_MESSAGES[summary.reason]),
    )


class AutopilotPanel(QGroupBox):
    """Arm one unattended session and show whether it is still working."""

    arm_requested = Signal()

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardPanel")
        self._translator = translator
        self._snapshot = AutopilotSnapshot()
        self._summary: AutopilotSummary | None = None
        self._stalled = False
        self.arm_button = QPushButton()
        self.arm_button.setObjectName("ActionStart")
        self.arm_button.clicked.connect(self.arm_requested.emit)
        self.state_label = QLabel()
        self.state_label.setObjectName("StatChip")
        self.goal_label = QLabel()
        self.goal_label.setObjectName("StatChip")
        self.goal_label.setWordWrap(True)
        self.budget_label = QLabel()
        self.budget_label.setObjectName("StatChip")
        self.counters_label = QLabel()
        self.counters_label.setObjectName("StatChip")
        self.fault_label = QLabel()
        self.fault_label.setObjectName("StatChip")
        self.fault_label.setWordWrap(True)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("StatChip")
        self.summary_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.arm_button)
        for label in (
            self.state_label,
            self.goal_label,
            self.budget_label,
            self.counters_label,
            self.fault_label,
            self.summary_label,
        ):
            layout.addWidget(label)
        self.set_translator(translator)

    def set_translator(self, translator: Translator) -> None:
        """Retranslate every label from the state currently held."""

        self._translator = translator
        self.setTitle(translator.text(Message.UI_CARD_AUTOPILOT))
        self.arm_button.setText(translator.text(Message.UI_AUTOPILOT_ARM))
        self._render()

    def set_arming_allowed(self, allowed: bool, *, refusal: str = "") -> None:
        """Refuse arming with the same localized reason the start button carries."""

        self.arm_button.setEnabled(allowed)
        self.arm_button.setToolTip(
            self._translator.text(Message.UI_AUTOPILOT_ARM_TOOLTIP) if allowed else refusal
        )

    def set_snapshot(self, snapshot: AutopilotSnapshot, summary: AutopilotSummary | None) -> None:
        """Adopt one immutable unattended-session state published by the worker."""

        self._snapshot = snapshot
        self._summary = summary
        self._render()

    def set_worker_stalled(self, stalled: bool) -> None:
        """Say that the worker stopped publishing ticks rather than showing stale state."""

        self._stalled = stalled
        self._render()

    def _render(self) -> None:
        translator = self._translator
        snapshot = self._snapshot
        if self._stalled:
            self.state_label.setText(translator.text(Message.UI_AUTOPILOT_WORKER_STALLED))
        else:
            self.state_label.setText(
                translator.text(
                    Message.UI_AUTOPILOT_STATE_ARMED
                    if snapshot.armed
                    else Message.UI_AUTOPILOT_STATE_DISARMED
                )
            )
        self.goal_label.setText(goal_text(translator, snapshot))
        self.budget_label.setText(budget_text(translator, snapshot))
        self.counters_label.setText(
            translator.text(
                Message.UI_AUTOPILOT_COUNTERS,
                deaths=snapshot.deaths,
                recoveries=snapshot.recoveries,
            )
        )
        self.fault_label.setText(fault_text(translator, snapshot))
        self.summary_label.setText(
            "" if self._summary is None else summary_text(translator, self._summary)
        )
