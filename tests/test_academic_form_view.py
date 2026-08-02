"""Tests for typed academic form submission and callback result rendering."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from backend.academic_service import (
    DUPLICATE_RUT_MESSAGE,
    INCOMPATIBLE_PLANT_PROFILE_MESSAGE,
    validate_academic_form,
)
from backend.contracts import (
    AcademicErrorCode,
    AcademicFormData,
    AcademicRecord,
    DuplicateRutConfirmation,
    SubmissionResult,
)
from frontend.controller import FakeFrontendController
from frontend.frontend_main import (
    ACADEMIC_LIST_SCREEN,
    build_frontend_window,
)
from frontend.views.academic_form_view import HISTORICAL_INCOMPATIBILITY_MESSAGE
from persistence.settings_repository import load_application_settings

SETTINGS = load_application_settings()


def _fill_form(window: object) -> None:
    form = window.academic_form_view
    form.name_input.setText("Ana de prueba")
    form.rut_input.setText("rut deliberadamente inválido")
    form.plant_combo.setCurrentIndex(form.plant_combo.findData("Ordinaria"))
    form.profile_combo.setCurrentIndex(form.profile_combo.findData("Mixto"))
    form.weekly_hours_input.setValue(40)
    form.status_combo.setCurrentIndex(form.status_combo.findData("Activo"))


def test_save_builds_exact_contract_and_invokes_callback_once(
    qtbot: QtBot,
) -> None:
    received: list[AcademicFormData] = []

    def callback(data: AcademicFormData) -> SubmissionResult:
        received.append(data)
        return SubmissionResult(success=True, message="Aceptado sin persistencia.")

    window = build_frontend_window(
        FakeFrontendController(), settings=SETTINGS, submit_callback=callback
    )
    qtbot.addWidget(window)
    _fill_form(window)

    qtbot.mouseClick(
        window.academic_form_view.save_button,
        Qt.MouseButton.LeftButton,
    )

    assert received == [
        AcademicFormData(
            name="Ana de prueba",
            rut="rut deliberadamente inválido",
            plant="Ordinaria",
            profile="Mixto",
            weekly_hours=40,
            status="Activo",
        )
    ]
    assert isinstance(received[0].weekly_hours, int)


def test_success_result_message_is_presented(qtbot: QtBot) -> None:
    result = SubmissionResult(
        success=True,
        message="Simulación aceptada; los datos no fueron almacenados.",
    )
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=lambda _data: result,
    )
    qtbot.addWidget(window)
    _fill_form(window)

    qtbot.mouseClick(
        window.academic_form_view.save_button,
        Qt.MouseButton.LeftButton,
    )

    label = window.academic_form_view.result_label
    assert label.text() == result.message
    assert label.objectName() == "successMessage"
    assert window.current_screen == ACADEMIC_LIST_SCREEN
    assert window.academics_list_view.feedback_label.text() == result.message
    assert window.academics_list_view.feedback_label.objectName() == "successMessage"


def test_general_error_result_is_presented(qtbot: QtBot) -> None:
    result = SubmissionResult(
        success=False,
        message="Simulación rechazada; no se almacenaron datos.",
    )
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=lambda _data: result,
    )
    qtbot.addWidget(window)
    _fill_form(window)

    qtbot.mouseClick(
        window.academic_form_view.save_button,
        Qt.MouseButton.LeftButton,
    )

    label = window.academic_form_view.result_label
    assert label.text() == result.message
    assert label.objectName() == "failureMessage"
    assert label.isVisibleTo(window.academic_form_view)


def test_field_errors_are_presented_verbatim(qtbot: QtBot) -> None:
    result = SubmissionResult(
        success=False,
        message="Revise los campos; no se almacenaron datos.",
        field_errors={
            "rut": "Error de RUT simulado por el callback.",
            "weekly_hours": "Error de jornada simulado por el callback.",
        },
    )
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=lambda _data: result,
    )
    qtbot.addWidget(window)
    _fill_form(window)

    qtbot.mouseClick(
        window.academic_form_view.save_button,
        Qt.MouseButton.LeftButton,
    )

    labels = window.academic_form_view.field_error_labels
    assert labels["rut"].text() == result.field_errors["rut"]
    assert labels["rut"].isVisibleTo(window.academic_form_view)
    assert labels["weekly_hours"].text() == result.field_errors["weekly_hours"]
    assert labels["weekly_hours"].isVisibleTo(window.academic_form_view)


def test_cancel_neither_builds_contract_nor_calls_callback(qtbot: QtBot) -> None:
    received: list[AcademicFormData] = []

    def callback(data: AcademicFormData) -> SubmissionResult:
        received.append(data)
        return SubmissionResult(success=True, message="No debe ocurrir.")

    window = build_frontend_window(
        FakeFrontendController(), settings=SETTINGS, submit_callback=callback
    )
    qtbot.addWidget(window)
    window.show_academic_form()
    _fill_form(window)

    qtbot.mouseClick(
        window.academic_form_view.cancel_button,
        Qt.MouseButton.LeftButton,
    )

    assert received == []
    assert window.current_screen == ACADEMIC_LIST_SCREEN


def test_rut_widget_has_no_validator_and_invalid_text_reaches_callback(
    qtbot: QtBot,
) -> None:
    received: list[AcademicFormData] = []

    def callback(data: AcademicFormData) -> SubmissionResult:
        received.append(data)
        return SubmissionResult(
            success=False,
            message="Validación simulada fuera de la vista.",
        )

    window = build_frontend_window(
        FakeFrontendController(), settings=SETTINGS, submit_callback=callback
    )
    qtbot.addWidget(window)
    form = window.academic_form_view
    _fill_form(window)

    assert form.rut_input.validator() is None
    assert form.rut_input.inputMask() == ""
    qtbot.mouseClick(form.save_button, Qt.MouseButton.LeftButton)
    assert received[0].rut == "rut deliberadamente inválido"


def test_profile_starts_disabled_and_only_lists_compatible_options(
    qtbot: QtBot,
) -> None:
    window = build_frontend_window(FakeFrontendController(), settings=SETTINGS)
    qtbot.addWidget(window)
    form = window.academic_form_view
    form.prepare_new()

    assert form.profile_combo.isEnabled() is False
    form.plant_combo.setCurrentIndex(form.plant_combo.findData("Ordinaria"))
    assert form.profile_combo.isEnabled() is True
    assert [
        form.profile_combo.itemData(index)
        for index in range(1, form.profile_combo.count())
    ] == ["Investigador", "Mixto"]


def test_changing_plant_clears_an_incompatible_profile(qtbot: QtBot) -> None:
    window = build_frontend_window(FakeFrontendController(), settings=SETTINGS)
    qtbot.addWidget(window)
    form = window.academic_form_view
    form.prepare_new()
    form.plant_combo.setCurrentIndex(form.plant_combo.findData("Ordinaria"))
    form.profile_combo.setCurrentIndex(form.profile_combo.findData("Mixto"))

    form.plant_combo.setCurrentIndex(form.plant_combo.findData("Especial"))

    assert form.profile_combo.currentData() == ""
    assert [
        form.profile_combo.itemData(index)
        for index in range(1, form.profile_combo.count())
    ] == ["Standard", "Docente", "Gestión"]


def test_empty_profile_is_not_sent_to_submission_callback(qtbot: QtBot) -> None:
    received: list[AcademicFormData] = []

    def callback(data: AcademicFormData) -> SubmissionResult:
        received.append(data)
        return SubmissionResult(True, "No debe ejecutarse.")

    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=callback,
    )
    qtbot.addWidget(window)
    form = window.academic_form_view
    form.prepare_new()
    form.name_input.setText("Persona sintética")
    form.rut_input.setText("12345678-5")
    form.plant_combo.setCurrentIndex(form.plant_combo.findData("Ordinaria"))

    form.submit()

    assert received == []
    assert form.field_error_labels["profile"].text() == "Seleccione un perfil válido."


def test_historical_incompatible_record_is_visible_warned_and_cannot_be_saved(
    qtbot: QtBot,
) -> None:
    received: list[AcademicFormData] = []

    def callback(_academic_id: str, data: AcademicFormData) -> SubmissionResult:
        received.append(data)
        return validate_academic_form(data)

    record = AcademicRecord(
        academic_id="historical-incompatible",
        rut="12345678-5",
        name="Persona histórica sintética",
        plant="Ordinaria",
        profile="Docente",
        weekly_hours=20,
        status="Activo",
    )
    window = build_frontend_window(FakeFrontendController(), settings=SETTINGS)
    qtbot.addWidget(window)
    form = window.academic_form_view
    form.prepare_edit(
        record,
        update_callback=callback,
    )

    assert form.profile_combo.currentData() == "Docente"
    assert "histórico incompatible" in form.profile_combo.currentText()
    assert form.result_label.text() == HISTORICAL_INCOMPATIBILITY_MESSAGE

    form.submit()

    assert form.result_label.objectName() == "failureMessage"
    assert (
        form.field_error_labels["profile"].text() == INCOMPATIBLE_PLANT_PROFILE_MESSAGE
    )
    assert received == []


def _duplicate_warning() -> SubmissionResult:
    return SubmissionResult(
        False,
        DUPLICATE_RUT_MESSAGE,
        {"rut": DUPLICATE_RUT_MESSAGE},
        error_code=AcademicErrorCode.DUPLICATE_RUT,
        duplicate_confirmation=DuplicateRutConfirmation(
            academic_id="duplicate-id",
            snapshot_token="synthetic-snapshot",
        ),
    )


def test_duplicate_cancel_does_not_send_overwrite_or_write(
    qtbot: QtBot,
) -> None:
    callback_calls: list[DuplicateRutConfirmation | None] = []
    writes: list[str] = []

    def callback(
        _data: AcademicFormData,
        confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult:
        callback_calls.append(confirmation)
        if confirmation is None:
            return _duplicate_warning()
        writes.append(confirmation.academic_id)
        return SubmissionResult(True, "Sobrescritura sintética.")

    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=callback,
    )
    qtbot.addWidget(window)
    form = window.academic_form_view
    _fill_form(window)
    form._confirm_duplicate_overwrite = lambda _message: False

    form.submit()

    assert callback_calls == [None]
    assert writes == []
    assert form.result_label.text() == DUPLICATE_RUT_MESSAGE


def test_duplicate_overwrite_resends_explicit_expected_identity(
    qtbot: QtBot,
) -> None:
    callback_calls: list[DuplicateRutConfirmation | None] = []

    def callback(
        _data: AcademicFormData,
        confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult:
        callback_calls.append(confirmation)
        if confirmation is None:
            return _duplicate_warning()
        return SubmissionResult(True, "Sobrescritura sintética.")

    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=callback,
    )
    qtbot.addWidget(window)
    form = window.academic_form_view
    _fill_form(window)
    form._confirm_duplicate_overwrite = lambda _message: True

    form.submit()

    assert callback_calls[0] is None
    assert callback_calls[1] == _duplicate_warning().duplicate_confirmation
    assert window.current_screen == ACADEMIC_LIST_SCREEN


def test_duplicate_dialog_uses_exact_message_and_actions(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def controlled_exec(dialog: QMessageBox) -> int:
        captured["text"] = dialog.text()
        captured["buttons"] = [button.text() for button in dialog.buttons()]
        return 0

    monkeypatch.setattr(QMessageBox, "exec", controlled_exec)
    window = build_frontend_window(FakeFrontendController(), settings=SETTINGS)
    qtbot.addWidget(window)

    accepted = window.academic_form_view._confirm_duplicate_overwrite(
        DUPLICATE_RUT_MESSAGE
    )

    assert accepted is False
    assert captured == {
        "text": "RUT ya existe. Se sobrescribirán los datos del académico.",
        "buttons": ["Cancelar", "Sobrescribir"],
    }
