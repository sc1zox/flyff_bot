"""Localized unattended-session dashboard card and its arming control (US-086)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from flyff_bot.features.automation.autopilot import (
    AutopilotCompletionReason,
    AutopilotGoalDecision,
    AutopilotGoalKind,
    AutopilotGoalReason,
    AutopilotSnapshot,
    AutopilotSummary,
)
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.autopilot_panel import AutopilotPanel, format_duration

REFUSAL = "Finish setup first."


@pytest.fixture
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, "0:00:00"), (59.4, "0:00:59"), (3_600.0, "1:00:00"), (-5.0, "0:00:00")],
)
def test_durations_are_rendered_without_needing_translation(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_an_idle_panel_says_no_goal_and_no_budget(application: QApplication) -> None:
    panel = AutopilotPanel(Translator(Language.ENGLISH))
    application.processEvents()

    translator = Translator(Language.ENGLISH)
    assert panel.state_label.text() == translator.text(Message.UI_AUTOPILOT_STATE_DISARMED)
    assert panel.goal_label.text() == translator.text(Message.UI_AUTOPILOT_GOAL_NONE)
    assert panel.budget_label.text() == translator.text(Message.UI_AUTOPILOT_BUDGET_IDLE)
    assert panel.fault_label.text() == translator.text(Message.UI_AUTOPILOT_NO_FAULT)
    assert panel.summary_label.text() == ""


def test_an_armed_session_shows_goal_budget_counters_and_the_last_fault(
    application: QApplication,
) -> None:
    panel = AutopilotPanel(Translator(Language.ENGLISH))

    panel.set_snapshot(
        AutopilotSnapshot(
            armed=True,
            started_at_seconds=0.0,
            elapsed_seconds=90.0,
            remaining_seconds=30.0,
            goal=AutopilotGoalDecision(
                AutopilotGoalKind.FALLBACK_FARM, AutopilotGoalReason.NO_EXECUTABLE_QUEST
            ),
            deaths=2,
            recoveries=3,
            last_fault="RuntimeError: boom",
            last_fault_at_seconds=61.0,
        ),
        None,
    )
    application.processEvents()

    assert "0:01:30" in panel.budget_label.text()
    assert "0:00:30" in panel.budget_label.text()
    assert "2" in panel.counters_label.text() and "3" in panel.counters_label.text()
    assert "RuntimeError: boom" in panel.fault_label.text()
    assert "0:01:01" in panel.fault_label.text()
    assert panel.goal_label.text() != ""


@pytest.mark.parametrize("goal", list(AutopilotGoalKind))
def test_every_goal_has_a_distinct_localized_sentence_in_both_languages(
    application: QApplication, goal: AutopilotGoalKind
) -> None:
    texts = set()
    for language in Language:
        panel = AutopilotPanel(Translator(language))
        panel.set_snapshot(
            AutopilotSnapshot(
                armed=True,
                goal=AutopilotGoalDecision(goal, AutopilotGoalReason.ACTIVE_QUEST),
            ),
            None,
        )
        application.processEvents()
        texts.add(panel.goal_label.text())

    assert len(texts) == len(Language)
    assert all(text.strip() for text in texts)


@pytest.mark.parametrize("reason", list(AutopilotCompletionReason))
def test_every_completion_reason_renders_a_full_summary_sentence(
    application: QApplication, reason: AutopilotCompletionReason
) -> None:
    panel = AutopilotPanel(Translator(Language.GERMAN))

    panel.set_snapshot(
        AutopilotSnapshot(completion_reason=reason),
        AutopilotSummary(7_200.0, 42, 3, 1, 2, reason),
    )
    application.processEvents()

    summary = panel.summary_label.text()
    assert "2:00:00" in summary
    assert "42" in summary and "3" in summary
    assert summary.endswith(".")


def test_arming_is_refused_with_the_same_reason_the_start_button_carries(
    application: QApplication,
) -> None:
    panel = AutopilotPanel(Translator(Language.ENGLISH))

    panel.set_arming_allowed(False, refusal=REFUSAL)
    application.processEvents()

    assert not panel.arm_button.isEnabled()
    assert panel.arm_button.toolTip() == REFUSAL

    panel.set_arming_allowed(True)
    application.processEvents()

    assert panel.arm_button.isEnabled()
    assert panel.arm_button.toolTip() == Translator(Language.ENGLISH).text(
        Message.UI_AUTOPILOT_ARM_TOOLTIP
    )


def test_the_arm_button_emits_one_request(application: QApplication) -> None:
    panel = AutopilotPanel(Translator(Language.ENGLISH))
    requests: list[int] = []
    panel.arm_requested.connect(lambda: requests.append(1))

    panel.arm_button.click()
    application.processEvents()

    assert requests == [1]


def test_a_stalled_worker_replaces_the_state_line_instead_of_showing_stale_state(
    application: QApplication,
) -> None:
    panel = AutopilotPanel(Translator(Language.ENGLISH))
    panel.set_snapshot(AutopilotSnapshot(armed=True), None)

    panel.set_worker_stalled(True)
    application.processEvents()

    assert panel.state_label.text() == Translator(Language.ENGLISH).text(
        Message.UI_AUTOPILOT_WORKER_STALLED
    )


def test_switching_language_retranslates_the_card(application: QApplication) -> None:
    panel = AutopilotPanel(Translator(Language.ENGLISH))
    english = panel.arm_button.text()

    panel.set_translator(Translator(Language.GERMAN))
    application.processEvents()

    assert panel.arm_button.text() != english
    assert panel.title() == Translator(Language.GERMAN).text(Message.UI_CARD_AUTOPILOT)
