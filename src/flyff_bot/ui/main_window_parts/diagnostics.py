from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel

from flyff_bot.features.automation.controllers import EngagementBreakReason
from flyff_bot.features.automation.models import (
    SelectedTarget,
    TargetNameStatus,
    TargetState,
)
from flyff_bot.i18n import Message, Translator


def _pass_fail_text(translator: Translator, passed: bool) -> str:
    return translator.text(Message.UI_TARGET_DEBUG_PASS if passed else Message.UI_TARGET_DEBUG_FAIL)


def _target_state_message(state: TargetState) -> Message:
    return {
        TargetState.VALID: Message.UI_TARGET_VALID,
        TargetState.WRONG: Message.UI_TARGET_WRONG,
        TargetState.NONE: Message.UI_TARGET_NONE,
    }[state]


def _engagement_break_message(reason: EngagementBreakReason | None) -> Message:
    if reason is None:
        return Message.UI_TARGET_DEBUG_BREAK_NONE
    return {
        EngagementBreakReason.ACQUISITION_TIMEOUT: Message.UI_TARGET_DEBUG_BREAK_ACQUISITION,
        EngagementBreakReason.TARGET_UNVERIFIED: Message.UI_TARGET_DEBUG_BREAK_UNVERIFIED,
        EngagementBreakReason.ENGAGEMENT_TIMEOUT: Message.UI_TARGET_DEBUG_BREAK_TIMEOUT,
        EngagementBreakReason.OBSTACLE_STALL: Message.UI_TARGET_DEBUG_BREAK_OBSTACLE,
    }[reason]


def _target_failure_reason_message(target: SelectedTarget) -> Message:
    metrics = target.metrics
    if target.state is TargetState.VALID:
        return Message.UI_TARGET_DEBUG_REASON_OK
    if not metrics.anchor_passed:
        return Message.UI_TARGET_DEBUG_REASON_ANCHOR
    if not metrics.hp_passed:
        return Message.UI_TARGET_DEBUG_REASON_HP
    return _target_name_reason_message(metrics.name_status)


def _target_name_reason_message(status: TargetNameStatus) -> Message:
    return {
        TargetNameStatus.NOT_EVALUATED: Message.UI_TARGET_DEBUG_REASON_ANCHOR,
        TargetNameStatus.MATCHED: Message.UI_TARGET_DEBUG_REASON_OK,
        TargetNameStatus.NO_MATCH: Message.UI_TARGET_DEBUG_REASON_NAME,
        TargetNameStatus.UNREADABLE: Message.UI_TARGET_DEBUG_REASON_NAME_UNREADABLE,
        TargetNameStatus.OCR_FAILED: Message.UI_TARGET_DEBUG_REASON_NAME_OCR_FAILED,
        TargetNameStatus.ENGINE_UNAVAILABLE: Message.UI_TARGET_DEBUG_REASON_NAME_ENGINE,
    }[status]


class TargetDebugPanel(QGroupBox):
    """Detailed verification diagnostics for the selected target."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self._labels = {
            key: QLabel() for key in ("anchor", "hp", "name", "state", "reason", "break")
        }
        self._values = {key: QLabel() for key in self._labels}
        for value in self._values.values():
            value.setObjectName("StatChip")

        layout = QGridLayout(self)
        for row, key in enumerate(self._labels):
            layout.addWidget(self._labels[key], row, 0)
            layout.addWidget(self._values[key], row, 1)

    @property
    def anchor_value(self) -> QLabel:
        return self._values["anchor"]

    @property
    def hp_value(self) -> QLabel:
        return self._values["hp"]

    @property
    def name_value(self) -> QLabel:
        return self._values["name"]

    @property
    def state_value(self) -> QLabel:
        return self._values["state"]

    @property
    def reason_value(self) -> QLabel:
        return self._values["reason"]

    @property
    def break_value(self) -> QLabel:
        return self._values["break"]

    def retranslate(self, translator: Translator) -> None:
        titles = {
            "anchor": Message.UI_TARGET_DEBUG_ANCHOR,
            "hp": Message.UI_TARGET_DEBUG_HP,
            "name": Message.UI_TARGET_DEBUG_NAME,
            "state": Message.UI_TARGET_DEBUG_STATE,
            "reason": Message.UI_TARGET_DEBUG_REASON,
            "break": Message.UI_TARGET_DEBUG_BREAK,
        }
        self.setTitle(translator.text(Message.UI_TARGET_DEBUG_TITLE))
        for key, message in titles.items():
            self._labels[key].setText(translator.text(message))

    def render_target(
        self,
        translator: Translator,
        target: SelectedTarget,
        break_reason: EngagementBreakReason | None,
    ) -> None:
        metrics = target.metrics
        self.anchor_value.setText(
            translator.text(
                Message.UI_TARGET_DEBUG_ANCHOR_VALUE,
                status=_pass_fail_text(translator, metrics.anchor_passed),
                score=f"{metrics.anchor_score:.2f}",
                threshold=f"{metrics.anchor_threshold:.2f}",
            )
        )
        self.hp_value.setText(
            translator.text(
                Message.UI_TARGET_DEBUG_HP_VALUE,
                status=_pass_fail_text(translator, metrics.hp_passed),
                pixels=metrics.hp_pixel_count,
                percentage=f"{metrics.hp_percentage:.1f}",
            )
        )
        self.name_value.setText(
            translator.text(Message.UI_TARGET_DEBUG_NAME_NOT_EVALUATED)
            if metrics.name_status is TargetNameStatus.NOT_EVALUATED
            else translator.text(
                Message.UI_TARGET_DEBUG_NAME_VALUE,
                status=_pass_fail_text(translator, metrics.name_passed),
                text=metrics.name_text,
                name=metrics.name_candidate or translator.text(Message.UI_NO_TARGET_NAME),
            )
        )
        self.state_value.setText(translator.text(_target_state_message(target.state)))
        self.reason_value.setText(translator.text(_target_failure_reason_message(target)))
        self.break_value.setText(translator.text(_engagement_break_message(break_reason)))
