"""Tests for typed academic form submission and callback result rendering."""

from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from backend.contracts import AcademicFormData, SubmissionResult
from frontend.controller import FakeFrontendController
from frontend.frontend_main import (
    ACADEMIC_LIST_SCREEN,
    build_frontend_window,
)
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
