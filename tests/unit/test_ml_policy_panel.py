"""The localized ML and policy dashboard view and its rendering rules (US-087)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from flyff_bot.features.policy.action_payloads import StrategicGoalKind, TacticalActionKind
from flyff_bot.features.policy.insights import (
    CandidateInsight,
    CandidateVerdict,
    ChosenActionInsight,
    ModelArtifactIdentity,
    ParameterOverrideInsight,
    PolicyInsightSnapshot,
    ShadowComparison,
)
from flyff_bot.features.policy.models import POLICY_LATENCY_BUDGET_SECONDS, PolicyRuntimeMode
from flyff_bot.features.policy.runner import PolicyFault, PolicyFaultCode
from flyff_bot.features.tactical_parameters import TacticalParameterName
from flyff_bot.features.telemetry.models import SessionExperienceTotals
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.ml_policy_panel import MlPolicyPanel, fault_message, latency_state

ARTIFACT_DIGEST = "a" * 64
CHOSEN_CANDIDATE_INDEX = 1


@pytest.fixture
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _snapshot() -> PolicyInsightSnapshot:
    return PolicyInsightSnapshot(
        mode=PolicyRuntimeMode.ML_ACTIVE,
        artifact=ModelArtifactIdentity(
            "models/policy", "hierarchical-metadata.json", ARTIFACT_DIGEST
        ),
        inference_latency_seconds=0.002,
        candidates=(
            CandidateInsight(0, "Aibatt", distance_units=8.0, verdict=CandidateVerdict.MASKED),
            CandidateInsight(
                CHOSEN_CANDIDATE_INDEX,
                "Burudeng",
                distance_units=12.0,
                is_reachable=True,
                verdict=CandidateVerdict.ALLOWED,
                score=3.25,
                is_chosen=True,
            ),
        ),
        chosen=ChosenActionInsight(
            StrategicGoalKind.TARGET,
            TacticalActionKind.ATTACK_POINT,
            candidate_index=CHOSEN_CANDIDATE_INDEX,
            approach_distance_units=4.5,
        ),
        experience=SessionExperienceTotals(
            reward_config_version="us071-v1",
            storage_path="data/telemetry.sqlite3",
            recorded_records=42,
            decisions=7,
            episode_index=2,
            episode_steps=3,
            episode_reward=-0.4,
            session_reward=1.6,
            kill_reward=2.0,
            navigation_penalty=0.4,
            objective_reward=0.5,
            last_termination_reason="reached_target",
            verified_kills=2,
            elapsed_seconds=60.0,
            navigation_seconds=20.0,
            stall_seconds=6.0,
        ),
        parameter_overrides=(
            ParameterOverrideInsight(TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS, 3.0, 4.5),
            ParameterOverrideInsight(TacticalParameterName.REPLAN_INTERVAL_SECONDS, 20.0, 20.0),
        ),
    )


@pytest.mark.parametrize(
    ("latency_seconds", "expected"),
    [
        (None, "unmeasured"),
        (POLICY_LATENCY_BUDGET_SECONDS, "ok"),
        (POLICY_LATENCY_BUDGET_SECONDS * 1.5, "warn"),
        (POLICY_LATENCY_BUDGET_SECONDS * 4.0, "breach"),
    ],
)
def test_the_latency_chip_states_follow_the_decision_budget(
    latency_seconds: float | None, expected: str
) -> None:
    assert latency_state(latency_seconds) == expected


@pytest.mark.parametrize("code", list(PolicyFaultCode))
def test_every_policy_fault_code_has_a_distinct_localized_name(code: PolicyFaultCode) -> None:
    texts = {
        language: Translator(language).text(fault_message(PolicyFault(code)))
        for language in Language
    }

    assert all(text.strip() for text in texts.values())
    assert all(
        text != Translator(language).text(Message.UI_ML_FAULT_NONE)
        for language, text in texts.items()
    )


def test_an_idle_panel_says_nothing_was_measured_instead_of_showing_zeroes(
    application: QApplication,
) -> None:
    panel = MlPolicyPanel(Translator(Language.ENGLISH))
    application.processEvents()

    translator = Translator(Language.ENGLISH)
    unmeasured = translator.text(Message.UI_ML_VALUE_NOT_MEASURED)
    assert panel.policy_card.value_label(Message.UI_ML_INFERENCE_LATENCY).text() == unmeasured
    assert panel.policy_card.value_label(Message.UI_ML_FAULT_STATUS).text() == translator.text(
        Message.UI_ML_FAULT_NONE
    )
    assert panel.policy_card.value_label(Message.UI_ML_MODEL_DIGEST).text() == translator.text(
        Message.UI_ML_VALUE_HEURISTIC
    )
    assert panel.decision_card.table.rowCount() == 0
    assert panel.decision_card.details.value_label(Message.UI_ML_CHOSEN_GOAL).text() == (
        translator.text(Message.UI_ML_NO_DECISION)
    )
    assert panel.experience_card.value_label(Message.UI_ML_BENCHMARK_KPM).text() == unmeasured


def test_a_served_decision_shows_the_artifact_latency_and_ranked_candidates(
    application: QApplication,
) -> None:
    panel = MlPolicyPanel(Translator(Language.ENGLISH))

    panel.set_snapshot(_snapshot())
    application.processEvents()

    policy_card = panel.policy_card
    assert policy_card.value_label(Message.UI_ML_MODEL_ARTIFACT).text() == (
        "hierarchical-metadata.json"
    )
    assert policy_card.value_label(Message.UI_ML_MODEL_DIGEST).text() == ARTIFACT_DIGEST
    assert policy_card.value_label(Message.UI_ML_INFERENCE_LATENCY).text() == "2.00 ms"
    assert policy_card.value_label(Message.UI_ML_INFERENCE_LATENCY).property("sla") == "ok"

    table = panel.decision_card.table
    assert table.rowCount() == 2
    verdicts = [table.item(row, 5) for row in range(table.rowCount())]
    assert [item.text() if item is not None else "" for item in verdicts] == [
        "Rejected",
        "Allowed",
    ]
    chosen_row = table.item(1, 0)
    assert chosen_row is not None and chosen_row.text() == str(CHOSEN_CANDIDATE_INDEX)
    details = panel.decision_card.details
    assert details.value_label(Message.UI_ML_CHOSEN_ACTION).text() == "Go to attack point"
    assert details.value_label(Message.UI_ML_CHOSEN_APPROACH).text() == "4.5"


def test_reward_experience_and_override_cards_render_the_recorded_session(
    application: QApplication,
) -> None:
    panel = MlPolicyPanel(Translator(Language.ENGLISH))

    panel.set_snapshot(_snapshot())
    application.processEvents()

    reward = panel.reward_card
    assert reward.value_label(Message.UI_ML_REWARD_EPISODE).text() == "2"
    assert reward.value_label(Message.UI_ML_REWARD_STEPS).text() == "3"
    assert reward.value_label(Message.UI_ML_REWARD_SESSION_TOTAL).text() == "1.60"
    assert reward.value_label(Message.UI_ML_REWARD_NAVIGATION).text() == "-0.40"
    assert reward.value_label(Message.UI_ML_REWARD_TERMINATION).text() == "reached_target"

    experience = panel.experience_card
    assert experience.value_label(Message.UI_ML_EXPERIENCE_TRANSITIONS).text() == "7"
    assert experience.value_label(Message.UI_ML_EXPERIENCE_PATH).text() == (
        "data/telemetry.sqlite3"
    )
    assert experience.value_label(Message.UI_ML_BENCHMARK_KPM).text() == "2.00"
    assert experience.value_label(Message.UI_ML_BENCHMARK_STALL).text() == "10.0 %"

    overrides = panel.override_card.table
    assert overrides.rowCount() == 2
    override_flags = [overrides.item(row, 3) for row in range(overrides.rowCount())]
    assert [item.text() if item is not None else "" for item in override_flags] == ["Yes", "No"]


def test_a_shadow_session_shows_both_choices_and_the_running_agreement_rate(
    application: QApplication,
) -> None:
    panel = MlPolicyPanel(Translator(Language.ENGLISH))
    snapshot = _snapshot()

    panel.set_snapshot(
        PolicyInsightSnapshot(
            mode=PolicyRuntimeMode.ML_SHADOW,
            artifact=snapshot.artifact,
            inference_latency_seconds=snapshot.inference_latency_seconds,
            candidates=snapshot.candidates,
            chosen=snapshot.chosen,
            shadow=ShadowComparison(0, 1, agreements=3, disagreements=1),
            experience=snapshot.experience,
        )
    )
    application.processEvents()

    shadow = panel.decision_card.shadow
    assert shadow.isVisibleTo(panel)
    assert shadow.value_label(Message.UI_ML_SHADOW_HEURISTIC).text() == "0"
    assert shadow.value_label(Message.UI_ML_SHADOW_POLICY).text() == "1"
    assert shadow.value_label(Message.UI_ML_SHADOW_AGREEMENT).text() == "75.0 %"


def test_a_fail_closed_fault_is_named_and_carries_its_localized_diagnostic(
    application: QApplication,
) -> None:
    panel = MlPolicyPanel(Translator(Language.ENGLISH))
    fault = PolicyFault(PolicyFaultCode.LATENCY_BUDGET_EXCEEDED)

    panel.set_snapshot(_snapshot(), fault)
    application.processEvents()

    status = panel.policy_card.value_label(Message.UI_ML_FAULT_STATUS)
    assert status.text() == Translator(Language.ENGLISH).text(Message.UI_ML_FAULT_LATENCY)
    assert fault.reason in status.toolTip()


def test_switching_the_language_retranslates_every_header_and_column(
    application: QApplication,
) -> None:
    panel = MlPolicyPanel(Translator(Language.ENGLISH))
    panel.set_snapshot(_snapshot())

    panel.set_translator(Translator(Language.GERMAN))
    application.processEvents()

    german = Translator(Language.GERMAN)
    assert panel.policy_card.title() == german.text(Message.UI_ML_CARD_POLICY)
    assert panel.reward_card.title() == german.text(Message.UI_ML_CARD_REWARD)
    header = panel.decision_card.table.horizontalHeaderItem(0)
    assert header is not None
    assert header.text() == german.text(Message.UI_ML_COLUMN_CANDIDATE)
    override_header = panel.override_card.table.horizontalHeaderItem(1)
    assert override_header is not None
    assert override_header.text() == german.text(Message.UI_ML_COLUMN_BASELINE)
