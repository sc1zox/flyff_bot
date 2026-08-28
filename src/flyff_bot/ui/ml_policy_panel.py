"""The operator-facing ML and policy view: what the policy decided, and what it cost (US-087).

Every widget here renders one immutable :class:`PolicyInsightSnapshot` that the farming worker
already finished producing. Nothing in this module reads live session state, blocks, or calls
back into the worker thread, so a slow or hidden view can never delay a decision (ADR-002).

A value the session did not measure is shown as "not measured" rather than as zero. Reading a
zero where nothing was observed is how an operator concludes that a policy is fast, a baseline
agrees, or a session is idle when in truth none of that was ever established.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

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
from flyff_bot.features.telemetry.models import SessionExperienceTotals
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.main_window_parts.combat_settings import policy_fault_text
from flyff_bot.ui.main_window_parts.tactical_parameters import (
    PARAMETER_MESSAGES,
    format_number,
)

MILLISECONDS_PER_SECOND = 1000.0
# The service level the latency chip reports against. The budget itself is the policy contract
# (US-086); twice the budget is the point at which a decision is late enough that the operator
# should be looking at the machine, not at the model.
LATENCY_WARNING_FACTOR = 2.0
LATENCY_DECIMALS = 2
REWARD_DECIMALS = 2
RATE_DECIMALS = 2
PERCENT_DECIMALS = 1
PERCENT_SCALE = 100.0

_MODE_MESSAGES = {
    PolicyRuntimeMode.HEURISTIC: Message.UI_POLICY_MODE_HEURISTIC,
    PolicyRuntimeMode.ML_SHADOW: Message.UI_POLICY_MODE_SHADOW,
    PolicyRuntimeMode.ML_ACTIVE: Message.UI_POLICY_MODE_ACTIVE,
}
_FAULT_MESSAGES = {
    PolicyFaultCode.MODEL_UNAVAILABLE: Message.UI_ML_FAULT_MODEL_UNAVAILABLE,
    PolicyFaultCode.NO_VALID_ACTION: Message.UI_ML_FAULT_NO_VALID_ACTION,
    PolicyFaultCode.INVALID_OR_MASKED_ACTION: Message.UI_ML_FAULT_MASKED_ACTION,
    PolicyFaultCode.LATENCY_BUDGET_EXCEEDED: Message.UI_ML_FAULT_LATENCY,
    PolicyFaultCode.POLICY_EXCEPTION: Message.UI_ML_FAULT_EXCEPTION,
}
_GOAL_MESSAGES = {
    StrategicGoalKind.TARGET: Message.UI_ML_GOAL_TARGET,
    StrategicGoalKind.NAVIGATE: Message.UI_ML_GOAL_NAVIGATE,
    StrategicGoalKind.INTERACT: Message.UI_ML_GOAL_INTERACT,
    StrategicGoalKind.WAIT: Message.UI_ML_GOAL_WAIT,
}
_ACTION_MESSAGES = {
    TacticalActionKind.TARGET: Message.UI_ML_ACTION_TARGET,
    TacticalActionKind.NAVIGATE: Message.UI_ML_ACTION_NAVIGATE,
    TacticalActionKind.ATTACK_POINT: Message.UI_ML_ACTION_ATTACK_POINT,
    TacticalActionKind.CORRIDOR: Message.UI_ML_ACTION_CORRIDOR,
    TacticalActionKind.INTERACT: Message.UI_ML_ACTION_INTERACT,
    TacticalActionKind.WAIT: Message.UI_ML_ACTION_WAIT,
}
_VERDICT_MESSAGES = {
    CandidateVerdict.ALLOWED: Message.UI_ML_VERDICT_ALLOWED,
    CandidateVerdict.MASKED: Message.UI_ML_VERDICT_MASKED,
}

_CANDIDATE_COLUMNS = (
    Message.UI_ML_COLUMN_CANDIDATE,
    Message.UI_ML_COLUMN_CLASS,
    Message.UI_ML_COLUMN_DISTANCE,
    Message.UI_ML_COLUMN_REACHABLE,
    Message.UI_ML_COLUMN_SCORE,
    Message.UI_ML_COLUMN_VERDICT,
)
_OVERRIDE_COLUMNS = (
    Message.UI_ML_COLUMN_PARAMETER,
    Message.UI_ML_COLUMN_BASELINE,
    Message.UI_ML_COLUMN_ACTIVE,
    Message.UI_ML_COLUMN_OVERRIDE,
)


def latency_state(latency_seconds: float | None) -> str:
    """Return the service-level state one measured inference latency falls into."""

    if latency_seconds is None:
        return "unmeasured"
    if latency_seconds <= POLICY_LATENCY_BUDGET_SECONDS:
        return "ok"
    if latency_seconds <= POLICY_LATENCY_BUDGET_SECONDS * LATENCY_WARNING_FACTOR:
        return "warn"
    return "breach"


def fault_message(fault: PolicyFault | None) -> Message:
    """Return the localized name of the active fault, or of the absence of one."""

    if fault is None:
        return Message.UI_ML_FAULT_NONE
    return _FAULT_MESSAGES[fault.code]


class _RowCard(QGroupBox):
    """A card of caption and value rows, retranslated from the state it currently holds."""

    def __init__(self, title: Message, rows: tuple[Message, ...]) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self._title = title
        self._rows: dict[Message, tuple[QLabel, QLabel]] = {}
        layout = QGridLayout(self)
        for index, message in enumerate(rows):
            caption = QLabel()
            caption.setObjectName("StatCaption")
            value = QLabel()
            value.setObjectName("StatChip")
            value.setWordWrap(True)
            layout.addWidget(caption, index, 0)
            layout.addWidget(value, index, 1)
            self._rows[message] = (caption, value)

    def value_label(self, message: Message) -> QLabel:
        """Expose one value widget for focused UI assertions."""

        return self._rows[message][1]

    def retranslate_captions(self, translator: Translator) -> None:
        """Re-render every caption; values are rewritten by the owning card's render."""

        self.setTitle(translator.text(self._title))
        for message, (caption, _value) in self._rows.items():
            caption.setText(translator.text(message))

    def set_value(self, message: Message, text: str) -> None:
        """Write one already-formatted value."""

        self._rows[message][1].setText(text)


