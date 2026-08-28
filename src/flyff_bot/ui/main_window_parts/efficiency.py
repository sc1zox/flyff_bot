"""Show what a farming session achieved and, separately, what it spent (US-083 AC9).

Each cost keeps its own row and its own unit. Folding them into one score would hide the very
thing an operator opens this panel to find out -- whether the session is slow because it is
walking, waiting, stalling, or dying -- and there is deliberately no combined "efficiency
score" here for that reason.

The panel can only render what the session measured. A rate that does not exist yet reads as
"not measured" rather than as zero, and there is no row for expected loot at all: the widget
has no way to display a declared drop, so it cannot present one as yield.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel

from flyff_bot.features.telemetry.efficiency import FarmingEfficiencyReport
from flyff_bot.i18n import Message, Translator

# Rendering precision. Seconds and percentages are reported to one decimal because a farming
# session's buckets are seconds-scale, and more digits imply a precision the clocks do not have.
MEASUREMENT_DECIMALS = 1
RATE_DECIMALS = 2


class EfficiencyPanel(QGroupBox):
    """Verified yield over real time, with every cost itemised beside it."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self._rows: dict[Message, tuple[QLabel, QLabel]] = {}
        layout = QGridLayout(self)
        for row, message in enumerate(_ROW_ORDER):
            caption = QLabel()
            caption.setObjectName("StatCaption")
            value = QLabel()
            value.setObjectName("StatChip")
            layout.addWidget(caption, row, 0)
            layout.addWidget(value, row, 1)
            self._rows[message] = (caption, value)
        self._loot_note = QLabel()
        self._loot_note.setObjectName("StatCaption")
        self._loot_note.setWordWrap(True)
        layout.addWidget(self._loot_note, len(_ROW_ORDER), 0, 1, 2)

    def retranslate(self, translator: Translator) -> None:
        """Re-render every caption in the active language."""

        self.setTitle(translator.text(Message.EFFICIENCY_TITLE))
        for message, (caption, _value) in self._rows.items():
            caption.setText(translator.text(message))
        self._loot_note.setText(translator.text(Message.EFFICIENCY_LOOT_UNOBSERVED))

    def render_report(self, translator: Translator, report: FarmingEfficiencyReport) -> None:
        """Show one report, stating plainly where a measurement does not exist."""

        rate = report.verified_kills_per_minute
        self._set(
            Message.EFFICIENCY_VERIFIED_KILLS_PER_MINUTE,
            translator.text(Message.EFFICIENCY_NOT_MEASURED)
            if rate is None
            else f"{rate:.{RATE_DECIMALS}f}",
        )
        self._set(Message.EFFICIENCY_VERIFIED_KILLS, str(report.verified_kills))
        for message, seconds in (
            (Message.EFFICIENCY_TIME_DECISION, report.decision_seconds),
            (Message.EFFICIENCY_TIME_NAVIGATION, report.navigation_seconds),
            (Message.EFFICIENCY_TIME_COMBAT, report.combat_seconds),
            (Message.EFFICIENCY_TIME_IDLE, report.idle_seconds),
            (Message.EFFICIENCY_TIME_STALLED, report.stall_seconds),
            (Message.EFFICIENCY_TIME_UNACCOUNTED, report.unaccounted_seconds),
        ):
            self._set(
                message,
                translator.text(
                    Message.EFFICIENCY_SECONDS_UNIT,
                    seconds=f"{seconds:.{MEASUREMENT_DECIMALS}f}",
                ),
            )
        self._set(
            Message.EFFICIENCY_DISTANCE,
            translator.text(
                Message.EFFICIENCY_UNITS_UNIT,
                units=f"{report.distance_units:.{MEASUREMENT_DECIMALS}f}",
            ),
        )
        self._set(
            Message.EFFICIENCY_DAMAGE_TAKEN,
            translator.text(
                Message.EFFICIENCY_PERCENT_UNIT,
                percent=f"{report.damage_taken_percent:.{MEASUREMENT_DECIMALS}f}",
            ),
        )
        self._set(Message.EFFICIENCY_ACTION_FAILURES, str(report.action_failures))
        self._set(Message.EFFICIENCY_REWARD_CONFIG, report.reward_config_version)
        # Only an observed collection is ever shown as loot value; anything else says so.
        self._set(
            Message.EFFICIENCY_COLLECTED_LOOT,
            translator.text(Message.EFFICIENCY_NOT_MEASURED)
            if report.collected_loot_value is None
            else f"{report.collected_loot_value:.{MEASUREMENT_DECIMALS}f}",
        )

    def _set(self, message: Message, text: str) -> None:
        self._rows[message][1].setText(text)


_ROW_ORDER: tuple[Message, ...] = (
    Message.EFFICIENCY_VERIFIED_KILLS_PER_MINUTE,
    Message.EFFICIENCY_VERIFIED_KILLS,
    Message.EFFICIENCY_TIME_DECISION,
    Message.EFFICIENCY_TIME_NAVIGATION,
    Message.EFFICIENCY_TIME_COMBAT,
    Message.EFFICIENCY_TIME_IDLE,
    Message.EFFICIENCY_TIME_STALLED,
    Message.EFFICIENCY_TIME_UNACCOUNTED,
    Message.EFFICIENCY_DISTANCE,
    Message.EFFICIENCY_DAMAGE_TAKEN,
    Message.EFFICIENCY_ACTION_FAILURES,
    Message.EFFICIENCY_REWARD_CONFIG,
    Message.EFFICIENCY_COLLECTED_LOOT,
)
