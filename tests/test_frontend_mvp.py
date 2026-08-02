"""Qt coverage for the active local demonstration frontend."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QAbstractButton, QCheckBox, QLineEdit
from pytestqt.qtbot import QtBot

from backend.academic_service import DUPLICATE_RUT_MESSAGE
from frontend.controller import FakeFrontendController
from frontend.frontend_main import (
    LOGIN_SCREEN,
    MENU_SCREEN,
    REGISTER_SCREEN,
    build_frontend_window,
)
from persistence.settings_repository import load_application_settings

SETTINGS = load_application_settings()


def _window(qtbot: QtBot):
    window = build_frontend_window(
        controller=FakeFrontendController(),
        settings=SETTINGS,
    )
    qtbot.addWidget(window)
    window.show()
    return window


def _authenticate(
    window: object,
    qtbot: QtBot,
    username: str = "persona.sintetica",
) -> None:
    window.login_view.username_input.setText(username)
    window.login_view.password_input.setText("1234")
    qtbot.mouseClick(window.login_view.login_button, Qt.MouseButton.LeftButton)


def _fill_academic_form(window: object, rut: str) -> None:
    form = window.academic_form_view
    form.name_input.setText("Académico de prueba")
    form.rut_input.setText(rut)
    form.plant_combo.setCurrentIndex(form.plant_combo.findData("Ordinaria"))
    form.profile_combo.setCurrentIndex(form.profile_combo.findData("Mixto"))
    form.weekly_hours_input.setValue(40)
    form.status_combo.setCurrentIndex(form.status_combo.findData("Activo"))


def test_login_is_empty_password_is_hidden_and_length_controls_submit(
    qtbot: QtBot,
) -> None:
    window = _window(qtbot)
    login = window.login_view

    assert window.current_screen == LOGIN_SCREEN
    assert login.username_input.text() == ""
    assert login.password_input.text() == ""
    assert login.username_input.placeholderText() == ""
    assert login.password_input.placeholderText() == ""
    assert login.password_input.echoMode() is QLineEdit.EchoMode.Password
    assert login.password_input.maxLength() == 8
    login.username_input.setText("persona.sintetica")
    login.password_input.setText("123")
    assert not login.login_button.isEnabled()
    login.password_input.setText("1234")
    assert login.login_button.isEnabled()
    login.password_input.setText("123456789")
    assert login.password_input.text() == "12345678"


def test_authentication_failure_is_generic_and_logout_clears_session(
    qtbot: QtBot,
) -> None:
    window = _window(qtbot)
    login = window.login_view
    login.username_input.setText("error")
    login.password_input.setText("1234")
    qtbot.mouseClick(login.login_button, Qt.MouseButton.LeftButton)

    assert window.current_screen == LOGIN_SCREEN
    assert login.result_label.text() == "Las credenciales no son válidas."
    assert login.result_label.objectName() == "failureMessage"

    login.username_input.setText("persona.sintetica")
    qtbot.mouseClick(login.login_button, Qt.MouseButton.LeftButton)
    assert window.current_screen == MENU_SCREEN
    assert window.authenticated_username == "persona.sintetica"
    qtbot.mouseClick(
        window.main_menu_view.header.logout_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.current_screen == LOGIN_SCREEN
    assert window.authenticated_username == ""
    assert window.login_view.username_input.text() == ""
    assert window.login_view.password_input.text() == ""


def test_main_menu_has_exact_actions_order_states_and_independent_signals(
    qtbot: QtBot,
) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot)
    menu = window.main_menu_view

    assert [button.text() for button in menu.action_buttons] == [
        "Asignar carga",
        "Académicos",
        "Asignaciones",
        "Bajar información",
        "Subir información",
    ]
    assert [button.isEnabled() for button in menu.action_buttons] == [
        False,
        True,
        False,
        True,
        True,
    ]
    assert not hasattr(menu, "courses_button")
    assert all(
        first.geometry().bottom() < second.geometry().top()
        for first, second in zip(menu.action_buttons, menu.action_buttons[1:])
    )

    download = QSignalSpy(menu.download_requested)
    upload = QSignalSpy(menu.upload_requested)
    qtbot.mouseClick(menu.download_button, Qt.MouseButton.LeftButton)
    assert download.count() == 1
    assert upload.count() == 0
    qtbot.waitUntil(lambda: not window._sync_operation.active)
    assert "Academic.csv" in menu.sync_message.text()
    qtbot.mouseClick(menu.upload_button, Qt.MouseButton.LeftButton)
    assert download.count() == 1
    assert upload.count() == 1
    qtbot.waitUntil(lambda: not window._sync_operation.active)
    assert "Academic.csv" in menu.sync_message.text()


def test_global_button_padding_and_clickable_cursors(
    qtbot: QtBot,
    qapp: object,
) -> None:
    window = _window(qtbot)
    padding = window.style_manager.button_horizontal_padding
    stylesheet = window.styleSheet()
    rule_start = stylesheet.index("QAbstractButton {")
    rule_end = stylesheet.index("}", rule_start)
    abstract_button_rule = stylesheet[rule_start:rule_end]

    assert padding == SETTINGS.visual.spacing["medium"]
    assert f"padding-left: {padding}px;" in abstract_button_rule
    assert f"padding-right: {padding}px;" in abstract_button_rule
    enabled_buttons = [
        button for button in window.findChildren(QAbstractButton) if button.isEnabled()
    ]
    assert enabled_buttons
    assert all(
        button.cursor().shape() is Qt.CursorShape.PointingHandCursor
        for button in enabled_buttons
    )

    login = window.login_view
    assert login.login_button.cursor().shape() is Qt.CursorShape.ArrowCursor
    login.username_input.setText("persona.sintetica")
    login.password_input.setText("1234")
    assert login.login_button.cursor().shape() is Qt.CursorShape.PointingHandCursor

    checkbox = QCheckBox("Control clickeable", login)
    checkbox.show()
    qapp.processEvents()
    assert checkbox.cursor().shape() is Qt.CursorShape.PointingHandCursor
    checkbox.setEnabled(False)
    assert checkbox.cursor().shape() is Qt.CursorShape.ArrowCursor


def test_registration_starts_session_immediately(qtbot: QtBot) -> None:
    window = _window(qtbot)
    qtbot.mouseClick(window.login_view.register_button, Qt.MouseButton.LeftButton)
    assert window.current_screen == REGISTER_SCREEN
    registration = window.register_view
    assert registration.username_input.text() == ""
    assert registration.password_input.echoMode() is QLineEdit.EchoMode.Password
    assert registration.confirmation_input.echoMode() is QLineEdit.EchoMode.Password
    registration.username_input.setText("nueva.persona")
    registration.password_input.setText("1234")
    registration.confirmation_input.setText("1234")
    qtbot.mouseClick(registration.register_button, Qt.MouseButton.LeftButton)

    assert window.current_screen == MENU_SCREEN
    assert window.authenticated_username == "nueva.persona"
    assert registration.password_input.text() == ""
    assert registration.confirmation_input.text() == ""


def test_selection_enables_edit_and_opens_prefilled_reused_form(
    qtbot: QtBot,
) -> None:
    controller = FakeFrontendController()
    window = build_frontend_window(controller=controller, settings=SETTINGS)
    qtbot.addWidget(window)
    _authenticate(window, qtbot)
    window.show_academic_form()
    _fill_academic_form(window, "12345678-5")
    window.academic_form_view.submit()
    view = window.academics_list_view

    assert not view.edit_selected_button.isEnabled()
    view.table.selectRow(0)
    assert view.edit_selected_button.isEnabled()
    qtbot.mouseClick(view.edit_selected_button, Qt.MouseButton.LeftButton)
    form = window.academic_form_view
    assert form.page_title.label.text() == "EDITAR ACADÉMICO"
    assert form.name_input.text() == "Académico de prueba"
    assert form.rut_input.text() == "12345678-5"
    assert form.plant_combo.currentData() == "Ordinaria"
    assert form.profile_combo.currentData() == "Mixto"
    assert form.weekly_hours_input.value() == 40
    assert form.status_combo.currentData() == "Activo"


def test_academic_form_prepares_duplicate_invalid_and_save_errors(
    qtbot: QtBot,
) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot)
    expected = (
        ("11111111-1", DUPLICATE_RUT_MESSAGE),
        ("00000000-0", "Rut inválido."),
        ("guardar-error", "Error al guardar."),
    )
    for rut, message in expected:
        window.show_academic_form()
        _fill_academic_form(window, rut)
        window.academic_form_view.submit()
        assert window.academic_form_view.result_label.text() == message
        assert window.academic_form_view.result_label.objectName() == "failureMessage"
        assert window.academic_form_view.field_error_labels["rut"].text() == message


def test_active_pages_remain_operational_after_window_resize(
    qtbot: QtBot,
    qapp: object,
) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot)
    navigations = (
        window.show_main_menu,
        window.show_academics_list,
        window.show_academic_form,
    )
    for width, height in ((720, 600), (768, 768), (1280, 900)):
        window.resize(width, height)
        for navigate in navigations:
            navigate()
            qapp.processEvents()
            assert window.stack.currentWidget().isVisibleTo(window)
            assert not window.grab().isNull()

        window.show_academics_list()
        qapp.processEvents()
        for control in (
            window.academics_list_view.search_input,
            window.academics_list_view.edit_selected_button,
            window.academics_list_view.add_button,
            window.academics_list_view.back_button,
        ):
            top_left = control.mapTo(window, QPoint(0, 0))
            assert top_left.x() >= 0
            assert top_left.y() >= 0
            assert top_left.x() + control.width() <= window.width()
            assert top_left.y() + control.height() <= window.height()


def test_login_registration_and_menu_geometry_focus_and_text_fit(
    qtbot: QtBot,
    qapp: object,
) -> None:
    window = _window(qtbot)

    def geometry(control: object) -> QRect:
        return QRect(control.mapTo(window, QPoint(0, 0)), control.size())

    def assert_inside(control: object) -> None:
        rect = geometry(control)
        assert rect.left() >= 0 and rect.top() >= 0
        assert rect.right() < window.width()
        assert rect.bottom() < window.height()

    for width, height in ((720, 600), (768, 768), (1280, 900)):
        window.resize(width, height)
        window.show_login()
        window.login_view.username_input.setFocus()
        qapp.processEvents()
        for control in (
            window.login_view.username_input,
            window.login_view.password_input,
            window.login_view.register_button,
            window.login_view.login_button,
        ):
            assert_inside(control)
        assert window.login_view.username_input.hasFocus()
        window.focusNextChild()
        assert window.login_view.password_input.hasFocus()

        window.show_registration()
        window.register_view.username_input.setFocus()
        qapp.processEvents()
        for control in (
            window.register_view.username_input,
            window.register_view.password_input,
            window.register_view.confirmation_input,
            window.register_view.back_button,
            window.register_view.register_button,
        ):
            assert_inside(control)
        assert window.register_view.username_input.hasFocus()
        window.focusNextChild()
        assert window.register_view.password_input.hasFocus()
        window.focusNextChild()
        assert window.register_view.confirmation_input.hasFocus()

        window._handle_authenticated("visual.sintetica")
        window.main_menu_view.academics_button.setFocus()
        qapp.processEvents()
        actions = window.main_menu_view.action_buttons
        action_rects = [geometry(button) for button in actions]
        assert all(
            first.bottom() < second.top()
            for first, second in zip(action_rects, action_rects[1:])
        )
        for button in actions:
            assert_inside(button)
            available = (
                button.width() - 2 * window.style_manager.button_horizontal_padding
            )
            assert QFontMetrics(button.font()).horizontalAdvance(button.text()) < (
                available
            )
        assert window.main_menu_view.academics_button.hasFocus()
        window.focusNextChild()
        assert window.main_menu_view.download_button.hasFocus()
        window.focusNextChild()
        assert window.main_menu_view.upload_button.hasFocus()
