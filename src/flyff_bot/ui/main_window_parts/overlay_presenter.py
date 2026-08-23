from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QWidget

from flyff_bot.features.automation.models import SelectedTarget, TargetState, WorldState
from flyff_bot.features.vision.models import CapturedFrame
from flyff_bot.i18n import Translator
from flyff_bot.ui.debug_overlay import DebugOverlayWidget, render_debug_overlay


class OverlayPresenter(QWidget):
    """Camera preview viewport and placement-guide rendering state."""

    def __init__(
        self,
        translator: Translator,
        placement_toggle: QCheckBox,
    ) -> None:
        super().__init__()
        self.translator = translator
        self.placement_toggle = placement_toggle
        self.preview = DebugOverlayWidget()
        self.preview.setVisible(False)

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator

    def set_visible(self, visible: bool) -> None:
        self.preview.setVisible(visible)

    def clear(self) -> None:
        self.preview.clear()

    def render_frame(
        self,
        frame: CapturedFrame | None,
        state: WorldState | None = None,
    ) -> None:
        if frame is None:
            self.clear()
            return
        mobs = state.visible_mobs if state is not None else ()
        target = (
            state.selected_target
            if state is not None
            else SelectedTarget(TargetState.NONE, None, 0)
        )
        vitals = state.player_vitals if state is not None else None
        pixmap = render_debug_overlay(
            frame,
            mobs,
            target,
            self.translator,
            vitals=vitals,
            show_placements=self.placement_toggle.isChecked(),
        )
        self.preview.setPixmap(pixmap)
