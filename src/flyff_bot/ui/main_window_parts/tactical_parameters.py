"""Read-only tactical profile diagnostics and explicit load/export/reset controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from flyff_bot.features.tactical_parameters import (
    DEFAULT_TACTICAL_PARAMETERS,
    TACTICAL_PARAMETER_DEFINITIONS,
    TacticalParameterDiagnostic,
    TacticalParameterDiagnosticCode,
    TacticalParameterName,
    TacticalParameterProfile,
    TacticalParameterSpace,
    TacticalProfileError,
    load_tactical_profile,
    save_tactical_profile,
)
from flyff_bot.i18n import Message, Translator

PARAMETER_MESSAGES = {
    TacticalParameterName.NAVMESH_WAYPOINT_ARRIVAL_UNITS: (
        Message.UI_TACTICAL_NAVMESH_ARRIVAL,
        Message.UI_TACTICAL_NAVMESH_ARRIVAL_TOOLTIP,
    ),
    TacticalParameterName.HEADING_TOLERANCE_DEGREES: (
        Message.UI_TACTICAL_HEADING_TOLERANCE,
        Message.UI_TACTICAL_HEADING_TOLERANCE_TOOLTIP,
    ),
    TacticalParameterName.HEADING_PIVOT_THRESHOLD_DEGREES: (
        Message.UI_TACTICAL_HEADING_PIVOT,
        Message.UI_TACTICAL_HEADING_PIVOT_TOOLTIP,
    ),
    TacticalParameterName.REPLAN_INTERVAL_SECONDS: (
        Message.UI_TACTICAL_REPLAN_INTERVAL,
        Message.UI_TACTICAL_REPLAN_INTERVAL_TOOLTIP,
    ),
    TacticalParameterName.STALL_TIMEOUT_SECONDS: (
        Message.UI_TACTICAL_STALL_TIMEOUT,
        Message.UI_TACTICAL_STALL_TIMEOUT_TOOLTIP,
    ),
    TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS: (
        Message.UI_TACTICAL_ENGAGEMENT_DISTANCE,
        Message.UI_TACTICAL_ENGAGEMENT_DISTANCE_TOOLTIP,
    ),
    TacticalParameterName.ATTACK_KEY_DELAY_SECONDS: (
        Message.UI_TACTICAL_ATTACK_DELAY,
        Message.UI_TACTICAL_ATTACK_DELAY_TOOLTIP,
    ),
    TacticalParameterName.TARGET_LOCKOUT_SECONDS: (
        Message.UI_TACTICAL_TARGET_LOCKOUT,
        Message.UI_TACTICAL_TARGET_LOCKOUT_TOOLTIP,
    ),
    TacticalParameterName.CLICK_DEBOUNCE_SECONDS: (
        Message.UI_TACTICAL_CLICK_DEBOUNCE,
        Message.UI_TACTICAL_CLICK_DEBOUNCE_TOOLTIP,
    ),
    TacticalParameterName.CAMERA_PITCH_DEGREES: (
        Message.UI_TACTICAL_CAMERA_PITCH,
        Message.UI_TACTICAL_CAMERA_PITCH_TOOLTIP,
    ),
    TacticalParameterName.CAMERA_ZOOM_LEVEL: (
        Message.UI_TACTICAL_CAMERA_ZOOM,
        Message.UI_TACTICAL_CAMERA_ZOOM_TOOLTIP,
    ),
    TacticalParameterName.SEARCH_TURN_DURATION_SECONDS: (
        Message.UI_TACTICAL_SEARCH_TURN,
        Message.UI_TACTICAL_SEARCH_TURN_TOOLTIP,
    ),
    TacticalParameterName.TARGET_VERIFICATION_THRESHOLD: (
        Message.UI_TACTICAL_TARGET_THRESHOLD,
        Message.UI_TACTICAL_TARGET_THRESHOLD_TOOLTIP,
    ),
    TacticalParameterName.HP_POTION_THRESHOLD_PERCENT: (
        Message.UI_TACTICAL_HP_THRESHOLD,
        Message.UI_TACTICAL_HP_THRESHOLD_TOOLTIP,
    ),
    TacticalParameterName.MP_THRESHOLD_PERCENT: (
        Message.UI_TACTICAL_MP_THRESHOLD,
        Message.UI_TACTICAL_MP_THRESHOLD_TOOLTIP,
    ),
    TacticalParameterName.RECOVERY_DEBOUNCE_SECONDS: (
        Message.UI_TACTICAL_RECOVERY_DEBOUNCE,
        Message.UI_TACTICAL_RECOVERY_DEBOUNCE_TOOLTIP,
    ),
}


class TacticalParametersPanel(QGroupBox):
    """Display one immutable profile and emit typed profile changes."""

    parameters_changed = Signal(object)

    def __init__(self, translator: Translator) -> None:
        super().__init__()
        self.setObjectName("CardPanel")
        self._translator = translator
        self._parameters = DEFAULT_TACTICAL_PARAMETERS
        self._profile_name = "default"
        self._last_error: str | None = None
        self._load_dialog_title = ""
        self._export_dialog_title = ""

        self._profile_label = QLabel()
        self._profile_value = QLabel()
        self._name_header = QLabel()
        self._value_header = QLabel()
        self._range_header = QLabel()
        self._rows: dict[TacticalParameterName, tuple[QLabel, QLabel, QLabel]] = {}
        self._diagnostic_label = QLabel()
        self._diagnostic_label.setWordWrap(True)
        self._load_button = QPushButton()
        self._export_button = QPushButton()
        self._reset_button = QPushButton()

        layout = QGridLayout(self)
        layout.addWidget(self._profile_label, 0, 0)
        layout.addWidget(self._profile_value, 0, 1, 1, 2)
        layout.addWidget(self._name_header, 1, 0)
        layout.addWidget(self._value_header, 1, 1)
        layout.addWidget(self._range_header, 1, 2)
        for row_index, name in enumerate(TacticalParameterName, start=2):
            labels = (QLabel(), QLabel(), QLabel())
            self._rows[name] = labels
            for column, label in enumerate(labels):
                layout.addWidget(label, row_index, column)
        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self._load_button)
        button_layout.addWidget(self._export_button)
        button_layout.addWidget(self._reset_button)
        layout.addWidget(button_row, len(TacticalParameterName) + 2, 0, 1, 3)
        layout.addWidget(self._diagnostic_label, len(TacticalParameterName) + 3, 0, 1, 3)

        self._load_button.clicked.connect(self._browse_load)
        self._export_button.clicked.connect(self._browse_export)
        self._reset_button.clicked.connect(self.reset_profile)
        self.retranslate(translator)
        self._render()

    @property
    def parameters(self) -> TacticalParameterSpace:
        return self._parameters

    @property
    def profile_name(self) -> str:
        return self._profile_name

    @property
    def diagnostic_text(self) -> str:
        return self._diagnostic_label.text()

    def set_parameters(
        self,
        parameters: TacticalParameterSpace,
        *,
        profile_name: str | None = None,
        emit: bool = False,
    ) -> None:
        self._parameters = parameters
        if profile_name is not None:
            self._profile_name = profile_name
        self._last_error = None
        self._render()
        if emit:
            self.parameters_changed.emit(parameters)

    def load_profile(self, path: Path) -> bool:
        try:
            profile = load_tactical_profile(path)
        except TacticalProfileError:
            self._last_error = "invalid"
            self._render_diagnostics(())
            return False
        self.set_parameters(
            profile.parameters,
            profile_name=profile.profile_name,
            emit=True,
        )
        return True

    def export_profile(self, path: Path) -> None:
        save_tactical_profile(
            TacticalParameterProfile(self._profile_name, self._parameters),
            path,
        )
        self._last_error = None
        self._render_diagnostics(self._parameters.diagnostics)

    def reset_profile(self) -> None:
        self.set_parameters(
            DEFAULT_TACTICAL_PARAMETERS,
            profile_name="default",
            emit=True,
        )

    def show_diagnostics(self, diagnostics: tuple[TacticalParameterDiagnostic, ...]) -> None:
        self._render_diagnostics(diagnostics)

    def retranslate(self, translator: Translator) -> None:
        self._translator = translator
        self.setTitle(translator.text(Message.UI_TACTICAL_PARAMETERS_TITLE))
        self._profile_label.setText(translator.text(Message.UI_TACTICAL_PROFILE))
        self._name_header.setText(translator.text(Message.UI_TACTICAL_NAME_COLUMN))
        self._value_header.setText(translator.text(Message.UI_TACTICAL_VALUE_COLUMN))
        self._range_header.setText(translator.text(Message.UI_TACTICAL_RANGE_COLUMN))
        self._load_button.setText(translator.text(Message.UI_TACTICAL_LOAD))
        self._export_button.setText(translator.text(Message.UI_TACTICAL_EXPORT))
        self._reset_button.setText(translator.text(Message.UI_TACTICAL_RESET))
        self._load_dialog_title = translator.text(Message.UI_TACTICAL_LOAD_DIALOG)
        self._export_dialog_title = translator.text(Message.UI_TACTICAL_EXPORT_DIALOG)
        self._render()

    def _render(self) -> None:
        self._profile_value.setText(
            self._translator.text(Message.UI_TACTICAL_DEFAULT_PROFILE)
            if self._profile_name == "default"
            else self._profile_name
        )
        for name, (name_label, value_label, range_label) in self._rows.items():
            title, tooltip = PARAMETER_MESSAGES[name]
            definition = TACTICAL_PARAMETER_DEFINITIONS[name]
            name_label.setText(self._translator.text(title))
            name_label.setToolTip(self._translator.text(tooltip))
            value = format_number(float(getattr(self._parameters, name.value)))
            if (
                name is TacticalParameterName.ENGAGEMENT_DISTANCE_UNITS
                and self._parameters.engagement_distance_profiles
            ):
                overrides = ", ".join(
                    f"{item.monster_class_name}={format_number(item.distance_units)}"
                    for item in self._parameters.engagement_distance_profiles
                )
                value = f"{value} ({overrides})"
            value_label.setText(value)
            range_label.setText(
                f"{format_number(definition.minimum)} - {format_number(definition.maximum)}"
            )
        self._render_diagnostics(self._parameters.diagnostics)

    def _render_diagnostics(self, diagnostics: tuple[TacticalParameterDiagnostic, ...]) -> None:
        if self._last_error is not None:
            self._diagnostic_label.setText(
                self._translator.text(
                    Message.UI_TACTICAL_PROFILE_ERROR,
                    reason=self._translator.text(Message.UI_TACTICAL_PROFILE_INVALID),
                )
            )
            return
        if not diagnostics:
            self._diagnostic_label.setText(
                self._translator.text(Message.UI_TACTICAL_PARAMETERS_VALID)
            )
            return
        diagnostic = diagnostics[-1]
        parameter_message = PARAMETER_MESSAGES[diagnostic.parameter][0]
        message = (
            Message.UI_TACTICAL_NON_FINITE_FALLBACK
            if diagnostic.code is TacticalParameterDiagnosticCode.NON_FINITE_FALLBACK
            else Message.UI_TACTICAL_OUT_OF_RANGE_CLAMPED
        )
        self._diagnostic_label.setText(
            self._translator.text(
                message,
                parameter=self._translator.text(parameter_message),
                received=format_number(diagnostic.received),
                applied=format_number(diagnostic.applied),
            )
        )

    def _browse_load(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self._load_dialog_title,
            "",
            self._translator.text(Message.UI_TACTICAL_JSON_FILTER),
        )
        if path:
            self.load_profile(Path(path))

    def _browse_export(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            self._export_dialog_title,
            "tactical-profile.json",
            self._translator.text(Message.UI_TACTICAL_JSON_FILTER),
        )
        if path:
            self.export_profile(Path(path))


def format_number(value: float) -> str:
    """Return a compact fixed-point value without trailing zeroes."""

    return f"{value:.3f}".rstrip("0").rstrip(".")