class PolicyTelemetryCard(_RowCard):
    """The active mode, the loaded artifact, the decision latency and the fault state."""

    def __init__(self) -> None:
        super().__init__(
            Message.UI_ML_CARD_POLICY,
            (
                Message.UI_ML_POLICY_MODE,
                Message.UI_ML_MODEL_DIRECTORY,
                Message.UI_ML_MODEL_ARTIFACT,
                Message.UI_ML_MODEL_DIGEST,
                Message.UI_ML_INFERENCE_LATENCY,
                Message.UI_ML_FAULT_STATUS,
            ),
        )
        self._latency_label = self.value_label(Message.UI_ML_INFERENCE_LATENCY)

    def render_snapshot(
        self,
        translator: Translator,
        snapshot: PolicyInsightSnapshot,
        fault: PolicyFault | None,
    ) -> None:
        """Show one snapshot's serving state and the diagnostic behind any fault."""

        self.retranslate_captions(translator)
        self.set_value(Message.UI_ML_POLICY_MODE, translator.text(_MODE_MESSAGES[snapshot.mode]))
        heuristic = translator.text(Message.UI_ML_VALUE_HEURISTIC)
        artifact = snapshot.artifact
        self.set_value(Message.UI_ML_MODEL_DIRECTORY, artifact.directory or heuristic)
        self.set_value(Message.UI_ML_MODEL_ARTIFACT, _artifact_document(translator, artifact))
        self.set_value(Message.UI_ML_MODEL_DIGEST, artifact.sha256 or heuristic)
        self.set_value(Message.UI_ML_INFERENCE_LATENCY, _latency_text(translator, snapshot))
        self._latency_label.setToolTip(translator.text(Message.UI_ML_INFERENCE_LATENCY_TOOLTIP))
        self._apply_latency_state(latency_state(snapshot.inference_latency_seconds))
        status = self.value_label(Message.UI_ML_FAULT_STATUS)
        status.setText(translator.text(fault_message(fault)))
        status.setToolTip("" if fault is None else policy_fault_text(translator, fault))

    def _apply_latency_state(self, state: str) -> None:
        self._latency_label.setProperty("sla", state)
        style = self._latency_label.style()
        style.unpolish(self._latency_label)
        style.polish(self._latency_label)


