"""Qt tests for the single-window frontend navigation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMainWindow
from pytestqt.qtbot import QtBot

from backend.contracts import AcademicFormData, AcademicRecord, SubmissionResult
from frontend.controller import FakeFrontendController
from frontend.frontend_main import (
    ACADEMIC_FORM_SCREEN,
    ACADEMIC_LIST_SCREEN,
    LOGIN_SCREEN,
    MENU_SCREEN,
    build_frontend_window,
)
from persistence.settings_repository import load_application_settings

SETTINGS = load_application_settings()


def _controlled_callback(_data: AcademicFormData) -> SubmissionResult:
    return SubmissionResult(success=False, message="Resultado controlado.")


def test_initial_screen_has_one_instance_of_each_view_and_one_application(
    qtbot: QtBot,
    qapp: QApplication,
) -> None:
    application_before = QApplication.instance()
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=_controlled_callback,
    )
    qtbot.addWidget(window)

    assert QApplication.instance() is application_before is qapp
    assert isinstance(window, QMainWindow)
    assert window.current_screen == LOGIN_SCREEN
    assert window.stack.currentWidget() is window.login_view
    assert window.stack.count() == 5
    assert len({id(window.stack.widget(index)) for index in range(5)}) == 5
    assert (window.width(), window.height()) == (768, 768)


def test_menu_to_list_emits_one_screen_change_and_resizes(qtbot: QtBot) -> None:
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=_controlled_callback,
    )
    qtbot.addWidget(window)
    spy = QSignalSpy(window.stack.currentChanged)

    qtbot.mouseClick(
        window.main_menu_view.academics_button,
        Qt.MouseButton.LeftButton,
    )

    assert window.current_screen == ACADEMIC_LIST_SCREEN
    assert window.stack.currentWidget() is window.academics_list_view
    assert (window.width(), window.height()) == (1080, 768)
    assert spy.count() == 1


def test_list_to_form_and_cancel_to_list(qtbot: QtBot) -> None:
    callback_calls: list[AcademicFormData] = []

    def callback(data: AcademicFormData) -> SubmissionResult:
        callback_calls.append(data)
        return SubmissionResult(success=True, message="Aceptado.")

    window = build_frontend_window(
        FakeFrontendController(), settings=SETTINGS, submit_callback=callback
    )
    qtbot.addWidget(window)
    window.show_academics_list()

    qtbot.mouseClick(
        window.academics_list_view.add_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.current_screen == ACADEMIC_FORM_SCREEN
    assert (window.width(), window.height()) == (1080, 768)

    qtbot.mouseClick(
        window.academic_form_view.cancel_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.current_screen == ACADEMIC_LIST_SCREEN
    assert (window.width(), window.height()) == (1080, 768)
    assert callback_calls == []


def test_list_to_menu_restores_native_menu_size(qtbot: QtBot) -> None:
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=_controlled_callback,
    )
    qtbot.addWidget(window)
    window.show_academics_list()

    qtbot.mouseClick(
        window.academics_list_view.back_button,
        Qt.MouseButton.LeftButton,
    )

    assert window.current_screen == MENU_SCREEN
    assert (window.width(), window.height()) == (768, 768)


def test_out_of_scope_actions_are_not_executable(qtbot: QtBot) -> None:
    academic = AcademicRecord(
        academic_id="academic-test-id",
        name="Dato de prueba",
        rut="12345678-5",
        plant="Mixta",
        profile="Docente",
        weekly_hours=40,
        status="Activo",
    )
    window = build_frontend_window(
        FakeFrontendController(academics=(academic,)),
        settings=SETTINGS,
        submit_callback=_controlled_callback,
        academics=(academic,),
    )
    qtbot.addWidget(window)

    menu = window.main_menu_view
    assert not menu.assign_load_button.isEnabled()
    assert not menu.assignments_button.isEnabled()
    assert menu.academics_button.isEnabled()
    assert menu.download_button.isEnabled()
    assert menu.upload_button.isEnabled()

    academics = window.academics_list_view
    assert not academics.search_input.isEnabled()
    assert academics.action_buttons
    assert (
        academics.table.selectionMode()
        is QAbstractItemView.SelectionMode.SingleSelection
    )
    edit_buttons = [
        button
        for button in academics.action_buttons
        if button.objectName() == "tableEditAction"
    ]
    delete_buttons = [
        button
        for button in academics.action_buttons
        if button.objectName() == "tableDeleteAction"
    ]
    assert edit_buttons and all(button.isEnabled() for button in edit_buttons)
    assert delete_buttons and all(button.isEnabled() for button in delete_buttons)
