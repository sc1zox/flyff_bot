from __future__ import annotations

from PySide6.QtWidgets import QLabel

from flyff_bot.features.automation.kill_goals import MobKillProgress
from flyff_bot.features.automation.models import SelectedTarget, TargetState, WorldState
from flyff_bot.i18n import Message, Translator
from flyff_bot.ui.dashboard import DashboardUpdate, FarmingGoal
from flyff_bot.ui.main_window_parts.header import goal_text, kill_progress_text


class DashboardPresenter:
    """Render the persistent summary labels from one immutable world snapshot."""

    def __init__(
        self,
        translator: Translator,
        *,
        mob_label: QLabel,
        target_label: QLabel,
        goal_label: QLabel,
        vitals_label: QLabel,
        kill_progress_label: QLabel,
    ) -> None:
        self.translator = translator
        self._mob_label = mob_label
        self._target_label = target_label
        self._goal_label = goal_label
        self._vitals_label = vitals_label
        self._kill_progress_label = kill_progress_label

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator

    def render_initial_state(self) -> None:
        self.render_mob_count(0)
        self.render_vitals(None)

    def render_update(self, update: DashboardUpdate) -> None:
        self.render_mob_count(update.state.nearby_mob_count)
        self.render_target(update.state.selected_target)
        self.render_goal(update.goal, update.state)
        self.render_vitals(update.state)
        self.render_kill_progress(update.kill_progress)

    def render_mob_count(self, count: int) -> None:
        self._mob_label.setText(self.translator.text(Message.UI_MOBS_COUNT, count=count))

    def render_target(self, target: SelectedTarget) -> None:
        message = (
            Message.UI_TARGET_VALID
            if target.state is TargetState.VALID
            else Message.UI_TARGET_WRONG
            if target.state is TargetState.WRONG
            else Message.UI_TARGET_NONE
        )
        self._target_label.setText(self.translator.text(message))

    def render_goal(
        self,
        goal: FarmingGoal | None,
        state: WorldState | None,
    ) -> None:
        self._goal_label.setText(goal_text(self.translator, state, goal))

    def render_vitals(self, state: WorldState | None = None) -> None:
        vitals = state.player_vitals if state is not None else None
        values = {
            "hp": _percentage_text(vitals.hp_percentage if vitals is not None else None),
            "mp": _percentage_text(vitals.mp_percentage if vitals is not None else None),
            "fp": _percentage_text(vitals.fp_percentage if vitals is not None else None),
        }
        self._vitals_label.setText(self.translator.text(Message.UI_VITALS_STATUS, **values))

    def render_kill_progress(self, progress: tuple[MobKillProgress, ...]) -> None:
        self._kill_progress_label.setText(kill_progress_text(self.translator, progress))


def _percentage_text(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "--"