class DecisionInspectorCard(QGroupBox):
    """The ranked option set, the chosen parameterized action and the shadow comparison."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self.table = QTableWidget(0, len(_CANDIDATE_COLUMNS), self)
        self.table.setObjectName("CandidateTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self._details = _RowCard(
            Message.UI_ML_CHOSEN_ACTION_TITLE,
            (
                Message.UI_ML_CHOSEN_GOAL,
                Message.UI_ML_CHOSEN_ACTION,
                Message.UI_ML_CHOSEN_CANDIDATE,
                Message.UI_ML_CHOSEN_APPROACH,
                Message.UI_ML_CHOSEN_CORRIDOR,
                Message.UI_ML_CHOSEN_WAIT,
            ),
        )
        self._shadow = _RowCard(
            Message.UI_ML_SHADOW_TITLE,
            (
                Message.UI_ML_SHADOW_HEURISTIC,
                Message.UI_ML_SHADOW_POLICY,
                Message.UI_ML_SHADOW_AGREEMENT,
            ),
        )
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self._details)
        layout.addWidget(self._shadow)

    @property
    def details(self) -> _RowCard:
        """Expose the chosen-action rows for focused UI assertions."""

        return self._details

    @property
    def shadow(self) -> _RowCard:
        """Expose the shadow comparison rows for focused UI assertions."""

        return self._shadow

    def render_snapshot(self, translator: Translator, snapshot: PolicyInsightSnapshot) -> None:
        """Replace every row from one immutable decision snapshot."""

        self.setTitle(translator.text(Message.UI_ML_CARD_DECISION))
        for column, message in enumerate(_CANDIDATE_COLUMNS):
            self.table.setHorizontalHeaderItem(column, QTableWidgetItem(translator.text(message)))
        self.table.setRowCount(0)
        for candidate in snapshot.candidates:
            self._append_candidate(translator, candidate)
        self._render_details(translator, snapshot.chosen)
        self._render_shadow(translator, snapshot.shadow)

    def _append_candidate(self, translator: Translator, candidate: CandidateInsight) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        unmeasured = translator.text(Message.UI_ML_VALUE_NOT_MEASURED)
        cells = (
            str(candidate.candidate_index),
            candidate.class_name,
            (
                unmeasured
                if candidate.distance_units is None
                else format_number(candidate.distance_units)
            ),
            translator.text(Message.UI_ML_YES if candidate.is_reachable else Message.UI_ML_NO),
            unmeasured if candidate.score is None else format_number(candidate.score),
            translator.text(_VERDICT_MESSAGES[candidate.verdict]),
        )
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if candidate.is_chosen:
                item.setToolTip(translator.text(Message.UI_ML_CHOSEN_CANDIDATE_TOOLTIP))
            self.table.setItem(row, column, item)
        if candidate.is_chosen:
            self.table.selectRow(row)

    def _render_details(self, translator: Translator, chosen: ChosenActionInsight | None) -> None:
        self._details.retranslate_captions(translator)
        if chosen is None:
            none_text = translator.text(Message.UI_ML_NO_DECISION)
            for message in (
                Message.UI_ML_CHOSEN_GOAL,
                Message.UI_ML_CHOSEN_ACTION,
                Message.UI_ML_CHOSEN_CANDIDATE,
                Message.UI_ML_CHOSEN_APPROACH,
                Message.UI_ML_CHOSEN_CORRIDOR,
                Message.UI_ML_CHOSEN_WAIT,
            ):
                self._details.set_value(message, none_text)
            return
        unmeasured = translator.text(Message.UI_ML_VALUE_NOT_MEASURED)
        self._details.set_value(
            Message.UI_ML_CHOSEN_GOAL, translator.text(_GOAL_MESSAGES[chosen.goal])
        )
        self._details.set_value(
            Message.UI_ML_CHOSEN_ACTION, translator.text(_ACTION_MESSAGES[chosen.action_kind])
        )
        self._details.set_value(
            Message.UI_ML_CHOSEN_CANDIDATE,
            unmeasured if chosen.candidate_index is None else str(chosen.candidate_index),
        )
        self._details.set_value(
            Message.UI_ML_CHOSEN_APPROACH,
            (
                unmeasured
                if chosen.approach_distance_units is None
                else format_number(chosen.approach_distance_units)
            ),
        )
        self._details.set_value(Message.UI_ML_CHOSEN_CORRIDOR, chosen.corridor_id or unmeasured)
        self._details.set_value(
            Message.UI_ML_CHOSEN_WAIT,
            unmeasured if chosen.wait_seconds is None else format_number(chosen.wait_seconds),
        )

    def _render_shadow(self, translator: Translator, shadow: ShadowComparison | None) -> None:
        self._shadow.retranslate_captions(translator)
        self._shadow.setVisible(shadow is not None)
        if shadow is None:
            return
        inactive = translator.text(Message.UI_ML_VALUE_NOT_MEASURED)
        self._shadow.set_value(
            Message.UI_ML_SHADOW_HEURISTIC,
            inactive
            if shadow.heuristic_candidate_index is None
            else str(shadow.heuristic_candidate_index),
        )
        self._shadow.set_value(
            Message.UI_ML_SHADOW_POLICY,
            inactive
            if shadow.policy_candidate_index is None
            else str(shadow.policy_candidate_index),
        )
        rate = shadow.agreement_rate
        self._shadow.set_value(
            Message.UI_ML_SHADOW_AGREEMENT,
            inactive if rate is None else f"{rate * PERCENT_SCALE:.{PERCENT_DECIMALS}f} %",
        )


class RewardTelemetryCard(_RowCard):
    """Episode progress and the decomposed reward the session actually accrued."""

    def __init__(self) -> None:
        super().__init__(
            Message.UI_ML_CARD_REWARD,
            (
                Message.UI_ML_REWARD_EPISODE,
                Message.UI_ML_REWARD_STEPS,
                Message.UI_ML_REWARD_EPISODE_TOTAL,
                Message.UI_ML_REWARD_SESSION_TOTAL,
                Message.UI_ML_REWARD_KILLS,
                Message.UI_ML_REWARD_NAVIGATION,
                Message.UI_ML_REWARD_OBJECTIVE,
                Message.UI_ML_REWARD_TERMINATION,
            ),
        )

    def render_totals(self, translator: Translator, totals: SessionExperienceTotals) -> None:
        """Show one session's reward accounting exactly as it was recorded."""

        self.retranslate_captions(translator)
        self.set_value(Message.UI_ML_REWARD_EPISODE, str(totals.episode_index))
        self.set_value(Message.UI_ML_REWARD_STEPS, str(totals.episode_steps))
        self.set_value(
            Message.UI_ML_REWARD_EPISODE_TOTAL, f"{totals.episode_reward:.{REWARD_DECIMALS}f}"
        )
        self.set_value(
            Message.UI_ML_REWARD_SESSION_TOTAL, f"{totals.session_reward:.{REWARD_DECIMALS}f}"
        )
        self.set_value(Message.UI_ML_REWARD_KILLS, f"{totals.kill_reward:.{REWARD_DECIMALS}f}")
        self.set_value(
            Message.UI_ML_REWARD_NAVIGATION, f"-{totals.navigation_penalty:.{REWARD_DECIMALS}f}"
        )
        self.set_value(
            Message.UI_ML_REWARD_OBJECTIVE, f"{totals.objective_reward:.{REWARD_DECIMALS}f}"
        )
        self.set_value(
            Message.UI_ML_REWARD_TERMINATION,
            totals.last_termination_reason or translator.text(Message.UI_ML_VALUE_NOT_MEASURED),
        )


