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
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from backend.academic_catalog import AcademicCatalogs, CatalogOption
from backend.academic_service import (
    INCOMPATIBLE_PLANT_PROFILE_MESSAGE,
    INVALID_PLANT_MESSAGE,
    INVALID_PROFILE_MESSAGE,
)
from backend.contracts import (
    AcademicErrorCode,
    AcademicFormData,
    AcademicRecord,
    SubmissionResult,
)
from frontend.settings import ApplicationSettings
from frontend.style_manager import StyleManager
from frontend.widgets import (
    AppHeader,
    PageTitle,
    ResultBanner,
    Surface,
    add_page_footer,
)

SubmissionCallback = Callable[..., SubmissionResult]
UpdateCallback = Callable[[str, AcademicFormData], SubmissionResult]

HISTORICAL_INCOMPATIBILITY_MESSAGE = (
    "La combinación histórica de planta y perfil no es compatible. "
    "Seleccione una combinación válida antes de guardar."
)


class AcademicFormView(QWidget):
    cancel_requested = Signal()
    submission_succeeded = Signal(str)
    logout_requested = Signal()
    error_requested = Signal(str)

    def __init__(
        self,
        settings: ApplicationSettings,
        style_manager: StyleManager,
        catalogs: AcademicCatalogs,
        submit_callback: SubmissionCallback,
        update_callback: UpdateCallback | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.catalogs = catalogs
        self._submit_callback = submit_callback
        self._default_update_callback = update_callback
        self._active_update_callback = update_callback
        self.field_error_labels: dict[str, QLabel] = {}
        self._latest_error = settings.texts.messages["save_error"]
        self._editing_id: str | None = None
        self._historical_warning_active = False
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
        self.plant_combo = self._catalog_combo(self.catalogs.plants, placeholder=True)
        self.profile_combo = self._catalog_combo((), placeholder=True)
        self.profile_combo.setEnabled(False)
        self.weekly_hours_input = QSpinBox()
        self.weekly_hours_input.setRange(-(2**31), 2**31 - 1)
        self.status_combo = self._catalog_combo(
            self.catalogs.statuses,
            placeholder=False,
        )
        self.plant_combo.currentIndexChanged.connect(self._reload_profiles)
        self.profile_combo.currentIndexChanged.connect(self._clear_historical_warning)
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

    def _catalog_combo(
        self,
        options: tuple[CatalogOption, ...],
        *,
        placeholder: bool,
    ) -> QComboBox:
        combo = QComboBox()
        self._populate_catalog_combo(combo, options, placeholder=placeholder)
        return combo

    def _populate_catalog_combo(
        self,
        combo: QComboBox,
        options: tuple[CatalogOption, ...],
        *,
        placeholder: bool,
    ) -> None:
        combo.clear()
        if placeholder:
            combo.addItem(self.settings.texts.messages["select_placeholder"], "")
        for option in options:
            combo.addItem(option.label, option.key)

    def _reload_profiles(self, _index: int | None = None) -> None:
        previous_profile = str(self.profile_combo.currentData() or "")
        plant = str(self.plant_combo.currentData() or "")
        options = self.catalogs.profiles_for_plant(plant)
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem(
            self.settings.texts.messages["select_placeholder"],
            "",
        )
        for option in options:
            self.profile_combo.addItem(option.label, option.key)
        profile_index = self.profile_combo.findData(previous_profile)
        self.profile_combo.setCurrentIndex(max(profile_index, 0))
        self.profile_combo.setEnabled(bool(plant))
        self.profile_combo.blockSignals(False)
        if self._historical_warning_active:
            self._clear_historical_warning()

    def _clear_historical_warning(self, _index: int | None = None) -> None:
        if not self._historical_warning_active:
            return
        self._historical_warning_active = False
        profile_error = self.field_error_labels["profile"]
        profile_error.clear()
        profile_error.hide()
        if self.result_label.text() == HISTORICAL_INCOMPATIBILITY_MESSAGE:
            self.result_label.clear_result()

    def set_session(self, username: str) -> None:
        self.header.username_label.setText(username)
        self.header.username_label.setVisible(bool(username))

    def prepare_new(self) -> None:
        self._editing_id = None
        self._active_update_callback = self._default_update_callback
        self.save_button.setText(self.settings.texts.button_labels["save"])
        self.page_title.label.setText(
            self.settings.texts.screen_titles["academic_form"].upper()
        )
        self._populate_catalog_combo(
            self.plant_combo,
            self.catalogs.plants,
            placeholder=True,
        )
        self._populate_catalog_combo(
            self.status_combo,
            self.catalogs.statuses,
            placeholder=False,
        )
        self.name_input.clear()
        self.rut_input.clear()
        self.plant_combo.setCurrentIndex(0)
        self._reload_profiles()
        self.weekly_hours_input.setValue(0)
        self.status_combo.setCurrentIndex(0)
        self._clear_result()

    def prepare_edit(
        self,
        record: AcademicRecord,
        *,
        update_callback: UpdateCallback | None = None,
        publication: bool = False,
    ) -> None:
        self._editing_id = record.academic_id
        self._active_update_callback = update_callback or self._default_update_callback
        self.save_button.setText(
            "Publicar" if publication else self.settings.texts.button_labels["save"]
        )
        self._clear_result()
        self._populate_catalog_combo(
            self.plant_combo,
            self.catalogs.plants,
            placeholder=True,
        )
        self._populate_catalog_combo(
            self.status_combo,
            self.catalogs.statuses,
            placeholder=False,
        )
        self.page_title.label.setText("EDITAR ACADÉMICO")
        self.name_input.setText(record.name)
        self.rut_input.setText(record.rut)
        plant = self.catalogs.normalize_plant_for_read(record.plant)
        profile = self.catalogs.normalize_profile_for_read(record.profile)
        plant_index = self.plant_combo.findData(plant)
        if plant_index < 0 and plant:
            self.plant_combo.addItem(f"{record.plant} (histórico)", plant)
            plant_index = self.plant_combo.count() - 1
        self.plant_combo.setCurrentIndex(max(plant_index, 0))
        profile_index = self.profile_combo.findData(profile)
        incompatible = bool(plant and profile) and not self.catalogs.is_compatible(
            plant,
            profile,
        )
        if profile_index < 0 and profile:
            suffix = " (histórico incompatible)" if incompatible else " (histórico)"
            self.profile_combo.addItem(f"{record.profile}{suffix}", profile)
            profile_index = self.profile_combo.count() - 1
            self.profile_combo.setEnabled(True)
        self.profile_combo.setCurrentIndex(max(profile_index, 0))
        self.weekly_hours_input.setValue(record.weekly_hours)
        status = self.catalogs.normalize_status_for_read(record.status)
        status_index = self.status_combo.findData(status)
        if status_index < 0 and status:
            self.status_combo.addItem(f"{record.status} (histórico)", status)
            status_index = self.status_combo.count() - 1
        self.status_combo.setCurrentIndex(max(status_index, 0))
        if incompatible:
            self._historical_warning_active = True
            self.result_label.present(
                HISTORICAL_INCOMPATIBILITY_MESSAGE,
                success=False,
            )
            profile_error = self.field_error_labels["profile"]
            profile_error.setText(INCOMPATIBLE_PLANT_PROFILE_MESSAGE)
            profile_error.show()

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
        selection_error = self._validate_profile_selection(data)
        if selection_error is not None:
            self._present_result(selection_error)
            return
        result = (
            self._active_update_callback(self._editing_id, data)
            if self._editing_id is not None and self._active_update_callback is not None
            else self._submit_callback(data)
        )
        if (
            self._editing_id is None
            and result.error_code is AcademicErrorCode.DUPLICATE_RUT
            and result.duplicate_confirmation is not None
        ):
            self._present_result(result)
            if not self._confirm_duplicate_overwrite(result.message):
                return
            result = self._submit_callback(data, result.duplicate_confirmation)
        self._present_result(result)

    def _validate_profile_selection(
        self,
        data: AcademicFormData,
    ) -> SubmissionResult | None:
        plant = self.catalogs.strict_plant_key(data.plant)
        if plant is None:
            return SubmissionResult(
                False,
                INVALID_PLANT_MESSAGE,
                {"plant": INVALID_PLANT_MESSAGE},
                error_code=AcademicErrorCode.INVALID_PLANT,
            )
        profile = self.catalogs.strict_profile_key(data.profile)
        if profile is None:
            return SubmissionResult(
                False,
                INVALID_PROFILE_MESSAGE,
                {"profile": INVALID_PROFILE_MESSAGE},
                error_code=AcademicErrorCode.INVALID_PROFILE,
            )
        if not self.catalogs.is_compatible(plant, profile):
            return SubmissionResult(
                False,
                INCOMPATIBLE_PLANT_PROFILE_MESSAGE,
                {"profile": INCOMPATIBLE_PLANT_PROFILE_MESSAGE},
                error_code=AcademicErrorCode.INCOMPATIBLE_PLANT_PROFILE,
            )
        return None

    def _present_result(self, result: SubmissionResult) -> None:
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

    def _confirm_duplicate_overwrite(self, message: str) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self.settings.texts.screen_titles["academic_form"])
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message)
        cancel_button = dialog.addButton(
            self.settings.texts.button_labels["cancel"],
            QMessageBox.ButtonRole.RejectRole,
        )
        overwrite_button = dialog.addButton(
            self.settings.texts.button_labels["overwrite"],
            QMessageBox.ButtonRole.DestructiveRole,
        )
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is overwrite_button

    def _clear_result(self) -> None:
        self._historical_warning_active = False
        self.result_label.clear_result()
        for label in self.field_error_labels.values():
            label.clear()
            label.hide()
