from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel

from flyff_bot.features.automation.kill_goals import MobKillProgress
from flyff_bot.features.automation.models import PlayerVitals
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.main_window_parts.header import kill_progress_text


class DashboardSummary(QGroupBox):
    """Persistent top-level automation metrics."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self.mob_label = QLabel()
        self.mob_label.setObjectName("StatChip")
        self.target_label = QLabel()
        self.target_label.setObjectName("StatChip")
        self.kill_progress_label = QLabel()
        self.kill_progress_label.setObjectName("StatChip")
        self.vitals_label = QLabel()
        self.vitals_label.setObjectName("StatChip")

        layout = QGridLayout(self)
        layout.addWidget(self.mob_label, 0, 0)
        layout.addWidget(self.target_label, 0, 1)
        layout.addWidget(self.kill_progress_label, 0, 2)
        layout.addWidget(self.vitals_label, 1, 0, 1, 2)

    def retranslate(self, translator: Translator) -> None:
        self.setTitle(translator.text(Message.UI_DASHBOARD_SUMMARY))

    def render_mob_count(self, translator: Translator, count: int) -> None:
        self.mob_label.setText(translator.text(Message.UI_MOBS_COUNT, count=count))

    def render_vitals(
        self,
        translator: Translator,
        vitals: PlayerVitals | None,
    ) -> None:
        hp = (
            f"{vitals.hp_percentage:.1f}"
            if vitals is not None and vitals.hp_percentage is not None
            else "--"
        )
        mp = (
            f"{vitals.mp_percentage:.1f}"
            if vitals is not None and vitals.mp_percentage is not None
            else "--"
        )
        fp = (
            f"{vitals.fp_percentage:.1f}"
            if vitals is not None and vitals.fp_percentage is not None
            else "--"
        )
        self.vitals_label.setText(translator.text(Message.UI_VITALS_STATUS, hp=hp, mp=mp, fp=fp))

    def render_kill_progress(
        self,
        translator: Translator,
        progress: tuple[MobKillProgress, ...],
    ) -> None:
        self.kill_progress_label.setText(kill_progress_text(translator, progress))


class StatusHeaderCard(QGroupBox):
    """Window and live client status chips."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self.status_label = QLabel()
        self.status_label.setObjectName("StatusBadge")
        self.window_label = QLabel()
        self.window_label.setObjectName("StatChip")
        self.gps_label = QLabel()
        self.gps_label.setObjectName("StatChip")
        self.camera_label = QLabel()
        self.camera_label.setObjectName("StatChip")

        layout = QHBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.window_label)
        layout.addWidget(self.gps_label)
        layout.addWidget(self.camera_label)
        layout.addStretch()

    def retranslate(self, translator: Translator) -> None:
        self.setTitle(translator.text(Message.UI_CARD_STATUS))