class ExperienceCard(_RowCard):
    """What the session contributed to the experience record, and what it achieved."""

    def __init__(self) -> None:
        super().__init__(
            Message.UI_ML_CARD_EXPERIENCE,
            (
                Message.UI_ML_EXPERIENCE_TRANSITIONS,
                Message.UI_ML_EXPERIENCE_EPISODES,
                Message.UI_ML_EXPERIENCE_PATH,
                Message.UI_ML_EXPERIENCE_RECORDS,
                Message.UI_ML_EXPERIENCE_DROPPED,
                Message.UI_ML_EXPERIENCE_SCHEMA,
                Message.UI_ML_BENCHMARK_KPM,
                Message.UI_ML_BENCHMARK_TRAVEL,
                Message.UI_ML_BENCHMARK_STALL,
            ),
        )

    def render_totals(self, translator: Translator, totals: SessionExperienceTotals) -> None:
        """Show the recorded volume beside the measured farming benchmarks."""

        self.retranslate_captions(translator)
        unmeasured = translator.text(Message.UI_ML_VALUE_NOT_MEASURED)
        self.set_value(Message.UI_ML_EXPERIENCE_TRANSITIONS, str(totals.decisions))
        self.set_value(Message.UI_ML_EXPERIENCE_EPISODES, str(totals.episode_index))
        self.set_value(Message.UI_ML_EXPERIENCE_PATH, totals.storage_path or unmeasured)
        self.set_value(Message.UI_ML_EXPERIENCE_RECORDS, str(totals.recorded_records))
        self.set_value(Message.UI_ML_EXPERIENCE_DROPPED, str(totals.dropped_records))
        self.set_value(Message.UI_ML_EXPERIENCE_SCHEMA, str(totals.schema_version))
        self.set_value(Message.UI_ML_BENCHMARK_KPM, _rate_text(totals.kills_per_minute, unmeasured))
        self.set_value(
            Message.UI_ML_BENCHMARK_TRAVEL,
            _rate_text(totals.navigation_seconds_per_kill, unmeasured),
        )
        stall_rate = totals.stall_rate
        self.set_value(
            Message.UI_ML_BENCHMARK_STALL,
            unmeasured
            if stall_rate is None
            else f"{stall_rate * PERCENT_SCALE:.{PERCENT_DECIMALS}f} %",
        )


