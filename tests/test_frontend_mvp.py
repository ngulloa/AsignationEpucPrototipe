"""Qt coverage for the complete presentation-only MVP."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QPushButton
from pytestqt.qtbot import QtBot

from backend.contracts import AcademicFormData
from frontend.contracts import OwnerAlert, UiResult
from frontend.controller import FakeFrontendController
from frontend.frontend_main import (
    ALERTS_SCREEN,
    APPROVAL_SCREEN,
    ERROR_NOTIFICATION_SCREEN,
    LOGIN_SCREEN,
    MENU_SCREEN,
    REGISTER_SCREEN,
    UPDATE_SCREEN,
    build_frontend_window,
)
from persistence.settings_repository import load_application_settings

SETTINGS = load_application_settings()


def _window(qtbot: QtBot):
    window = build_frontend_window(
        controller=FakeFrontendController(), settings=SETTINGS
    )
    qtbot.addWidget(window)
    window.show()
    return window


def _authenticate(window: object, qtbot: QtBot, username: str = "propietario") -> None:
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


def test_login_is_initial_password_is_hidden_and_length_controls_submit(
    qtbot: QtBot,
) -> None:
    window = _window(qtbot)
    login = window.login_view

    assert window.current_screen == LOGIN_SCREEN
    assert login.password_input.echoMode() is QLineEdit.EchoMode.Password
    assert login.password_input.maxLength() == 8
    login.username_input.setText("usuario")
    login.password_input.setText("123")
    assert not login.login_button.isEnabled()
    login.password_input.setText("1234")
    assert login.login_button.isEnabled()
    login.password_input.setText("123456789")
    assert login.password_input.text() == "12345678"
    assert login.login_button.isEnabled()


def test_authentication_error_and_success_owner_capabilities(qtbot: QtBot) -> None:
    window = _window(qtbot)
    login = window.login_view
    login.username_input.setText("error")
    login.password_input.setText("1234")
    qtbot.mouseClick(login.login_button, Qt.MouseButton.LeftButton)

    assert window.current_screen == LOGIN_SCREEN
    assert login.result_label.text() == "Error de autenticación."
    assert login.result_label.objectName() == "failureMessage"

    login.username_input.setText("propietario")
    qtbot.mouseClick(login.login_button, Qt.MouseButton.LeftButton)
    assert window.current_screen == MENU_SCREEN
    assert window.authenticated_username == "propietario"
    assert window.main_menu_view.approvals_button.isVisibleTo(window.main_menu_view)
    assert window.main_menu_view.alerts_button.isVisibleTo(window.main_menu_view)


def test_normal_user_does_not_receive_owner_actions_and_can_logout(
    qtbot: QtBot,
) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot, "usuario.demo")

    menu = window.main_menu_view
    assert not menu.approvals_button.isVisibleTo(menu)
    assert not menu.alerts_button.isVisibleTo(menu)
    qtbot.mouseClick(menu.header.logout_button, Qt.MouseButton.LeftButton)
    assert window.current_screen == LOGIN_SCREEN
    assert window.authenticated_username == ""
    assert window.login_view.password_input.text() == ""


def test_registration_navigation_hidden_passwords_and_fake_result(qtbot: QtBot) -> None:
    window = _window(qtbot)
    qtbot.mouseClick(
        window.login_view.register_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.current_screen == REGISTER_SCREEN
    registration = window.register_view
    assert registration.password_input.echoMode() is QLineEdit.EchoMode.Password
    assert registration.confirmation_input.echoMode() is QLineEdit.EchoMode.Password
    registration.username_input.setText("nueva.persona")
    registration.password_input.setText("1234")
    registration.confirmation_input.setText("1234")
    assert registration.register_button.isEnabled()
    qtbot.mouseClick(registration.register_button, Qt.MouseButton.LeftButton)
    assert window.current_screen == LOGIN_SCREEN
    assert "registro" in window.login_view.result_label.text().lower()


def test_shared_table_selector_has_required_columns_and_selectable_records(
    qtbot: QtBot,
) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot)
    window.show_academics_list()
    view = window.academics_list_view
    qtbot.mouseClick(view.shared_tables_button, Qt.MouseButton.LeftButton)

    assert [
        view.shared_tables_table.horizontalHeaderItem(column).text()
        for column in range(view.shared_tables_table.columnCount())
    ] == ["#", "Nombre de usuario"]
    assert view.shared_tables_table.rowCount() == 2
    assert (
        view.shared_tables_table.selectionMode()
        is QAbstractItemView.SelectionMode.SingleSelection
    )
    assert (
        view.shared_records_table.selectionMode()
        is QAbstractItemView.SelectionMode.SingleSelection
    )
    view.shared_tables_table.selectRow(0)
    assert view.shared_records_table.rowCount() == 1
    assert "maria.soto" in view.shared_context_label.text()
    assert "Autor" not in [
        view.shared_records_table.horizontalHeaderItem(column).text()
        for column in range(view.shared_records_table.columnCount())
    ]


def test_personal_selection_enables_edit_and_opens_prefilled_reused_form(
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
    assert window.academic_form_view.name_input.text() == "Académico de prueba"
    assert window.academic_form_view.page_title.label.text() == "EDITAR ACADÉMICO"


def test_approved_user_edits_shared_record_through_reused_form(
    qtbot: QtBot,
) -> None:
    controller = FakeFrontendController()
    window = build_frontend_window(controller=controller, settings=SETTINGS)
    qtbot.addWidget(window)
    window.show()
    _authenticate(window, qtbot)
    window.show_academics_list()
    view = window.academics_list_view
    qtbot.mouseClick(view.shared_tables_button, Qt.MouseButton.LeftButton)
    view.shared_tables_table.selectRow(0)
    view.shared_records_table.selectRow(0)

    assert view.edit_selected_button.isEnabled()
    qtbot.mouseClick(view.edit_selected_button, Qt.MouseButton.LeftButton)
    assert window.academic_form_view.page_title.label.text() == "EDITAR ACADÉMICO"
    window.academic_form_view.name_input.setText("Académica compartida editada")
    qtbot.mouseClick(
        window.academic_form_view.save_button,
        Qt.MouseButton.LeftButton,
    )

    assert window.current_screen == "academic_list"
    assert controller.list_shared_tables()[0].academics[0].name == (
        "Académica compartida editada"
    )
    assert "actualizada" in view.feedback_label.text().lower()


def test_unapproved_user_cannot_start_or_save_shared_edit(qtbot: QtBot) -> None:
    controller = FakeFrontendController()
    window = build_frontend_window(controller=controller, settings=SETTINGS)
    qtbot.addWidget(window)
    window.show()
    _authenticate(window, qtbot, "usuario.demo")
    window.show_academics_list()
    view = window.academics_list_view
    qtbot.mouseClick(view.shared_tables_button, Qt.MouseButton.LeftButton)
    view.shared_tables_table.selectRow(0)
    view.shared_records_table.selectRow(0)

    assert not view.edit_selected_button.isEnabled()
    assert "acceso denegado" in view.edit_selected_button.toolTip().lower()
    view._edit_selected()
    assert "acceso denegado" in view.feedback_label.text().lower()
    record = controller.list_shared_tables()[0].academics[0]
    denied = controller.update_shared_academic(
        1,
        record.academic_id,
        AcademicFormData(
            name=record.name,
            rut=record.rut,
            plant=record.plant,
            profile=record.profile,
            weekly_hours=record.weekly_hours,
            status=record.status,
        ),
    )
    assert denied.success is False
    assert "acceso denegado" in denied.message.lower()


def test_academic_form_prepares_duplicate_invalid_and_save_errors(qtbot: QtBot) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot)
    expected = (
        ("11111111-1", "Rut ya registrado."),
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

    assert window.academic_form_view.rut_input.validator() is None


def test_error_link_opens_origin_aware_form_with_preselected_error(
    qtbot: QtBot,
) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot)
    window.show_academic_form()
    _fill_academic_form(window, "00000000-0")
    form = window.academic_form_view
    form.submit()
    footer_button = form.findChild(QPushButton, "linkButton")
    qtbot.mouseClick(footer_button, Qt.MouseButton.LeftButton)

    error_view = window.error_notification_view
    assert window.current_screen == ERROR_NOTIFICATION_SCREEN
    assert error_view.source_input.text() == "Agregar académico"
    assert error_view.error_type_combo.currentText() == "Rut inválido."
    assert not hasattr(error_view, "detail_text")
    assert not hasattr(error_view, "username_input")
    qtbot.mouseClick(error_view.back_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is form


def test_every_page_contains_the_error_link(qtbot: QtBot) -> None:
    window = build_frontend_window(
        controller=FakeFrontendController(), settings=SETTINGS
    )
    qtbot.addWidget(window)
    for page in window._views.values():
        links = page.findChildren(QPushButton, "linkButton")
        assert len(links) == 1, page.objectName()
        assert links[0].text() == "Notificar error"


def test_update_form_has_read_only_user_summary_result_and_error(qtbot: QtBot) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot)
    window.show_update()
    view = window.update_view

    assert window.current_screen == UPDATE_SCREEN
    assert view.username_input.isReadOnly()
    assert view.username_input.text() == "propietario"
    assert view.summary_text.isReadOnly()
    assert "Git" in view.summary_text.toPlainText()
    assert not view.update_button.isEnabled()
    view.update_name_input.setText("error")
    assert view.update_button.isEnabled()
    qtbot.mouseClick(view.update_button, Qt.MouseButton.LeftButton)
    assert view.result_label.text() == "Error de actualización."
    assert view.result_label.objectName() == "failureMessage"


def test_update_exposes_a_transient_busy_state(qtbot: QtBot) -> None:
    observed: list[tuple[bool, bool, str]] = []

    class BusyAwareController(FakeFrontendController):
        window: object | None = None

        def run_update(self, request: object) -> UiResult:
            assert self.window is not None
            view = self.window.update_view
            observed.append(
                (
                    view.update_button.isEnabled(),
                    view.update_name_input.isEnabled(),
                    view.update_button.text(),
                )
            )
            return UiResult(True, "Actualización controlada.")

    controller = BusyAwareController()
    window = build_frontend_window(controller=controller, settings=SETTINGS)
    controller.window = window
    qtbot.addWidget(window)
    window.show()
    _authenticate(window, qtbot)
    window.show_update()
    view = window.update_view
    view.update_name_input.setText("Prueba de progreso")

    qtbot.mouseClick(view.update_button, Qt.MouseButton.LeftButton)

    assert observed == [(False, False, "Actualizando…")]
    assert view.update_button.isEnabled()
    assert view.update_name_input.isEnabled()
    assert view.update_button.text() == "Actualizar"


def test_approvals_and_owner_alerts_have_selectable_state(qtbot: QtBot) -> None:
    alert = OwnerAlert(
        alert_id="alert-with-detail",
        source_screen="academic_form",
        created_at="30-07-2026 12:10",
        category="persistence",
        error_code="SAVE_ERROR",
        status="new",
    )
    window = build_frontend_window(
        controller=FakeFrontendController(alerts=(alert,)), settings=SETTINGS
    )
    qtbot.addWidget(window)
    window.show()
    _authenticate(window, qtbot)
    window.show_approvals()
    approval = window.approval_view
    assert window.current_screen == APPROVAL_SCREEN
    assert not approval.approve_button.isEnabled()
    approval.table.selectRow(0)
    assert approval.approve_button.isEnabled()
    qtbot.mouseClick(approval.approve_button, Qt.MouseButton.LeftButton)
    assert approval.table.item(0, 3).text() == "Aprobado"

    window.show_alerts()
    alerts = window.alerts_view
    assert window.current_screen == ALERTS_SCREEN
    assert alerts.table.rowCount() == 1
    alerts.table.selectRow(0)
    assert "SAVE_ERROR" in alerts.detail_text.toPlainText()
    assert "persistence" in alerts.detail_text.toPlainText()
    assert "maria.soto" not in alerts.detail_text.toPlainText()


def test_reference_pages_remain_operational_after_window_resize(
    qtbot: QtBot,
    qapp: object,
) -> None:
    window = _window(qtbot)
    _authenticate(window, qtbot)
    navigations = (
        window.show_main_menu,
        window.show_academics_list,
        window.show_academic_form,
        window.show_approvals,
        window.show_update,
        window.show_alerts,
    )
    window.resize(820, 640)
    for navigate in navigations:
        navigate()
        qapp.processEvents()
        assert window.stack.currentWidget().isVisibleTo(window)
        assert not window.grab().isNull()

    window.show_academics_list()
    qapp.processEvents()
    academics = window.academics_list_view
    assert window.size().width() == 820
    assert academics._compact_toolbar is True
    assert academics.minimumSizeHint().width() <= 820
    assert academics.body_scroll.horizontalScrollBar().maximum() == 0
    for control in (
        academics.search_input,
        academics.edit_selected_button,
        academics.add_button,
        academics.back_button,
    ):
        top_left = control.mapTo(window, QPoint(0, 0))
        assert top_left.x() >= 0
        assert top_left.y() >= 0
        assert top_left.x() + control.width() <= window.width()
        assert top_left.y() + control.height() <= window.height()

    window.resize(1280, 900)
    window.show_academics_list()
    qapp.processEvents()
    assert window.size().width() == 1280
    assert window.size().height() == 900
    assert academics._compact_toolbar is False
    assert academics.search_input.y() == academics.add_button.y()
    assert window.academics_list_view.table.width() > 0
    assert window.academics_list_view.table.height() > 0
