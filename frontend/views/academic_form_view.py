"""Reusable add/edit academic form driven by an injected submission callback."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from backend.contracts import AcademicFormData, AcademicRecord, SubmissionResult
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import (
    AppHeader,
    PageTitle,
    ResultBanner,
    Surface,
    add_page_footer,
)

SubmissionCallback = Callable[[AcademicFormData], SubmissionResult]
UpdateCallback = Callable[[str, AcademicFormData], SubmissionResult]


class AcademicFormView(QWidget):
    cancel_requested = Signal()
    submission_succeeded = Signal(str)
    logout_requested = Signal()
    error_requested = Signal(str)

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        submit_callback: SubmissionCallback,
        update_callback: UpdateCallback | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._submit_callback = submit_callback
        self._default_update_callback = update_callback
        self._active_update_callback = update_callback
        self.field_error_labels: dict[str, QLabel] = {}
        self._latest_error = settings.texts.messages["save_error"]
        self._editing_id: str | None = None
        self.setObjectName("academicFormView")
        self._build_ui(style_manager)

    def _build_ui(self, style_manager: StyleManager) -> None:
        visual = self.settings.visual
        texts = self.settings.texts
        spacing = visual.spacing
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = AppHeader(self.settings, username="usuario", show_logout=True)
        self.header.logout_requested.connect(self.logout_requested)
        root.addWidget(self.header)

        body = QVBoxLayout()
        body.setContentsMargins(
            visual.margins["page"] + spacing["medium"],
            spacing["large"],
            visual.margins["section"],
            spacing["medium"],
        )
        body.setSpacing(spacing["medium"])
        self.page_title = PageTitle(texts.screen_titles["academic_form"], self.settings)
        body.addWidget(self.page_title)

        panel = Surface(style_manager)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            spacing["large"], visual.margins["page"], spacing["large"], spacing["large"]
        )
        panel_layout.setSpacing(spacing["medium"])

        fields = QGridLayout()
        fields.setHorizontalSpacing(spacing["medium"])
        fields.setVerticalSpacing(spacing["small"])
        control_height = spacing["large"] + spacing["medium"]
        self.name_input = self._line_edit(control_height)
        self.rut_input = self._line_edit(control_height)
        self.plant_combo = self._catalog_combo("plant", placeholder=True)
        self.profile_combo = self._catalog_combo("profile", placeholder=True)
        self.weekly_hours_input = QSpinBox()
        self.weekly_hours_input.setRange(-(2**31), 2**31 - 1)
        self.status_combo = self._catalog_combo("status", placeholder=False)
        for control in (
            self.plant_combo,
            self.profile_combo,
            self.weekly_hours_input,
            self.status_combo,
        ):
            control.setProperty("sizeRole", "form")
            control.setMinimumHeight(control_height)

        left_controls = (
            ("name", self.name_input, 0),
            ("rut", self.rut_input, 2),
            ("plant", self.plant_combo, 4),
            ("profile", self.profile_combo, 6),
        )
        right_controls = (
            ("weekly_hours", self.weekly_hours_input, 0),
            ("status", self.status_combo, 2),
        )
        for name, control, row in left_controls:
            self._add_field(fields, name, control, row, 0)
        for name, control, row in right_controls:
            self._add_field(fields, name, control, row, 3)
        fields.setColumnStretch(1, 3)
        fields.setColumnMinimumWidth(2, visual.margins["page"])
        fields.setColumnStretch(4, 2)
        panel_layout.addLayout(fields)
        panel_layout.addStretch()

        self.result_label = ResultBanner()
        panel_layout.addWidget(self.result_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(visual.margins["page"] - spacing["extra_small"])
        buttons.addStretch()
        self.cancel_button = QPushButton(texts.button_labels["cancel"])
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.setProperty("sizeRole", "large")
        self.cancel_button.setMinimumSize(220, 64)
        self.cancel_button.clicked.connect(self.cancel_requested)
        buttons.addWidget(self.cancel_button)
        self.save_button = QPushButton(texts.button_labels["save"])
        self.save_button.setObjectName("primaryButton")
        self.save_button.setProperty("sizeRole", "large")
        self.save_button.setMinimumSize(220, 64)
        self.save_button.clicked.connect(self.submit)
        buttons.addWidget(self.save_button)
        buttons.addStretch()
        panel_layout.addLayout(buttons)
        body.addWidget(panel, stretch=1)
        add_page_footer(
            body, self.settings, lambda: self.error_requested.emit(self._latest_error)
        )
        root.addLayout(body, stretch=1)

    def _line_edit(self, height: int) -> QLineEdit:
        edit = QLineEdit()
        edit.setProperty("sizeRole", "form")
        edit.setMinimumHeight(height)
        return edit

    def _add_field(
        self, layout: QGridLayout, name: str, control: QWidget, row: int, column: int
    ) -> None:
        label = QLabel(self.settings.texts.field_labels[name])
        label.setObjectName("fieldLabel")
        layout.addWidget(label, row, column)
        layout.addWidget(control, row, column + 1)
        error = QLabel()
        error.setObjectName("errorLabel")
        error.setWordWrap(True)
        error.hide()
        layout.addWidget(error, row + 1, column + 1)
        self.field_error_labels[name] = error

    def _catalog_combo(self, name: str, *, placeholder: bool) -> QComboBox:
        combo = QComboBox()
        if placeholder:
            combo.addItem(self.settings.texts.messages["select_placeholder"], "")
        for value in self.settings.texts.catalogs[name].values:
            combo.addItem(value, value)
        return combo

    def set_session(self, username: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))

    def prepare_new(self) -> None:
        self._editing_id = None
        self._active_update_callback = self._default_update_callback
        self.page_title.label.setText(
            self.settings.texts.screen_titles["academic_form"].upper()
        )
        self.name_input.clear()
        self.rut_input.clear()
        self.plant_combo.setCurrentIndex(0)
        self.profile_combo.setCurrentIndex(0)
        self.weekly_hours_input.setValue(0)
        self.status_combo.setCurrentIndex(0)
        self._clear_result()

    def prepare_edit(
        self,
        record: AcademicRecord,
        *,
        update_callback: UpdateCallback | None = None,
    ) -> None:
        self._editing_id = record.academic_id
        self._active_update_callback = update_callback or self._default_update_callback
        self.page_title.label.setText("EDITAR ACADÉMICO")
        self.name_input.setText(record.name)
        self.rut_input.setText(record.rut)
        self.plant_combo.setCurrentIndex(self.plant_combo.findData(record.plant))
        self.profile_combo.setCurrentIndex(self.profile_combo.findData(record.profile))
        self.weekly_hours_input.setValue(record.weekly_hours)
        self.status_combo.setCurrentIndex(self.status_combo.findData(record.status))
        self._clear_result()

    def form_data(self) -> AcademicFormData:
        return AcademicFormData(
            name=self.name_input.text(),
            rut=self.rut_input.text(),
            plant=str(self.plant_combo.currentData() or ""),
            profile=str(self.profile_combo.currentData() or ""),
            weekly_hours=self.weekly_hours_input.value(),
            status=str(self.status_combo.currentData() or ""),
        )

    def submit(self) -> None:
        self._clear_result()
        data = self.form_data()
        result = (
            self._active_update_callback(self._editing_id, data)
            if self._editing_id is not None and self._active_update_callback is not None
            else self._submit_callback(data)
        )
        self.result_label.present(result.message, success=result.success)
        unknown_errors: list[str] = []
        for field_name, message in result.field_errors.items():
            error_label = self.field_error_labels.get(field_name)
            if error_label is None:
                unknown_errors.append(message)
            else:
                error_label.setText(message)
                error_label.show()
        if unknown_errors:
            self.result_label.setText("\n".join((result.message, *unknown_errors)))
        if result.success:
            self.submission_succeeded.emit(result.message)
        else:
            self._latest_error = result.message

    def _clear_result(self) -> None:
        self.result_label.clear_result()
        for label in self.field_error_labels.values():
            label.clear()
            label.hide()