class ParameterOverrideCard(QGroupBox):
    """The configured tactical baseline beside the value a learned decision used."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self.table = QTableWidget(0, len(_OVERRIDE_COLUMNS), self)
        self.table.setObjectName("ParameterOverrideTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)

    def render_overrides(
        self, translator: Translator, overrides: tuple[ParameterOverrideInsight, ...]
    ) -> None:
        """Replace every row; an unmodulated parameter still states its baseline."""

        self.setTitle(translator.text(Message.UI_ML_CARD_OVERRIDES))
        for column, message in enumerate(_OVERRIDE_COLUMNS):
            self.table.setHorizontalHeaderItem(column, QTableWidgetItem(translator.text(message)))
        self.table.setRowCount(0)
        for override in overrides:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_message, tooltip_message = PARAMETER_MESSAGES[override.parameter]
            name_item = QTableWidgetItem(translator.text(name_message))
            name_item.setToolTip(translator.text(tooltip_message))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(format_number(override.baseline)))
            self.table.setItem(row, 2, QTableWidgetItem(format_number(override.active)))
            self.table.setItem(
                row,
                3,
                QTableWidgetItem(
                    translator.text(
                        Message.UI_ML_YES if override.is_overridden else Message.UI_ML_NO
                    )
                ),
            )


class MlPolicyPanel(QWidget):
    """The whole ML and policy view, rendered from one snapshot per published tick."""

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._snapshot = PolicyInsightSnapshot()
        self._fault: PolicyFault | None = None
        self.policy_card = PolicyTelemetryCard()
        self.decision_card = DecisionInspectorCard()
        self.reward_card = RewardTelemetryCard()
        self.experience_card = ExperienceCard()
        self.override_card = ParameterOverrideCard()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for card in (
            self.policy_card,
            self.decision_card,
            self.reward_card,
            self.experience_card,
            self.override_card,
        ):
            layout.addWidget(card)
        self._render()

    def set_translator(self, translator: Translator) -> None:
        """Retranslate every card from the snapshot currently held."""

        self._translator = translator
        self._render()

    def set_snapshot(
        self, snapshot: PolicyInsightSnapshot, fault: PolicyFault | None = None
    ) -> None:
        """Adopt one immutable snapshot published by the farming worker."""

        self._snapshot = snapshot
        self._fault = fault
        self._render()

    def _render(self) -> None:
        translator = self._translator
        snapshot = self._snapshot
        self.policy_card.render_snapshot(translator, snapshot, self._fault)
        self.decision_card.render_snapshot(translator, snapshot)
        self.reward_card.render_totals(translator, snapshot.experience)
        self.experience_card.render_totals(translator, snapshot.experience)
        self.override_card.render_overrides(translator, snapshot.parameter_overrides)


def _artifact_document(translator: Translator, artifact: ModelArtifactIdentity) -> str:
    """Return the artifact document name, or why there is none to name."""

    if artifact.is_loaded:
        return artifact.filename
    if artifact.directory:
        return translator.text(Message.UI_ML_VALUE_NO_ARTIFACT_DOCUMENT)
    return translator.text(Message.UI_ML_VALUE_HEURISTIC)


def _latency_text(translator: Translator, snapshot: PolicyInsightSnapshot) -> str:
    """Return the measured inference latency in milliseconds, or that none was measured."""

    latency = snapshot.inference_latency_seconds
    if latency is None:
        return translator.text(Message.UI_ML_VALUE_NOT_MEASURED)
    return f"{latency * MILLISECONDS_PER_SECOND:.{LATENCY_DECIMALS}f} ms"


def _rate_text(value: float | None, unmeasured: str) -> str:
    """Return one measured rate, or the caller's localized "not measured" text."""

    return unmeasured if value is None else f"{value:.{RATE_DECIMALS}f}"
